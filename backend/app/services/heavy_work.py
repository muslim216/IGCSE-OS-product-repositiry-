"""One memory-heavy piece of work at a time in this process.

The API runs on one 512 MB instance, and two kinds of work there can each take
most of it: decoding an iPhone photo (about 330 MB at the pixel ceiling in
`storage.py`) and a PDF read in its child process (up to 256 MB, the limit
`pdf_child.py` sets). Each fits beside the app on its own; both at once do not.
So both take this lock, and their peaks never overlap.

The two wait differently. A PDF read is a background job and waits as long as
it takes; its own deadline starts only once it holds the lock, so waiting in
line is never counted against the file. A photo arrives in a student's request,
so it waits a few seconds and then asks them to try again rather than stalling
the request behind a booklet.

Per event loop, not one global: an `asyncio.Lock` belongs to the loop that
first waits on it, and the test suite runs many loops in one process.
Production has one loop, so this is one lock there. It does not reach across
processes: an API and a separate worker process (`python -m app.workers`) would
each have their own, which is one of the things the move off one instance has
to revisit (`RISK-1`).
"""

import asyncio
import contextlib
import weakref
from collections.abc import AsyncIterator, Callable

#: Starts as it does because the frontend passes a 503 through to the person
#: only when it begins "Avora is busy" (`frontend/src/lib/errors.ts`).
HEAVY_WORK_BUSY_MESSAGE = "Avora is busy reading another file. Try again in a moment."


class HeavyWorkBusy(RuntimeError):
    """The lock was not free within the wait the caller allowed.

    Our own sentence (`safe_to_show`), and retryable: nothing is wrong with the
    file. Deliberately not a `ValueError`, which `save_bytes` callers read as
    "this file was refused"."""

    safe_to_show = True
    job_retryable = True

    def __init__(self) -> None:
        super().__init__(HEAVY_WORK_BUSY_MESSAGE)


_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


def lock_for_this_loop() -> asyncio.Lock:
    """The running loop's lock, made on first use."""
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = _locks[loop] = asyncio.Lock()
    return lock


async def acquire(*, wait: float | None = None) -> Callable[[], None]:
    """Take the lock, waiting at most `wait` seconds (for ever if None), and
    return the function that gives it back.

    A function rather than only a context manager because the photo decode
    must give it back when its thread finishes, which can be after the request
    that started it was cancelled. Calling the function twice does nothing the
    second time: a double release would let two holders in at once.

    Raises `HeavyWorkBusy` if the wait runs out, holding nothing."""
    lock = lock_for_this_loop()
    if wait is None:
        await lock.acquire()
    else:
        try:
            await asyncio.wait_for(lock.acquire(), timeout=wait)
        except TimeoutError:
            raise HeavyWorkBusy() from None
    released = False

    def release() -> None:
        nonlocal released
        if not released:
            released = True
            lock.release()

    return release


@contextlib.asynccontextmanager
async def held(*, wait: float | None = None) -> AsyncIterator[None]:
    """`acquire` as a block, for work that ends when the block does."""
    release = await acquire(wait=wait)
    try:
        yield
    finally:
        release()
