"""The separate process that reads an uploaded PDF, and the format it speaks.

The only place pypdf runs (`tests/test_pdf_guards.py` holds it to that). A
crafted PDF can make the library use memory or CPU without bound, and in the
API process that stops every request and job on the instance. In here it can
only exhaust this process, which the limits below then end.

`services/pdf_sandbox.py` starts it as::

    python -I -B -m app.services.pdf_child [--uid N --gid N]

`-I` so nothing from the environment or the working directory decides what
is imported, `-B` because the file-size limit forbids writing bytecode anyway.

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

Then it reads the request, does the work through `services/pdf.py`, and writes
the result. **It writes codes, never text.** Every sentence a tutor sees is
written by the parent from the code, so nothing this process emits, however it
was made to behave, can put words on a tutor's screen.

This module is also imported by the parent, for the format. The library is
therefore imported only inside `_serve`, after the limits are set.
"""

import enum
import gc
import os
import resource
import struct
import sys
import time
from collections.abc import Sequence
from typing import BinaryIO

#: Written first, once the child is set up and before it reads anything.
READY = b"R"

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

#: The limits, soft equal to hard except CPU: the soft one sends SIGXCPU, and
#: the hard one, a few seconds later, SIGKILL for a process that ignores it.
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
CPU_SOFT_SECONDS = 60
CPU_HARD_SECONDS = 65
OPEN_FILES = 16

OOM_SCORE_ADJ = "/proc/self/oom_score_adj"


class Op(enum.IntEnum):
    count = 1
    split = 2


class Code(enum.IntEnum):
    ok = 0
    unreadable = 1
    encrypted = 2
    range_invalid = 3
    too_complex = 4


class Detail(enum.IntEnum):
    """Which limit a `too_complex` hit, for the log."""

    none = 0
    memory = 1
    recursion = 2


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


def _set_limits() -> None:
    limits = [
        (resource.RLIMIT_AS, MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES),
        (resource.RLIMIT_CPU, CPU_SOFT_SECONDS, CPU_HARD_SECONDS),
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


def encode_request(op: Op, ranges: Sequence[tuple[int, int]], data: bytes) -> bytes:
    head = REQUEST_HEAD.pack(REQUEST_MAGIC, VERSION, int(op), len(ranges), len(data))
    return head + b"".join(RANGE.pack(first, last) for first, last in ranges) + data


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
    """Encrypted or unreadable, by type, never by the message."""
    from app.services.pdf import PdfEncrypted

    return Code.encrypted if isinstance(exc, PdfEncrypted) else Code.unreadable


def _serve(op: Op, ranges: list[tuple[int, int]], data: bytes, stdout: BinaryIO) -> None:
    from app.services import pdf  # here, under the limits, never at import
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


def _options(argv: Sequence[str]) -> dict[str, str]:
    options = {}
    args = list(argv)
    while args:
        name = args.pop(0)
        if not name.startswith("--") or not args:
            raise SetupFailed("bad arguments")
        options[name[2:]] = args.pop(0)
    return options


def main(
    argv: Sequence[str],
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> int:
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    try:
        options = _options(argv)
        _raise_oom_score()
        uid, gid = options.get("uid"), options.get("gid")
        _drop_privileges(int(uid) if uid else None, int(gid) if gid else None)
        _set_limits()
    except (SetupFailed, OSError, ValueError):
        return 2  # before READY: the parent treats this as its own failure
    stdout.write(READY)
    stdout.flush()

    op, ranges, data = _read_request(stdin)
    # Test-only hooks. The sandbox passes these only from tests, through its
    # private `_run`; the public `page_count` and `split` never do.
    if "test-allocate-mb" in options:
        try:
            ballast = bytearray(int(options["test-allocate-mb"]) * 1024 * 1024)
            del ballast
        except MemoryError:
            _write_result(stdout, Code.too_complex, detail=Detail.memory)
            return 0
    if "test-hold" in options:
        time.sleep(float(options["test-hold"]))

    try:
        _serve(op, ranges, data, stdout)
    except MemoryError:
        del data
        _write_result(stdout, Code.too_complex, detail=Detail.memory)
    except RecursionError:
        _write_result(stdout, Code.too_complex, detail=Detail.recursion)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
