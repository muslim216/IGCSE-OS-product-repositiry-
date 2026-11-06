"""Reading an uploaded PDF in a separate, limited process.

Every page count and every split goes through here. Each call starts
`services/pdf_child.py`, hands it the file, and reads back a small framed
result. The child is the only process that runs the PDF library, so a file
that makes the library run away costs that child and nothing else: before
this, it ran inside the API process, where it could hold the interpreter or
get the whole instance killed for memory, stopping every request and job.

**What the parent guarantees, whatever the child does:**

- It starts with no inherited descriptors, in its own process group, with
  stderr discarded, a minimal environment and an empty temporary directory.
  The empty environment is defence in depth. The boundary is the separate
  process, its limits, and, when the API runs as root (the image has no
  `USER` yet, T-009), the separate `pdfsandbox` account the child drops to.
  T-009 must keep a separate account for this child when it gives the API one.
- It writes the request and reads the result at the same time, so neither
  side can block the other, and it caps what it reads.
- It allows `DEADLINE_SECONDS` per child, counted from when it holds the
  heavy-work lock (`services/heavy_work.py`), so waiting in line behind
  another file is never the file's fault.
- However the call ends (result, deadline, too much output, cancellation),
  `finally` kills the child's process group and waits for it, shielded, so
  no child is ever left running or unreaped.
- **The child sends codes; every message is written here.**

**What a failure means.** A file that hits a limit, is killed by a signal,
overruns the deadline or the output cap, or sends a malformed result is
`PdfTooComplex`, which is never retried: the same file would do the same
again. A child that could not be started, or died before saying it was ready
(before it had read any of the file), is `PdfSandboxUnavailable`, which is
ours and is retried. The log names the reason, the exit status and the limit,
never the child's output or the file.
"""

import asyncio
import contextlib
import logging
import os
import pwd
import shutil
import signal
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass

from app.services import heavy_work
from app.services.job_errors import DocumentProblem
from app.services.pdf_child import (
    MAX_RANGES,
    PIECE_LENGTH,
    READY,
    RESULT_HEAD,
    RESULT_MAGIC,
    VERSION,
    Code,
    Detail,
    Op,
    encode_request,
)
from app.services.storage import MAX_FILE_BYTES

log = logging.getLogger(__name__)

#: Wall-clock time one child may take once it holds the heavy-work lock. Above
#: the child's 65-second CPU limit, so a CPU-bound child is stopped by that
#: first and the log says so; this catches one that waits instead of working.
DEADLINE_SECONDS = 90.0
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

_said_same_user = [False]


class PdfTooComplex(DocumentProblem):
    """The file hit one of the child's limits, or made it misbehave.

    Never retried: the same bytes would do the same again, and a retry is a
    second chance to tie up the instance. `safe_to_show` is inherited, so the
    sentence reaches the tutor."""

    job_retryable = False

    def __init__(self) -> None:
        super().__init__(TOO_COMPLEX_MESSAGE)


class PdfSandboxUnavailable(RuntimeError):
    """The child could not be started, or died before it read the file. Ours,
    not the file's: retried, and the tutor sees the generic sentence."""


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


def _child_argv(test_args: Sequence[str]) -> list[str]:
    argv = [sys.executable, "-I", "-B", "-m", "app.services.pdf_child"]
    if os.geteuid() == 0:
        try:
            account = pwd.getpwnam(SANDBOX_USER)
        except KeyError:
            log.error("pdf sandbox: running as root and the %s account is missing", SANDBOX_USER)
            raise PdfSandboxUnavailable("no sandbox account") from None
        if account.pw_uid == 0 or account.pw_gid == 0:
            log.error("pdf sandbox: the %s account is root", SANDBOX_USER)
            raise PdfSandboxUnavailable("sandbox account is root")
        argv += ["--uid", str(account.pw_uid), "--gid", str(account.pw_gid)]
    else:
        _say_same_user_once()
    return [*argv, *test_args]


def _say_same_user_once() -> None:
    """Local runs, CI, and the API once T-009 gives it an account of its own:
    the child cannot change user, so it says so, once per process."""
    if not _said_same_user[0]:
        _said_same_user[0] = True
        log.info("pdf sandbox: the API is not root, so the child runs as the same user")


def _output_cap(n_ranges: int) -> int:
    """The most the parent reads from one child. Ranges may overlap, but a
    booklet's slices sum to roughly its own size, so twice the largest upload
    is room for every genuine split."""
    return len(READY) + RESULT_HEAD.size + PIECE_LENGTH.size * n_ranges + 2 * MAX_FILE_BYTES


