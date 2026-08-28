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
    try:
        await supervised_worker()
    except asyncio.CancelledError:
        log.info("standalone job worker stopped")


if __name__ == "__main__":
    # Ctrl-C / SIGINT is how this process is meant to stop; a traceback would
    # make a normal shutdown look like a crash in the logs.
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
