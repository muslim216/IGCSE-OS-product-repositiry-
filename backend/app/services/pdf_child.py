"""The separate process that reads an uploaded PDF or photo, and the format
it speaks.

The only place pypdf, Pillow and the HEIF decoder run (`tests/test_pdf_guards.py`
holds it to that). A crafted file can make any of them use memory or CPU
without bound, and in the API process that stops every request and job on the
instance. In here it can only exhaust this process, which the limits below
then end. The name says PDF because it read only PDFs first (T-027); since
T-030 it reads iPhone photos too.

`services/pdf_sandbox.py` starts it as::

    python -I -B -m app.services.pdf_child --kind pdf|photo [--uid N --gid N]

`-I` so nothing from the environment or the working directory decides what
is imported, `-B` because the file-size limit forbids writing bytecode anyway.

**The kind decides everything that differs, before a byte of the file is
read:** which library is imported (`services/pdf.py` or `services/photo.py`,
never both), the memory and CPU limits (`LIMITS`), and which operations the
child will run (`OPS`). A photo child refuses a PDF operation, and the
reverse, as a request it could not read.

**Order matters, and is tested.** Before a single byte of the file is read:

1. `oom_score_adj` goes to 1000, so if the instance runs short the kernel kills
   this process and not the API.
2. Started as root (the image has no `USER` yet), it drops to the `pdfsandbox`
   account the parent named, and refuses to go on if it is still root. It does
   this itself because uvloop, which production runs, does not take `user=`
   in `subprocess_exec`.
3. The limits are set with soft equal to hard, so they cannot be raised again.
4. It writes `READY`. Anything that goes wrong before this is our fault (a
   broken image, a missing account), not the file's, and the parent retries.

Then it reads the whole request, checks the operation belongs to its kind, and
writes `REQUEST_OK` before calling the library. Exiting with
`EXIT_BAD_REQUEST` means "the parent sent something I could not read" only
until that marker: after it, the library has the file, and anything the
process does next may be the file's doing, so the parent blames the file. Then
it does the work and writes the result. **It writes codes, never text.** Every
sentence a tutor or student sees is written by the parent from the code, so
nothing this process emits, however it was made to behave, can put words on
their screen.

This module is also imported by the parent, for the format. The libraries are
therefore imported only in `_load_library`, after the limits are set.
"""

import enum
import gc
import json
import os
import resource
import struct
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import BinaryIO

#: Written first, once the child is set up and before it reads anything.
READY = b"R"
#: Written once the whole request is read and its operation checked against
#: the kind, before the library sees the file.
REQUEST_OK = b"K"

REQUEST_MAGIC = b"AVPQ"
RESULT_MAGIC = b"AVPR"
VERSION = 1

#: magic, version, op, number of ranges, then the file's length.
REQUEST_HEAD = struct.Struct("!4sBBIQ")
#: One page range: first and last page, 1-based and inclusive.
RANGE = struct.Struct("!II")
#: magic, version, code, detail, index, total, number of pieces.
#: `index` is the range a failure belongs to, -1 for the whole file. `total`
#: is the page count when the child knows it.
RESULT_HEAD = struct.Struct("!4sBBBiII")
#: Each piece's length, all of them before the first piece.
PIECE_LENGTH = struct.Struct("!Q")

#: The largest file the child will read. Must equal `storage.MAX_FILE_BYTES`
#: (a test holds them together); not imported from there because `storage`
#: pulls in the app's settings, which this process has no business loading.
MAX_INPUT_BYTES = 20 * 1024 * 1024
#: A booklet holds at most 60 papers (`api/booklets.py`), so no request needs
#: more ranges than this; a request with more is refused unread.
MAX_RANGES = 64

