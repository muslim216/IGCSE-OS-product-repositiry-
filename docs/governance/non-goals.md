# Architectural Non-Goals

> **Governance layer.** What MANARA deliberately does not do, and what it is deliberately
> not built with.
>
> **Status:** Active · Part of Engineering Constitution v1.0

## Purpose

Architectural drift rarely arrives as a decision. It arrives as a series of individually
reasonable additions, each of which seemed small. This document names the things MANARA has
decided against, so that proposing one is a conversation rather than a commit.

**A non-goal is not a permanent ban.** It is a statement that the default answer is no, and
that reversing it requires an ADR naming the trigger that changed. Every entry below
therefore carries the condition under which it should be revisited.

Individual documents carry their own domain non-goals in their **Scope** section. This
document holds the ones that span the whole system.

---

## Architecture and infrastructure

### No microservices

MANARA is one FastAPI application and one React application. There is no service mesh, no
inter-service RPC, no per-domain deployable.

*Why:* the entire system is ~12,400 lines of Python serving a single-tutor product. Service
boundaries would add network failure modes, distributed transactions, and deployment
coordination to buy independent scaling nobody needs. The `api/ → services/ → models/`
layering already provides the module boundaries; they simply do not need a network between
them.

*Revisit when:* a single subsystem's resource profile genuinely conflicts with the rest —
for example, if document processing needs GPUs or 10× the memory of the API. Extract that
one thing. Do not decompose on principle.

### No Kubernetes

Deployment is a Render Docker service and a Vercel static site. There is no cluster, no
Helm, no operator.

*Why:* the API runs as a single instance by construction (see below). Kubernetes solves
orchestration problems that a single container does not have, and costs a permanent
operational surface.

*Revisit when:* the single-instance constraint is lifted **and** the service count exceeds
what a platform-as-a-service handles comfortably.

### No Redis, no external queue, no message broker

Background work is rows in the `jobs` Postgres table, claimed by an in-process asyncio
worker. Rate limiting is a process-global dict. Caching is Postgres, the AI providers'
prompt cache, and TanStack Query in the browser.

*Why:* one datastore is one thing to back up, one thing to restore, one thing to reason
about, and one place a job can hide. A job is a row you can `SELECT`. See
`docs/adr/0002-postgres-backed-job-queue.md`.

*Revisit when:* the API scales beyond one instance. At that moment the in-process rate
limiter and local-disk storage break simultaneously, and Redis or equivalent becomes the
obvious answer for at least the limiter. This is a named trigger, not a hypothetical — see
`RISK-1` in `governance/risk-register.md`.

### No event sourcing, no CQRS

State is current-value rows. Where history matters, MANARA uses explicit append-only tables
— `evidence`, `factor_evaluations`, `readiness_history`, `mark_override_audit` — rather than
deriving state from a log.

*Why:* append-only tables give the audit trail and the explainability the product needs
(§01 P2) at a fraction of the complexity. Reads stay simple, and the tables are queryable
directly rather than through a projection.

*Revisit when:* an auditor or regulator requires reconstruction of arbitrary past state that
the existing append-only tables cannot provide.

### No multi-region, no read replicas

One Postgres instance, one region.

*Why:* the product serves tutors and students in a small number of timezones, and the data
volume is small. Replication buys latency and availability we do not currently need, at the
cost of consistency questions we would then have to answer.

*Revisit when:* p95 latency for a meaningful user population is dominated by geography, or
availability requirements exceed what a single region provides.

## Data

### No UUID primary keys

Every table uses an integer autoincrement primary key.

*Why:* consistency across 52 tables is worth more than the individual merits of either
choice, and integer keys are smaller, faster to index, and easier to read in logs and
support conversations.

*Note:* this means **object IDs are enumerable**, so authorization must never rely on ID
unguessability. It does not — see `SEC` rules in §07. That is the price of this decision and
it is paid explicitly.

*Revisit when:* IDs must be generated offline or merged across databases.

### No soft deletes

Deletion is deletion. There is no `deleted_at` column anywhere in `backend/app/models/`.

