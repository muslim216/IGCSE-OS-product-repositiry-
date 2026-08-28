"""Keeping a worker alive, wherever it runs.

The supervisor lived in `main.py` while the worker was only ever an asyncio
task inside the API. Task 1.3 (AV-82) gives the worker its own process, and
both need the same "restart the loop if it dies" behaviour — so it lives here,
below the routing layer, and `main.py` calls it rather than owning it.
"""

import asyncio
import logging

from app.workers.jobs import note_worker_restart, worker_loop

log = logging.getLogger("jobs")

#: Pause before restarting a worker that died, so a failure that recurs
#: immediately (a bad DB URL, say) logs at a readable rate instead of spinning.
WORKER_RESTART_SECONDS = 5.0


async def supervised_worker() -> None:
    """Keep the job worker running for the whole life of the process.

    worker_loop() already survives any individual job failing, but nothing
    survived the loop itself ending: the task was created and never looked at
    again, so an exception escaping it left the API serving requests normally
    with no background work happening at all and no signal that anything had
    changed. Extraction, marking, readiness synthesis, reports and Classroom
    sync all stop together, and the only visible symptom is homework that stays
    "processing" forever (RISK-4).
    """
    while True:
        try:
            await worker_loop()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — supervising means surviving anything
            log.exception("job worker died; restarting in %ss", WORKER_RESTART_SECONDS)
        else:
            # worker_loop() loops forever, so a clean return is itself a bug.
            log.error("job worker returned unexpectedly; restarting in %ss", WORKER_RESTART_SECONDS)
        # Counted, not just logged. worker_loop() re-stamps its liveness clock on
        # entry, so without this a loop that raises immediately and restarts every
        # few seconds reports `running` forever while completing no work — the one
        # failure readiness exists to catch, hidden by the fix for the other one.
        await note_worker_restart()
        await asyncio.sleep(WORKER_RESTART_SECONDS)