#: Converting a HEIC photo decodes it to raw pixels first: about 14 bytes a pixel
#: at peak, measured (pillow 12.3, pillow-heif 1.8, libheif 1.23). The 20 MB cap
#: is on the file, not the picture: a 21 KB file can declare 10,000 x 10,000 and
#: took enough memory to kill the process for everyone (`SA-03`). The header's
#: size is the size decoded — libheif refuses a picture that differs from it.
#:
#: 25 megapixels is the default photo of a current iPhone (5712 x 4284, 24 MP;
#: full-resolution 48 MP is opt-in and refused with a reason). The photo
#: child's memory limit is what bounds a decode now; this refuses anything
#: larger before a single pixel is decoded, with a sentence the student can act
#: on, rather than letting it run into that limit. Not Pillow's own
#: `Image.MAX_IMAGE_PIXELS`, which only warns at this size. The parent may ask
#: for a lower ceiling (`--max-pixels`), never a higher one.
MAX_IMAGE_PIXELS = 25_000_000


class Kind(enum.Enum):
    """What the child reads. The parent chooses it; nothing in the file can."""

    pdf = "pdf"
    photo = "photo"


@dataclass(frozen=True)
class Limits:
    """One kind's limits, soft equal to hard except CPU: the soft one sends
    SIGXCPU, and the hard one, a few seconds later, SIGKILL for a process that
    ignores it. The deadline is the parent's: wall-clock time from when it
    holds the heavy-work lock, above the hard CPU limit so a busy child is
    stopped by that first and the log says so; it catches one that waits
    instead of working."""

    memory_bytes: int
    cpu_soft_seconds: int
    cpu_hard_seconds: int
    deadline_seconds: float


#: The PDF limits (T-027).
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
CPU_SOFT_SECONDS = 60
CPU_HARD_SECONDS = 65
PDF_DEADLINE_SECONDS = 90.0

#: A photo's address space. 448 MB is the stop line the T-030 design set: a
#: 24 MP photo peaked at about 314 MB resident decoding on its own (macOS, one
#: decoder thread), and address space runs above resident by the mapped
#: libraries and the allocator's reserve. The Linux test that converts a real
#: 24 MP photo under this limit prints the child's peak, so CI shows the
#: margin. If a genuine photo needs more, that is the owner's decision (a
#: bigger instance, or a lower pixel ceiling), not a quiet raise here.
PHOTO_MEMORY_LIMIT_BYTES = 448 * 1024 * 1024
#: A 24 MP decode took about 1.1 s of CPU on one thread (macOS). Ten seconds
#: leaves room for a much slower instance, and is short enough that one photo
#: cannot hold the one heavy-work slot for long. The Linux test prints the
#: decode's CPU time and fails if it uses more than half of this.
PHOTO_CPU_SOFT_SECONDS = 10
PHOTO_CPU_HARD_SECONDS = 12
#: A photo arrives in a student's request, so its deadline is short.
PHOTO_DEADLINE_SECONDS = 20.0

#: Built once; the child reads its memory and CPU limits here, the parent its
#: deadline.
LIMITS: dict[Kind, Limits] = {
    Kind.pdf: Limits(MEMORY_LIMIT_BYTES, CPU_SOFT_SECONDS, CPU_HARD_SECONDS, PDF_DEADLINE_SECONDS),
    Kind.photo: Limits(
        PHOTO_MEMORY_LIMIT_BYTES,
        PHOTO_CPU_SOFT_SECONDS,
        PHOTO_CPU_HARD_SECONDS,
        PHOTO_DEADLINE_SECONDS,
    ),
}
OPEN_FILES = 16

OOM_SCORE_ADJ = "/proc/self/oom_score_adj"

#: Exit statuses the parent reads as its own failure, retried, never as the
#: file's: setting up failed before `READY`, or the request it was sent did
#: not parse (before `REQUEST_OK`). Any other non-zero exit after `READY` is
#: the file's, and so is this one once `REQUEST_OK` has been written.
EXIT_SETUP = 2
EXIT_BAD_REQUEST = 3

#: The only options the child takes, unless `--test-mode 1` comes first among
#: them, which only the tests' private `_run` and `_photo` pass.
_OPTIONS = {"kind", "uid", "gid", "max-pixels"}
_TEST_OPTIONS = {"test-mode", "test-hold", "test-allocate-mb", "test-report"}


class Op(enum.IntEnum):
    count = 1
    split = 2
    photo_to_jpeg = 3


