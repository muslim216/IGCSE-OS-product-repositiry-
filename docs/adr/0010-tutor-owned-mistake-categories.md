# ADR-0010 — Mistake categories are a tutor-owned table, not an enum

**Status:** Accepted · **Date:** 2026-09-18 · **Owner:** Architecture owner
**Supersedes:** — · **Superseded by:** —
**Relates to:** [ADR-0007](0007-varchar-enums.md), which counts mistake categories among the
22 enums it governs. 0007 is untouched and still right for the other 21 — this is one enum
leaving that set, not a change to how enums are stored.

## Context

`MistakeCategory` was a five-member enum in `models/readiness_v2.py`: `misread`,
`content_gap`, `careless`, `calculation`, `time_management`. A `Mistake` row carried one of
them, and the Mistake Analysis readiness factor counted them by name.

Those five words are a claim: that every tutor, teaching every subject, sorts a wrong answer
the same way. A Chemistry tutor distinguishing "wrote the formula backwards" from "balanced it
wrong" has neither, and "careless" flattens both. A tutor who disagreed with the list had
nothing to change — the vocabulary was in the schema.

ADR-0007 made adding a member cheap, which is why this went unexamined for so long: the list
could always grow. But growing a shared list is not the same as a tutor owning their own, and
a member added for one organization would have appeared for every other.

The enum was also never written to. `mistakes` has no writer anywhere in `backend/app`, so
Phase 4 is the first change that makes any of this observable, and the first chance to settle
the model while there is no data to migrate.

## Decision

**A mistake category is a row in a `mistake_categories` table, owned by an organization and
scoped to a subject** — `unique(organization_id, subject_id, lower(name))`, the same scoping
`GradeBoundary` already uses, for the same reason: a subject belongs to one tenant, tutors
sharing an organization share its setup, and no tenant may see another's.

Three consequences follow, and each is load-bearing:

**Nothing may branch on a category's value.** No `if name == "careless"`, anywhere, ever. The
contents are tutor data. Code that reads meaning into them breaks the moment someone renames
one — silently, because a rename is a valid edit that fails nothing. This is the rule the
whole change exists to make possible, and it is the one a future reader is most likely to
break by accident.

**Defaults are offered, never written.** The five words survive as `DEFAULT_CATEGORIES`, a
module constant the editor pre-fills and `ensure_categories()` writes on first use. Until one
of those happens the organization has no categories and the table says so. Writing a published
starting point on a tutor's behalf would make a guess indistinguishable from their own
decision afterwards — the discipline `services/grade_boundaries.py` already established.

**A category in use is archived, not deleted.** A `Mistake` points at a category; deleting one
would take away the word a mistake was tagged with. Archiving hides it from new tagging and
from the editor while everything already tagged keeps reading back. This is why the save
**diffs** rather than replacing, which is the one place it diverges from
`set_org_boundaries`'s delete-then-insert.

Unique on the *folded* name, because the editor and `save_categories` both
treat "Careless" and "careless" as one category. A database that did not would
let two saves landing at once store both, after which the editor reads its own
stored list as a duplicate and refuses to save anything — a state the tutor
cannot leave from the screen. An expression index rather than a constraint:
Postgres has no functional `UNIQUE` constraint.

## Alternatives considered

**Keep the enum, add a free-text "other".** Smallest change, and it preserves aggregation
across tenants. Rejected: "other" becomes the majority bucket for any tutor whose vocabulary
is not the five, and an unanalysable majority bucket is worse than no category at all.

**A global category table with per-tutor overrides.** Rejected as the worst of both — it keeps
a canonical list nobody agreed to, and adds a resolution rule to every read.

**Per-organization but not per-subject.** Rejected: mistakes in Chemistry and in English
Literature do not sort alike, and `GradeBoundary` had already settled that subject-level
configuration is the right grain. The cost is real — a tutor with five subjects maintains five
lists — and accepted.

## Consequences

Cross-tenant aggregation over mistake categories is no longer possible, by construction. Two
organizations' "Careless" are different rows and may mean different things. Nothing in the
product aggregates across tenants today, and `PROD-1` would require a traceable source for
anything that did.

A tutor who archives every category on a subject leaves it with none, and `ensure_categories`
will not refill it — it writes the defaults only the first time a subject has never had a
category at all. So 4.2's tagging job must treat "no categories" as a real, expected outcome:
it sets `mistakes_analysed_at`, records why it tagged nothing, and returns **without calling
the model**. Calling it with no categories would spend a request to have every tag dropped as
unrecognised, and the factor would go dark with nothing saying why — the failure class task
4.0 existed to close.

Category names and descriptions are tutor-supplied strings that 4.2 interpolates into a
prompt. They are bounded (60 and 400 characters) and trimmed, but deliberately not escaped —
the prompt is what must treat them as labelled data rather than instructions, in the same
terms `MARKING` already uses for page content (`SEC-20`, `SEC-21`, `AI-8`).

The enum is gone rather than deprecated, and `0051`'s `downgrade()` refuses if any `mistakes`
row exists: a tutor's own word has no enum member to become, and picking one for them is not a
migration's call (`PROD-1`).
