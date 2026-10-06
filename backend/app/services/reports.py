"""The Report Writer: turns a student's readiness data into an audience-specific
narrative report. The AI writes prose strictly from the factual block we build —
it is told never to invent marks, grades, or facts not present in the data."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiFeature,
    CustomCriterion,
    CustomCriterionScore,
    Group,
    GroupMember,
    Report,
    ReportAudience,
    ReportStatus,
    Subject,
    User,
    UserRole,
)
from app.schemas.readiness import StudentReadinessSummary
from app.services.ai import record_usage, text_complete
from app.services.custom_criteria import criteria_for_student, subject_names
from app.services.knowledge import build_tutor_context
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


async def build_report_facts(
    session: AsyncSession,
    student: User,
    subject_ids: list[int],
    summary: StudentReadinessSummary | None = None,
) -> str:
    """The factual block the report prompt writes from — the same numbers the
    student's profile shows, because both read build_summary_v2. Pass the
    `summary` already read by `report_summary()` to save reading it twice."""
    lines: list[str] = [f"Student: {student.name}"]
    codes: dict[int, str] = dict(
        tuple(row)
        for row in (
            await session.execute(
                select(Subject.id, Subject.code).where(Subject.id.in_(subject_ids or [0]))
            )
        ).all()
    )
    if summary is None:
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
            # Already the tutor's threshold for this subject, lowest first.
            weak = s.weak_topics
            if strong:
                lines.append(
                    "Strongest topics: "
                    + ", ".join(
                        f"{t.topic_title} ({t.score:.0f}%"
                        f"{', includes tutor estimate' if t.tutor_estimate else ''})"
                        for t in strong
                    )
                )
            if weak:
                lines.append(
                    "Weakest topics: "
                    + ", ".join(
                        f"{t.topic_title} ({t.score:.0f}%"
                        f"{', includes tutor estimate' if t.tutor_estimate else ''})"
                        for t in weak
                    )
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
        # (PROD-1). A subject with no snapshot never carries these counts
        # (they are None there), so this naturally stays silent for it.
        if s.homework_assignment_count:
            lines.append(
                f"Homework: submitted {s.homework_submitted_count} of "
                f"{s.homework_assignment_count} assignments"
            )
        # Marked work counts as something to report (`report_summary`), so the
        # block has to say it: otherwise a student with marks and no readiness
        # run is let through to a model told only "No readiness data yet".
        if s.averaging_score is not None:
            lines.append(
                f"Average on marked work: {s.averaging_score}% "
                f"(across {s.marked_piece_count} marked pieces)"
            )
    return "\n".join(lines)


class NothingToReport(ValueError):
    """The student is in no class the report could draw on, or is in one with
    nothing measured yet. The message is the tutor-facing sentence; the router
    maps this to a 409 (`BE-1`)."""


async def report_subjects(
    session: AsyncSession, generator: User, student_id: int, subject_id: int | None
) -> list[int]:
    """The subjects a report covers, or `NothingToReport`.

    Only what the tutor who asked for it may see: classes in the generator's
    organization, and for a tutor only the ones they teach. A student can sit
    in a second organization's class, and an "all subjects" report used to
    cover that one too (`SEC-8`).

    This is close to `api/readiness.visible_subject_ids` but not the same rule,
    and a job handler could not import that router anyway (`BE-1`). The admin
    branches match. The tutor branch there filters by `Group.tutor_id` alone;
    this one also requires the class to be in the generator's organization, so
    it can only ever be the narrower of the two.

    Report subjects come from class membership, which is narrower than CRM
    enrolment: a tutor can ask for a subject the student is enrolled in but has
    no class for. That used to yield an empty list, a facts block of just
    "Student: X", and a model asked to write a report from nothing — which it
    did, fluently. Never returns an empty list, so no caller can reach the
    model without a subject to write about (`PROD-1`, `PROD-2`).
    """
    enrolled = (
        await session.scalars(
            select(Group.subject_id)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(
                GroupMember.student_id == student_id,
                Group.organization_id == generator.organization_id,
                Group.deleted_at.is_(None),
                *([Group.tutor_id == generator.id] if generator.role == UserRole.tutor else []),
            )
            .distinct()
        )
    ).all()
    subjects = list(enrolled) if subject_id is None else [s for s in enrolled if s == subject_id]
    if not subjects:
        raise NothingToReport(
            "This student isn't in a class yet, so there is nothing to report."
            if subject_id is None
            else "This student isn't in a class for that subject yet, "
            "so there is nothing to report."
        )
    return subjects


async def report_summary(
    session: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    """What the report will be written from, or `NothingToReport`.

    A student in a class with no readiness score, no marked work and no homework
    on record has a facts block of "No readiness data yet" — and the model wrote
    a fluent report from that. Absent data is said to be absent (`PROD-2`), by
    us and before the model is asked.
    """
    summary = await build_summary_v2(session, student, subject_ids)
    if not any(
        s.score is not None or s.averaging_score is not None or s.homework_assignment_count
        for s in summary.subjects
    ):
        raise NothingToReport(
            "Not enough data yet: this student has no readiness score, marked work or "
            "homework to report on."
        )
    return summary


def criteria_section(
    rows: list[tuple[CustomCriterion, CustomCriterionScore | None]],
    subject_id: int | None,
    subject_names: dict[int, str],
) -> str:
    """The tutor's hand scores as a fixed list for the end of a report (owner
    decision 19). Appended after the AI has written, never passed to it: the
    model must not blend a tutor's judgement into prose that reads as measured
    (decision 6). A bullet list, not a table, because the report `Markdown`
    renderer draws lists and not tables. Unscored says so — never 0 (`PROD-2`).

    A subject-scoped criterion carries its subject's name, because two of them
    may share a name; an account-wide one stays bare."""

    def label(criterion: CustomCriterion) -> str:
        subject = subject_names.get(criterion.subject_id) if criterion.subject_id else None
        # A subject name is tutor-typed and lands in Markdown a parent reads as
        # Avora's own, so it is held to one line exactly as a criterion name is
        # (`schemas/custom_criteria._strip`) — a newline could forge a heading.
        return f"{criterion.name} ({' '.join(subject.split())})" if subject else criterion.name

    lines = [
        f"- {label(criterion)}: "
        + ("Not scored" if score is None else f"{score.score} / 100 (tutor-entered)")
        for criterion, score in rows
        if subject_id is None or criterion.subject_id in (None, subject_id)
    ]
    if not lines:
        return ""
    return "\n".join(
        [
            "## Tutor-entered criteria",
            "",
            "Scored by the tutor, not measured by Avora. Not part of the readiness score.",
            "",
            *lines,
        ]
    )


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
    # Already written: delivery is at-least-once, and a re-run used to call the
    # model again and overwrite a report someone may already have read (`BE-6`).
    if report is None or report.status == ReportStatus.ready:
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
        tutor = await session.get(User, report.generated_by_id)
        if tutor is None:
            # Whose classes and whose criteria the report covers is decided by
            # who asked for it; with nobody to ask there is no safe scope.
            report.status = ReportStatus.failed
            report.error = "The tutor who asked for this report no longer exists"
            return
        try:
            subject_ids = await report_subjects(
                session, tutor, report.student_id, report.subject_id
            )
            summary = await report_summary(session, student, subject_ids)
        except NothingToReport as exc:
            # The router refuses this before queueing; reaching here means the
            # student left the class, or the data went, in between. Failed with
            # the reason and a plain return, not a raise: a retry in a minute
            # asks the same question, and the model is never called on an
            # empty facts block.
            report.status = ReportStatus.failed
            report.error = str(exc)
            return
        facts = await build_report_facts(session, student, subject_ids, summary)
        kb_context = await build_tutor_context(session, tutor.id, report.subject_id)
        report.content = await _write_report(
            report.audience,
            facts,
            session,
            # The cost belongs to the organization that asked for the report —
            # for a shared student that is not the student's home one.
            organization_id=tutor.organization_id,
            tutor_id=report.generated_by_id,
            student_id=report.student_id,
            kb_context=kb_context,
        )
        # The generating tutor's criteria, not the student's home
        # organization's: for a student who also sits in a second
        # organization's class those are two different lists (`SEC-7`).
        rows = await criteria_for_student(session, tutor.organization_id, student.id)
        criteria = criteria_section(
            rows,
            report.subject_id,
            await subject_names(
                session, [criterion for criterion, _ in rows], tutor.organization_id
            ),
        )
        if criteria:
            report.content = f"{report.content}\n\n{criteria}"
        report.status = ReportStatus.ready
        from app.models.base import utcnow

        report.generated_at = utcnow()
        report.error = None
    except Exception as exc:
        report.status = ReportStatus.failed
        report.error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise
