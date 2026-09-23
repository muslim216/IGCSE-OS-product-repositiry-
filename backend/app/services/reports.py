"""The Report Writer: turns a student's readiness data into an audience-specific
narrative report. The AI writes prose strictly from the factual block we build —
it is told never to invent marks, grades, or facts not present in the data."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiFeature,
    Group,
    GroupMember,
    Report,
    ReportAudience,
    ReportStatus,
    Subject,
    User,
)
from app.services.ai import record_usage, text_complete
from app.services.knowledge import build_tutor_context
from app.services.readiness_shared import WEAK_THRESHOLD
from app.services.readiness_summary_v2 import build_summary_v2

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


async def build_report_facts(session: AsyncSession, student: User, subject_ids: list[int]) -> str:
    """The factual block the report prompt writes from — the same numbers the
    student's profile shows, because both read build_summary_v2."""
    lines: list[str] = [f"Student: {student.name}"]
    codes: dict[int, str] = dict(
        tuple(row)
        for row in (
            await session.execute(
                select(Subject.id, Subject.code).where(Subject.id.in_(subject_ids or [0]))
            )
        ).all()
    )
    summary = await build_summary_v2(session, student, subject_ids)
    for s in summary.subjects:
        lines.append(f"\n## {s.subject_name} ({s.exam_board} {codes.get(s.subject_id, '')})")
        if s.score is None:
            lines.append("No readiness data yet for this subject.")
        else:
            # One source since 2.4 (AV-11): no boundaries set means no predicted
            # grade in the report either — the sentence drops rather than carrying
            # a dash a model would then have to explain (PROD-2).
            lines.append(
                f"Overall readiness: {s.score}% (estimated grade: {s.predicted_grade})"
                if s.predicted_grade
                else f"Overall readiness: {s.score}% (no grade boundaries set for this subject)"
            )
            strong = sorted(s.topics, key=lambda t: t.score, reverse=True)[:3]
            weak = sorted(
                (t for t in s.topics if t.score <= WEAK_THRESHOLD), key=lambda t: t.score
            )[:5]
            if strong:
                lines.append(
                    "Strongest topics: "
                    + ", ".join(f"{t.topic_title} ({t.score:.0f}%)" for t in strong)
                )
            if weak:
                lines.append(
                    "Weakest topics: "
                    + ", ".join(f"{t.topic_title} ({t.score:.0f}%)" for t in weak)
                )
            if s.direction is not None:
                word = {"up": "improved", "down": "declined", "flat": "held steady"}[s.direction]
                moved = (
                    f" ({s.month_delta:+.1f} points in the last 30 days)"
                    if s.month_delta is not None
                    else ""
                )
                lines.append(f"Trend: {word}{moved}")
        # Homework completion is independent of the readiness score: a
        # ready, score=None run (no factor had evidence) still persists its
        # homework_performance row, so "N of M handed in" is a fact the
        # report can state even with no overall number to lead with
        # (PROD-1). v1-fallback subjects never carry these counts (they are
        # None there), so this naturally stays silent for them.
        if s.homework_assignment_count:
            lines.append(
                f"Homework: submitted {s.homework_submitted_count} of "
                f"{s.homework_assignment_count} assignments"
            )
    return "\n".join(lines)


async def _visible_subjects(
    session: AsyncSession, student_id: int, subject_id: int | None
) -> list[int]:
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
    audience: ReportAudience,
    facts: str,
    session: AsyncSession,
    *,
    organization_id: int,
    tutor_id: int,
    student_id: int,
    kb_context: str = "",
) -> str:
    """The AI call — factored out so tests can patch it."""
    response = await text_complete(
        surface="reports",
        prompt=(
            f"{AUDIENCE_GUIDANCE[audience]}\n\n"
            f"Here is the factual data — write the report from this only:\n\n{facts}"
        ),
        max_tokens=2000,
        extra_system=[kb_context] if kb_context else [],
    )
    await record_usage(
        session,
        response,
        organization_id=organization_id,
        tutor_id=tutor_id,
        student_id=student_id,
        feature=AiFeature.report,
    )
    return response.text.strip()


async def generate_report(session: AsyncSession, payload: dict) -> None:
    report_id = payload["report_id"]
    report = await session.get(Report, report_id)
    if report is None:
        return
    try:
        student = await session.get(User, report.student_id)
        if student is None:
            # Fail the row rather than returning quietly. The handler returning
            # successfully makes process_one_job() mark the job done, so a bare
            # return leaves the report in `generating` for ever — no retry, no
            # error, and a tutor watching a spinner that will never resolve.
            report.status = ReportStatus.failed
            report.error = "The student this report was for no longer exists"
            return
        subject_ids = await _visible_subjects(session, report.student_id, report.subject_id)
        facts = await build_report_facts(session, student, subject_ids)
        tutor = await session.get(User, report.generated_by_id)
        kb_context = (
            await build_tutor_context(session, tutor.id, report.subject_id)
            if tutor is not None
            else ""
        )
        report.content = await _write_report(
            report.audience,
            facts,
            session,
            organization_id=student.organization_id,
            tutor_id=report.generated_by_id,
            student_id=report.student_id,
            kb_context=kb_context,
        )
        report.status = ReportStatus.ready
        from app.models.base import utcnow

        report.generated_at = utcnow()
        report.error = None
    except Exception as exc:
        report.status = ReportStatus.failed
        report.error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise
