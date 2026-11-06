"""T-027: uploaded PDFs are read in a separate, limited process.

`services/pdf_sandbox.py` starts `services/pdf_child.py` for every count or
split, so a file that makes the PDF library run away costs that one child, never
the process serving every request and job.

Every test that starts a real child runs under the default event loop and under
uvloop, because uvloop is what production runs and its subprocess support is
not the standard library's. The tests marked Linux-only need `RLIMIT_AS` and
`/proc`; they skip on macOS and run in CI.
"""

import asyncio
import errno
import logging
import os
import signal
import sys
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
import uvloop
from pypdf import PdfWriter

from app.services import heavy_work, pdf, pdf_child, pdf_sandbox, storage
from app.services.job_errors import GENERIC_JOB_ERROR, DocumentProblem, safe_job_error
from app.services.pdf_sandbox import PdfSandboxUnavailable, PdfTooComplex
from app.workers.jobs import is_permanent
from tests.test_booklets import _pdf, _widths

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="RLIMIT_AS, oom_score_adj and /proc are Linux-only; CI runs these",
)


@pytest.fixture(
    params=[
        pytest.param(asyncio.new_event_loop, id="asyncio"),
        pytest.param(uvloop.new_event_loop, id="uvloop"),
    ]
)
def run(request):
    """Run a coroutine to completion on a fresh loop of the parametrized kind."""

    def _run(coro):
        with asyncio.Runner(loop_factory=request.param) as runner:
            return runner.run(coro)

    return _run


@pytest.fixture
def spawned(monkeypatch):
    """Every child the sandbox starts, with the arguments it was started with.
    The spawn itself is the real one."""
    seen: list[SimpleNamespace] = []
    real = asyncio.create_subprocess_exec

    async def _spy(*args, **kwargs):
        proc = await real(*args, **kwargs)
        seen.append(SimpleNamespace(args=args, kwargs=kwargs, pid=proc.pid))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spy)
    return seen


