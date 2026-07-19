"""The Report Writer: turns a student's readiness data into an audience-specific
narrative report. The AI writes prose strictly from the factual block we build —
it is told never to invent marks, grades, or facts not present in the data."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    Assignment,
    Group,
    GroupMember,
    ReadinessConfidence,
    ReadinessHistory,
    Report,
    ReportAudience,
    ReportStatus,
    Subject,
    Submission,
    SubmissionStatus,
    Topic,
    TopicReadiness,
    User,
)
from app.services.ai import get_client
from app.services.grades import predict_grade

AUDIENCE_GUIDANCE = {
    ReportAudience.parent: (
        "Write for a PARENT with no technical background. Use plain, warm, "
        "encouraging language. Explain what the numbers mean for their child in "
        "everyday terms. Avoid jargon and raw percentages where a plain-language "
        "description works better. Focus on: is my child improving, are they on "
        "track, what needs attention, and what has changed recently."
    ),
    ReportAudience.student: (
        "Write directly to the STUDENT in a motivating, coaching tone. Celebrate "
        "progress, be honest about weak areas, and give 2-3 concrete, actionable "
        "next steps for revision. Be encouraging, not discouraging."
    ),
    ReportAudience.tutor: (
        "Write for the TUTOR: concise and analytical. Highlight strengths, weak "
        "topics to target in lessons, trend direction, and homework engagement. "
        "Bullet points are fine."
    ),
}

SYSTEM_PROMPT = """You are writing an academic progress report for an IGCSE/O Level \
student. You must write ONLY from the factual data provided — never invent marks, \
grades, percentages, topic names, or events that are not in the data. If the data \
is limited, say so honestly rather than filling gaps. Always describe predicted \
grades as estimates. Output clean Markdown with a short heading and a few sections."""


async def build_report_facts(session: AsyncSession, student: User, subject_ids: list[int]) -> str:
    lines: list[str] = [f"Student: {student.name}"]
    for subject_id in subject_ids:
        subject = await session.get(Subject, subject_id)
        if subject is None:
            continue
        topics = {
            t.id: t
            for t in (
                await session.scalars(select(Topic).where(Topic.subject_id == subject_id))
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
        lines.append(f"\n## {subject.name} ({subject.exam_board} {subject.code})")
        if not confident:
            lines.append("No readiness data yet for this subject.")
            continue
        overall = round(
            sum(topics[r.topic_id].weight * r.score for r in confident)
            / sum(topics[r.topic_id].weight for r in confident),
            1,
        )
        grade = predict_grade(overall, subject.grade_boundaries)
        lines.append(f"Overall readiness: {overall}% (estimated grade: {grade})")

        strong = sorted(confident, key=lambda r: r.score, reverse=True)[:3]
        weak = sorted(
            (r for r in confident if r.score <= 60), key=lambda r: r.score
        )[:5]
        if strong:
            lines.append(
                "Strongest topics: "
                + ", ".join(f"{topics[r.topic_id].title} ({r.score:.0f}%)" for r in strong)
            )
        if weak:
            lines.append(
                "Weakest topics: "
                + ", ".join(f"{topics[r.topic_id].title} ({r.score:.0f}%)" for r in weak)
            )

        # Trend: compare earliest vs latest subject-readiness snapshot.
        history = (
            await session.scalars(
                select(ReadinessHistory)
                .where(
                    ReadinessHistory.student_id == student.id,
                    ReadinessHistory.subject_id == subject_id,
                )
                .order_by(ReadinessHistory.recorded_at)
            )
        ).all()
        if len(history) >= 2:
            delta = round(history[-1].score - history[0].score, 1)
            direction = "improved" if delta > 1 else "declined" if delta < -1 else "held steady"
            lines.append(f"Trend: {direction} ({delta:+.1f} points over {len(history)} snapshots)")

        # Homework completion for this subject.
        total = (
            await session.scalar(
                select(func.count(Assignment.id))
                .join(Group, Group.id == Assignment.group_id)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(
                    GroupMember.student_id == student.id,
                    Group.subject_id == subject_id,
                    Assignment.status.in_(["published", "closed"]),
                )
            )
        ) or 0
        submitted = (
            await session.scalar(
                select(func.count(Submission.id))
                .join(Assignment, Assignment.id == Submission.assignment_id)
                .join(Group, Group.id == Assignment.group_id)
                .where(Submission.student_id == student.id, Group.subject_id == subject_id)
            )
        ) or 0
        if total:
            lines.append(f"Homework: submitted {submitted} of {total} assignments")
    return "\n".join(lines)


async def _visible_subjects(session: AsyncSession, student_id: int, subject_id: int | None) -> list[int]:
    enrolled = (
        await session.scalars(
            select(Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(GroupMember.student_id == student_id)
            .distinct()
        )
    ).all()
    if subject_id is not None:
        return [subject_id] if subject_id in enrolled else []
    return list(enrolled)


async def _write_report(
    audience: ReportAudience, facts: str
) -> str:
    """The AI call — factored out so tests can patch it."""
    client = get_client()
    response = await client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{AUDIENCE_GUIDANCE[audience]}\n\n"
                    f"Here is the factual data — write the report from this only:\n\n{facts}"
                ),
            }
        ],
    )
    return "".join(block.text for block in response.content if block.type == "text").strip()


async def generate_report(session: AsyncSession, payload: dict) -> None:
    report_id = payload["report_id"]
    report = await session.get(Report, report_id)
    if report is None:
        return
    try:
        student = await session.get(User, report.student_id)
        subject_ids = await _visible_subjects(session, report.student_id, report.subject_id)
        facts = await build_report_facts(session, student, subject_ids)
        report.content = await _write_report(report.audience, facts)
        report.status = ReportStatus.ready
        from app.models.base import utcnow

        report.generated_at = utcnow()
        report.error = None
    except Exception as exc:
        report.status = ReportStatus.failed
        report.error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise
