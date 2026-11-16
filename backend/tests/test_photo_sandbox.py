"""T-030: iPhone photos are decoded in the separate, limited process.

The photo decoder is native code, reachable by any student with one upload.
`services/pdf_sandbox.py` now starts `services/pdf_child.py --kind photo` for
every HEIC, so a photo that makes the decoder run away costs that one child,
never the process serving every request and job. These tests are the photo
side of `tests/test_pdf_sandbox.py`, which still covers the shared machinery.

The tests marked Linux-only need `RLIMIT_AS` and `/proc`; they skip on macOS
and run in CI.
"""

import asyncio
import dataclasses
import errno
import io
import json
import logging
import os
import sys
import time
from io import BytesIO
from types import SimpleNamespace

import pytest
import uvloop

from app.services import heavy_work, pdf_child, pdf_sandbox, photo, rate_limit, storage
from app.services.heavy_work import HeavyWorkBusy
from app.services.pdf_child import Code, Kind, Op
from app.services.pdf_sandbox import (
    PdfSandboxUnavailable,
    PhotoTooComplex,
    PhotoTooLarge,
    PhotoUnreadable,
)
from app.workers.jobs import is_permanent
from tests.test_booklets import _pdf
from tests.test_storage import _heic

linux_only = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="RLIMIT_AS, oom_score_adj and /proc are Linux-only; CI runs these",
)

UNREADABLE = "That photo couldn't be read. Try saving it as JPEG and uploading again."
UNSAFE = "That photo couldn't be read safely. Try saving it as JPEG and uploading again."
STRUCK_OUT = "That photo couldn't be read safely. Save it as JPEG and upload it again."


@pytest.fixture(
    params=[
        pytest.param(asyncio.new_event_loop, id="asyncio"),
        pytest.param(uvloop.new_event_loop, id="uvloop"),
    ]
)
def run(request):
    def _run(coro):
        with asyncio.Runner(loop_factory=request.param) as runner:
            return runner.run(coro)

    return _run


@pytest.fixture
def spawned(monkeypatch):
    """Every child the sandbox starts, with its arguments. The spawn is real."""
    seen: list[SimpleNamespace] = []
    real = asyncio.create_subprocess_exec

    async def _spy(*args, **kwargs):
        proc = await real(*args, **kwargs)
        seen.append(SimpleNamespace(args=args, kwargs=kwargs, pid=proc.pid, proc=proc))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spy)
    return seen


def _set_deadline(monkeypatch, seconds: float, kind: Kind) -> None:
    monkeypatch.setitem(
        pdf_child.LIMITS,
        kind,
        dataclasses.replace(pdf_child.LIMITS[kind], deadline_seconds=seconds),
    )


def _gone(pid: int) -> bool:
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


async def _wait_for(predicate, *, seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.05)


def _jpeg_size(data: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(BytesIO(data)) as img:
        assert img.format == "JPEG"
        return img.size


def _png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (50, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def _fake_child(monkeypatch, code: str) -> None:
    monkeypatch.setattr(
        pdf_sandbox, "_child_argv", lambda *a, **k: [sys.executable, "-I", "-c", code]
    )


def _answer(code: Code, pieces: list[bytes] = (), *, index: int = -1, detail: int = 0) -> bytes:
    """What a child would write after reading its request."""
    head = pdf_child.RESULT_HEAD.pack(
        pdf_child.RESULT_MAGIC, pdf_child.VERSION, int(code), detail, index, 0, len(pieces)
    )
    lengths = b"".join(pdf_child.PIECE_LENGTH.pack(len(p)) for p in pieces)
    return pdf_child.READY + pdf_child.REQUEST_OK + head + lengths + b"".join(pieces)


def _child_says(monkeypatch, payload: bytes, *, then: str = "") -> None:
    _fake_child(
        monkeypatch,
        "import os, signal, sys; sys.stdin.buffer.read(); "
        f"sys.stdout.buffer.write({payload!r}); sys.stdout.flush(); {then}",
    )


# --- 1. a normal photo --------------------------------------------------------------


def test_a_normal_photo_becomes_a_jpeg_of_the_same_size(run, spawned):
    jpeg = run(pdf_sandbox.photo_to_jpeg(_heic(120, 80)))
    assert jpeg.startswith(b"\xff\xd8\xff")
    assert jpeg.endswith(b"\xff\xd9")
    assert _jpeg_size(jpeg) == (120, 80)
    (child,) = spawned
    assert list(child.args[5:7]) == ["--kind", "photo"]


async def test_storage_converts_a_photo_through_the_sandbox(spawned):
    data, mime = await storage._normalize(_heic(64, 48), "image/heic")
    assert mime == "image/jpeg"
    assert _jpeg_size(data) == (64, 48)
    assert len(spawned) == 1
    assert not heavy_work.lock_for_this_loop().locked()


def test_the_jpeg_carries_no_exif_or_location(run):
    """A phone photo can carry where it was taken; a child's location must not
    be stored with their homework."""
    from PIL import Image

    exif = Image.Exif()
    exif[0x010F] = "Apple"  # Make
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (51.0, 30.0, 12.0)
    gps[3] = "W"
    gps[4] = (0.0, 7.0, 39.0)
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 90, 140)).save(buffer, format="HEIF", exif=exif.tobytes())
    heic = buffer.getvalue()
    with Image.open(BytesIO(heic)) as source:
        assert source.getexif().get_ifd(0x8825), "the test photo should carry a location"

    jpeg = run(pdf_sandbox.photo_to_jpeg(heic))
    with Image.open(BytesIO(jpeg)) as out:
        assert not out.getexif()
        assert "exif" not in out.info
    assert b"Exif\x00\x00" not in jpeg
    assert b"\xff\xe1" not in jpeg[:4096]  # no APP1 segment at all


# --- 2. only a real HEIF reaches a child -----------------------------------------------


def _ftyp(size: int, brand: bytes, rest: bytes = b"\x00" * 64) -> bytes:
    return size.to_bytes(4, "big") + b"ftyp" + brand + b"\x00\x00\x00\x00" + rest


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"0123456789a", id="eleven-bytes"),
        pytest.param(None, id="png"),
        pytest.param(_ftyp(24, b"avif"), id="avif-brand"),
        pytest.param(_ftyp(24, b"avis"), id="avif-sequence-brand"),
        pytest.param(_ftyp(24, b"isom"), id="mp4-brand"),
        pytest.param(_ftyp(8, b"heic"), id="box-too-small"),
        pytest.param(_ftyp(10_000, b"heic"), id="box-longer-than-the-file"),
        pytest.param(b"\x00\x00\x00\x18moov" + b"heic" + b"\x00" * 64, id="not-ftyp"),
    ],
)
async def test_a_body_that_is_not_heif_is_refused_without_a_child(spawned, body):
    body = _png() if body is None else body
    with pytest.raises(ValueError, match="couldn't be read"):
        await storage._normalize(body, "image/heic")
    assert spawned == []
    assert not heavy_work.lock_for_this_loop().locked()