#: The operations each kind runs. Anything else is a request it cannot read.
OPS: dict[Kind, frozenset[Op]] = {
    Kind.pdf: frozenset({Op.count, Op.split}),
    Kind.photo: frozenset({Op.photo_to_jpeg}),
}


class Code(enum.IntEnum):
    ok = 0
    unreadable = 1
    encrypted = 2
    range_invalid = 3
    too_complex = 4
    #: A photo over the pixel ceiling, read from its header.
    too_large = 5


class Detail(enum.IntEnum):
    """For the log: which limit a `too_complex` hit, or, for a photo that is
    `unreadable`, which kind of exception said so. A fixed list, never the
    exception's text, which a crafted file can choose."""

    none = 0
    memory = 1
    recursion = 2
    #: Unreadable photos, by exception class. The decoder's own refusals:
    not_heif = 3
    decoder_os_error = 4
    decoder_syntax_error = 5
    decoder_value_error = 6
    decoder_eof = 7
    decoder_runtime_error = 8
    #: A class no corrupt photo should raise (a TypeError, an AttributeError):
    #: most likely a fault in our code or the library, logged as an ERROR.
    unexpected = 9


#: Unreadable details that point at our code rather than at the photo.
OUR_FAULT_DETAILS = frozenset({Detail.unexpected})


def unreadable_detail(exc: BaseException) -> Detail:
    """The `Detail` for an exception the photo library raised, by class only.
    Order matters: `UnidentifiedImageError` is an `OSError`, and the format
    check in `photo.to_jpeg` raises `NotHeif`, a `ValueError`."""
    if type(exc).__name__ == "NotHeif":
        return Detail.not_heif
    for kind, detail in (
        (OSError, Detail.decoder_os_error),
        (SyntaxError, Detail.decoder_syntax_error),
        (ValueError, Detail.decoder_value_error),
        (EOFError, Detail.decoder_eof),
        (struct.error, Detail.decoder_value_error),
        (RuntimeError, Detail.decoder_runtime_error),
    ):
        if isinstance(exc, kind):
            return detail
    return Detail.unexpected


class SetupFailed(Exception):
    """The child could not make itself safe to run. It stops before `READY`."""


def _linux() -> bool:
    return sys.platform.startswith("linux")


def _raise_oom_score() -> None:
    if not os.path.exists(OOM_SCORE_ADJ):
        return  # not Linux: nothing to set, and nothing that would read it
    try:
        with open(OOM_SCORE_ADJ, "w") as f:
            f.write("1000")
    except OSError as exc:
        raise SetupFailed("oom_score_adj") from exc


def _drop_privileges(uid: int | None, gid: int | None) -> None:
    """Root becomes the account the parent named; anyone else stays as they
    are. Groups first, then the group, then the user: once the user has
    changed, the process no longer has the right to change the other two."""
    if os.getuid() != 0 and os.geteuid() != 0:
        return
    if uid is None or gid is None or uid == 0 or gid == 0:
        raise SetupFailed("started as root with no account to drop to")
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    if os.getuid() == 0 or os.geteuid() == 0:
        raise SetupFailed("still root after dropping privileges")


def _set_limits(kind: Kind) -> None:
    own = LIMITS[kind]
    limits = [
        (resource.RLIMIT_AS, own.memory_bytes, own.memory_bytes),
        (resource.RLIMIT_CPU, own.cpu_soft_seconds, own.cpu_hard_seconds),
        (resource.RLIMIT_CORE, 0, 0),
        (resource.RLIMIT_FSIZE, 0, 0),
        (resource.RLIMIT_NOFILE, OPEN_FILES, OPEN_FILES),
    ]
    for which, soft, hard in limits:
        try:
            resource.setrlimit(which, (soft, hard))
        except (OSError, ValueError) as exc:
            # macOS refuses some of these (it has no enforced RLIMIT_AS), and a
            # laptop is not what this protects. On Linux every one must hold.
            if _linux():
                raise SetupFailed(f"limit {which}") from exc


def _read_exact(stream: BinaryIO, n: int) -> bytes:
    chunks = []
    while n > 0:
        chunk = stream.read(min(n, 1 << 20))
        if not chunk:
            raise SetupFailed("request ended early")
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


