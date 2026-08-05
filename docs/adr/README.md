# Architecture Decision Records

> **Tier 2 — Architecture Specifications.** Why the structural decisions were made, and
> what each one cost.
>
> **Status:** Active · Part of Engineering Constitution v1.2

## What an ADR is for

**Standards say what to do. ADRs say why, and what was given up.**

A rule's rationale is one line, and rules get edited. An architectural decision needs more
than a line and must not be edited — the next engineer needs to know not just that MANARA
uses a Postgres job table, but that Redis and Celery were considered, what they would have
bought, and what condition would justify revisiting.

Without ADRs, that reasoning survives only in the head of whoever made the decision. With
them, a competent engineer can disagree with a decision on its merits instead of
rediscovering it by accident.

## When to write one

Write an ADR when a decision:

- **is expensive to reverse** — a schema shape, a storage engine, a deployment topology, an
  auth model;
- **rejects a reasonable alternative** that someone will otherwise re-propose;
- **creates a constraint other work must live within**;
- **is a trade-off rather than a best practice** — something a competent engineer might
  legitimately have decided the other way.

Do not write one for choosing a variable name, adopting an obvious library, or anything an
existing rule already covers completely.

## Lifecycle

| Status | Meaning |
|---|---|
| **Proposed** | Written, under discussion. Not binding. |
| **Accepted** | Binding. **Immutable** from this point. |
| **Superseded** | Replaced by a later ADR, which is named in the header. The original text is never edited. |
| **Deprecated** | No longer applies, and nothing replaced it. Carries the reason. |

**An accepted ADR is never edited.** A decision that changes gets a new ADR that supersedes
the old one, so the history of the system's reasoning stays readable in order. Correcting a
typo is fine; changing the decision, the context, or the consequences is not.

Accepted and superseded by the architecture owner — see `governance/ownership.md`.

## Format

Numbered `NNNN-kebab-case-title.md`, allocated sequentially and never reused.

```markdown
# ADR-NNNN — Title

**Status:** Accepted · **Date:** YYYY-MM · **Owner:** <role>
**Supersedes:** — · **Superseded by:** —

## Context
The situation and the forces at play. What made a decision necessary.

## Decision
What was decided, stated in the active voice.

## Alternatives considered
Each real option, what it would have bought, and why it lost.

## Consequences
What this makes easy, what it makes hard, and what is now permanently more expensive.
Include the bad consequences — an ADR listing only benefits is marketing.

## Revisit when
The observable condition that should reopen this decision.
```

## Index

| ADR | Title | Status | Relates to |
|---|---|---|---|
| [0001](0001-monolith-not-microservices.md) | One deployable API, not microservices | Accepted | §04, §08 |
| [0002](0002-postgres-backed-job-queue.md) | Postgres-backed job queue instead of a broker | Accepted | §04, §11 |
| [0003](0003-deterministic-explainable-readiness.md) | Readiness is deterministic and explainable; AI synthesizes but never grades | Accepted | §01, §09 |
| [0004](0004-polymorphic-submissions.md) | Past papers reuse the homework pipeline via polymorphic submissions | Accepted | §01, §06 |
| [0005](0005-multi-tenant-schema-single-tutor-ux.md) | Multi-tenant schema from day one, single-tutor UX | Accepted | §01, §07 |
| [0006](0006-per-surface-ai-routing.md) | AI providers are routed per surface, not globally | Accepted | §09 |
| [0007](0007-varchar-enums.md) | Enums are stored as VARCHAR, not native database enums | Accepted | §06 |
| [0008](0008-split-token-storage.md) | Access token in memory, refresh token in an httpOnly cookie | Accepted | §07, §03 |
| [0009](0009-trust-first-auto-finalized-marking.md) | Confident, scheme-backed marks auto-finalize | Accepted | §09, §01 |

## Retroactive ADRs

ADRs 0001–0009 were written **after** the decisions they record, as part of establishing
this constitution. They are reconstructions: the decision and its consequences are read from
the code and the surviving design documents, and the alternatives are stated as they would
reasonably have been weighed.

This is worth knowing when reading them. A retroactive ADR is a faithful account of *what
was decided and what it costs*, but it is not a contemporaneous record of the discussion.
ADR-0010 onward should be written before or alongside the change.

## Review triggers

- A decision meeting the criteria above is made.
- An accepted ADR's "Revisit when" condition occurs.
- A non-goal in `governance/non-goals.md` is reversed — that always needs an ADR.
- An ADR is superseded, which requires updating the index and both ADRs' headers.