def test_the_sandbox_itself_refuses_a_body_that_is_not_heif(run, spawned):
    pending = pdf_sandbox.photo_to_jpeg(_png())
    with pytest.raises(PhotoUnreadable):
        run(pending)
    assert spawned == []


def test_every_brand_accepted_is_one_the_decoder_lists_and_none_is_avif():
    assert set(pdf_sandbox.HEIF_BRANDS) == {
        b"heic",
        b"heix",
        b"hevc",
        b"hevx",
        b"heim",
        b"heis",
        b"hevm",
        b"hevs",
        b"mif1",
        b"msf1",
    }
    assert pdf_sandbox.looks_like_heif(_heic(16, 16))


async def test_the_signature_is_checked_before_the_lock_is_asked_for(spawned, monkeypatch):
    """A body that is not a photo never waits in line, so it cannot hold up
    the one heavy slot or be told the server is busy."""
    asked: list[float | None] = []
    real = heavy_work.acquire

    async def _spy(*, wait=None):
        asked.append(wait)
        return await real(wait=wait)

    monkeypatch.setattr(heavy_work, "acquire", _spy)
    png = _png()
    with pytest.raises(ValueError, match="couldn't be read"):
        await storage._normalize(png, "image/heic")
    assert asked == []


async def test_an_upload_that_is_not_heif_is_a_415_and_starts_nothing(
    client, student, published_assignment, spawned
):
    resp = await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.heic", _png(), "image/heic"))],
        headers=student["headers"],
    )
    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"] == UNREADABLE
    assert spawned == []


# --- 3. the pixel ceiling --------------------------------------------------------------


def _count_decodes(monkeypatch) -> list[int]:
    """Every time the HEIF plugin decodes a picture's pixels."""
    from pillow_heif import as_plugin

    decoded: list[int] = []
    real_load = as_plugin._LibHeifImageFile.load

    def _load(self, *a, **k):
        decoded.append(1)
        return real_load(self, *a, **k)

    monkeypatch.setattr(as_plugin._LibHeifImageFile, "load", _load)
    return decoded


def test_over_the_ceiling_the_child_says_too_large_before_decoding(monkeypatch):
    """Read from the header; not a pixel is decoded. Fails if the size check
    ever moves after the decode."""
    photo.configure()
    decoded = _count_decodes(monkeypatch)
    heic = _heic(200, 200)
    with pytest.raises(photo.OverCeiling):
        photo.to_jpeg(heic, max_pixels=200 * 200 - 1)
    assert decoded == []
    # And the spy does see a decode, so its silence above means something.
    photo.to_jpeg(heic, max_pixels=200 * 200)
    assert decoded


def test_converting_does_not_set_the_decoder_up_again(monkeypatch):
    """The child sets the decoder up once, before READY, where a failure is
    ours and retried; a second set-up inside the conversion would turn the
    same failure into an "unreadable" photo."""
    photo.configure()
    calls: list[int] = []
    monkeypatch.setattr(photo, "configure", lambda: calls.append(1))
    photo.to_jpeg(_heic(16, 16), max_pixels=10**6)
    assert calls == []


def test_too_large_from_the_child_is_its_own_error(run):
    pending = pdf_sandbox.photo_to_jpeg(_heic(200, 200), max_pixels=200 * 200 - 1)
    with pytest.raises(PhotoTooLarge):
        run(pending)


def test_the_child_never_raises_its_own_ceiling():
    """The parent may lower the ceiling (the tests do); it cannot raise it."""
    assert pdf_child._max_pixels(Kind.photo, {"max-pixels": str(10**9)}) == (
        pdf_child.MAX_IMAGE_PIXELS
    )
    assert pdf_child._max_pixels(Kind.photo, {"max-pixels": "100"}) == 100
    assert pdf_child._max_pixels(Kind.photo, {}) == pdf_child.MAX_IMAGE_PIXELS
    assert storage.MAX_IMAGE_PIXELS == pdf_child.MAX_IMAGE_PIXELS
    with pytest.raises(pdf_child.SetupFailed):
        pdf_child._max_pixels(Kind.pdf, {"max-pixels": "100"})


# --- 4. the deadline -------------------------------------------------------------------


def test_a_photo_child_held_past_its_deadline_is_killed(run, spawned, monkeypatch, caplog):
    _set_deadline(monkeypatch, 2.0, Kind.photo)
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    started = time.monotonic()
    pending = pdf_sandbox._photo(_heic(32, 32), test_args=("--test-hold", "60"))
    with pytest.raises(PhotoTooComplex):
        run(pending)
    assert time.monotonic() - started < 20
    assert _gone(spawned[0].pid)
    assert "reason=deadline" in caplog.text
    assert "kind=photo" in caplog.text
    assert is_permanent(PhotoTooComplex())  # never retried


def test_the_photo_deadline_is_its_own_and_short():
    photo_limits, pdf_limits = pdf_child.LIMITS[Kind.photo], pdf_child.LIMITS[Kind.pdf]
    assert photo_limits.deadline_seconds < pdf_limits.deadline_seconds
    # Above the hard CPU limit, so a busy child is stopped by that first.
    assert photo_limits.deadline_seconds > photo_limits.cpu_hard_seconds
    assert photo_limits.cpu_soft_seconds < photo_limits.cpu_hard_seconds
    # The worker's booklet timeout still reads the PDF deadline by name.
    assert pdf_limits.deadline_seconds == pdf_sandbox.DEADLINE_SECONDS


# --- 5. memory (Linux) -------------------------------------------------------------------


@linux_only
def test_an_allocation_past_the_photo_limit_is_refused_and_the_parent_survives(run, spawned):
    mb = pdf_child.LIMITS[Kind.photo].memory_bytes // (1024 * 1024) + 64
    pending = pdf_sandbox._photo(_heic(32, 32), test_args=("--test-allocate-mb", str(mb)))
    with pytest.raises(PhotoTooComplex):
        run(pending)
    assert _gone(spawned[0].pid)
    assert _jpeg_size(run(pdf_sandbox.photo_to_jpeg(_heic(40, 30)))) == (40, 30)