def _gone(pid: int) -> bool:
    """No process with this id, and no process left in its group."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        return False
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _message(call) -> str:
    with pytest.raises(DocumentProblem) as caught:
        call()
    return str(caught.value)


async def _wait_for(predicate, *, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.05)


# --- 1. a normal PDF ----------------------------------------------------------


def test_count_and_split_match_the_library_byte_for_byte(run):
    data = _pdf(6)
    ranges = [(1, 2), (3, 6), (2, 4)]

    count = run(pdf_sandbox.page_count(data))
    result = run(pdf_sandbox.split(data, ranges))

    assert count == pdf.page_count(data) == 6
    assert result.failure is None
    assert result.pieces == [pdf.extract_pages(data, f, last) for f, last in ranges]
    assert _widths(result.pieces[1]) == [120, 130, 140, 150]


def test_a_split_with_no_ranges_starts_no_child(run, spawned):
    result = run(pdf_sandbox.split(_pdf(2), []))
    assert result.pieces == []
    assert result.failure is None
    assert spawned == []


# --- 2. broken and encrypted PDFs keep today's messages -----------------------


def test_a_broken_pdf_gives_todays_message(run):
    data = b"%PDF-1.4 not really a pdf"
    expected = _message(lambda: pdf.page_count(data))

    with pytest.raises(DocumentProblem) as caught:
        run(pdf_sandbox.page_count(data))
    assert str(caught.value) == expected == "This file could not be read as a PDF."
    assert not isinstance(caught.value, PdfTooComplex)

    result = run(pdf_sandbox.split(data, [(1, 1)]))
    assert result.pieces == []
    assert str(result.failure) == _message(lambda: pdf.extract_pages(data, 1, 1))


def test_an_encrypted_pdf_gives_todays_message(run):
    data = _encrypted_pdf()
    expected = _message(lambda: pdf.page_count(data))

    with pytest.raises(DocumentProblem) as caught:
        run(pdf_sandbox.page_count(data))
    assert str(caught.value) == expected
    assert "password-protected" in expected


@pytest.mark.parametrize("bad", [(0, 2), (4, 3), (5, 99)])
def test_a_range_that_does_not_fit_gives_todays_message_after_the_good_ones(run, bad):
    """The pieces before a bad range come back, so a split that fails part-way
    behaves as it did when each range was cut on its own."""
    data = _pdf(6)
    result = run(pdf_sandbox.split(data, [(1, 2), bad, (3, 4)]))

    assert result.pieces == [pdf.extract_pages(data, 1, 2)]
    assert str(result.failure) == _message(lambda: pdf.extract_pages(data, *bad))
    assert safe_job_error(result.failure) == str(result.failure)


def test_a_page_that_cannot_be_read_names_its_range():
    """A file that parses but fails on one page's content is told apart from a
    file that does not parse at all, as `pdf.extract_pages` tells them apart."""
    problem = pdf_sandbox._problem(
        pdf_child.Code.unreadable, index=1, total=6, ranges=[(1, 2), (3, 4)]
    )
    assert str(problem) == "Pages 3-4 of this PDF could not be read."
    whole = pdf_sandbox._problem(pdf_child.Code.unreadable, index=-1, total=0, ranges=[(1, 2)])
    assert str(whole) == "This file could not be read as a PDF."


# --- 3. the deadline -----------------------------------------------------------


def test_a_child_held_past_the_deadline_is_killed(run, spawned, monkeypatch, caplog):
    monkeypatch.setattr(pdf_sandbox, "DEADLINE_SECONDS", 2.0)
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    started = time.monotonic()

    with pytest.raises(PdfTooComplex):
        run(pdf_sandbox._run(pdf_child.Op.count, _pdf(1), [], test_args=("--test-hold", "60")))

    assert time.monotonic() - started < 20
    assert len(spawned) == 1
    assert _gone(spawned[0].pid)
    assert "deadline" in caplog.text


def test_the_deadline_starts_once_the_lock_is_held(run, spawned, monkeypatch):
    """Waiting in line behind another file is not the file's fault."""
    monkeypatch.setattr(pdf_sandbox, "DEADLINE_SECONDS", 3.0)
    data = _pdf(3)

    async def _scenario():
        release = await heavy_work.acquire()
        task = asyncio.create_task(pdf_sandbox.page_count(data))
        await asyncio.sleep(3.5)
        assert not task.done()
        assert spawned == [], "a child started while another held the lock"
        release()
        return await task

    assert run(_scenario()) == 3


# --- 4. memory -----------------------------------------------------------------


@linux_only
def test_an_allocation_past_the_limit_is_refused_and_the_parent_survives(run, spawned):
    with pytest.raises(PdfTooComplex):
        run(
            pdf_sandbox._run(
                pdf_child.Op.count, _pdf(1), [], test_args=("--test-allocate-mb", "400")
            )
        )
    assert _gone(spawned[0].pid)
    # And the parent carries on reading files.
    assert run(pdf_sandbox.page_count(_pdf(2))) == 2


@linux_only
def test_the_child_runs_under_its_limits(run, spawned):
    """Read off the live child, not off the code that set them."""

    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._run(pdf_child.Op.count, _pdf(1), [], test_args=("--test-hold", "30"))
        )
        await _wait_for(lambda: bool(spawned))
        pid = spawned[0].pid
        # The hold starts after the request is read, which is after the limits.
        await _wait_for(lambda: _limit_line(pid, "Max open files").split()[3] == "16")
        limits = {
            name: _limit_line(pid, name).split()[-3:-1]
            for name in (
                "Max address space",
                "Max cpu time",
                "Max core file size",
                "Max file size",
                "Max open files",
            )
        }
        oom = _proc_file(pid, "oom_score_adj").decode().strip()
        environ = _proc_file(pid, "environ")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return limits, oom, environ

    limits, oom, environ = run(_scenario())
    assert limits["Max address space"] == [str(256 * 1024 * 1024)] * 2
    assert limits["Max cpu time"] == ["60", "65"]
    assert limits["Max core file size"] == ["0", "0"]
    assert limits["Max file size"] == ["0", "0"]
    assert limits["Max open files"] == ["16", "16"]
    assert oom == "1000"
    for secret in (b"DATABASE_URL", b"JWT_SECRET", b"_API_KEY"):
        assert secret not in environ