def request_head(op: Op, ranges: Sequence[tuple[int, int]], length: int) -> bytes:
    """Everything of a request but the file, which the parent writes after it
    as it is, so this side never joins the two into a new bytes object."""
    head = REQUEST_HEAD.pack(REQUEST_MAGIC, VERSION, int(op), len(ranges), length)
    return head + b"".join(RANGE.pack(first, last) for first, last in ranges)


def encode_request(op: Op, ranges: Sequence[tuple[int, int]], data: bytes) -> bytes:
    return request_head(op, ranges, len(data)) + data


def _read_request(stream: BinaryIO) -> tuple[Op, list[tuple[int, int]], bytes]:
    magic, version, op, n_ranges, length = REQUEST_HEAD.unpack(
        _read_exact(stream, REQUEST_HEAD.size)
    )
    if magic != REQUEST_MAGIC or version != VERSION:
        raise SetupFailed("not a request")
    if n_ranges > MAX_RANGES or length > MAX_INPUT_BYTES:
        raise SetupFailed("request over its limits")
    raw = _read_exact(stream, RANGE.size * n_ranges)
    ranges = [RANGE.unpack_from(raw, i * RANGE.size) for i in range(n_ranges)]
    return Op(op), ranges, _read_exact(stream, length)


def _write_result(
    stream: BinaryIO,
    code: Code,
    *,
    detail: Detail = Detail.none,
    index: int = -1,
    total: int = 0,
    pieces: Sequence[bytes] = (),
) -> None:
    stream.write(
        RESULT_HEAD.pack(RESULT_MAGIC, VERSION, int(code), int(detail), index, total, len(pieces))
    )
    for piece in pieces:
        stream.write(PIECE_LENGTH.pack(len(piece)))
    # One write per piece rather than a join, which would hold a second copy
    # of everything cut.
    for piece in pieces:
        stream.write(piece)
    stream.flush()


def _file_code(exc: Exception) -> Code:
    """A PDF's refusal: encrypted or unreadable, by type, never by the message."""
    from app.services.pdf import PdfEncrypted

    return Code.encrypted if isinstance(exc, PdfEncrypted) else Code.unreadable


def _serve(op: Op, ranges: list[tuple[int, int]], data: bytes, stdout: BinaryIO) -> None:
    from app.services import pdf  # loaded before READY by `_load_library`
    from app.services.job_errors import DocumentProblem

    # One parse of the file for every range (`pdf.extract_ranges`).
    try:
        if op is Op.count:
            total = pdf.page_count(data)
        else:
            total, cuts = pdf.extract_ranges(data, ranges)
    except DocumentProblem as exc:
        _write_result(stdout, _file_code(exc))
        return
    except (MemoryError, RecursionError):
        raise  # too complex, answered in `main`
    # Anything else the library throws on a corrupt file is an unreadable
    # file, the tutor's ordinary problem, never the final "too complex".
    except Exception:  # noqa: BLE001 — a corrupt file is not a server fault
        _write_result(stdout, Code.unreadable)
        return
    if op is Op.count:
        _write_result(stdout, Code.ok, total=total)
        return

    pieces: list[bytes] = []
    for index, (first, last) in enumerate(ranges):
        # Checked here rather than left to `extract_pages`, whose refusals are
        # sentences: the parent rebuilds the same sentence from the range and
        # the total.
        if first < 1 or last < first or last > total:
            _write_result(stdout, Code.range_invalid, index=index, total=total, pieces=pieces)
            return
        try:
            pieces.append(next(cuts))
        except (MemoryError, RecursionError):
            raise
        except Exception:  # noqa: BLE001 — as above
            _write_result(stdout, Code.unreadable, index=index, total=total, pieces=pieces)
            return
        # Each cut builds a writer whose objects refer to one another, so a
        # finished one is freed only by the cycle collector. Left to its own
        # schedule it lagged several cuts behind: a 20 MB, 30-paper booklet
        # peaked at 338 MB (macOS RSS) that way, and near one cut's size with
        # this.
        gc.collect()
    _write_result(stdout, Code.ok, total=total, pieces=pieces)