@linux_only
def test_the_photo_child_runs_under_its_own_limits(run, spawned):
    def _limit(pid, name):
        with open(f"/proc/{pid}/limits") as f:
            for line in f:
                if line.startswith(name):
                    return line.split()[-3:-1]
        raise AssertionError(name)

    def _environ(pid):
        with open(f"/proc/{pid}/environ", "rb") as f:
            return f.read()

    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._photo(_heic(32, 32), test_args=("--test-hold", "30"))
        )
        await _wait_for(lambda: bool(spawned))
        pid = spawned[0].pid
        await _wait_for(lambda: _limit(pid, "Max open files") == ["16", "16"])
        found = {n: _limit(pid, n) for n in ("Max address space", "Max cpu time")}
        environ = _environ(pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return found, environ

    found, environ = run(_scenario())
    limits = pdf_child.LIMITS[Kind.photo]
    assert found["Max address space"] == [str(limits.memory_bytes)] * 2
    assert found["Max cpu time"] == [str(limits.cpu_soft_seconds), str(limits.cpu_hard_seconds)]
    for secret in (b"DATABASE_URL", b"JWT_SECRET", b"_API_KEY"):
        assert secret not in environ


def test_the_photo_memory_limit_is_the_stop_line():
    assert pdf_child.LIMITS[Kind.photo].memory_bytes == 448 * 1024 * 1024
    assert pdf_child.LIMITS[Kind.pdf].memory_bytes == 256 * 1024 * 1024


def test_the_photo_child_sets_its_own_limits_soft_equal_to_hard(monkeypatch):
    calls: dict[int, tuple[int, int]] = {}
    monkeypatch.setattr(
        pdf_child.resource, "setrlimit", lambda res, lim: calls.__setitem__(res, lim)
    )
    pdf_child._set_limits(Kind.photo)
    r = pdf_child.resource
    limits = pdf_child.LIMITS[Kind.photo]
    assert calls[r.RLIMIT_AS] == (limits.memory_bytes, limits.memory_bytes)
    assert calls[r.RLIMIT_CPU] == (limits.cpu_soft_seconds, limits.cpu_hard_seconds)
    assert calls[r.RLIMIT_CORE] == (0, 0)
    assert calls[r.RLIMIT_FSIZE] == (0, 0)
    assert calls[r.RLIMIT_NOFILE] == (16, 16)


# --- 6. a real 24 MP iPhone photo, under the real limit (Linux) ---------------------------


def _iphone_sized_heic() -> bytes:
    """5712 x 4284, the default iPhone photo, laid out as an iPhone lays it
    out: a grid of 512-pixel tiles. Low-frequency noise, so it compresses like
    a photograph rather than like a flat colour."""
    from PIL import Image

    w, h = 5712, 4284
    small = Image.frombytes("RGB", (w // 16, h // 16), os.urandom((w // 16) * (h // 16) * 3))
    buffer = io.BytesIO()
    small.resize((w, h), Image.BILINEAR).save(buffer, format="HEIF", quality=80, tile_size=512)
    return buffer.getvalue()


@linux_only
def test_a_real_24_mp_photo_converts_under_the_real_limit(run, monkeypatch):
    """The limits exist to stop hostile photos, not genuine ones. Prints the
    child's own peak address space (VmPeak), resident peak (VmHWM) and decode
    time, so CI shows the numbers the limits were set from."""
    reports: list[bytes] = []
    real = asyncio.create_subprocess_exec

    async def _capture_stderr(*args, **kwargs):
        kwargs["stderr"] = asyncio.subprocess.PIPE
        proc = await real(*args, **kwargs)
        reports.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _capture_stderr)
    data = _iphone_sized_heic()

    async def _scenario():
        jpeg = await pdf_sandbox._photo(data, test_args=("--test-report", "1"))
        (proc,) = reports
        return jpeg, await proc.stderr.read()

    jpeg, raw = run(_scenario())
    report = json.loads(raw.decode().strip().splitlines()[-1])
    limits = pdf_child.LIMITS[Kind.photo]
    line = (
        f"24 MP photo in the child: VmPeak {report['vm_peak_kb'] / 1024:.0f} MB, "
        f"VmHWM {report['vm_hwm_kb'] / 1024:.0f} MB, decode {report['seconds']:.2f} s "
        f"wall / {report['cpu_seconds']:.2f} s CPU; limits {limits.memory_bytes >> 20} MB, "
        f"CPU {limits.cpu_soft_seconds}/{limits.cpu_hard_seconds} s, "
        f"deadline {limits.deadline_seconds:.0f} s; input {len(data)} bytes"
    )
    print("\n" + line)
    assert _jpeg_size(jpeg) == (5712, 4284), line
    assert report["vm_peak_kb"] * 1024 < limits.memory_bytes, line
    # Room for a slower instance: at most half the soft CPU limit.
    assert report["cpu_seconds"] * 2 < limits.cpu_soft_seconds, line
    assert report["modules"] == ["PIL", "app.services.photo", "pillow_heif"], line


# --- 7. a child that cannot start ----------------------------------------------------------


def _no_room(monkeypatch) -> None:
    async def _fail(*args, **kwargs):
        raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fail)


async def test_a_photo_upload_whose_child_cannot_start_is_a_503(
    client, student, published_assignment, monkeypatch
):
    _no_room(monkeypatch)
    resp = await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.heic", _heic(50, 50), "image/heic"))],
        headers=student["headers"],
    )
    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"].startswith("Avora is busy")
    assert resp.headers.get("retry-after")
    assert not heavy_work.lock_for_this_loop().locked()


async def test_a_job_saving_a_photo_whose_child_cannot_start_is_retried(monkeypatch):
    """`save_bytes` callers read a ValueError as "this file was refused"."""
    _no_room(monkeypatch)
    heic = _heic(50, 50)
    with pytest.raises(PdfSandboxUnavailable) as caught:
        await storage.save_bytes(heic, "image/heic", "a.heic", organization_id=1)
    assert not isinstance(caught.value, ValueError)
    assert not is_permanent(caught.value)
    assert not heavy_work.lock_for_this_loop().locked()


async def test_a_root_parent_with_no_sandbox_account_still_frees_the_lock(spawned, monkeypatch):
    """The account is looked up before the spawn; failing there gives the lock
    back like every other way out."""
    monkeypatch.setattr(pdf_sandbox.os, "geteuid", lambda: 0)

    def _missing(name):
        raise KeyError(name)

    monkeypatch.setattr(pdf_sandbox.pwd, "getpwnam", _missing)
    release = await heavy_work.acquire()
    heic = _heic(20, 20)
    with pytest.raises(PdfSandboxUnavailable):
        await pdf_sandbox.photo_to_jpeg(heic, held=release)
    assert spawned == []
    assert not heavy_work.lock_for_this_loop().locked()


# --- 8. cancellation -------------------------------------------------------------------------


def test_cancelling_mid_decode_reaps_the_child_and_frees_the_lock(run, spawned):
    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._photo(_heic(32, 32), test_args=("--test-hold", "60"))
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


async def test_cancelling_a_storage_photo_frees_the_lock_once(spawned, monkeypatch):
    monkeypatch.setattr(
        pdf_sandbox, "photo_to_jpeg", _held_photo(("--test-hold", "60")), raising=True
    )
    task = asyncio.create_task(storage._normalize(_heic(32, 32), "image/heic"))
    await _wait_for(lambda: bool(spawned))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not heavy_work.lock_for_this_loop().locked()
    # Freed exactly once: a second holder gets in, a third waits.
    first = await heavy_work.acquire(wait=0.1)
    with pytest.raises(HeavyWorkBusy):
        await heavy_work.acquire(wait=0.1)
    first()
    await _wait_for(lambda: _gone(spawned[0].pid))