def _proc_file(pid: int, name: str) -> bytes:
    with open(f"/proc/{pid}/{name}", "rb") as f:
        return f.read()


def _limit_line(pid: int, name: str) -> str:
    with open(f"/proc/{pid}/limits") as f:
        for line in f:
            if line.startswith(name):
                return line
    raise AssertionError(f"{name} not in /proc/{pid}/limits")


# --- 5. output and framing -------------------------------------------------------


def test_output_over_the_cap_is_refused(run, monkeypatch, caplog):
    monkeypatch.setattr(pdf_sandbox, "_output_cap", lambda n_ranges: 256)
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    with pytest.raises(PdfTooComplex):
        run(pdf_sandbox.split(_pdf(6), [(1, 6)]))
    # Its own name in the log, so a genuine booklet whose ranges overlap is
    # told apart from a hostile one.
    assert "output_cap" in caplog.text


def test_the_output_cap_allows_twice_the_largest_upload():
    assert pdf_sandbox._output_cap(60) >= 2 * storage.MAX_FILE_BYTES
    assert pdf_child.MAX_INPUT_BYTES == storage.MAX_FILE_BYTES


def _fake_child(monkeypatch, code: str) -> None:
    monkeypatch.setattr(
        pdf_sandbox, "_child_argv", lambda test_args=(): [sys.executable, "-I", "-c", code]
    )


_READY = pdf_child.READY


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"nonsense" * 10, id="garbage"),
        pytest.param(
            pdf_child.RESULT_HEAD.pack(
                pdf_child.RESULT_MAGIC, pdf_child.VERSION, 0, 0, -1, 1, 10**6
            ),
            id="header-claims-a-million-pieces",
        ),
        pytest.param(
            pdf_child.RESULT_HEAD.pack(pdf_child.RESULT_MAGIC, pdf_child.VERSION, 0, 0, -1, 1, 1)
            + pdf_child.PIECE_LENGTH.pack(10**9),
            id="piece-longer-than-the-output",
        ),
        pytest.param(
            pdf_child.RESULT_HEAD.pack(pdf_child.RESULT_MAGIC, pdf_child.VERSION, 0, 0, -1, 1, 1)
            + pdf_child.PIECE_LENGTH.pack(3)
            + b"abc"
            + b"trailing",
            id="trailing-bytes",
        ),
        pytest.param(
            pdf_child.RESULT_HEAD.pack(pdf_child.RESULT_MAGIC, pdf_child.VERSION, 99, 0, -1, 1, 0),
            id="unknown-code",
        ),
        pytest.param(
            pdf_child.RESULT_HEAD.pack(b"XXXX", pdf_child.VERSION, 0, 0, -1, 1, 0),
            id="wrong-magic",
        ),
    ],
)
def test_bad_framing_is_refused(run, monkeypatch, caplog, body):
    payload = _READY + body
    _fake_child(
        monkeypatch,
        f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({payload!r})",
    )
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    with pytest.raises(PdfTooComplex):
        run(pdf_sandbox.split(_pdf(1), [(1, 1)]))
    assert "bad_framing" in caplog.text


def test_a_child_killed_by_a_signal_is_too_complex(run, monkeypatch, caplog):
    _fake_child(
        monkeypatch,
        "import os, signal, sys; sys.stdout.buffer.write(b'R'); sys.stdout.flush(); "
        "os.kill(os.getpid(), signal.SIGTERM)",
    )
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    with pytest.raises(PdfTooComplex):
        run(pdf_sandbox.page_count(_pdf(1)))
    assert "SIGTERM" in caplog.text


