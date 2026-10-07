"""Group (class) aggregation: the counts and next-lesson pick behind the
tutor's class cards."""

from collections import defaultdict
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AssessableWork,
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    ScheduleSlot,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.schemas.groups import GroupSummary, NextLesson
from app.services.class_readiness import LearnerSnapshot, latest_learner_snapshots

#: Submission states that are waiting on the tutor's eyes, mirroring the
#: attention endpoint: an AI draft to confirm, an AI failure to handle, or
#: auto-marking's uncertain rows. Finalized and auto-finalized work is done;
#: submitted/marking is still in flight.
AWAITING_REVIEW = (
    SubmissionStatus.ai_marked,
    SubmissionStatus.ai_failed,
    SubmissionStatus.needs_review,
)


def live_classes_taught_by(tutor_id: int) -> tuple:
    """Conditions on `Group` for "a class this tutor teaches that still exists".

    The one definition behind every "does this tutor teach this student?" check,
    read or write: deleting a class ends the tutor-student relationship it gave,
    exactly as removing the student from it would. Spread into a `.where(...)`
    of a query that joins `Group`, so a new site cannot forget the deleted-class
    half. The only history exception is `_tutor_owns` in api/submissions.py, so
    work already handed in can still be marked.
    """
    return (Group.tutor_id == tutor_id, Group.deleted_at.is_(None))


async def student_in_organization(db: AsyncSession, student: User, organization_id: int) -> bool:
    """Homed in this organization, or a member of one of its classes — the rule
    `api/readiness.visible_subject_ids` applies to an admin. A student can sit
    in a second organization's class, so home organization alone gave an admin
    less reach than a tutor beside them: the tutor opened the student, the
    admin got a 404."""
    if student.organization_id == organization_id:
        return True
    membership = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(
            GroupMember.student_id == student.id,
            Group.organization_id == organization_id,
            Group.deleted_at.is_(None),
        )
        .limit(1)
    )
    return membership is not None


async def tutor_teaches_student(db: AsyncSession, tutor: User, student: User) -> bool:
    """Whether this tutor (or admin) may act on this student: a tutor must share
    a live class with them; an admin only needs the student in their own
    organization (`SEC-7`). The one rule behind `api/students._tutor_student`
    and a tutor's redo of an attempt."""
    if tutor.role == UserRole.admin:
        return await student_in_organization(db, student, tutor.organization_id)
    shares_group = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student.id, *live_classes_taught_by(tutor.id))
    )
    return shares_group is not None


def review_queue_predicate(organization_id: int):
    """The one definition of "waiting on a tutor **in the review queue**".

    Distinct from AWAITING_REVIEW above, and deliberately so: that tuple is the
    per-class workload on a class card, which counts an AI draft still to be
    confirmed. The review queue is narrower — only `needs_review` — and is
    scoped by organization rather than by who owns the class, because past
    papers have no group and a tutor covering for a colleague still has to mark
    the work.

    Shared because the home's headline count links straight to the page this
    predicate selects. When the two drifted, the home said "3 pieces to mark"
    and the queue it linked to listed a different set — the count was built
    from AWAITING_REVIEW scoped by `Group.tutor_id`, so it counted AI drafts the
    queue never shows and dropped a colleague's homework the queue does show.

    Whose work it is now comes off the parent row (D4). Until this change the
    organization was ORed across three columns — the assignment's group, the
    past paper, the mock — and a kind left out of that OR did not raise, it
    just vanished from the queue and the count. That is how the mock arm
    shipped broken. Every submission has exactly one parent carrying one
    `organization_id`, so a fourth kind of work is now scoped correctly by
    existing without anyone editing this line. Both call sites join
    `AssessableWork` on `Submission.work_id`, which is NOT NULL, so the join is
    inner and drops nothing.
    """
    return (
        Submission.status == SubmissionStatus.needs_review,
        AssessableWork.organization_id == organization_id,
    )


