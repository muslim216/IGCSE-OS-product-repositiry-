"""Condensing a tutor's marking rules into what the marking prompt is given.

Task 3.2c, on the owner's instruction of 9 Sep 2026: the subject's rules are
summarised and the AI uses the summary. The full text stays the tutor's — it is
what they wrote, what they edit, and what they see first. This produces the
form that goes into every marking call for the subject.

**Why not just send the text.** The rules cap at 8,000 characters and chapter
notes at 4,000, so a marking prompt could carry 12,000 characters of tutor
prose on every submission — a per-mark cost, paid again for every student in
the class. The owner's word for that was "way too much".

**What the tutor gives up, said plainly.** A model now sits between a tutor and
their own instructions. A rule lost in summarisation changes how a student is
marked and nothing announces it, which is why the summary is shown to the tutor
(`PROD-7`: they have final authority over everything the AI produces) and why
the prompt's central instruction is to lose nothing that could change a mark.

**Staleness is impossible by construction.** Writing `marking_rules` clears
`marking_rules_summary` in the same statement and enqueues this job, and
`build_marking_context` falls back to the full text whenever the summary is
absent. So the summary is absent or current, never stale; the window between a
save and this job finishing marks correctly at full cost; and a summarisation
that fails permanently degrades to that same state rather than dropping the
tutor's rules.

`BE-6`: safe to re-run on the same payload — it re-reads the subject's current
rules and replaces the summary rather than appending to it.
"""

import logging

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiFeature, Subject
from app.services.ai import record_usage, require_parsed, structured_complete

log = logging.getLogger("api")

SUMMARISE_JOB = "summarise_marking_rules"


class MarkingRulesSummary(BaseModel):
    rules: list[str] = Field(
        description=(
            "The tutor's marking rules as imperatives, one per rule, in the order they "
            "wrote them. Empty when the text contains no marking instructions."
        )
    )


async def summarise_marking_rules(session: AsyncSession, payload: dict) -> None:
    """Rebuild one subject's rule summary from its current full text.

    Does nothing when the rules are empty or the summary is already present:
    the first is nothing to summarise, and the second means a save has not
    invalidated it since the last run — which makes a duplicate job delivery
    free rather than a second billed call (`BE-6`).
    """
    subject = await session.get(Subject, payload["subject_id"])
    if subject is None or not subject.marking_rules or subject.marking_rules_summary:
        return

    response = await structured_complete(
        surface="marking_rules",
        content=[{"type": "text", "text": subject.marking_rules}],
        output_format=MarkingRulesSummary,
        max_tokens=2000,
    )
    await record_usage(
        session,
        response,
        organization_id=subject.organization_id,
        # From the payload, not looked up: the tutor whose rules these are is
        # known at enqueue time, and `BE-9` says payloads carry identifiers.
        # Attributing the spend to whoever happens to be the organization's
        # tutor at run time would be a different fact.
        tutor_id=payload["tutor_id"],
        # No student: this is a per-subject call, not work for anyone.
        student_id=None,
        feature=AiFeature.marking,
    )
    summary = require_parsed(response)

    # An empty result is not a summary — it is the model finding no marking
    # instructions in text the tutor believed was marking instructions. Leaving
    # the column null keeps the full text in the prompt, which is the safe
    # reading of a disagreement between the two (PROD-2's posture: an absent
    # answer is not a zero).
    lines = [line.strip() for line in summary.rules if line.strip()]
    if not lines:
        log.warning(
            "marking-rules summary came back empty for subject %s; "
            "marking keeps using the full text",
            subject.id,
        )
        return
    subject.marking_rules_summary = "\n".join(f"- {line}" for line in lines)
    await session.commit()
