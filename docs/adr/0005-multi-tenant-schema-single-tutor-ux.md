# ADR-0005 — Multi-tenant schema from day one, single-tutor UX

**Status:** Accepted · **Date:** 2026-08 (retroactive) · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —

## Context

MANARA's first customers are individual tutors. Its stated long-term market includes
tutoring centres and schools — organizations with several tutors sharing students, classes,
and settings.

Retrofitting tenancy onto a live system is among the most expensive migrations there is:
every table needs a column, every query needs a filter, and every missed filter is a
cross-customer data leak discovered by a customer.

## Decision

**The data model is organization-scoped from the first tenancy migration (0012). The user
experience is deliberately single-tutor.**

- `organizations` table; every user carries `organization_id`, non-nullable.
- A personal organization is auto-created for each tutor at signup. Students and parents
  inherit their creating tutor's organization.
- Every top-level aggregate carries `organization_id`; child rows scope through their
  parent.
- `api/deps.py` provides `get_current_org_id()` and `CurrentOrg` for scoping.

Going organization-level later — multiple tutors per organization, an `org_admin` role — is
intended to be a role and interface change, **not a schema migration**.

## Alternatives considered

**Single-tenant, add tenancy later.** Cheaper immediately. Rejected because the migration
cost grows with every table added, and the failure mode of getting it wrong under time
pressure is a data leak between paying customers.

**Database-per-tenant.** Strong isolation. Rejected: unworkable migration story across N
databases, and the wrong shape for a product where subjects and syllabuses are deliberately
shared globally.

**Row-level security in Postgres.** Genuinely attractive — it would enforce in the database
what is currently enforced by convention. Rejected because the test suite runs on SQLite,
which has no equivalent, so the enforcement would be untested in CI and only present in
production. Worth revisiting if the test database changes.

## Consequences

**Easier:** adding a second tutor to an organization is a role change. Every aggregate
already has the column. The expensive, risky migration was done once, early, on a small
dataset.

**Harder:** every new table must remember `organization_id` (`PROD-3`), and every query must
remember to filter (`PROD-4`). Nothing enforces either.

**The gap this decision exposes:** `CurrentOrg` and `get_current_org_id()` were built for
exactly this and **are never called**. Scoping is applied ad hoc per query with
`user.organization_id`. The decision was sound; the mechanism intended to make it safe was
not adopted. That is RISK-7, and it is the single largest unrealized benefit of this ADR.

**A subtlety worth stating:** subjects are deliberately **global**, shared across
organizations, because the five built-in syllabuses serve everyone. This means scoping by
subject alone leaks across tenants — the past-paper visibility bug this caused is why
`_enrolled_scope` in `api/past_papers.py` scopes by (organization, subject).

## Revisit when

A tutoring centre becomes an actual customer. If enabling that turns out to require a schema
migration, this ADR's central bet failed, and the reason should be recorded — it will
almost certainly be a table added later without `organization_id`.
