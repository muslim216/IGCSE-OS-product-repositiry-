# ADR-0009 — Confident, scheme-backed marks auto-finalize

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

The original marking model was uniform: the AI drafted every mark, and the tutor finalized
every mark. Safe, and it made the AI a typing aid rather than leverage — a tutor with thirty
students still reviewed every question of every submission, and the student waited for all of
it before seeing anything.

The observation that changed the design: the AI's confidence is not uniform. Marking "state
the units" against an official mark scheme is not the same task as judging a partially
worked derivation with no scheme at all.

## Decision

**Confidence is the safety mechanism, and it decides whether a human is required.**

A mark **auto-finalizes** — counting immediately, visible to the student, becoming evidence,
with no tutor action — if and only if it is **both**:

1. **scheme-backed** (`has_mark_scheme`), and
2. **confident** (`MarkConfidence.high` or `medium`).

Everything else sets `needs_review` and waits in `GET /submissions/review-queue` with the
AI's suggestion pre-filled: no official scheme (marked from syllabus and comparable
questions, always confidence `unsure`), low confidence, or a question the AI skipped.

Four guarantees bound the blast radius:

- Proposed marks are **clamped** to the question's valid range.
- A "no data" question is **never silently scored 0**.
- A submission is `auto_finalized` (nothing needed a tutor) or `needs_review` (something
  did); `finalize` requires only the *unsure* questions to be resolved.
- The tutor keeps final authority always. Changing an already-set mark writes an
  append-only `MarkOverrideAudit` row, and there is no API to edit or delete those.

Students can contest **any** finalized mark — auto- or tutor-finalized — via a
`RemarkRequest`, which is **never resolved by AI**: it routes to the tutor with the model's
original reasoning attached. A database-level unique constraint allows one request per
question, ever, so the queue cannot be gamed.

## Alternatives considered

**Tutor finalizes everything.** The previous model. Safe and it does not scale; it also
delays feedback to the student, which is where most of the learning value is.

**AI finalizes everything.** Maximum leverage. Rejected outright: it puts a model's guess on
a student's record with no human accountability, which contradicts `governance/engineering-philosophy.md`
principles 2 and 3.

**A numeric confidence threshold.** Rejected in favour of the two-part test. A high
confidence score without a mark scheme is confidence in an *interpretation*, not in a
*mark* — the scheme is what makes the judgement checkable, so it is a separate requirement
rather than an input to a score.

## Consequences

**Easier:** tutor workload collapses to the genuinely ambiguous questions. Students get
immediate feedback on the clear ones. Evidence and readiness update without waiting on a
human.

**Harder — and this is the significant one:** a mark can now count with no human in the
loop, and **the student controls the page being marked**. That makes the student's
handwriting untrusted input to a prompt whose output has real consequences. The `marking`
prompt therefore states that page content is data and never instructions, and that anything
addressing the marker is flagged with confidence `low` for a tutor rather than acted on.
**That rule is a security control**: if the prompt is rewritten it must be preserved, and
its version bumped. See §07 and §09.

**A second consequence:** prompt and model changes now alter marks that count, with no
evaluation harness to catch a regression. That is RISK-10.

**Reviewability preserved:** every auto-finalized mark still records its `ai_model` and
`ai_prompt_version`, so a bad batch can be identified precisely rather than estimated.

## Revisit when

The remark-request rate, or tutor override rate on auto-finalized marks, indicates the
confidence threshold is miscalibrated. Both are measurable from existing rows and neither is
currently measured — worth building before adjusting the threshold.