*Why:* soft deletes leak into every query in the system, and every query that forgets the
filter is a data-leak bug. Where history genuinely matters, MANARA keeps an append-only
table instead.

*Revisit when:* a product requirement needs undo or retention for a specific entity. Add it
to that entity deliberately — do not adopt it globally.

### No native database enums

Every enum column is `Enum(X, native_enum=False, length=N)` — a `VARCHAR` with a check.

*Why:* adding an enum member needs no migration, and the test suite runs on SQLite where
native enums do not exist. See `docs/adr/0007-varchar-enums.md`.

*Revisit when:* the cost of an unconstrained column exceeds the cost of a migration per
enum value. It does not currently.

### No ORM-generated migrations

Migrations are hand-written, sequentially numbered, and reviewed as code.

*Why:* autogenerate produces diffs nobody reads, misses data migrations entirely, and does
not understand SQLite's batch-mode constraints — which this project has already had to work
around by hand.

*Revisit when:* never, realistically. Autogenerate may be used as a **starting point** for a
hand-written migration; its output is not the migration.

## AI

### MANARA is not an AI tutor and not a homework marker

The platform is the product; AI enhances every layer. A feature that is impressive AI but
strengthens none of the six surfaces is not a MANARA feature.

*Why:* §01 P1. This is a product boundary with architectural consequences — it is why AI
output is a proposal, why the tutor's authority is structural rather than a setting, and why
no model is asked for a grade.

*Revisit when:* the product strategy changes, which is an owner decision and not an
engineering one.

### No model is asked to produce a grade

The AI returns a score, weak topics, and prose. `predict_grade()` maps score to grade
through tutor-entered boundaries.

*Why:* a grade is a claim about an examination board's boundaries, not a judgement. See
§01 P2 and §09.

*Revisit when:* never, while grade boundaries remain a factual input.

### No AI resolves a dispute about AI output

A student's remark request routes to the tutor with the model's original reasoning attached.
It is never re-adjudicated by a model.

*Why:* §01 P4, and the trust principle in `governance/engineering-philosophy.md`.

*Revisit when:* never.

### No training on user data, no fine-tuning

MANARA calls hosted models with prompts. It does not train, fine-tune, or contribute student
work to any model.

*Why:* the data is minors' academic records. See the data-classification section of §07.

*Revisit when:* only with explicit, informed consent and a legal review — not an engineering
decision.

## Product and process

### No premature multi-tutor UX

The backend is multi-tenant from the first migration. The interface is deliberately
single-tutor.

*Why:* the schema decision is expensive to reverse and was made early; the UX decision is
cheap to reverse and was deferred. That asymmetry is the whole point. See
`docs/adr/0005-multi-tenant-schema-single-tutor-ux.md`.

*Revisit when:* a tutoring centre is an actual customer. It should then be a role and UI
change, and if it turns out to need a migration, that is a defect in how a later table was
designed.

### No payments, no billing

AI usage is metered (`ai_usage_events`) as the foundation for tutor allowances and student
top-ups. Nothing charges anyone.

*Why:* metering is the hard part and it is built; billing is a well-understood integration
that should be added when there is something to bill for.

*Revisit when:* the business model is ready to charge.

### No unnecessary complexity

The catch-all, and the one that decides the cases the entries above do not name.

Every dependency, abstraction layer, and configuration option is a permanent tax paid by
everyone who touches the system afterwards. The default answer to "should we add X" is no,
until X solves a problem MANARA actually has, demonstrated with a specific instance.

*Why:* `governance/engineering-philosophy.md` principles 5, 6, and 8.

---

## Proposing a reversal

A non-goal is reversed by an ADR that states:

1. Which non-goal is being reversed.
2. Which named trigger has occurred — or why the trigger was wrong.
3. What the reversal costs, and who pays it.
4. What is now permanently harder.

The ADR supersedes the entry here, and this document is updated to point at it.

## Review triggers

- Any entry's named trigger occurs.
- An ADR reverses a non-goal.
- A pull request proposes something on this list — whether or not it is accepted, the
  discussion belongs here.
- The single-instance constraint is lifted, which affects several entries at once.