def _held_photo(test_args):
    real = pdf_sandbox._photo

    async def _photo_to_jpeg(data, *, max_pixels=pdf_child.MAX_IMAGE_PIXELS, held=None, **kw):
        return await real(data, max_pixels=max_pixels, held=held, test_args=test_args)

    return _photo_to_jpeg


# --- 9. a photo behind a PDF ---------------------------------------------------------------


def test_a_photo_behind_a_pdf_child_waits_briefly_then_is_busy(run, spawned):
    async def _scenario():
        booklet = asyncio.create_task(
            pdf_sandbox._run(Op.count, _pdf(1), [], test_args=("--test-hold", "30"))
        )
        await _wait_for(lambda: bool(spawned))
        started = time.monotonic()
        heic = _heic(20, 20)
        with pytest.raises(HeavyWorkBusy):
            await pdf_sandbox.photo_to_jpeg(heic, wait=0.5)
        waited = time.monotonic() - started
        booklet.cancel()
        with pytest.raises(asyncio.CancelledError):
            await booklet
        return waited

    waited = run(_scenario())
    assert 0.4 < waited < 3
    assert len(spawned) == 1, "a photo child started while the PDF child held the lock"


# --- 11. the environment and the account --------------------------------------------------


def test_the_photo_child_gets_a_minimal_environment(run, spawned, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/avora")
    monkeypatch.setenv("JWT_SECRET", "a-secret-the-child-must-not-see")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-for-the-child")
    run(pdf_sandbox.photo_to_jpeg(_heic(20, 20)))
    (child,) = spawned
    assert list(child.args[:7]) == [
        sys.executable,
        "-I",
        "-B",
        "-m",
        "app.services.pdf_child",
        "--kind",
        "photo",
    ]
    assert set(child.kwargs["env"]) <= {"PATH", "MALLOC_ARENA_MAX", "PYTHONHASHSEED"}
    assert child.kwargs["close_fds"] is True
    assert child.kwargs["start_new_session"] is True
    assert child.kwargs["stderr"] == asyncio.subprocess.DEVNULL


def test_a_root_parent_hands_the_photo_child_the_sandbox_account(monkeypatch):
    monkeypatch.setattr(pdf_sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        pdf_sandbox.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=4242, pw_gid=4343)
    )
    argv = pdf_sandbox._child_argv(Kind.photo, max_pixels=1000)
    assert argv[5:7] == ["--kind", "photo"]
    assert argv[argv.index("--uid") + 1] == "4242"
    assert argv[argv.index("--max-pixels") + 1] == "1000"


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") and os.geteuid() == 0),
    reason="needs a root parent on Linux; the CI image test checks the uid there",
)
def test_as_root_the_photo_child_is_not_root(run, spawned):
    def _uid(pid):
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
        raise AssertionError("no Uid line")

    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._photo(_heic(20, 20), test_args=("--test-hold", "30"))
        )
        await _wait_for(lambda: bool(spawned))
        pid = spawned[0].pid
        await _wait_for(lambda: _uid(pid) != 0)
        uid = _uid(pid)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return uid

    assert run(_scenario()) != 0


def test_a_photo_child_as_the_same_user_in_production_is_an_error_once(monkeypatch, caplog):
    """Until the API has its own account (T-009), a photo child that is not
    root runs as the API's user and could read the stored uploads."""
    from app.config import get_settings

    monkeypatch.setattr(pdf_sandbox.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(pdf_sandbox, "_warned_photo_same_user", False)
    monkeypatch.setattr(get_settings(), "render", True)
    monkeypatch.setattr(get_settings(), "storage_backend", "local")
    caplog.set_level(logging.INFO, logger="app.services.pdf_sandbox")
    pdf_sandbox._child_argv(Kind.photo)
    pdf_sandbox._child_argv(Kind.photo)
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "photo" in errors[0].getMessage()

    caplog.clear()
    monkeypatch.setattr(pdf_sandbox, "_warned_photo_same_user", False)
    monkeypatch.setattr(get_settings(), "render", False)
    pdf_sandbox._child_argv(Kind.photo)
    assert not [r for r in caplog.records if r.levelno == logging.ERROR]


# --- kind and operation are bound together ---------------------------------------------------


def _stub_setup(monkeypatch) -> None:
    monkeypatch.setattr(pdf_child, "_raise_oom_score", lambda: None)
    monkeypatch.setattr(pdf_child, "_drop_privileges", lambda uid, gid: None)
    monkeypatch.setattr(pdf_child, "_set_limits", lambda kind: None)


@pytest.mark.parametrize(
    "kind,op",
    [
        (Kind.photo, Op.count),
        (Kind.photo, Op.split),
        (Kind.pdf, Op.photo_to_jpeg),
    ],
)
def test_a_child_refuses_an_operation_of_the_other_kind(monkeypatch, kind, op):
    _stub_setup(monkeypatch)
    loaded: list[Kind] = []
    monkeypatch.setattr(pdf_child, "_load_library", loaded.append)
    out = BytesIO()
    request = pdf_child.encode_request(op, [], b"%PDF-1.4")
    assert (
        pdf_child.main(["--kind", kind.value], stdin=BytesIO(request), stdout=out)
        == pdf_child.EXIT_BAD_REQUEST
    )
    # Ready, then nothing: the request was refused before the marker.
    assert out.getvalue() == pdf_child.READY
    assert loaded == [kind]


def test_a_photo_child_loads_only_the_photo_library(run, monkeypatch):
    reports: list = []
    real = asyncio.create_subprocess_exec

    async def _capture_stderr(*args, **kwargs):
        kwargs["stderr"] = asyncio.subprocess.PIPE
        proc = await real(*args, **kwargs)
        reports.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _capture_stderr)

    async def _scenario():
        await pdf_sandbox._photo(_heic(20, 20), test_args=("--test-report", "1"))
        await pdf_sandbox._run(Op.count, _pdf(1), [], test_args=("--test-report", "1"))
        return [json.loads((await p.stderr.read()).decode()) for p in reports]

    photo_report, pdf_report = run(_scenario())
    assert photo_report["modules"] == ["PIL", "app.services.photo", "pillow_heif"]
    assert pdf_report["modules"] == ["app.services.pdf", "pypdf"]


def test_an_unknown_kind_stops_the_child_before_ready(monkeypatch):
    _stub_setup(monkeypatch)
    out = BytesIO()
    assert pdf_child.main(["--kind", "video"], stdin=BytesIO(b""), stdout=out) == (
        pdf_child.EXIT_SETUP
    )
    assert out.getvalue() == b""


