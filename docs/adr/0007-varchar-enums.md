# ADR-0007 — Enums are stored as VARCHAR, not native database enums

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

MANARA's schema is enum-heavy: 22 enum types across 52 tables (at the time of this decision;
task 0.3 later dropped the two chat tables, see §06) cover roles, statuses,
confidence levels, evidence sources, difficulty tiers, mistake categories, readiness factors,
and more. These are a young product's most-churned schema elements — new statuses and new
categories arrive constantly.

Postgres offers native `ENUM` types. SQLAlchemy will happily create them. Adding a value to
one requires `ALTER TYPE ... ADD VALUE`, which historically could not run inside a
transaction and cannot be reversed.

The test suite runs on SQLite in memory, which has no native enum type at all.

## Decision

**Every enum column is `Enum(SomeEnum, native_enum=False, length=N)`** — stored as `VARCHAR`
with a check constraint, never as a native database enum type.

The consequence is stated explicitly in migration `0020_past_papers.py`: *"EvidenceSource
gains 'past_paper' with no DDL — it is stored as VARCHAR."* Adding an enum member requires
**no migration at all**.

One column goes further: `ai_usage_events.provider` is a plain `String(16)` rather than an
enum, precisely so that adding an AI provider never touches the schema.

## Alternatives considered

**Native Postgres enums.** Real database-level validation and a compact on-disk
representation. Rejected because `ALTER TYPE ADD VALUE` is awkward to write, effectively
irreversible in a down-migration, and unavailable in the SQLite test environment — so the
production and test schemas would differ in exactly the dimension being changed most often.

**Plain `VARCHAR` with no constraint.** Maximum flexibility, no validation. Rejected: the
check constraint costs nothing and catches a typo'd status at write time.

**Integer codes with a lookup table.** Compact and referentially sound. Rejected as
unreadable — `status = 3` in a support conversation or a log line is worthless, and this
system's operability depends on being able to read its own rows.

## Consequences

**Easier:** adding an enum value is a one-line Python change. Rows are human-readable in
`psql`, in logs, and in support. The SQLite test schema matches the Postgres schema in shape,
so `Base.metadata.create_all` is a faithful stand-in for this aspect.

**Harder:** slightly larger on-disk representation and index size — irrelevant at this scale.
**Removing or renaming** an enum value still needs a data migration, and the check constraint
must be rebuilt, which on SQLite means `batch_alter_table`.

**The subtle cost:** because adding a value needs no migration, there is no natural moment
that forces you to consider existing rows. A new `SubmissionStatus` member is invisible to
every `if/elif` chain that already exists, and nothing will tell you. Exhaustive handling of
enum values is therefore a review responsibility, not a compiler one.

## Revisit when

The test database becomes Postgres — at which point native enums become testable and the
main objection falls away. Even then the migration cost of switching 22 enum types is
unlikely to be worth it; the decision would apply to new enums only.
