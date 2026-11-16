"""Reading an uploaded PDF or photo in a separate, limited process.

Every page count, every split and every iPhone photo goes through here. Each
call starts `services/pdf_child.py` with the kind it reads (`--kind pdf` or
`--kind photo`), hands it the file, and reads back a small framed result. The
child is the only process that runs the PDF library or the photo decoder, so a
file that makes one run away costs that child and nothing else: before this,
they ran inside the API process, where they could hold the interpreter or get
the whole instance killed for memory, stopping every request and job.

**What the parent guarantees, whatever the child does:**

- It starts with no inherited descriptors, in its own process group, with
  stderr discarded, a minimal environment and an empty temporary directory.
  The empty environment is defence in depth. The boundary is the separate
  process, its limits, and, when the API runs as root (the image has no
  `USER` yet, T-009), the separate `pdfsandbox` account the child drops to.
  T-009 must keep a separate account for this child when it gives the API one.
- It writes the request and reads the result at the same time, so neither
  side can block the other, and it caps what it reads.
- It allows each kind's deadline (`pdf_child.LIMITS`), counted from when it holds the
  heavy-work lock (`services/heavy_work.py`), so waiting in line behind
  another file is never the file's fault.
- However the call ends (result, deadline, too much output, cancellation),
  `finally` kills the child's process group and waits for it, shielded, so
  no child is ever left running or unreaped.
- **The child sends codes; every message is written by its callers.** A
  result is accepted only in the shape the child writes for that operation;
  a photo's JPEG is checked again before it is handed back.

**What a failure means.** A file that hits a limit, is killed by a signal,
overruns the deadline or the output cap, or sends a malformed result is
`PdfTooComplex` (or `PhotoTooComplex`), which is never retried: the same file
would do the same again. A child that could not be started, died before
saying it was ready (before it had read any of the file), or could not read
the request it was sent, is `PdfSandboxUnavailable`, which is ours and is
retried. The log names the kind, the reason, the exit status and the limit,
never the child's output or the file.
"""

import asyncio
import contextlib
import logging
import os
import pwd
import shutil
import signal
import stat
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services import heavy_work
from app.services.job_errors import DocumentProblem
from app.services.pdf_child import (
    LIMITS,
    MAX_IMAGE_PIXELS,
    MAX_INPUT_BYTES,
    MAX_RANGES,
    OUR_FAULT_DETAILS,
    PIECE_LENGTH,
    READY,
    REQUEST_OK,
    RESULT_HEAD,
    RESULT_MAGIC,
    VERSION,
    Code,
    Detail,
    Kind,
    Op,
    request_head,
)

log = logging.getLogger(__name__)

#: The PDF child's deadline (`pdf_child.LIMITS`, where every kind's limits
#: live). Named here only because the job worker builds a booklet job's own
#: timeout from it (`workers/handlers.py`); the sandbox reads the table.
DEADLINE_SECONDS = LIMITS[Kind.pdf].deadline_seconds


def _deadline(kind: Kind) -> float:
    return LIMITS[kind].deadline_seconds


#: How long to wait for a killed child to be reaped. SIGKILL cannot be caught,
#: so this is a ceiling for a pathological kernel, not an expected wait.
REAP_SECONDS = 5.0
#: The account the child drops to when the API runs as root.
SANDBOX_USER = "pdfsandbox"

TOO_COMPLEX_MESSAGE = "This PDF is too complex to read safely."

#: The same sentences `services/pdf.py` writes, so a tutor sees exactly what
#: they saw when the library ran in this process.
_UNREADABLE = "This file could not be read as a PDF."
_ENCRYPTED = "This PDF is password-protected, so its pages cannot be read."

#: A minimal environment. Nothing of the API's: no database address, no
#: signing secret, no provider key. PYTHONHASHSEED is ignored under `-I`, and
#: is set only so the child's environment is fully written here.
_CHILD_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "MALLOC_ARENA_MAX": "2",
    "PYTHONHASHSEED": "random",
}