def test_the_photo_library_refuses_to_run_with_its_safety_limits_off(monkeypatch):
    from pillow_heif import options

    monkeypatch.setattr(options, "DISABLE_SECURITY_LIMITS", True)
    with pytest.raises(RuntimeError):
        photo.configure()
    _stub_setup(monkeypatch)
    out = BytesIO()
    assert pdf_child.main(["--kind", "photo"], stdin=BytesIO(b""), stdout=out) == (
        pdf_child.EXIT_SETUP
    )
    assert out.getvalue() == b""


def test_the_photo_library_is_set_up_lean():
    from pillow_heif import options

    photo.configure()
    assert options.DECODE_THREADS == 1
    assert options.THUMBNAILS is False
    assert options.DEPTH_IMAGES is False
    assert options.AUX_IMAGES is False
    assert options.DISABLE_SECURITY_LIMITS is False


# --- the request-read marker -------------------------------------------------------------------


def test_the_child_marks_its_request_read_before_calling_the_library(monkeypatch):
    _stub_setup(monkeypatch)
    monkeypatch.setattr(pdf_child, "_load_library", lambda kind: None)
    steps: list[str] = []

    def _serve(data, max_pixels, stdout):
        steps.append("library")
        pdf_child._write_result(stdout, Code.unreadable)

    monkeypatch.setattr(pdf_child, "_serve_photo", _serve)

    class _Stdout(BytesIO):
        def write(self, b):
            steps.append(
                {pdf_child.READY: "ready", pdf_child.REQUEST_OK: "request_ok"}.get(
                    bytes(b), "write"
                )
            )
            return super().write(b)

    request = pdf_child.encode_request(Op.photo_to_jpeg, [], _heic(8, 8))
    assert pdf_child.main(["--kind", "photo"], stdin=BytesIO(request), stdout=_Stdout()) == 0
    assert steps[:3] == ["ready", "request_ok", "library"]


def test_exit_3_after_the_marker_is_the_files_fault(run, monkeypatch, caplog):
    """A child that has read its request has started on the file; any exit
    from then on, whatever its number, is the file's and is not retried."""
    _child_says(
        monkeypatch,
        pdf_child.READY + pdf_child.REQUEST_OK,
        then=f"sys.exit({pdf_child.EXIT_BAD_REQUEST})",
    )
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoTooComplex):
        run(pending)
    assert "kind=photo" in caplog.text


def test_exit_3_after_the_marker_is_the_files_fault_for_a_pdf_too(run, monkeypatch):
    _child_says(
        monkeypatch,
        pdf_child.READY + pdf_child.REQUEST_OK,
        then=f"sys.exit({pdf_child.EXIT_BAD_REQUEST})",
    )
    pending = pdf_sandbox.page_count(_pdf(1))
    with pytest.raises(pdf_sandbox.PdfTooComplex):
        run(pending)


def test_exit_3_before_the_marker_is_ours_and_retried(run, monkeypatch):
    _fake_child(
        monkeypatch,
        "import sys; sys.stdout.buffer.write(b'R'); sys.stdout.flush(); "
        f"sys.exit({pdf_child.EXIT_BAD_REQUEST})",
    )
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PdfSandboxUnavailable) as caught:
        run(pending)
    assert not is_permanent(caught.value)


# --- the child's answer is untrusted -------------------------------------------------------------


_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_answer(Code.ok, [b"not a jpeg at all"]), id="not-jpeg"),
        pytest.param(_answer(Code.ok, [_JPEG[:-2]]), id="no-end-marker"),
        pytest.param(_answer(Code.ok, [b"\xff\xd9"]), id="only-an-end-marker"),
        pytest.param(_answer(Code.ok, []), id="no-piece"),
        pytest.param(_answer(Code.ok, [_JPEG, _JPEG]), id="two-pieces"),
        pytest.param(_answer(Code.encrypted), id="a-pdf-code"),
        pytest.param(_answer(Code.range_invalid, index=0), id="a-range-code"),
        pytest.param(_answer(Code.unreadable, [_JPEG]), id="error-with-bytes"),
        pytest.param(_answer(Code.ok, [_JPEG], index=0), id="ok-with-an-index"),
    ],
)
def test_an_answer_a_photo_child_would_not_write_is_refused(run, monkeypatch, payload):
    _child_says(monkeypatch, payload)
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoTooComplex):
        run(pending)


def test_a_well_formed_answer_is_accepted(run, monkeypatch):
    _child_says(monkeypatch, _answer(Code.ok, [_JPEG]))
    assert run(pdf_sandbox.photo_to_jpeg(_heic(8, 8))) == _JPEG


def test_a_jpeg_over_the_size_cap_is_refused_before_it_is_read(run, monkeypatch, caplog):
    monkeypatch.setattr(pdf_sandbox, "PHOTO_OUTPUT_CAP", 16)
    _child_says(monkeypatch, _answer(Code.ok, [_JPEG]))
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoTooComplex):
        run(pending)
    assert "output_cap" in caplog.text


def test_the_photo_output_cap_is_the_upload_cap():
    assert pdf_sandbox.PHOTO_OUTPUT_CAP == storage.MAX_FILE_BYTES


def test_a_pdf_answer_carrying_a_photo_code_is_refused(run, monkeypatch):
    _child_says(monkeypatch, _answer(Code.too_large))
    pending = pdf_sandbox.page_count(_pdf(1))
    with pytest.raises(pdf_sandbox.PdfTooComplex):
        run(pending)


def test_a_photo_child_killed_by_a_signal_is_too_complex(run, monkeypatch, caplog):
    _child_says(
        monkeypatch,
        pdf_child.READY + pdf_child.REQUEST_OK,
        then="os.kill(os.getpid(), signal.SIGKILL)",
    )
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoTooComplex):
        run(pending)
    assert "SIGKILL" in caplog.text
    assert "kind=photo" in caplog.text


# --- messages, and the strike rule -----------------------------------------------------------------


async def test_too_complex_is_a_415_with_the_safely_sentence(
    client, student, published_assignment, monkeypatch
):
    _child_says(monkeypatch, _answer(Code.too_complex))
    resp = await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        files=[("files", ("page1.heic", _heic(20, 20), "image/heic"))],
        headers=student["headers"],
    )
    assert resp.status_code == 415, resp.text
    assert resp.json()["detail"] == UNSAFE


async def test_a_job_saving_a_too_complex_photo_is_refused_not_retried(monkeypatch):
    _child_says(monkeypatch, _answer(Code.too_complex))
    heic = _heic(20, 20)
    with pytest.raises(ValueError, match="couldn't be read safely") as caught:
        await storage.save_bytes(heic, "image/heic", "a.heic", organization_id=1)
    assert is_permanent(caught.value)


async def test_an_unreadable_photo_from_the_child_keeps_todays_sentence(monkeypatch):
    _child_says(monkeypatch, _answer(Code.unreadable))
    heic = _heic(20, 20)
    with pytest.raises(ValueError) as caught:
        await storage._normalize(heic, "image/heic")
    assert str(caught.value) == UNREADABLE


