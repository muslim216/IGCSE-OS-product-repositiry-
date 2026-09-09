"""Queue a marking-rules summary for every subject that has rules and no summary.

Task 3.2c added `Subject.marking_rules_summary`, which is built by a job the
save endpoint enqueues. Subjects whose rules were written *before* that shipped
have never been saved since, so nothing ever queued one for them: they keep
sending the tutor's full text into every marking call, which is correct but is
the exact cost the task exists to remove (cubic).

Run once after deploying 3.2c:

    python -m seed.summarise_marking_rules

Idempotent, and safe to run at any time — it skips any subject whose summary
already matches its current rules, and the handler checks the same fingerprint
again before spending anything. Nothing is enqueued for a subject with no rules.

A script rather than a data migration: it costs one AI call per subject, and a
migration that spends money while `alembic upgrade head` runs is a migration
that can fail a deploy on a provider outage (`INF-1`). `seed/recompute_readiness.py`
is the same pattern for the same reason.
"""

import asyncio

from sqlalchemy import select

from app.db import async_session
from app.models import Subject, User, UserRole
from app.services.marking_rules import SUMMARISE_JOB, fingerprint
from app.workers.jobs import enqueue


async def main() -> None:
    queued = 0
    async with async_session() as session:
        subjects = (
            await session.scalars(select(Subject).where(Subject.marking_rules.is_not(None)))
        ).all()
        for subject in subjects:
            rules = subject.marking_rules or ""
            if not rules.strip() or subject.marking_rules_summary_of == fingerprint(rules):
                continue
            # The organization's tutor, for the usage row's attribution — the
            # same resolution `services/knowledge.py` makes, and well-defined
            # while the product is single-tutor-per-org.
            tutor_id = await session.scalar(
                select(User.id).where(
                    User.organization_id == subject.organization_id,
                    User.role == UserRole.tutor,
                )
            )
            if tutor_id is None:
                print(f"skipped subject {subject.id}: its organization has no tutor")
                continue
            await enqueue(session, SUMMARISE_JOB, {"subject_id": subject.id, "tutor_id": tutor_id})
            queued += 1
        await session.commit()
    print(f"queued {queued} marking-rules summaries")


if __name__ == "__main__":
    asyncio.run(main())
