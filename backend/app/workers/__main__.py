"""The worker as its own process: `python -m app.workers`.

Task 1.3 (AV-82). Runs exactly the same loop the API runs in-process today —
same claim query, same handlers, same supervisor — with no HTTP server and no
routers imported. What makes two of these safe together is unchanged and
predates this task: the claim in `jobs.py` uses
`.with_for_update(skip_locked=True)`, so two workers cannot take the same job.

Deliberately not wired into `render.yaml` by this change. Turning the worker
into a deployed service is a cutover with its own failure mode — an API with
`RUN_WORKER_IN_API=false` and no worker service running means every piece of
background work stops silently — so it is a separate, deliberate step. Phase 1
makes it possible and proves it in tests; deployment stays single-instance
until Phase 11 (AV-85).
"""

import asyncio
import contextlib
import logging
import signal

from app.workers.handlers import register_all
from app.workers.runner import supervised_worker

log = logging.getLogger("jobs")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    register_all()
    log.info("standalone job worker starting")

    worker = asyncio.ensure_future(supervised_worker())

    # SIGTERM is how Docker, Render and Kubernetes stop a container — SIGKILL
    # only follows if the process ignores it. Without handling it the process
    # dies where it stands: an in-flight job stays claimed as `running` with
    # nothing to release it, and the heartbeat row is left behind to age out.
    # Cancelling the worker instead runs the same shutdown path the API's
    # lifespan uses.
    loop = asyncio.get_running_loop()
    for signame in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(signame, worker.cancel)

    try:
        await worker
    except asyncio.CancelledError:
        log.info("standalone job worker stopped")
        # Re-raised rather than swallowed here. Awaiting a task that gets
        # cancelled and being cancelled *ourselves* arrive at this line
        # identically, and swallowing the second would silently turn a
        # cancellation into a normal return for whatever is above us. The
        # shutdown is absorbed at the top level instead, where the process is
        # exiting anyway and nothing is left to mislead.
        raise


if __name__ == "__main__":
    # Ctrl-C / SIGINT and SIGTERM are how this process is meant to stop; a
    # traceback would make a normal shutdown look like a crash in the logs.
    # CancelledError lands here because main() re-raises it — see above.
    with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
        asyncio.run(main())