async def _second_student(client, tutor, group) -> dict:
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    assert invite.status_code == 201, invite.text
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Omar",
            "email": "omar@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    return {"headers": {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}}


async def test_after_two_unsafe_photos_a_student_is_refused_without_a_child(
    client, tutor, group, student, published_assignment, monkeypatch, spawned
):
    """One student cannot keep the shared slot busy with photos that each run
    to a limit: after two in a day their photos are refused unread. Another
    student, and the same student's JPEGs, are not affected."""
    _child_says(monkeypatch, _answer(Code.too_complex))
    url = f"/api/v1/assignments/{published_assignment['id']}/submissions"
    heic = [("files", ("page1.heic", _heic(20, 20), "image/heic"))]

    for _ in range(2):
        resp = await client.post(url, files=heic, headers=student["headers"])
        assert resp.status_code == 415, resp.text
        assert resp.json()["detail"] == UNSAFE
    assert len(spawned) == 2

    third = await client.post(url, files=heic, headers=student["headers"])
    assert third.status_code == 415, third.text
    assert third.json()["detail"] == STRUCK_OUT
    assert len(spawned) == 2, "a child started for a student already refused"

    other = await _second_student(client, tutor, group)
    resp = await client.post(url, files=heic, headers=other["headers"])
    assert resp.json()["detail"] == UNSAFE
    assert len(spawned) == 3

    from tests.conftest import PNG_BYTES

    jpeg_like = await client.post(
        url, files=[("files", ("page1.png", PNG_BYTES, "image/png"))], headers=student["headers"]
    )
    assert jpeg_like.status_code == 201, jpeg_like.text


async def test_an_unreadable_or_too_large_photo_is_not_a_strike(monkeypatch):
    for code in (Code.unreadable, Code.too_large):
        _child_says(monkeypatch, _answer(code))
        for _ in range(3):
            heic = _heic(20, 20)
            with pytest.raises(ValueError):
                await storage._normalize(heic, "image/heic")
    assert not await storage.photo_strikes_spent(1, 7)


async def test_strikes_are_kept_per_student_inside_their_workspace():
    await storage.record_photo_strike(1, 7)
    await storage.record_photo_strike(1, 7)
    assert await storage.photo_strikes_spent(1, 7)
    assert not await storage.photo_strikes_spent(1, 8)
    assert not await storage.photo_strikes_spent(2, 7)
    assert rate_limit.photo_strike_daily_limiter in rate_limit.ALL_LIMITERS
    assert rate_limit.photo_strike_daily_limiter.window_seconds == rate_limit.DAY_SECONDS
    assert rate_limit.photo_strike_daily_limiter.limit == 2


# --- the log ---------------------------------------------------------------------------------------


def test_the_log_names_the_kind_and_never_the_content(run, monkeypatch, caplog):
    secret = b"a child's homework, which the log must never hold"
    _child_says(monkeypatch, _answer(Code.ok, [b"\xff\xd8\xff" + secret]))
    caplog.set_level(logging.DEBUG, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoTooComplex):
        run(pending)
    assert "kind=photo" in caplog.text
    assert "reason=bad_output" in caplog.text
    assert secret.decode() not in caplog.text


# --- review round: a refusal that is ours costs no allowance -------------------------------


def test_the_in_process_counter_gives_back_one_use_and_never_goes_below_zero():
    counter = rate_limit.FixedWindowLimiter(limit=2, window_seconds=60)
    counter.record("k", now=10.0)
    counter.record("k", now=11.0)
    assert counter.is_limited("k", now=12.0)
    counter.refund("k", now=12.0)
    assert not counter.is_limited("k", now=12.0)
    counter.refund("k", now=12.0)
    counter.refund("k", now=12.0)  # nothing left: not below zero
    counter.record("k", now=13.0)
    counter.record("k", now=13.0)
    assert counter.is_limited("k", now=13.0)
    # A use from an earlier window is not refunded into this one.
    counter.refund("k", now=75.0)
    assert counter._hits["k"][1] == 2


async def test_a_refund_reaches_the_shared_store_as_well_as_this_process(monkeypatch):
    """`record` writes both stores, so `refund` gives back on both."""
    limiter = rate_limit.RateLimiter(purpose="refund_test", limit=1, window_seconds=60)
    refunded: list[str] = []

    class _Store:
        async def refund(self, key):
            refunded.append(key)

    monkeypatch.setattr(limiter, "_available", lambda now: _Store())
    limiter.local.record(limiter.key("7", tenant=1))
    await limiter.refund("7", tenant=1)
    assert refunded == [limiter.key("7", tenant=1)]
    assert not limiter.local.is_limited(limiter.key("7", tenant=1))


async def test_a_refund_the_shared_store_refuses_falls_back_like_everything_else(monkeypatch):
    limiter = rate_limit.RateLimiter(purpose="refund_test_down", limit=1, window_seconds=60)

    class _Down:
        async def refund(self, key):
            raise ConnectionError("store is down")

    monkeypatch.setattr(limiter, "_available", lambda now: _Down())
    limiter.local.record(limiter.key("7", tenant=1))
    await limiter.refund("7", tenant=1)
    assert limiter.degradation.degraded
    assert not limiter.local.is_limited(limiter.key("7", tenant=1))


_REDIS_URL = os.environ.get("TEST_REDIS_URL")


@pytest.mark.skipif(not _REDIS_URL, reason="TEST_REDIS_URL is not set")
async def test_a_refund_against_real_redis_gives_back_one_and_never_goes_below_zero(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "redis_url", _REDIS_URL)
    limiter = rate_limit.RateLimiter(purpose="refund_test_redis", limit=1, window_seconds=60)
    try:
        await limiter.reset("7", tenant=1)
        await limiter.record("7", tenant=1)
        assert await limiter.is_limited("7", tenant=1)
        await limiter.refund("7", tenant=1)
        assert not await limiter.is_limited("7", tenant=1)
        await limiter.refund("7", tenant=1)  # already zero
        await limiter.record("7", tenant=1)
        assert await limiter.is_limited("7", tenant=1)
        assert not limiter.degradation.degraded
    finally:
        await limiter.reset("7", tenant=1)
        await limiter._redis().close()


async def test_a_photo_upload_refused_because_no_reader_could_start_costs_no_allowance(
    client, student, published_assignment, monkeypatch
):
    from tests.test_daily_workspace_limits import _allow

    _allow(monkeypatch, rate_limit.upload_daily_limiter, 1)
    _allow(monkeypatch, rate_limit.student_upload_daily_limiter, 1)
    url = f"/api/v1/assignments/{published_assignment['id']}/submissions"
    files = [("files", ("page1.heic", _heic(50, 50), "image/heic"))]

    real = asyncio.create_subprocess_exec
    _no_room(monkeypatch)
    busy = await client.post(url, files=files, headers=student["headers"])
    assert busy.status_code == 503, busy.text

    monkeypatch.setattr(asyncio, "create_subprocess_exec", real)
    later = await client.post(url, files=files, headers=student["headers"])
    assert later.status_code == 201, later.text