#: The ISO base-media major brands of a HEIF still image or sequence, exactly
#: the ones the photo decoder's own plugin claims (pillow-heif). The AVIF
#: brands are deliberately absent, so nothing reaches an AVIF decoder.
HEIF_BRANDS = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs", b"mif1", b"msf1"}
)
#: The largest JPEG accepted back from a photo child, the same as the largest
#: upload: `storage` would refuse anything bigger anyway.
PHOTO_OUTPUT_CAP = MAX_INPUT_BYTES

_said_same_user = False
_warned_photo_same_user = False


class PdfTooComplex(DocumentProblem):
    """The file hit one of the child's limits, or made it misbehave.

    Never retried: the same bytes would do the same again, and a retry is a
    second chance to tie up the instance. `safe_to_show` is inherited, so the
    sentence reaches the tutor."""

    job_retryable = False

    def __init__(self, message: str = TOO_COMPLEX_MESSAGE) -> None:
        super().__init__(message)


class PdfSandboxUnavailable(RuntimeError):
    """The child could not be started, or died before it read the file. Ours,
    not the file's: retried, and the person sees a generic or busy sentence.
    The same for photos as for PDFs."""


class PhotoProblem(Exception):
    """A photo the child would not turn into a JPEG. Carries no sentence:
    `storage` writes what the student reads, from the type."""

    job_retryable = False


class PhotoUnreadable(PhotoProblem):
    """Not a HEIF photo, or one the decoder could not read."""


class PhotoTooLarge(PhotoProblem):
    """More pixels than the ceiling, read from the photo's header."""


class PhotoTooComplex(PhotoProblem):
    """The photo hit one of the child's limits, or made it misbehave. Never
    retried, for the same reason as `PdfTooComplex`.

    `strike` is whether it counts against the student who sent it
    (`storage.record_photo_strike`): only when the child itself said the
    photo was too complex, or the photo used up its CPU (SIGXCPU). A SIGKILL
    (the hard CPU limit or the kernel's memory killer, which the log cannot
    tell apart), the deadline, or a child that died mid-answer is refused the
    same way but not counted, since any of those can be the instance's doing
    rather than the photo's."""

    def __init__(self, *, strike: bool = False) -> None:
        super().__init__()
        self.strike = strike


@dataclass(frozen=True)
class Split:
    """The pieces cut, in the order asked, and why the next one could not be.

    The child stops at the first range it cannot cut, and the pieces before it
    still come back, so a caller can behave as it did when each range was cut
    on its own: papers before a bad range are created, and the tutor is told
    which range was wrong."""

    pieces: list[bytes]
    failure: DocumentProblem | None


async def page_count(data: bytes) -> int:
    """How many pages the PDF has. Raises `DocumentProblem` (with
    `services/pdf.py`'s wording) if it cannot be read, `PdfTooComplex` if
    reading it hit a limit."""
    _, failure, total = await _run(Op.count, data, [])
    if failure is not None:
        raise failure
    return total


async def split(data: bytes, ranges: Sequence[tuple[int, int]]) -> Split:
    """Every range of one file, cut by one child. Raises `PdfTooComplex` if the
    file hit a limit; any other problem is the `failure` of the result."""
    if not ranges:
        return Split(pieces=[], failure=None)
    if len(ranges) > MAX_RANGES:
        # The booklet routes cap a draft at 60 papers, so this is a bug in a
        # caller, not a tutor's file: refuse it before starting anything.
        raise ValueError(f"at most {MAX_RANGES} ranges per split")
    pieces, failure, _total = await _run(Op.split, data, list(ranges))
    return Split(pieces=pieces, failure=failure)


def looks_like_heif(data: bytes) -> bool:
    """Whether the bytes open as a HEIF photo would: an ISO base-media `ftyp`
    box first, of a plausible size, naming a HEIF brand (`SEC-15`). Checked
    before any lock or child, so a file that is anything else, whatever type
    it was sent as, never reaches a decoder. `storage` checks it first, and
    `photo_to_jpeg` again: defence in depth, so a caller that skips the first
    still never hands a decoder anything else."""
    if len(data) < 16 or data[4:8] != b"ftyp":
        return False
    size = int.from_bytes(data[:4], "big")
    return 16 <= size <= len(data) and data[8:12] in HEIF_BRANDS


