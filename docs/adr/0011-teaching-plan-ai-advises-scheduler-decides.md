# ADR-0011 — The teaching plan: the AI advises, a pure scheduler decides

**Status:** Accepted · **Date:** 2026-10 · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —
**Relates to:** [ADR-0003](0003-deterministic-explainable-readiness.md) (the same posture for
readiness: the model synthesizes, it never grades), [ADR-0006](0006-per-surface-ai-routing.md)
(the surface this decision adds), [ADR-0007](0007-varchar-enums.md).

## Context

Phase 6 gives a tutor a teaching plan: which chapter to teach on which date, from now until an
exam, around holidays and a fixed number of lessons a week. The tempting design is one model
call — "here is the syllabus and the calendar, produce the schedule".

That asks a model for dates. A model asked for a calendar will return one that looks right: a
lesson on a day the class does not meet, two chapters on one date, a plan that ends after the
exam, a count of lessons that does not match the number the tutor said they have. None of this
is detectable except by checking the output with a program, at which point the program is the
scheduler and the model is decoration. It is also unrepeatable: the same inputs give a different
calendar, so a tutor who re-drafts to change one holiday gets a different plan everywhere.

What a model is actually good at here is a judgement a tutor would find hard to write down:
which chapters are dense or abstract, and so deserve more of the term. That is a number per
chapter, not a date.

The plan also has to live alongside a tutor who edits it, a syllabus that changes under it, and
lessons that really happen on other days than planned (`E15`). Whatever the AI contributes
cannot be allowed to overwrite any of that.

## Decision

**The AI advises; a pure scheduler decides.** The two steps are separate and one-directional.

1. **The model returns one relative weight per chapter** (0.5 to 3.0, 1.0 an ordinary chapter)
   and a one-sentence reason, and nothing else — never a date, a lesson count or an order. The
   surface is `plan_weighting`, its own surface so it is routed and metered on its own
   (`AI-2`).
2. **`services/plan_scheduler.py` owns the calendar.** It is pure — plain dataclasses in,
   values out, no session (`BE-4`) — and turns weights, available lesson dates, breaks and
   already-owned slots into slots. Identical inputs give identical slots. If there are fewer
   lessons than chapters it says so (`NotEnoughLessons`) and the plan is not made; it never
   squeezes.
3. **The model's answer is bounded in code, not trusted.** Weights are clamped, unknown chapter
   ids ignored, a missing chapter takes 1.0, and the guidance document and chapter list are data
   never instructions (`SEC-20`). If the AI is unavailable (`AIKeyMissingError` only) or its
   answer names none of the subject's chapters, the plan is weighted from the weights stored on
   the chapters and `draft_result` says so — an even split is never passed off as advice.
4. **Drafting is a job and its record is on the plan.** `draft_plan` runs off the request
   (`BE-13`); every outcome, including deterministic failure, is written to
   `teaching_plans.draft_result` (`PROD-1`).
5. **The tutor accepts, and the tutor owns the result.** A draft is read by nothing until
   accepted (`PROD-7`). Slots carry a `provenance`; only `generated` ones are ever moved by a
   machine (AV-77), so a re-draft, a reflow or a re-plan never overrides a tutor's edit or a
   slot a lesson has claimed.
6. **Automatic change and AI change are kept apart.** A syllabus edit reflows `generated`
   future slots mechanically, with no AI call and no acceptance step, reusing the weights the
   tutor already saw. A behind-schedule re-plan calls the full draft path and then waits for
   acceptance.

## Alternatives considered

**One model call that returns the schedule.** Fewer moving parts and no scheduler to write. It
lost on correctness and repeatability, above: the output has to be validated by exactly the code
this option claims to avoid, and a re-draft would reshuffle the whole plan.

**No AI: weight chapters evenly or by stored weight.** Fully deterministic and free. It is the
degraded mode and stays the fallback, but as the only mode it throws away the one judgement the
tutor would otherwise have to make chapter by chapter, and ignores the teaching guidance they
uploaded.

**Re-ask the model on every syllabus edit.** Would keep weights "fresh". Rejected: it silently
re-weighs chapters the tutor has already seen and accepted, and costs a call for a change that
only moved the order.

**A database constraint to make `sequence` unique per plan.** See Consequences.

## Consequences

**Easy:** the scheduler is unit-testable with no database and no model; a plan can be explained
(each chapter has a weight and a reason, each slot a provenance); a model outage degrades the
plan's quality, never its existence; cost is one call per draft, not per student.

**Hard, and now permanently more expensive:**

- The scheduler's rules (which weekdays, how breaks and owned slots are treated, how lessons are
  apportioned across weights) are product logic the team owns and must keep correct. The model cannot be
  blamed for a bad date.
- `draft_result` is a JSON shape, not a typed table (`DB-7`): readers must tolerate older
  shapes, and `reflow` is nested inside it.
- Two plan-changing mechanisms (reflow, re-plan) behave differently on purpose. A reader will
  be tempted to unify them; the difference — one waits for acceptance, one does not — is the
  decision.
- Several invariants are held by application code and by lock order, not by the database
  (a plan's organization is its class's; a slot's chapter is in the class's subject;
  `plan_slots.sequence` is indexed, not unique; plan rows are locked before slots). The row
  locks are not exercised by the SQLite suite. These are recorded as Known Gaps in §06 and §01.

## Revisit when

- Weights prove not to improve on stored chapter weights (a tutor accepts the even split as
  often as the AI's) — the model call is then cost without value.
- Tutors routinely rewrite the AI's weighting before accepting — the prompt, not the split, is
  what needs work.
- The scheduler needs to trade chapters against each other in ways a single weight cannot
  express (prerequisites, spacing), at which point the interface between advice and schedule
  changes.