async def test_a_photo_saved_by_a_job_that_no_reader_could_take_costs_no_allowance(monkeypatch):
    from tests.test_daily_workspace_limits import _allow

    _allow(monkeypatch, rate_limit.upload_daily_limiter, 1)
    photo_bytes = _heic(50, 50)
    real = asyncio.create_subprocess_exec
    _no_room(monkeypatch)
    with pytest.raises(PdfSandboxUnavailable):
        await storage.save_bytes(photo_bytes, "image/heic", "a.heic", organization_id=1)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", real)
    _key, _name, mime = await storage.save_bytes(
        photo_bytes, "image/heic", "a.heic", organization_id=1
    )
    assert mime == "image/jpeg"


async def test_a_photo_saved_by_a_job_while_busy_costs_no_allowance(monkeypatch):
    from tests.test_daily_workspace_limits import _allow

    _allow(monkeypatch, rate_limit.upload_daily_limiter, 1)
    monkeypatch.setattr(heavy_work, "PHOTO_LOCK_WAIT_SECONDS", 0.2)
    photo_bytes = _heic(50, 50)
    release = await heavy_work.acquire()
    try:
        with pytest.raises(HeavyWorkBusy):
            await storage.save_bytes(photo_bytes, "image/heic", "a.heic", organization_id=1)
    finally:
        release()
    _key, _name, mime = await storage.save_bytes(
        photo_bytes, "image/heic", "a.heic", organization_id=1
    )
    assert mime == "image/jpeg"


# --- review round: why a photo was unreadable is logged, by class -----------------------------


@pytest.mark.parametrize(
    "exc,detail",
    [
        (photo.NotHeif("x"), pdf_child.Detail.not_heif),
        (OSError("x"), pdf_child.Detail.decoder_os_error),
        (SyntaxError("x"), pdf_child.Detail.decoder_syntax_error),
        (ValueError("x"), pdf_child.Detail.decoder_value_error),
        (EOFError("x"), pdf_child.Detail.decoder_eof),
        (RuntimeError("x"), pdf_child.Detail.decoder_runtime_error),
        (TypeError("x"), pdf_child.Detail.unexpected),
        (AttributeError("x"), pdf_child.Detail.unexpected),
        (KeyError("x"), pdf_child.Detail.unexpected),
    ],
)
def test_the_child_names_an_unreadable_photos_exception_by_class(monkeypatch, exc, detail):
    def _boom(data, *, max_pixels):
        raise exc

    monkeypatch.setattr(photo, "to_jpeg", _boom)
    out = BytesIO()
    pdf_child._serve_photo(b"", 100, out)
    head = pdf_child.RESULT_HEAD.unpack_from(out.getvalue(), 0)
    assert head[2] == Code.unreadable
    assert head[3] == detail


def test_an_unreadable_photo_is_logged_with_its_class(run, monkeypatch, caplog):
    _child_says(
        monkeypatch, _answer(Code.unreadable, detail=int(pdf_child.Detail.decoder_os_error))
    )
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoUnreadable):
        run(pending)
    (record,) = [r for r in caplog.records if "unreadable" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert "kind=photo" in record.getMessage()
    assert "detail=decoder_os_error" in record.getMessage()


def test_an_unreadable_photo_that_looks_like_our_fault_is_an_error(run, monkeypatch, caplog):
    _child_says(monkeypatch, _answer(Code.unreadable, detail=int(pdf_child.Detail.unexpected)))
    caplog.set_level(logging.WARNING, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoUnreadable):
        run(pending)
    (record,) = [r for r in caplog.records if "unreadable" in r.getMessage()]
    assert record.levelno == logging.ERROR
    assert "detail=unexpected" in record.getMessage()


def test_an_unknown_detail_code_is_bad_framing(run, monkeypatch):
    _child_says(monkeypatch, _answer(Code.unreadable, detail=200))
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PhotoTooComplex):
        run(pending)


# --- review round: a strike only for the photo's own fault -------------------------------------


async def _unsafe(monkeypatch, payload: bytes, then: str = "") -> storage.PhotoUnsafeError:
    _child_says(monkeypatch, payload, then=then)
    heic = _heic(20, 20)
    with pytest.raises(storage.PhotoUnsafeError) as caught:
        await storage._normalize(heic, "image/heic")
    return caught.value


async def test_too_complex_written_by_the_child_is_a_strike(monkeypatch):
    assert (await _unsafe(monkeypatch, _answer(Code.too_complex))).strike


async def test_running_out_of_cpu_is_a_strike(monkeypatch):
    marker = pdf_child.READY + pdf_child.REQUEST_OK
    unsafe = await _unsafe(monkeypatch, marker, then="os.kill(os.getpid(), signal.SIGXCPU)")
    assert unsafe.strike


async def test_a_sigkill_is_refused_but_not_a_strike(monkeypatch):
    """The hard CPU limit and the kernel's memory killer look the same, and
    the memory killer can be the instance's doing."""
    marker = pdf_child.READY + pdf_child.REQUEST_OK
    unsafe = await _unsafe(monkeypatch, marker, then="os.kill(os.getpid(), signal.SIGKILL)")
    assert not unsafe.strike


async def test_a_child_that_dies_mid_answer_is_refused_but_not_a_strike(monkeypatch):
    partial = pdf_child.READY + pdf_child.REQUEST_OK + pdf_child.RESULT_MAGIC
    unsafe = await _unsafe(monkeypatch, partial, then="os.kill(os.getpid(), signal.SIGTERM)")
    assert not unsafe.strike


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_answer(Code.ok, [b"not a jpeg"]), id="bad-output"),
        pytest.param(pdf_child.READY + pdf_child.REQUEST_OK + b"junk", id="bad-framing"),
    ],
)
async def test_a_malformed_answer_is_refused_but_not_a_strike(monkeypatch, payload):
    assert not (await _unsafe(monkeypatch, payload)).strike


async def test_the_deadline_is_refused_but_not_a_strike(monkeypatch):
    _set_deadline(monkeypatch, 1.0, Kind.photo)
    real = pdf_sandbox._photo

    async def _held(data, *, max_pixels=pdf_child.MAX_IMAGE_PIXELS, held=None, **kw):
        return await real(data, max_pixels=max_pixels, held=held, test_args=("--test-hold", "30"))

    monkeypatch.setattr(pdf_sandbox, "photo_to_jpeg", _held)
    heic = _heic(20, 20)
    with pytest.raises(storage.PhotoUnsafeError) as caught:
        await storage._normalize(heic, "image/heic")
    assert not caught.value.strike