async def photo_to_jpeg(
    data: bytes,
    *,
    max_pixels: int = MAX_IMAGE_PIXELS,
    held: Callable[[], None] | None = None,
    wait: float | None = None,
) -> bytes:
    """The photo as a JPEG, decoded by a photo child.

    `held` is the heavy-work lock if the caller already took it; from here
    this owns it and gives it back on every way out. Without it the lock is
    taken here, waiting at most `wait` seconds (by default
    `heavy_work.PHOTO_LOCK_WAIT_SECONDS`; `HeavyWorkBusy` after that).
    `max_pixels` may lower the child's pixel ceiling, never raise it.

    Raises `PhotoUnreadable`, `PhotoTooLarge` or `PhotoTooComplex` for the
    photo, `PdfSandboxUnavailable` when no child could read it."""
    return await _photo(data, max_pixels=max_pixels, held=held, wait=wait)


async def _photo(
    data: bytes,
    *,
    max_pixels: int = MAX_IMAGE_PIXELS,
    held: Callable[[], None] | None = None,
    wait: float | None = None,
    test_args: Sequence[str] = (),
) -> bytes:
    """`photo_to_jpeg`, with the child's test-only hooks for the tests."""
    release = held
    try:
        # Again here, though `storage` has checked: see `looks_like_heif`.
        if not looks_like_heif(data):
            raise PhotoUnreadable()
        argv = _child_argv(Kind.photo, test_args, max_pixels=max_pixels)
        if release is None:
            release = await heavy_work.acquire(
                wait=heavy_work.PHOTO_LOCK_WAIT_SECONDS if wait is None else wait
            )
        head = request_head(Op.photo_to_jpeg, [], len(data))
        exchange = await _exchange_with_child(Kind.photo, argv, head, data, Op.photo_to_jpeg, 0)
    finally:
        # Every way out, the spawn refused included. A cancellation that
        # arrives while the killed child is still being reaped (shielded, in
        # `_kill_and_reap`) gives the lock back before that reap ends. That is
        # safe: the child has already been sent SIGKILL, which it cannot
        # catch, so it is not decoding any more.
        if release is not None:
            release()
    return _photo_outcome(exchange)


def _child_argv(
    kind: Kind, test_args: Sequence[str] = (), *, max_pixels: int | None = None
) -> list[str]:
    argv = [sys.executable, "-I", "-B", "-m", "app.services.pdf_child", "--kind", kind.value]
    if max_pixels is not None:
        argv += ["--max-pixels", str(max_pixels)]
    if os.geteuid() == 0:
        try:
            account = pwd.getpwnam(SANDBOX_USER)
        except KeyError:
            log.error("pdf sandbox: running as root and the %s account is missing", SANDBOX_USER)
            raise PdfSandboxUnavailable("no sandbox account") from None
        if account.pw_uid == 0 or account.pw_gid == 0:
            log.error("pdf sandbox: the %s account is root", SANDBOX_USER)
            raise PdfSandboxUnavailable("sandbox account is root")
        _refuse_while_uploads_are_open()
        argv += ["--uid", str(account.pw_uid), "--gid", str(account.pw_gid)]
    else:
        _say_same_user_once()
        if kind is Kind.photo:
            _warn_photo_same_user_once()
    if test_args:
        argv += ["--test-mode", "1"]
    return [*argv, *test_args]


def _refuse_while_uploads_are_open() -> None:
    """The sandbox account is kept out of the stored files only by the upload
    folder being closed to everyone but its owner (`storage.secure_upload_root`).
    If that did not take, a child could read every tenant's uploads, so none is
    started: retried, and an ERROR for whoever reads the logs. Local storage
    only; with object storage there is no folder of uploads to read."""
    settings = get_settings()
    if settings.storage_backend != "local":
        return
    try:
        mode = stat.S_IMODE(Path(settings.upload_dir).stat().st_mode)
    except FileNotFoundError:
        return  # nothing stored yet, so nothing to read
    except OSError as exc:
        # Cannot tell whether it is closed, so treat it as open: ours, retried.
        log.error("pdf sandbox: could not read the upload folder's mode (errno %s)", exc.errno)
        raise PdfSandboxUnavailable("the upload folder could not be checked") from exc
    if mode & 0o077:
        log.error(
            "pdf sandbox: the upload folder is open to other accounts (mode %o); "
            "not starting the PDF reader until it is 0700",
            mode,
        )
        raise PdfSandboxUnavailable("the upload folder is open to other accounts")