class _Refused(Exception):
    """Why the parent gave up on a child. Never leaves this module."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _run(
    op: Op, data: bytes, ranges: list[tuple[int, int]], *, test_args: Sequence[str] = ()
) -> tuple[list[bytes], DocumentProblem | None, int]:
    """One child, start to finish. `test_args` turns on the child's test-only
    hooks; nothing but the tests passes it."""
    argv = _child_argv(test_args)
    async with heavy_work.held():
        # Encoded once in line, so a call waiting for the lock does not hold a
        # second copy of the file while it waits.
        return await _exchange_with_child(argv, encode_request(op, ranges, data), ranges)


async def _exchange_with_child(
    argv: list[str], request: bytes, ranges: list[tuple[int, int]]
) -> tuple[list[bytes], DocumentProblem | None, int]:
    cwd = await asyncio.to_thread(tempfile.mkdtemp, prefix="pdf-sandbox-")
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
            # EAGAIN, ENOMEM: the instance could not start a process. Ours.
            log.error("pdf sandbox: could not start the child (errno %s)", exc.errno)
            raise PdfSandboxUnavailable("could not start the child") from exc

        received = bytearray()
        refused: str | None = None
        try:
            async with asyncio.timeout(DEADLINE_SECONDS):
                await _talk(proc, request, received, _output_cap(len(ranges)))
                await proc.wait()
        except TimeoutError:
            refused = "deadline"
        except _Refused as exc:
            refused = exc.reason
        finally:
            await _kill_and_reap(proc)
    finally:
        await asyncio.to_thread(shutil.rmtree, cwd, True)

    return _outcome(proc.returncode, bytes(received), refused, ranges)


async def _talk(
    proc: asyncio.subprocess.Process, request: bytes, received: bytearray, cap: int
) -> None:
    """Write the request and read the result concurrently, so a child that
    answers before it has read everything cannot deadlock against a parent
    still writing. `received` is filled in place, so the caller can tell after
    a deadline whether the child ever said it was ready."""
    assert proc.stdin is not None and proc.stdout is not None
    feeder = asyncio.ensure_future(_feed(proc.stdin, request))
    try:
        while chunk := await proc.stdout.read(1 << 16):
            received += chunk
            if len(received) > cap:
                raise _Refused("output_cap")
        await feeder
    finally:
        feeder.cancel()


async def _feed(stdin: asyncio.StreamWriter, request: bytes) -> None:
    try:
        stdin.write(request)
        await stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # the child stopped reading; how it ended says why
    finally:
        with contextlib.suppress(OSError, RuntimeError):
            stdin.close()


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    """Kill the whole group, then wait for the child, shielded so that a
    cancellation arriving now cannot leave it unreaped. The group, not the
    pid, so that anything the child started goes too."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    try:
        await asyncio.shield(asyncio.wait_for(proc.wait(), timeout=REAP_SECONDS))
    except TimeoutError:
        log.error("pdf sandbox: child %s was not reaped within %ss", proc.pid, REAP_SECONDS)


def _outcome(
    returncode: int | None,
    received: bytes,
    refused: str | None,
    ranges: list[tuple[int, int]],
) -> tuple[list[bytes], DocumentProblem | None, int]:
    ready = received.startswith(READY)
    if not ready:
        # Nothing of the file was read before READY, so whatever stopped the
        # child here (a missing account, a broken image) is ours.
        _log("not_ready", returncode, refused=refused)
        raise PdfSandboxUnavailable("the child did not start")
    if refused is not None:
        # Named after itself, not after the SIGKILL the parent sent to end it.
        _log(refused, returncode, limit=refused)
        raise PdfTooComplex()
    if returncode != 0:
        reason = "signal" if returncode is not None and returncode < 0 else "exit_status"
        _log(reason, returncode)
        raise PdfTooComplex()
    try:
        code, detail, index, total, pieces = _parse(received[len(READY) :], len(ranges))
    except _Refused as exc:
        _log(exc.reason, returncode)
        raise PdfTooComplex() from None
    if code is Code.too_complex:
        _log("too_complex", returncode, limit=detail.name)
        raise PdfTooComplex()
    if code is Code.ok:
        return pieces, None, total
    return pieces, _problem(code, index=index, total=total, ranges=ranges), total


def _parse(body: bytes, n_ranges: int) -> tuple[Code, Detail, int, int, list[bytes]]:
    """The child's result, checked field by field. Anything the child would not
    have written is refused, never repaired."""
    if len(body) < RESULT_HEAD.size:
        raise _Refused("bad_framing")
    magic, version, raw_code, raw_detail, index, total, n_pieces = RESULT_HEAD.unpack_from(body)
    if magic != RESULT_MAGIC or version != VERSION:
        raise _Refused("bad_framing")
    try:
        code, detail = Code(raw_code), Detail(raw_detail)
    except ValueError:
        raise _Refused("bad_framing") from None
    # How many pieces each outcome carries, exactly: all of them on success,
    # those before the failing range on a range failure, none otherwise.
    if code is Code.ok:
        expected = n_ranges
        valid_index = index == -1
    elif code in (Code.range_invalid, Code.unreadable) and index >= 0:
        expected = index
        valid_index = index < n_ranges
    else:
        expected = 0
        valid_index = index == -1
    if n_pieces != expected or not valid_index:
        raise _Refused("bad_framing")
    offset = RESULT_HEAD.size
    if len(body) < offset + PIECE_LENGTH.size * n_pieces:
        raise _Refused("bad_framing")
    lengths = [
        PIECE_LENGTH.unpack_from(body, offset + i * PIECE_LENGTH.size)[0] for i in range(n_pieces)
    ]
    offset += PIECE_LENGTH.size * n_pieces
    if offset + sum(lengths) != len(body):
        raise _Refused("bad_framing")
    pieces = []
    for length in lengths:
        pieces.append(body[offset : offset + length])
        offset += length
    return code, detail, index, total, pieces


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
    reason: str,
    returncode: int | None,
    *,
    refused: str | None = None,
    limit: str | None = None,
) -> None:
    """One line per refusal: why, how the child ended, and which limit. Never
    the child's output and never the file, which are the uploader's."""
    name = _signal_name(returncode)
    if limit is None and returncode is not None and returncode < 0:
        with contextlib.suppress(ValueError):
            limit = _limit_for_signal(-returncode)
    log.warning(
        "pdf sandbox refused a file: reason=%s exit=%s signal=%s limit=%s%s",
        reason,
        returncode,
        name,
        limit,
        f" after={refused}" if refused else "",
    )
