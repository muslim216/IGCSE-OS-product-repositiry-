"""Backfill runner: re-enqueue a Readiness v2 synthesis for every student who
has any evidence, one subject at a time.

Run as `python -m seed.recompute_readiness`, mirroring
`python -m seed.load_syllabus`. There is deliberately no endpoint for this
(E4): a full recompute is an operator action, not a request, and adding a
route would mean securing a cross-student write that nothing in the product
needs.

Existing snapshots are not edited. `compute_readiness_v2` is append-only
(BE-7), so a re-run adds a fresh snapshot and the old rows remain as the
audit trail of what the tutor saw at the time.
"""

import asyncio

from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import Evidence, Topic
from app.services.readiness_v2_ai import enqueue_readiness_v2_debounced

#: Seconds added between consecutive pairs. Each synthesis is an AI call, so a
#: backfill of a few hundred students fired at once would hit the provider as a
#: burst and contend with live marking for the same worker. Spreading them is
#: the whole point of running this as a queue fill rather than a loop of calls.
STAGGER_SECONDS = 30


async def enqueue_all(session) -> int:
    """Queue one debounced v2 run per (student, subject) that has evidence.

    Returns the number of pairs found. The debounce in
    `enqueue_readiness_v2_debounced` is per (student, subject), so a pair that
    already has a run pending is skipped rather than duplicated — which makes
    this safe to re-run if it is interrupted part-way (BE-6).
    """
    pairs = (
        await session.execute(
            select(Evidence.student_id, Topic.subject_id)
            .join(Topic, Topic.id == Evidence.topic_id)
            .distinct()
            .order_by(Evidence.student_id, Topic.subject_id)
        )
    ).all()
    for index, (student_id, subject_id) in enumerate(pairs):
        await enqueue_readiness_v2_debounced(
            session,
            student_id,
            subject_id,
            delay_seconds=index * STAGGER_SECONDS,
        )
    return len(pairs)


async def main() -> None:
    # enqueue_readiness_v2_debounced returns silently when v2 is switched off,
    # so without this check the runner would report success having queued
    # nothing at all — the exact failure an operator running a backfill would
    # not think to look for.
    if not get_settings().readiness_v2_shadow_enabled:
        raise SystemExit(
            "READINESS_V2_SHADOW_ENABLED is off — nothing was queued. "
            "Turn it on before running the backfill."
        )
    async with async_session() as session:
        count = await enqueue_all(session)
        await session.commit()
    if count == 0:
        print("no student has any evidence yet — nothing to recompute")
        return
    span_minutes = round((count - 1) * STAGGER_SECONDS / 60)
    print(f"queued {count} readiness runs, spread over about {span_minutes} minutes")


if __name__ == "__main__":
    asyncio.run(main())