def _say_same_user_once() -> None:
    """Local runs, CI, and the API once T-009 gives it an account of its own:
    the child cannot change user, so it says so, once per process."""
    global _said_same_user
    if not _said_same_user:
        _said_same_user = True
        log.info("pdf sandbox: the API is not root, so the child runs as the same user")


def _warn_photo_same_user_once() -> None:
    """On the server, a child that runs as the API's own user can read the
    uploads on its disk, which the separate account exists to prevent. Today
    the API runs as root, so this does not happen; if it ever runs as another
    user before the child has an account of its own (T-009), say so loudly,
    once. Not a refusal: a student's photo still converts."""
    global _warned_photo_same_user
    settings = get_settings()
    if _warned_photo_same_user or not settings.render or settings.storage_backend != "local":
        return
    _warned_photo_same_user = True
    log.error(
        "pdf sandbox: photo child runs as the API's own user on the server, "
        "so it is not kept out of the stored uploads"
    )


def _output_cap(n_ranges: int) -> int:
    """The most piece bytes the parent accepts from one PDF child. Ranges may
    overlap, but a booklet's slices sum to roughly its own size, so twice the
    largest upload is room for every genuine split. Checked against the
    lengths the child announces, before any piece is read."""
    del n_ranges  # the same for every split; kept so a test can narrow it
    return 2 * MAX_INPUT_BYTES