def test_a_child_that_never_gets_ready_is_our_failure_and_retryable(run, monkeypatch):
    """Nothing of the file has been read before the child says it is ready, so
    a child that dies first is a broken image or deploy, not a hostile file."""
    _fake_child(monkeypatch, "import sys; sys.exit(3)")
    with pytest.raises(PdfSandboxUnavailable) as caught:
        run(pdf_sandbox.page_count(_pdf(1)))
    assert not is_permanent(caught.value)


def test_an_error_result_that_carries_bytes_is_refused(run, monkeypatch):
    """An error is a code and nothing else: there is no field for text, and an
    error frame with a piece attached is not a frame the child writes."""
    head = pdf_child.RESULT_HEAD.pack(
        pdf_child.RESULT_MAGIC, pdf_child.VERSION, int(pdf_child.Code.unreadable), 0, -1, 0, 1
    )
    payload = _READY + head + pdf_child.PIECE_LENGTH.pack(5) + b"hello"
    _fake_child(
        monkeypatch, f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({payload!r})"
    )
    with pytest.raises(PdfTooComplex):
        run(pdf_sandbox.page_count(_pdf(1)))


# --- 6. the child's environment ----------------------------------------------------


def test_the_child_gets_a_minimal_environment_and_its_own_directory(run, spawned, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/avora")
    monkeypatch.setenv("JWT_SECRET", "a-secret-the-child-must-not-see")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-child")
    monkeypatch.setenv("GEMINI_API_KEY", "not-for-the-child-either")

    assert run(pdf_sandbox.page_count(_pdf(1))) == 1

    (child,) = spawned
    assert list(child.args[:5]) == [sys.executable, "-I", "-B", "-m", "app.services.pdf_child"]
    env = child.kwargs["env"]
    assert set(env) <= {"PATH", "MALLOC_ARENA_MAX", "PYTHONHASHSEED"}
    assert env["MALLOC_ARENA_MAX"] == "2"
    assert child.kwargs["close_fds"] is True
    assert child.kwargs["start_new_session"] is True
    assert child.kwargs["stderr"] == asyncio.subprocess.DEVNULL
    assert "pass_fds" not in child.kwargs
    # Never the API's own directory, and gone once the child is.
    assert os.path.realpath(child.kwargs["cwd"]) != os.path.realpath(os.getcwd())
    assert not os.path.exists(child.kwargs["cwd"])
    # The child drops privileges itself: uvloop does not take user= or group=.
    assert not {"user", "group", "extra_groups"} & set(child.kwargs)


def test_a_root_parent_hands_the_child_the_sandbox_account(monkeypatch):
    monkeypatch.setattr(pdf_sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        pdf_sandbox.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid=4242, pw_gid=4343) if name == "pdfsandbox" else None,
    )
    argv = pdf_sandbox._child_argv(())
    assert argv[argv.index("--uid") + 1] == "4242"
    assert argv[argv.index("--gid") + 1] == "4343"


