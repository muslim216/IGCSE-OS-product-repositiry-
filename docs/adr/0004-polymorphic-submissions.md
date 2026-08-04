# ADR-0004 — Past papers reuse the homework pipeline via polymorphic submissions

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

Full past papers arrived after the homework pipeline was complete. A past paper is
superficially a different thing from a classified worksheet — it is a whole paper, sat under
conditions, and it feeds a distinct readiness factor.

But everything that happens *to* it is identical: a student submits pages, AI marks them
against a mark scheme, confident scheme-backed marks auto-finalize, the rest queue for tutor
review, overrides are audited, students may request a remark, and finalized marks become
evidence.

The obvious implementation is `PastPaperSubmission` and `PastPaperQuestionMark` tables with
their own marking service.

## Decision

**`Submission` and `QuestionMark` are polymorphic.** Each has two mutually exclusive foreign
keys, with exactly one set:

- `submissions.assignment_id` **xor** `submissions.past_paper_id`
- `question_marks.question_id` **xor** `question_marks.past_paper_question_id`

Marking, the review queue, auto-finalize, `MarkOverrideAudit`, `RemarkRequest`, and
evidence-building therefore apply to past papers **with no past-paper-specific code in those
layers**. `extract_past_paper` reuses the extraction prompt; `build_homework_evidence()`
branches once on `submission.past_paper_id is not None` and tags the evidence
`EvidenceSource.past_paper`, which carries a higher weight than homework.

Enforcement is by two unique constraints per table plus application code. **There is no
CHECK constraint** asserting exactly-one-of.

## Alternatives considered

**Parallel tables and a parallel marking service.** Simplest to reason about per-table, and
rejected because it duplicates the most safety-critical code in the product. Auto-finalize,
the override audit, and remark requests are exactly the logic that must not exist in two
versions — a fix applied to one and not the other is a silent correctness bug in student
marks.

**Single-table inheritance with a `kind` discriminator and nullable columns.** Effectively
what this is, minus the discriminator. A `kind` column was not added because the two foreign
keys already encode it and a third source of truth could disagree with them.

**A shared abstract `Submittable` parent with real joins.** More correct relationally, more
machinery, and it would have required rewriting the existing homework tables rather than
adding two nullable columns.

## Consequences

**Easier:** past papers inherited a mature, tested pipeline for free. One marking service.
One review queue. A fix to auto-finalize applies to both kinds by construction.

**Harder, and this is the real cost:** `assignment_id` is `None` on a past-paper submission.
Any code that reads it unconditionally raises — **including inside authorization checks**,
which is how this became a security-relevant trap rather than a mere bug. `_tutor_owns()` in
`api/submissions.py` is the single place that branch is allowed to live, and §05 makes that a
Critical rule.

**Not enforced by the database:** nothing stops a row with both foreign keys set, or
neither. The unique constraints permit it. This is accepted because every write path goes
through application code that sets exactly one — but it is a real gap, recorded in §06.

## Revisit when

A third kind of submittable work appears. Two polymorphic branches are manageable; three
suggest the abstract-parent design was right after all, and the migration should be done
then rather than accreting a third nullable foreign key.