class _Refused(Exception):
    """Why the parent gave up on a child. Never leaves this module."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Result:
    """What has been read from the child so far. Filled in place, so that
    after a deadline the caller can still tell how far it got."""

    def __init__(self) -> None:
        self.ready = False
        #: The child had read its whole request and checked it.
        self.request_ok = False
        self.parsed: tuple[Code, Detail, int, int, list[bytes]] | None = None


@dataclass
class _Exchange:
    """How one child ended, for the outcome functions."""

    kind: Kind
    returncode: int | None
    result: _Result
    refused: str | None
    killed: bool


async def _run(
    op: Op, data: bytes, ranges: list[tuple[int, int]], *, test_args: Sequence[str] = ()
) -> tuple[list[bytes], DocumentProblem | None, int]:
    """One PDF child, start to finish. `test_args` turns on the child's
    test-only hooks; nothing but the tests passes it."""
    argv = _child_argv(Kind.pdf, test_args)
    head = request_head(op, ranges, len(data))
    async with heavy_work.held():
        exchange = await _exchange_with_child(Kind.pdf, argv, head, data, op, len(ranges))
    return _outcome(exchange, ranges)


async def _exchange_with_child(
    kind: Kind, argv: list[str], head: bytes, data: bytes, op: Op, n_ranges: int
) -> _Exchange:
    try:
        cwd = await asyncio.to_thread(tempfile.mkdtemp, prefix="pdf-sandbox-")
    except OSError as exc:
        # A full or unwritable temporary disk: the instance, not the file.
        log.exception(
            "pdf sandbox: could not make the child's directory (kind=%s, errno %s)",
            kind.value,
            exc.errno,
        )
        raise PdfSandboxUnavailable("could not prepare the child") from exc
    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env=dict(_CHILD_ENV),
                cwd=cwd,
            )
        except OSError as exc:
            # EAGAIN, ENOMEM: the instance could not start a process. Ours. The
            # traceback is the spawn's own: it holds no file content and no
            # child output, so it is safe to log in full.
            log.exception(
                "pdf sandbox: could not start the child (kind=%s, errno %s)", kind.value, exc.errno
            )
            raise PdfSandboxUnavailable("could not start the child") from exc

        result = _Result()
        refused: str | None = None
        try:
            async with asyncio.timeout(_deadline(kind)):
                await _talk(proc, head, data, result, op, n_ranges)
                await proc.wait()
        except TimeoutError:
            refused = "deadline"
        except _Refused as exc:
            refused = exc.reason
            if refused == "bad_framing":
                # A result cut short is most often a child that died while
                # writing it. Let it finish dying first, so the log can say how
                # (a memory limit, a signal) rather than blame the framing.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=1.0)
        finally:
            killed = await _kill_and_reap(proc)
    finally:
        await asyncio.to_thread(shutil.rmtree, cwd, True)

    return _Exchange(kind, proc.returncode, result, refused, killed)


async def _talk(
    proc: asyncio.subprocess.Process,
    head: bytes,
    data: bytes,
    result: _Result,
    op: Op,
    n_ranges: int,
) -> None:
    """Write the request and read the result concurrently, so a child that
    answers before it has read everything cannot deadlock against a parent
    still writing."""
    assert proc.stdin is not None and proc.stdout is not None
    feeder = asyncio.ensure_future(_feed(proc.stdin, head, data))
    try:
        await _receive(proc.stdout, result, op, n_ranges)
        await feeder
    finally:
        feeder.cancel()


async def _exactly(stream: asyncio.StreamReader, n: int) -> bytes:
    try:
        return await stream.readexactly(n)
    except asyncio.IncompleteReadError:
        raise _Refused("bad_framing") from None


#: The codes a child may answer each operation with. Anything else, even a
#: code that exists, is a result that child would not have written.
_CODES: dict[Op, frozenset[Code]] = {
    Op.count: frozenset({Code.ok, Code.unreadable, Code.encrypted, Code.too_complex}),
    Op.split: frozenset(
        {Code.ok, Code.unreadable, Code.encrypted, Code.range_invalid, Code.too_complex}
    ),
    Op.photo_to_jpeg: frozenset({Code.ok, Code.unreadable, Code.too_large, Code.too_complex}),
}


def _expected_pieces(op: Op, code: Code, index: int, n_ranges: int) -> int | None:
    """How many pieces an answer of this shape carries, exactly, or None for
    a shape the child never writes: all of them on success, those before the
    failing range on a range failure, none otherwise. A photo's success is
    one JPEG."""
    if code not in _CODES[op]:
        return None
    if code is Code.ok:
        if index != -1:
            return None
        return 1 if op is Op.photo_to_jpeg else n_ranges
    if op is Op.split and code in (Code.range_invalid, Code.unreadable) and index >= 0:
        return index if index < n_ranges else None
    if code is Code.range_invalid or index != -1:
        return None
    return 0


async def _receive(stream: asyncio.StreamReader, result: _Result, op: Op, n_ranges: int) -> None:
    """The child's result, read as it arrives and checked field by field: the
    ready byte, the request marker, the header, every piece's length, then the
    pieces. Nothing is buffered whole and copied, and the announced lengths
    are held to the cap before a single piece is read. Anything the child
    would not have written is refused, never repaired."""
    if await stream.read(len(READY)) != READY:
        return  # exited (or wrote nonsense) before it was ready: see `_settle`
    result.ready = True
    if await stream.read(len(REQUEST_OK)) != REQUEST_OK:
        raise _Refused("bad_framing")  # or an early exit: `_settle` tells which
    result.request_ok = True
    head = await _exactly(stream, RESULT_HEAD.size)
    magic, version, raw_code, raw_detail, index, total, n_pieces = RESULT_HEAD.unpack(head)
    if magic != RESULT_MAGIC or version != VERSION:
        raise _Refused("bad_framing")
    try:
        code, detail = Code(raw_code), Detail(raw_detail)
    except ValueError:
        raise _Refused("bad_framing") from None
    if n_pieces != _expected_pieces(op, code, index, n_ranges):
        raise _Refused("bad_framing")
    raw = await _exactly(stream, PIECE_LENGTH.size * n_pieces)
    lengths = [PIECE_LENGTH.unpack_from(raw, i * PIECE_LENGTH.size)[0] for i in range(n_pieces)]
    cap = PHOTO_OUTPUT_CAP if op is Op.photo_to_jpeg else _output_cap(n_ranges)
    if sum(lengths) > cap:
        raise _Refused("output_cap")
    pieces = [await _exactly(stream, length) for length in lengths]
    if await stream.read(1):
        raise _Refused("bad_framing")  # more than it said
    result.parsed = (code, detail, index, total, pieces)


async def _feed(stdin: asyncio.StreamWriter, head: bytes, data: bytes) -> None:
    """The header, then the file as it is: never joined into one new bytes
    object. The pipe's transport may still buffer whatever part of the file
    the child has not read yet, until `drain` returns."""
    try:
        stdin.write(head)
        stdin.write(data)
        await stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the child stopped reading; how it ended says why
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            stdin.close()


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> bool:
    """Kill the whole group, then wait for the child, shielded so that a
    cancellation arriving now cannot leave it unreaped. The group, not the
    pid, so that anything the child started goes too. Not once the child
    has exited and been reaped: its id may already be someone else's.

    Returns whether this side sent the kill, so the log does not mistake its
    own SIGKILL for a limit the child hit."""
    killed = False
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
            killed = True
    try:
        await asyncio.shield(asyncio.wait_for(proc.wait(), timeout=REAP_SECONDS))
    except TimeoutError:
        log.error("pdf sandbox: child %s was not reaped within %ss", proc.pid, REAP_SECONDS)
    return killed


class _TooComplex(Exception):
    """`_settle` found the file at fault. Turned into the kind's own error.
    `strike` is whether the file's fault is certain (see `PhotoTooComplex`)."""

    def __init__(self, *, strike: bool) -> None:
        super().__init__()
        self.strike = strike