def _serve_photo(data: bytes, max_pixels: int, stdout: BinaryIO) -> None:
    from app.services import photo  # loaded before READY by `_load_library`

    try:
        jpeg = photo.to_jpeg(data, max_pixels=max_pixels)
    except photo.OverCeiling:
        _write_result(stdout, Code.too_large)
        return
    except (MemoryError, RecursionError):
        raise  # too complex, answered in `main`
    # Pillow and the HEIF decoder raise across a wide surface on a malformed
    # file (UnidentifiedImageError, OSError, SyntaxError, struct.error, and
    # whatever the decoder decides). All of it is a photo that could not be
    # read, never the final "too complex". The detail names the exception's
    # class, so the parent's log can tell a photo the decoder refused from a
    # fault of ours (`Detail.unexpected`).
    except Exception as exc:  # noqa: BLE001 — a corrupt photo is not a server fault
        _write_result(stdout, Code.unreadable, detail=unreadable_detail(exc))
        return
    _write_result(stdout, Code.ok, pieces=[jpeg])


def _options(argv: Sequence[str]) -> dict[str, str]:
    options = {}
    args = list(argv)
    while args:
        name = args.pop(0)
        if not name.startswith("--") or not args:
            raise SetupFailed("bad arguments")
        options[name[2:]] = args.pop(0)
    allowed = _OPTIONS | (_TEST_OPTIONS if options.get("test-mode") == "1" else set())
    if set(options) - allowed:
        raise SetupFailed("unexpected arguments")
    return options


def _max_pixels(kind: Kind, options: dict[str, str]) -> int:
    """The pixel ceiling for this child: the parent's, if it asked for a lower
    one, never above `MAX_IMAGE_PIXELS`. Only a photo child takes one."""
    if kind is not Kind.photo:
        if "max-pixels" in options:
            raise SetupFailed("a pixel ceiling for a PDF")
        return 0
    asked = int(options.get("max-pixels", MAX_IMAGE_PIXELS))
    if asked < 1:
        raise SetupFailed("bad pixel ceiling")
    return min(asked, MAX_IMAGE_PIXELS)


#: What each kind's child may never import, even indirectly. pypdf imports
#: Pillow whenever it can find it, and a PDF child has no use for an image
#: decoder; a photo child has none for a PDF parser. Each is one more library
#: a crafted file could reach.
_FORBIDDEN: dict[Kind, tuple[str, ...]] = {
    Kind.pdf: ("PIL", "pillow_heif", "app.services.photo"),
    Kind.photo: ("pypdf", "app.services.pdf"),
}


def _forbid_the_other_kind(kind: Kind) -> None:
    """Make the other kind's libraries impossible to import in this process:
    a `None` entry in `sys.modules` makes any later import of that name fail.
    Only in a real child (`isolate`); a test calling `main` in its own process
    must not lose its imports."""
    for name in _FORBIDDEN[kind]:
        if name in sys.modules:
            raise SetupFailed(f"{name} is already loaded")
        sys.modules[name] = None  # type: ignore[assignment]


def _load_library(kind: Kind) -> None:
    """Import this kind's library, and only that one, under the limits but
    before `READY`: a library that will not import, or will not set itself up
    safely, is a broken image, which is ours and retried, not the file's."""
    if kind is Kind.pdf:
        from app.services import pdf  # noqa: F401

        return
    from app.services import photo

    try:
        photo.configure()
    except RuntimeError as exc:
        raise SetupFailed("photo library") from exc


