# ADR-0003 — Readiness is deterministic and explainable; AI synthesizes but never grades

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

Readiness is MANARA's central metric. It drives every dashboard, recommendation, and report,
and it is what a tutor shows a parent when explaining whether a child is on track.

Predicting exam performance from academic history is a textbook supervised-learning problem,
and there is real temptation to treat it as one — or, more modernly, to hand a language model
the student's record and ask for a score.

## Decision

**Scoring is deterministic code. The AI's role is bounded and its inputs are mandated.**

Layer 1 (`services/readiness_factors.py`, `services/readiness_v2.py`) computes seven factor
sub-scores by explainable code from stored evidence, writing one append-only
`factor_evaluations` row per factor per run.

Layer 2 (`services/readiness_v2_ai.py`) receives those sub-scores, the tutor's weights, and
the tutor's Knowledge Base, and returns an overall score, weak topics, a rationale, and a
revision plan.

Three constraints make this safe:

1. **The predicted grade is never AI-produced.** `predict_grade()` maps score to grade
   through tutor-entered boundaries.
2. **Every run is traceable.** A shared `evaluation_run_id` links the snapshot to the exact
   factor rows it was synthesized from.
3. **Missing evidence is passed as "no data" and reported as such** — never fabricated, and
   omitted from the weighted average rather than scored zero.

The v1 engine's scoring functions are **pure** — plain frozen dataclasses, no database — and
are reused as Layer 1's internal library.

## Alternatives considered

**A trained model predicting grades from history.** Would likely be more accurate on average.
Rejected because it cannot explain itself to a tutor, cannot be corrected by one, needs
training data MANARA does not have, and would fail exactly where it matters most — on the
atypical student. Accuracy is not the objective function; actionability is.

**Ask a language model for the whole score.** Simple to build. Rejected because it is
non-reproducible, unauditable, and would silently invent numbers for students with sparse
evidence — the precise failure the product cannot survive.

**Pure deterministic scoring with no AI at all.** This is v1, and it works. The synthesis
layer was added because weighting seven factors into a coherent narrative — with a written
rationale and a revision plan a tutor can act on — is genuinely a language task.

## Consequences

**Easier:** any score can be decomposed to its inputs. Scoring math unit-tests without a
database. A tutor can adjust weights and see the effect. An AI outage degrades to v1 rather
than removing the metric.

**Harder:** seven factors plus weights plus decay is more machinery than a single model call.
Two engines currently coexist, and they can disagree (RISK-5). `factor_evaluations` grows
without bound (`DB` retention rule in §06).

**Permanently constrained:** readiness can never become a black box. Any future change must
preserve traceability, which rules out otherwise-attractive approaches.

## Revisit when

Never, for the explainability constraint — it is a product property, not an implementation
choice. The *division of labour* between Layer 1 and Layer 2 may be revisited if synthesis
proves unreliable, in which case the fallback is deterministic weighted aggregation, which
already exists.