def soonest_slot(slots: list[ScheduleSlot], now: datetime) -> NextLesson | None:
    """Pick the next occurrence of a weekly timetable.

    Pure, so it unit-tests without a database. Slots repeat weekly (weekday +
    start_time, no date), so "next" means the smallest number of days ahead; a
    slot earlier today has already passed and rolls round to next week.
    """
    if not slots:
        return None
    today, current = now.weekday(), now.time()

    def days_away(slot: ScheduleSlot) -> tuple[int, time]:
        days = (slot.weekday - today) % 7
        if days == 0 and slot.start_time <= current:
            days = 7
        return days, slot.start_time

    nxt = min(slots, key=days_away)
    return NextLesson(
        weekday=nxt.weekday,
        start_time=nxt.start_time,
        duration_min=nxt.duration_min,
        title=nxt.title,
    )


async def summaries(
    session: AsyncSession,
    group_ids: list[int],
    snapshots_by_group: dict[int, dict[int, LearnerSnapshot]] | None = None,
) -> dict[int, GroupSummary]:
    """Per-group counts for the class cards.

    Each aggregate is its own query rather than one wide join: joining members,
    assignments and submissions together would multiply the rows and inflate
    every count.

    `snapshots_by_group` lets a caller that already ran `latest_learner_snapshots`
    for these same `group_ids` pass the result straight through instead of this
    function fetching it again — `services/today.py`'s `build_today` also needs
    it for `class_scores()`, and running the window query twice for one request
    is exactly the duplication fix round 1 caught.
    """
    if not group_ids:
        return {}

    members: dict[int, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(GroupMember.group_id, func.count(GroupMember.id))
                .where(GroupMember.group_id.in_(group_ids))
                .group_by(GroupMember.group_id)
            )
        ).all()
    }
    published: dict[int, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Assignment.group_id, func.count(Assignment.id))
                .where(
                    Assignment.group_id.in_(group_ids),
                    Assignment.status == AssignmentStatus.published,
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    }
    awaiting: dict[int, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Assignment.group_id, func.count(Submission.id))
                .join(Assignment, Assignment.work_id == Submission.work_id)
                .where(
                    Assignment.group_id.in_(group_ids),
                    Submission.status.in_(AWAITING_REVIEW),
                )
                .group_by(Assignment.group_id)
            )
        ).all()
    }

    # Coverage numerator: how many enrolled students the class's readiness
    # picture actually speaks for. A status derived from 2 of 11 students is a
    # statement about a class made from part of it, and must not look like one
    # made from all of it (PROD-2) — so the count travels with member_count.
    # Since 5.3a this is the scored-learner count from latest_learner_snapshots
    # (services/class_readiness.py) — the same query the class score is
    # averaged over (decision 15). That query already yields one row per
    # (group, student), so there is nothing left to DISTINCT away; the old
    # DISTINCT existed only when this counted TopicReadiness rows, one per
    # topic per student.
    # SEC-7: group_ids arrive already scoped to the authenticated tutor by the
    # callers in api/groups.py, so this inherits that scoping rather than
    # re-deriving it from a parameter.
    if snapshots_by_group is None:
        snapshots_by_group = await latest_learner_snapshots(session, group_ids)
    covered: dict[int, int] = {
        gid: sum(1 for s in learners.values() if s.score is not None)
        for gid, learners in snapshots_by_group.items()
    }

    by_group: dict[int, list[ScheduleSlot]] = defaultdict(list)
    for slot in (
        await session.scalars(select(ScheduleSlot).where(ScheduleSlot.group_id.in_(group_ids)))
    ).all():
        by_group[slot.group_id].append(slot)

    now = utcnow()
    return {
        gid: GroupSummary(
            member_count=members.get(gid, 0),
            students_with_evidence=covered.get(gid, 0),
            published_assignment_count=published.get(gid, 0),
            awaiting_review_count=awaiting.get(gid, 0),
            next_lesson=soonest_slot(by_group.get(gid, []), now),
        )
        for gid in group_ids
    }
