"""T-027: one memory-heavy piece of work at a time in the API process.

Decoding an iPhone photo peaks near 330 MB and a PDF child may use 256 MB, on a
512 MB instance. They share one lock so the two peaks never overlap. A PDF job
waits its turn; a photo, which arrives in a student's request, waits only a few
seconds and then asks them to try again.
"""

import asyncio
import threading

import pytest

from app.services import heavy_work, storage
from app.services.heavy_work import HeavyWorkBusy
from app.workers.jobs import is_permanent
from tests.test_storage import _heic


async def test_a_photo_waits_briefly_for_the_lock_then_says_busy(monkeypatch):
    monkeypatch.setattr(storage, "HEIC_LOCK_WAIT_SECONDS", 0.2)
    release = await heavy_work.acquire()
    try:
        with pytest.raises(HeavyWorkBusy) as caught:
            await storage._normalize(_heic(50, 50), "image/heic")
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
    release = await heavy_work.acquire()
    try:
        with pytest.raises(HeavyWorkBusy) as caught:
            await storage.save_bytes(_heic(50, 50), "image/heic", "a.heic", organization_id=1)
    finally:
        release()
    assert not isinstance(caught.value, ValueError)
    assert not is_permanent(caught.value)


async def test_a_photo_holds_the_lock_until_its_decode_ends_even_if_cancelled(monkeypatch):
    """A thread cannot be stopped. If a cancelled request let go of the lock
    while its photo was still decoding, a PDF child could start beside it."""
    started = threading.Event()
    finish = threading.Event()
    real = storage._to_jpeg

    def _slow(data):
        started.set()
        finish.wait(10)
        return real(data)

    monkeypatch.setattr(storage, "_to_jpeg", _slow)
    task = asyncio.create_task(storage._normalize(_heic(50, 50), "image/heic"))
    await asyncio.to_thread(started.wait, 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert heavy_work.lock_for_this_loop().locked(), "released while the decode still ran"

    finish.set()
    for _ in range(200):
        if not heavy_work.lock_for_this_loop().locked():
            break
        await asyncio.sleep(0.02)
    assert not heavy_work.lock_for_this_loop().locked()


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