@pytest.mark.parametrize(
    "then",
    [
        pytest.param("sys.exit(1)", id="exit-1"),
        pytest.param("os.kill(os.getpid(), signal.SIGKILL)", id="sigkill"),
        pytest.param(f"sys.exit({pdf_child.EXIT_BAD_REQUEST})", id="exit-3"),
    ],
)
def test_a_child_that_dies_before_reading_its_request_is_ours(run, monkeypatch, then):
    """Ready, but no request marker: the library never had the photo, so
    whatever ended the child was ours. Retried, never a strike."""
    _child_says(monkeypatch, pdf_child.READY, then=then)
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PdfSandboxUnavailable):
        run(pending)


def test_a_garbled_byte_where_the_marker_belongs_is_ours(run, monkeypatch):
    _child_says(monkeypatch, pdf_child.READY + b"X")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PdfSandboxUnavailable):
        run(pending)


async def test_sigkills_never_strike_a_student_out(
    client, student, published_assignment, monkeypatch
):
    marker = pdf_child.READY + pdf_child.REQUEST_OK
    _child_says(monkeypatch, marker, then="os.kill(os.getpid(), signal.SIGKILL)")
    url = f"/api/v1/assignments/{published_assignment['id']}/submissions"
    heic = [("files", ("page1.heic", _heic(20, 20), "image/heic"))]
    for _ in range(3):
        resp = await client.post(url, files=heic, headers=student["headers"])
        assert resp.status_code == 415, resp.text
        assert resp.json()["detail"] == UNSAFE


# --- review round: a fault before the spawn is ours ---------------------------------------------


def test_no_room_for_the_childs_directory_is_ours_and_logged(run, spawned, monkeypatch, caplog):
    import tempfile

    def _full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tempfile, "mkdtemp", _full)
    caplog.set_level(logging.ERROR, logger="app.services.pdf_sandbox")
    pending = pdf_sandbox.photo_to_jpeg(_heic(8, 8))
    with pytest.raises(PdfSandboxUnavailable) as caught:
        run(pending)
    assert not is_permanent(caught.value)
    assert spawned == []
    assert "directory" in caplog.text


def test_an_upload_folder_that_cannot_be_checked_is_ours(monkeypatch, tmp_path, caplog):
    from pathlib import Path

    from app.config import get_settings

    monkeypatch.setattr(pdf_sandbox.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        pdf_sandbox.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=4242, pw_gid=4343)
    )
    monkeypatch.setattr(get_settings(), "storage_backend", "local")
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    real_stat = Path.stat

    def _denied(self, *a, **k):
        if str(self) == str(tmp_path):
            raise PermissionError(errno.EACCES, "Permission denied")
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", _denied)
    caplog.set_level(logging.ERROR, logger="app.services.pdf_sandbox")
    with pytest.raises(PdfSandboxUnavailable):
        pdf_sandbox._child_argv(Kind.photo)
    assert "upload folder" in caplog.text


# --- review round: only an HEVC decoder ---------------------------------------------------------


def test_the_installed_decoder_reads_hevc_only():
    """No AV1 (or other) decoder in the HEIF library this runs, so a HEIF
    container carrying an AV1 picture has nothing to decode it."""
    import pillow_heif

    info = pillow_heif.libheif_info()
    assert set(info["decoders"]) == {"libde265"}
    assert not info.get("AVIF")


def test_the_photo_child_will_not_start_with_another_decoder(monkeypatch):
    import pillow_heif

    real = pillow_heif.libheif_info

    def _with_av1():
        info = dict(real())
        info["decoders"] = {**info["decoders"], "dav1d": "dav1d AV1 decoder"}
        return info

    monkeypatch.setattr(pillow_heif, "libheif_info", _with_av1)
    with pytest.raises(RuntimeError):
        photo.configure()
    _stub_setup(monkeypatch)
    out = BytesIO()
    assert pdf_child.main(["--kind", "photo"], stdin=BytesIO(b""), stdout=out) == (
        pdf_child.EXIT_SETUP
    )
    assert out.getvalue() == b""


# --- review round: a cancel that lands during the reap -------------------------------------------


def test_a_cancel_during_the_reap_still_reaps_the_child_and_frees_the_lock(
    run, spawned, monkeypatch
):
    """The reap is shielded: a cancellation arriving while the killed child is
    being waited for ends the call at once, gives the lock back, and the child
    is still reaped behind it."""
    _set_deadline(monkeypatch, 1.0, Kind.photo)
    real_reap = pdf_sandbox._kill_and_reap
    reaping: list[bool] = []

    async def _cancelled_mid_reap(proc):
        reaping.append(True)
        asyncio.current_task().cancel()
        return await real_reap(proc)

    monkeypatch.setattr(pdf_sandbox, "_kill_and_reap", _cancelled_mid_reap)

    async def _scenario():
        task = asyncio.create_task(
            pdf_sandbox._photo(_heic(20, 20), test_args=("--test-hold", "30"))
        )
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reaping == [True]
        assert not heavy_work.lock_for_this_loop().locked()
        await _wait_for(lambda: _gone(spawned[0].pid))

    run(_scenario())


# --- review round: busy is never swallowed as a refused attachment ------------------------------


@pytest.mark.parametrize(
    "error",
    [pytest.param(HeavyWorkBusy, id="busy"), pytest.param(PdfSandboxUnavailable, id="no-reader")],
)
async def test_the_classroom_import_does_not_swallow_busy(monkeypatch, error):
    """It skips an attachment that was refused (a ValueError) and carries on;
    a reader that could not take it just now is not a refusal, so the sync
    stops and is retried rather than silently dropping the file."""
    from app.services import google_classroom

    async def _meta(token, file_id):
        return {"mimeType": "image/png", "name": "page.png"}

    async def _download(token, file_id):
        return b"\x89PNG\r\n\x1a\n"

    async def _save(*args, **kwargs):
        raise error() if error is HeavyWorkBusy else error("no reader")

    monkeypatch.setattr(google_classroom, "get_drive_file_metadata", _meta)
    monkeypatch.setattr(google_classroom, "download_drive_file", _download)
    monkeypatch.setattr(google_classroom.storage, "save_bytes", _save)
    sub = {"assignmentSubmission": {"attachments": [{"driveFile": {"id": "f1"}}]}}
    with pytest.raises(error):
        await google_classroom._download_attachments("token", sub, organization_id=1)


@pytest.mark.parametrize(
    "sig,strike",
    [
        pytest.param("SIGKILL", False, id="sigkill"),
        pytest.param("SIGXCPU", True, id="sigxcpu"),
    ],
)
async def test_a_whole_answer_followed_by_a_signal_strikes_only_for_cpu(monkeypatch, sig, strike):
    """The answer arrived whole but the child did not exit cleanly: refused,
    and a strike only if what ended it was the CPU limit."""
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"
    unsafe = await _unsafe(
        monkeypatch, _answer(Code.ok, [jpeg]), then=f"os.kill(os.getpid(), signal.{sig})"
    )
    assert unsafe.strike is strike
