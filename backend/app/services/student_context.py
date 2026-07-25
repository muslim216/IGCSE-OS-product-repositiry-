"""Builds a compact academic-context block about a student, injected into AI
calls (tutor chat now, reports later) so responses are grounded in the
student's actual readiness and workload rather than generic advice.

Reads from the same Student CRM aggregation the CRM UI uses
(services/student_crm.py) so the AI and the UI never see different numbers."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.services.student_crm import get_student_crm


async def build_student_context(session: AsyncSession, student: User) -> str:
    crm = await get_student_crm(session, student)
    lines: list[str] = [f"Student name: {student.name}"]

    if not crm.readiness:
        lines.append("This student is not enrolled in any subject yet.")
        return "\n".join(lines)

    for subject in crm.readiness:
        lines.append(f"\n{subject.subject_name} ({subject.exam_board}):")
        if subject.score is None:
            lines.append("  No readiness data yet.")
            continue
        lines.append(f"  Overall readiness: {subject.score:.0f}%")
        if subject.weak_topics:
            weak_str = ", ".join(f"{w.topic_title} ({w.score:.0f}%)" for w in subject.weak_topics)
            lines.append(f"  Weakest topics: {weak_str}")

    outstanding = sorted(
        (h for h in crm.homework if h.status == "published" and h.submission_status is None),
        key=lambda h: (h.due_at is None, h.due_at),
    )[:5]
    if outstanding:
        lines.append("\nOutstanding homework:")
        for h in outstanding:
            due = h.due_at.strftime("%d %b") if h.due_at else "no due date"
            lines.append(f"  - {h.title} (due {due})")

    return "\n".join(lines)
