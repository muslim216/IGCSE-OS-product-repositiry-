"""The Tutor Knowledge Base: teaching methods, preferred solving approaches,
resources, marking preferences, direct AI instructions, and notes. Compiled
into a single prompt block and injected into every AI surface that calls
build_tutor_context() — marking, extraction, report generation and readiness
synthesis — so the AI behaves like that specific tutor. (Student chat was a
fifth consumer until it was deleted, AV-57.)"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeEntry, User, UserRole

KIND_LABELS = {
    "teaching_method": "Teaching method",
    "solving_approach": "Preferred solving approach",
    "resource": "Reference resource",
    "marking_preference": "Marking preference",
    "ai_instruction": "Direct instruction to the AI",
    "note": "Note",
}


async def build_tutor_context(
    session: AsyncSession, tutor_id: int, subject_id: int | None = None
) -> str:
    """A prompt block of the tutor's knowledge base — entries that apply to
    every subject, plus (when given) entries scoped to this subject. Returns
    "" when the tutor has no entries, so callers can skip an empty block."""
    query = select(KnowledgeEntry).where(
        KnowledgeEntry.tutor_id == tutor_id, KnowledgeEntry.subject_id.is_(None)
    )
    entries = list((await session.scalars(query.order_by(KnowledgeEntry.created_at))).all())
    if subject_id is not None:
        subject_entries = (
            await session.scalars(
                select(KnowledgeEntry)
                .where(
                    KnowledgeEntry.tutor_id == tutor_id,
                    KnowledgeEntry.subject_id == subject_id,
                )
                .order_by(KnowledgeEntry.created_at)
            )
        ).all()
        entries.extend(subject_entries)
    if not entries:
        return ""
    lines = ["Tutor's knowledge base — teach and communicate the way this tutor does:"]
    for e in entries:
        label = KIND_LABELS.get(e.kind.value, e.kind.value)
        lines.append(f"\n[{label}] {e.title}\n{e.body}")
    return "\n".join(lines)


async def resolve_org_tutor_id(session: AsyncSession, organization_id: int) -> int | None:
    """The organization's tutor. The product is single-tutor-per-org today
    (see CLAUDE.md), so this is well-defined; it becomes a real choice once
    organizations support multiple tutors."""
    return await session.scalar(
        select(User.id).where(User.organization_id == organization_id, User.role == UserRole.tutor)
    )
