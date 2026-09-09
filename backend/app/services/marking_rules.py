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

**Never stale, by compare-and-swap.** Writing `marking_rules` clears
`marking_rules_summary` and enqueues this job, and `build_marking_context` falls
back to the full text whenever the summary is absent — so the window between a
save and this job finishing marks correctly, at full cost, and a permanently
failing summarisation degrades to that rather than dropping the tutor's rules.

Clearing on write is *not* sufficient on its own, and an earlier revision of
this module claimed it was. The job reads the rules, awaits a model call, then
writes; a save landing inside that gap leaves the older summary committed after
it, and the newer job then sees a non-null summary and returns early — stale
forever (cubic). `marking_rules_summary_of` closes it: the hash of the rules a
summary was built from, checked again after the call and before the write.

`BE-6`: safe to re-run on the same payload, and free — a redelivery whose hash
already matches returns without calling the provider.
"""

import hashlib
import logging

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiFeature, Subject
from app.services.ai import record_usage, require_parsed, structured_complete

log = logging.getLogger("api")

SUMMARISE_JOB = "summarise_marking_rules"


def fingerprint(rules: str) -> str:
    """The identity of one body of rules, for compare-and-swap.

    A hash rather than the text again: `marking_rules` caps at 8,000 characters
    and this is a fixed 64, and the only question ever asked of it is whether
    two bodies of rules are the same one."""
    return hashlib.sha256(rules.encode()).hexdigest()


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
    if subject is None or not subject.marking_rules:
        return
    rules = subject.marking_rules
    stamp = fingerprint(rules)
    # Keyed on the rules, not on "is there a summary". A redelivery for the same
    # text returns free; a job for text that has since been replaced does not
    # get skipped by the summary its predecessor left behind.
    if subject.marking_rules_summary_of == stamp:
        return

    response = await structured_complete(
        surface="marking_rules",
        content=[{"type": "text", "text": rules}],
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

    # Re-read after the await. The tutor may have saved again while the model
    # was working, and writing a summary of text that is no longer theirs is the
    # stale-forever case this whole mechanism exists to prevent.
    await session.refresh(subject)
    if subject.marking_rules != rules:
        log.info(
            "marking rules for subject %s changed while summarising; discarding this result",
            subject.id,
        )
        return

    # An empty result is not a summary — it is the model finding no marking
    # instructions in text the tutor believed was marking instructions. The
    # column stays null so the full text keeps reaching the prompt, which is the
    # safe reading of a disagreement between the two (PROD-2's posture: an
    # absent answer is not a zero). The *fingerprint* is still written, so this
    # answer is remembered rather than re-bought on every redelivery.
    lines = [line.strip() for line in summary.rules if line.strip()]
    subject.marking_rules_summary_of = stamp
    if not lines:
        log.warning(
            "marking-rules summary came back empty for subject %s; "
            "marking keeps using the full text",
            subject.id,
        )
    else:
        subject.marking_rules_summary = "\n".join(f"- {line}" for line in lines)
    await session.commit()