def _cpu_seconds() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def _report(started: float, cpu_started: float) -> None:
    """Test mode only: this process's peaks, the work's time and which
    libraries it loaded, to stderr, which the sandbox otherwise discards. Lets
    CI print what a real photo costs, read inside the child rather than
    guessed from outside. Numbers and module names only, never content."""
    status: dict[str, int] = {}
    try:
        with open("/proc/self/status") as f:
            for line in f:
                name, _, value = line.partition(":")
                if name in ("VmPeak", "VmHWM"):
                    status[name] = int(value.split()[0])
    except OSError:
        pass  # not Linux: the test that reads these runs on Linux only
    watched = ("PIL", "pillow_heif", "pypdf", "app.services.pdf", "app.services.photo")
    report = {
        "vm_peak_kb": status.get("VmPeak"),
        "vm_hwm_kb": status.get("VmHWM"),
        "max_rss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "seconds": time.monotonic() - started,
        "cpu_seconds": _cpu_seconds() - cpu_started,
        # Loaded, not merely forbidden (a `None` entry).
        "modules": sorted(m for m in watched if sys.modules.get(m) is not None),
    }
    sys.stderr.write(json.dumps(report) + "\n")
    sys.stderr.flush()


def _set_up(argv: Sequence[str], *, isolate: bool) -> tuple[dict[str, str], Kind, int]:
    """Everything before `READY`, in the tested order. Raises on any failure,
    which `main` turns into `EXIT_SETUP`."""
    options = _options(argv)
    # The PDF kind when none is named, which is how T-027's child was started;
    # the sandbox always names it.
    kind = Kind(options.get("kind", Kind.pdf.value))
    max_pixels = _max_pixels(kind, options)
    _raise_oom_score()
    uid, gid = options.get("uid"), options.get("gid")
    _drop_privileges(int(uid) if uid else None, int(gid) if gid else None)
    _set_limits(kind)
    if isolate:
        _forbid_the_other_kind(kind)
    _load_library(kind)
    return options, kind, max_pixels


def _accept_request(stdin: BinaryIO, kind: Kind) -> tuple[Op, list[tuple[int, int]], bytes]:
    """The whole request, checked against the kind. Raises if it is not one
    this child runs, which `main` turns into `EXIT_BAD_REQUEST`."""
    op, ranges, data = _read_request(stdin)
    if op not in OPS[kind] or (kind is Kind.photo and ranges):
        raise SetupFailed("not an operation of this kind")
    return op, ranges, data


def _test_hooks(options: dict[str, str], stdout: BinaryIO) -> bool:
    """Test-only hooks. The sandbox passes these only from tests, through its
    private `_run` and `_photo`; the public functions never do. True when a
    hook has already answered."""
    if "test-allocate-mb" in options:
        try:
            ballast = bytearray(int(options["test-allocate-mb"]) * 1024 * 1024)
            del ballast
        except MemoryError:
            _write_result(stdout, Code.too_complex, detail=Detail.memory)
            return True
    if "test-hold" in options:
        time.sleep(float(options["test-hold"]))
    return False


def _do_the_work(
    kind: Kind,
    op: Op,
    ranges: list[tuple[int, int]],
    data: bytes,
    max_pixels: int,
    stdout: BinaryIO,
) -> None:
    try:
        if kind is Kind.photo:
            _serve_photo(data, max_pixels, stdout)
        else:
            _serve(op, ranges, data, stdout)
    except MemoryError:
        del data
        _write_result(stdout, Code.too_complex, detail=Detail.memory)
    except RecursionError:
        _write_result(stdout, Code.too_complex, detail=Detail.recursion)


def main(
    argv: Sequence[str],
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    isolate: bool = False,
) -> int:
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    try:
        options, kind, max_pixels = _set_up(argv, isolate=isolate)
    except (SetupFailed, OSError, ValueError, ImportError):
        return EXIT_SETUP  # before READY: the parent treats this as its own failure
    stdout.write(READY)
    stdout.flush()

    try:
        op, ranges, data = _accept_request(stdin, kind)
    except (SetupFailed, struct.error, ValueError, OSError):
        # The parent's request, not the file, so its own exit status.
        return EXIT_BAD_REQUEST
    # From here the library has the file, so no exit is the parent's any more.
    stdout.write(REQUEST_OK)
    stdout.flush()
    if _test_hooks(options, stdout):
        return 0

    started, cpu_started = time.monotonic(), _cpu_seconds()
    _do_the_work(kind, op, ranges, data, max_pixels, stdout)
    if "test-report" in options:
        _report(started, cpu_started)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], isolate=True))
