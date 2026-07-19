"""Builds a compact academic-context block about a student, injected into AI
calls (tutor chat now, reports later) so responses are grounded in the
student's actual readiness and workload rather than generic advice."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    AssignmentStatus,
    Group,
    GroupMember,
    ReadinessConfidence,
    Submission,
    SubmissionStatus,
    Subject,
    Topic,
    TopicReadiness,
    User,
)


async def build_student_context(session: AsyncSession, student: User) -> str:
    lines: list[str] = [f"Student name: {student.name}"]

    # Subjects the student studies.
    subjects = (
        await session.scalars(
            select(Subject)
            .join(Group, Group.subject_id == Subject.id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == student.id)
            .distinct()
        )
    ).all()
    if not subjects:
        lines.append("This student is not enrolled in any subject yet.")
        return "\n".join(lines)

    for subject in subjects:
        topics = {
            t.id: t
            for t in (
                await session.scalars(select(Topic).where(Topic.subject_id == subject.id))
            ).all()
        }
        rows = (
            await session.scalars(
                select(TopicReadiness).where(
                    TopicReadiness.student_id == student.id,
                    TopicReadiness.topic_id.in_(list(topics.keys()) or [0]),
                )
            )
        ).all()
        confident = [r for r in rows if r.confidence != ReadinessConfidence.none]
        lines.append(f"\n{subject.name} ({subject.exam_board} {subject.code}):")
        if not confident:
            lines.append("  No readiness data yet.")
            continue
        overall = round(
            sum(topics[r.topic_id].weight * r.score for r in confident)
            / sum(topics[r.topic_id].weight for r in confident),
            0,
        )
        lines.append(f"  Overall readiness: {overall:.0f}%")
        weak = sorted(
            (
                r
                for r in confident
                if r.score <= 60
                and r.confidence in (ReadinessConfidence.medium, ReadinessConfidence.high)
            ),
            key=lambda r: r.score,
        )[:5]
        if weak:
            weak_str = ", ".join(
                f"{topics[r.topic_id].title} ({r.score:.0f}%)" for r in weak
            )
            lines.append(f"  Weakest topics: {weak_str}")

    # Outstanding homework.
    outstanding = (
        await session.scalars(
            select(Assignment)
            .join(Group, Group.id == Assignment.group_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .outerjoin(
                Submission,
                (Submission.assignment_id == Assignment.id)
                & (Submission.student_id == student.id),
            )
            .where(
                GroupMember.student_id == student.id,
                Assignment.status == AssignmentStatus.published,
                Submission.id.is_(None),
            )
            .order_by(Assignment.due_at)
        )
    ).all()
    if outstanding:
        lines.append("\nOutstanding homework:")
        for a in outstanding[:5]:
            due = a.due_at.strftime("%d %b") if a.due_at else "no due date"
            lines.append(f"  - {a.title} (due {due})")

    return "\n".join(lines)