def test_a_root_parent_without_the_sandbox_account_runs_nothing(run, spawned, monkeypatch):
    """Never run the child as root because an account is missing."""
    monkeypatch.setattr(pdf_sandbox.os, "geteuid", lambda: 0)

    def _missing(name):
        raise KeyError(name)

    monkeypatch.setattr(pdf_sandbox.pwd, "getpwnam", _missing)
    with pytest.raises(PdfSandboxUnavailable):
        run(pdf_sandbox.page_count(_pdf(1)))
    assert spawned == []


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") and os.geteuid() == 0),
    reason="needs a root parent on Linux; the CI image test checks the uid there",
)
def test_as_root_the_child_is_not_root(run, spawned):
    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._run(pdf_child.Op.count, _pdf(1), [], test_args=("--test-hold", "30"))
        )
        await _wait_for(lambda: bool(spawned))
        pid = spawned[0].pid
        await _wait_for(lambda: _status_uid(pid) != 0)
        uid = _status_uid(pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return uid

    assert run(_scenario()) != 0


def _status_uid(pid: int) -> int:
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("Uid:"):
                return int(line.split()[1])
    raise AssertionError("no Uid line")


# --- the child's own start-up, in process ------------------------------------------


def test_the_child_sets_itself_up_before_it_reads_the_file(monkeypatch):
    """`oom_score_adj`, then the privilege drop, then the limits, then ready, and
    only then the request."""
    steps: list[str] = []
    monkeypatch.setattr(pdf_child, "_raise_oom_score", lambda: steps.append("oom"))
    monkeypatch.setattr(pdf_child, "_drop_privileges", lambda uid, gid: steps.append("drop"))
    monkeypatch.setattr(pdf_child, "_set_limits", lambda: steps.append("limits"))

    request = pdf_child.encode_request(pdf_child.Op.count, [], _pdf(2))

    class _Stdin(BytesIO):
        def read(self, *args):
            if "read" not in steps:
                steps.append("read")
            return super().read(*args)

    class _Stdout(BytesIO):
        def write(self, b):
            steps.append("ready" if bytes(b) == pdf_child.READY else "write")
            return super().write(b)

    out = _Stdout()
    assert pdf_child.main([], stdin=_Stdin(request), stdout=out) == 0
    assert steps[:5] == ["oom", "drop", "limits", "ready", "read"]
    assert out.getvalue().startswith(pdf_child.READY)


def test_the_child_sets_soft_equal_to_hard(monkeypatch):
    calls: dict[int, tuple[int, int]] = {}
    monkeypatch.setattr(
        pdf_child.resource, "setrlimit", lambda res, lim: calls.__setitem__(res, lim)
    )
    pdf_child._set_limits()
    r = pdf_child.resource
    assert calls[r.RLIMIT_AS] == (256 * 1024 * 1024, 256 * 1024 * 1024)
    assert calls[r.RLIMIT_CPU] == (60, 65)
    assert calls[r.RLIMIT_CORE] == (0, 0)
    assert calls[r.RLIMIT_FSIZE] == (0, 0)
    assert calls[r.RLIMIT_NOFILE] == (16, 16)


def test_a_root_child_drops_to_the_given_account_in_order(monkeypatch):
    steps: list[tuple] = []
    state = {"uid": 0}
    monkeypatch.setattr(pdf_child.os, "getuid", lambda: state["uid"])
    monkeypatch.setattr(pdf_child.os, "geteuid", lambda: state["uid"])
    monkeypatch.setattr(pdf_child.os, "setgroups", lambda g: steps.append(("setgroups", g)))
    monkeypatch.setattr(pdf_child.os, "setgid", lambda g: steps.append(("setgid", g)))

    def _setuid(u):
        steps.append(("setuid", u))
        state["uid"] = u

    monkeypatch.setattr(pdf_child.os, "setuid", _setuid)
    pdf_child._drop_privileges(4242, 4343)
    assert steps == [("setgroups", []), ("setgid", 4343), ("setuid", 4242)]


def test_a_root_child_with_no_account_refuses_to_run(monkeypatch):
    monkeypatch.setattr(pdf_child.os, "getuid", lambda: 0)
    monkeypatch.setattr(pdf_child.os, "geteuid", lambda: 0)
    with pytest.raises(pdf_child.SetupFailed):
        pdf_child._drop_privileges(None, None)
    with pytest.raises(pdf_child.SetupFailed):
        pdf_child._drop_privileges(0, 0)


def test_a_root_child_that_stays_root_refuses_to_run(monkeypatch):
    monkeypatch.setattr(pdf_child.os, "getuid", lambda: 0)
    monkeypatch.setattr(pdf_child.os, "geteuid", lambda: 0)
    for name in ("setgroups", "setgid", "setuid"):
        monkeypatch.setattr(pdf_child.os, name, lambda *_: None)
    with pytest.raises(pdf_child.SetupFailed):
        pdf_child._drop_privileges(4242, 4343)


def test_memory_and_recursion_are_too_complex_not_unreadable(monkeypatch):
    for exc in (MemoryError, RecursionError):

        def _boom(data, _exc=exc):
            raise _exc()

        monkeypatch.setattr(pdf, "page_count", _boom)
        out = BytesIO()
        request = pdf_child.encode_request(pdf_child.Op.count, [], b"%PDF-1.4")
        monkeypatch.setattr(pdf_child, "_raise_oom_score", lambda: None)
        monkeypatch.setattr(pdf_child, "_drop_privileges", lambda uid, gid: None)
        monkeypatch.setattr(pdf_child, "_set_limits", lambda: None)
        assert pdf_child.main([], stdin=BytesIO(request), stdout=out) == 0
        head = pdf_child.RESULT_HEAD.unpack_from(out.getvalue(), len(pdf_child.READY))
        assert head[2] == pdf_child.Code.too_complex


# --- 7. what is retried ---------------------------------------------------------------


def test_a_spawn_failure_is_retryable_and_too_complex_is_not(run, monkeypatch):
    async def _no_room(*args, **kwargs):
        raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _no_room)
    with pytest.raises(PdfSandboxUnavailable) as caught:
        run(pdf_sandbox.page_count(_pdf(1)))
    assert not is_permanent(caught.value)
    # Ours, so the tutor sees the generic sentence, not the OS error.
    assert safe_job_error(caught.value) == GENERIC_JOB_ERROR

    too_complex = PdfTooComplex()
    assert is_permanent(too_complex)
    assert isinstance(too_complex, DocumentProblem)
    assert safe_job_error(too_complex) == "This PDF is too complex to read safely."