def _ran_out_of_cpu(returncode: int | None) -> bool:
    """SIGXCPU: the soft CPU limit, which only the work itself can use up."""
    return returncode == -signal.SIGXCPU


def _settle(exchange: _Exchange) -> tuple[Code, Detail, int, int, list[bytes]]:
    """Whose fault an ended child was, the same for every kind. Raises
    `PdfSandboxUnavailable` when it was ours, `_TooComplex` when it was the
    file's, and otherwise returns the parsed result."""
    kind, returncode, result = exchange.kind, exchange.returncode, exchange.result
    if not result.ready:
        # Nothing of the file was read before READY, so whatever stopped the
        # child here (a missing account, a broken image) is ours.
        _log(kind, "not_ready", returncode, refused=exchange.refused)
        raise PdfSandboxUnavailable("the child did not start")
    if not result.request_ok:
        # Ready, but it never said it had read the request: whatever ended it
        # (an exit, a signal, a garbled byte) came before the library had the
        # file, so it is ours, retried, and never counted against anyone.
        # Exit 3 lands here too, the child's own word that the request did not
        # parse; after the marker, that number means nothing special.
        _log(kind, "before_request_read", returncode, refused=exchange.refused)
        raise PdfSandboxUnavailable("the child could not read its request")
    _refuse_if_it_ended_badly(exchange)
    if result.parsed is None:
        _log(kind, "bad_framing", returncode)
        raise _TooComplex(strike=False)
    code, detail = result.parsed[0], result.parsed[1]
    if code is Code.too_complex:
        # The child's own verdict, written after it caught the limit itself.
        _log(kind, "too_complex", returncode, limit=detail.name)
        raise _TooComplex(strike=True)
    return result.parsed


def _refuse_if_it_ended_badly(exchange: _Exchange) -> None:
    """After the request was read: a child the parent had to give up on, or
    that did not exit cleanly, is the file's. Counted as a strike only when it
    used up its CPU; nothing else here tells the file apart from the instance."""
    kind, returncode, refused = exchange.kind, exchange.returncode, exchange.refused
    if refused == "bad_framing" and not exchange.killed and returncode not in (0, None):
        # It ended itself, mid-write: say how, with the framing as the context.
        reason = "signal" if returncode < 0 else "exit_status"
        _log(kind, reason, returncode, refused=refused)
        raise _TooComplex(strike=_ran_out_of_cpu(returncode))
    if refused is not None:
        # Named after itself, not after the SIGKILL the parent sent to end it.
        _log(kind, refused, returncode, limit=refused)
        raise _TooComplex(strike=False)
    if returncode != 0:
        reason = "signal" if returncode is not None and returncode < 0 else "exit_status"
        _log(kind, reason, returncode)
        raise _TooComplex(strike=_ran_out_of_cpu(returncode))


