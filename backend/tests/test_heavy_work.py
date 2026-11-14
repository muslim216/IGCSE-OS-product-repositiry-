"""T-027: one memory-heavy piece of work at a time in the API process.

Decoding an iPhone photo peaks near 330 MB and a PDF child may use 256 MB, on a
512 MB instance. They share one lock so the two peaks never overlap. A PDF job
waits its turn; a photo, which arrives in a student's request, waits only a few
seconds and then asks them to try again.
"""

import asyncio

import pytest

from app.services import heavy_work, pdf_sandbox, storage
from app.services.heavy_work import HeavyWorkBusy
from app.workers.jobs import is_permanent
from tests.test_storage import _heic


async def test_a_photo_waits_briefly_for_the_lock_then_says_busy(monkeypatch):
    monkeypatch.setattr(storage, "HEIC_LOCK_WAIT_SECONDS", 0.2)
    photo = _heic(50, 50)
    release = await heavy_work.acquire()
    try:
        with pytest.raises(HeavyWorkBusy) as caught:
            await storage._normalize(photo, "image/heic")
    finally:
        release()
    # Retryable, and in our own words.
    assert not is_permanent(caught.value)
    assert "try again" in str(caught.value).lower()
    # The lock was never taken by the refused photo.
    assert not heavy_work.lock_for_this_loop().locked()


async def test_a_photo_upload_while_busy_is_a_503_with_a_retry_hint(
    client, student, published_assignment, monkeypatch
):
    monkeypatch.setattr(storage, "HEIC_LOCK_WAIT_SECONDS", 0.2)
    release = await heavy_work.acquire()
    try:
        resp = await client.post(
            f"/api/v1/assignments/{published_assignment['id']}/submissions",
            files=[("files", ("page1.heic", _heic(50, 50), "image/heic"))],
            headers=student["headers"],
        )
    finally:
        release()
    assert resp.status_code == 503, resp.text
    assert "try again" in resp.json()["detail"].lower()
    # The frontend shows a 503's own sentence only when it starts this way
    # (`frontend/src/lib/errors.ts`); anything else becomes "something went
    # wrong on our side", which is not what a busy moment is.
    assert resp.json()["detail"].startswith("Avora is busy")
    assert resp.headers.get("retry-after")


async def test_a_busy_refusal_spends_no_upload_allowance(
    client, student, published_assignment, monkeypatch
):
    """The lock is asked for before either daily allowance is spent, so a
    student told to try again in a moment has not used a place by it."""
    from app.services.rate_limit import student_upload_daily_limiter, upload_daily_limiter
    from tests.test_daily_workspace_limits import _allow

    monkeypatch.setattr(storage, "HEIC_LOCK_WAIT_SECONDS", 0.2)
    _allow(monkeypatch, upload_daily_limiter, 1)
    _allow(monkeypatch, student_upload_daily_limiter, 1)
    url = f"/api/v1/assignments/{published_assignment['id']}/submissions"
    files = [("files", ("page1.heic", _heic(50, 50), "image/heic"))]

    release = await heavy_work.acquire()
    try:
        busy = await client.post(url, files=files, headers=student["headers"])
    finally:
        release()
    assert busy.status_code == 503, busy.text

    later = await client.post(url, files=files, headers=student["headers"])
    assert later.status_code != 429, later.text
    assert later.status_code < 300, later.text


async def test_a_job_saving_a_photo_while_busy_is_retried_not_refused(monkeypatch):
    """`save_bytes` callers catch ValueError as "this file was refused"; busy is
    not that, so it must not be one."""
    monkeypatch.setattr(storage, "HEIC_LOCK_WAIT_SECONDS", 0.2)
    photo = _heic(50, 50)
    release = await heavy_work.acquire()
    try:
        with pytest.raises(HeavyWorkBusy) as caught:
            await storage.save_bytes(photo, "image/heic", "a.heic", organization_id=1)
    finally:
        release()
    assert not isinstance(caught.value, ValueError)
    assert not is_permanent(caught.value)


async def test_a_photo_holds_the_lock_while_its_child_runs_and_frees_it_once_killed(monkeypatch):
    """The photo decodes in a child process, which, unlike a thread, can be
    stopped. While it runs it holds the lock, so no PDF child starts beside
    it; a cancelled request kills it and only then gives the lock back."""
    from tests.test_photo_sandbox import _gone, _held_photo

    spawned: list[int] = []
    real_spawn = asyncio.create_subprocess_exec

    async def _spy(*args, **kwargs):
        proc = await real_spawn(*args, **kwargs)
        spawned.append(proc.pid)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spy)
    monkeypatch.setattr(pdf_sandbox, "photo_to_jpeg", _held_photo(("--test-hold", "60")))
    task = asyncio.create_task(storage._normalize(_heic(50, 50), "image/heic"))
    for _ in range(200):
        if spawned:
            break
        await asyncio.sleep(0.05)
    assert spawned, "no photo child started"
    await asyncio.sleep(0.3)
    assert heavy_work.lock_for_this_loop().locked(), "a running photo child must hold the lock"

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not heavy_work.lock_for_this_loop().locked()
    for _ in range(200):
        if _gone(spawned[0]):
            break
        await asyncio.sleep(0.02)
    assert _gone(spawned[0])


async def test_the_lock_is_one_at_a_time():
    order: list[str] = []

    async def _work(name: str) -> None:
        async with heavy_work.held():
            order.append(f"{name} in")
            await asyncio.sleep(0.05)
            order.append(f"{name} out")

    await asyncio.gather(_work("a"), _work("b"))
    assert order in (["a in", "a out", "b in", "b out"], ["b in", "b out", "a in", "a out"])


async def test_a_bounded_wait_gives_up_without_holding_the_lock():
    release = await heavy_work.acquire()
    try:
        with pytest.raises(HeavyWorkBusy):
            await heavy_work.acquire(wait=0.05)
    finally:
        release()
    # Freed exactly once: a second release would let two holders in.
    assert not heavy_work.lock_for_this_loop().locked()
    again = await heavy_work.acquire(wait=0.05)
    again()