# --- 8. cancellation ---------------------------------------------------------------------


def test_cancelling_mid_run_reaps_the_child_and_frees_the_lock(run, spawned):
    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._run(pdf_child.Op.count, _pdf(1), [], test_args=("--test-hold", "60"))
        )
        await _wait_for(lambda: bool(spawned))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not heavy_work.lock_for_this_loop().locked()
        return spawned[0].pid

    pid = run(_scenario())
    assert _gone(pid)


# --- a large genuine booklet ----------------------------------------------------------------


def _large_booklet(pages: int = 300, target_bytes: int = 19 * 1024 * 1024) -> bytes:
    """About the largest booklet a tutor can upload: 300 pages, each carrying an
    incompressible stream, the way a scanned page carries its image."""
    from pypdf.generic import DecodedStreamObject, NameObject

    per_page = target_bytes // pages
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=595, height=842)
        stream = DecodedStreamObject()
        # Comment lines are valid content and survive a copy unchanged.
        stream.set_data(b"%" + os.urandom(per_page // 2).hex().encode()[: per_page - 2] + b"\n")
        page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_a_large_genuine_booklet_fits_the_limits():
    """The limit is meant to refuse hostile files, not real ones. On Linux this
    runs under the real 256 MB address-space limit; the peak is printed so it
    can be compared with that limit."""
    import resource

    data = _large_booklet()
    assert len(data) <= storage.MAX_FILE_BYTES
    ranges = [(i, i + 9) for i in range(1, 301, 10)]

    async def _scenario():
        count = await pdf_sandbox.page_count(data)
        result = await pdf_sandbox.split(data, ranges)
        return count, result

    started = time.monotonic()
    with asyncio.Runner() as runner:
        count, result = runner.run(_scenario())
    elapsed = time.monotonic() - started
    assert count == 300
    assert result.failure is None
    assert len(result.pieces) == 30
    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # Kilobytes on Linux, bytes on macOS.
    peak_mb = peak / 1024 if sys.platform.startswith("linux") else peak / (1024 * 1024)
    print(
        f"\nlarge booklet: {len(data) / 1e6:.1f} MB, child peak RSS {peak_mb:.0f} MB, {elapsed:.1f}s"
    )
    assert peak_mb < 256


def test_the_sandbox_signals_are_named_in_the_log():
    assert pdf_sandbox._signal_name(-signal.SIGXCPU) == "SIGXCPU"
    assert pdf_sandbox._limit_for_signal(signal.SIGXCPU) == "cpu_soft"
    assert pdf_sandbox._limit_for_signal(signal.SIGKILL) == "cpu_hard_or_oom_killer"