def _outcome(
    exchange: _Exchange, ranges: list[tuple[int, int]]
) -> tuple[list[bytes], DocumentProblem | None, int]:
    try:
        code, _detail, index, total, pieces = _settle(exchange)
    except _TooComplex:
        raise PdfTooComplex() from None
    if code is Code.ok:
        return pieces, None, total
    return pieces, _problem(code, index=index, total=total, ranges=ranges), total


def _photo_outcome(exchange: _Exchange) -> bytes:
    try:
        code, detail, _index, _total, pieces = _settle(exchange)
    except _TooComplex as exc:
        raise PhotoTooComplex(strike=exc.strike) from None
    if code is Code.too_large:
        raise PhotoTooLarge()
    if code is Code.unreadable:
        _log_unreadable(detail, exchange.returncode)
        raise PhotoUnreadable()
    (jpeg,) = pieces  # exactly one, checked by `_receive`
    # The child's output is as untrusted as its input: a JPEG, whole, and no
    # bigger than an upload may be, or nothing is stored.
    if not (jpeg.startswith(b"\xff\xd8\xff") and jpeg.endswith(b"\xff\xd9")):
        _log(Kind.photo, "bad_output", exchange.returncode)
        raise PhotoTooComplex(strike=False)
    return jpeg


def _log_unreadable(detail: Detail, returncode: int | None) -> None:
    """Every unreadable photo is logged by the kind of exception that said so,
    so a fault of ours (a class no corrupt photo raises) is never silent. The
    student is still told the photo could not be read: treating it as ours
    would make it free to send again and again."""
    level = logging.ERROR if detail in OUR_FAULT_DETAILS else logging.WARNING
    log.log(
        level,
        "pdf sandbox: photo unreadable: kind=photo detail=%s exit=%s",
        detail.name,
        returncode,
    )


def _problem(
    code: Code, *, index: int, total: int, ranges: Sequence[tuple[int, int]]
) -> DocumentProblem:
    """The tutor's sentence for a code, matching `services/pdf.py` word for word."""
    if code is Code.encrypted:
        return DocumentProblem(_ENCRYPTED)
    if index < 0:
        return DocumentProblem(_UNREADABLE)
    first, last = ranges[index]
    if code is Code.unreadable:
        return DocumentProblem(f"Pages {first}-{last} of this PDF could not be read.")
    if first < 1:
        return DocumentProblem(f"Pages start at 1, but the range starts at {first}.")
    if last < first:
        return DocumentProblem(f"Page range {first}-{last} ends before it starts.")
    return DocumentProblem(f"Page range {first}-{last} runs past the last page ({total}).")


def _signal_name(returncode: int | None) -> str | None:
    if returncode is None or returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return str(-returncode)


def _limit_for_signal(signum: int) -> str:
    """The limit a signal most likely means. SIGKILL is the hard CPU limit or
    the kernel's out-of-memory killer, which `oom_score_adj` points at the
    child; the log cannot tell those two apart."""
    return {
        signal.SIGXCPU: "cpu_soft",
        signal.SIGKILL: "cpu_hard_or_oom_killer",
        signal.SIGXFSZ: "file_size",
    }.get(signal.Signals(signum), "none_identified")


def _log(
    kind: Kind,
    reason: str,
    returncode: int | None,
    *,
    refused: str | None = None,
    limit: str | None = None,
) -> None:
    """One line per refusal: which kind, why, how the child ended, and which
    limit. Never the child's output and never the file, which are the
    uploader's."""
    name = _signal_name(returncode)
    if limit is None and returncode is not None and returncode < 0:
        with contextlib.suppress(ValueError):
            limit = _limit_for_signal(-returncode)
    log.warning(
        "pdf sandbox refused a file: kind=%s reason=%s exit=%s signal=%s limit=%s%s",
        kind.value,
        reason,
        returncode,
        name,
        limit,
        f" after={refused}" if refused else "",
    )
