# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the
codebase.

This repo is **single-context**. It has no root `CONTEXT.md` and no `CONTEXT-MAP.md`; its domain
vocabulary and its recorded decisions live in `docs/` instead, under the Avora Engineering
Constitution. The pointers below name the files that actually exist — read those.

## Before exploring, read these

- **`docs/governance/glossary.md`** — the vocabulary. This is what a root `CONTEXT.md` would be in
  another repo: the definition of every domain term (readiness, evidence, classified, submission,
  factor, snapshot). Read it when you are unsure what a term means.
- **`docs/adr/`** — read the ADRs that touch the area you are about to work in. `docs/adr/README.md`
  indexes them. Nine exist today (monolith, Postgres job queue, deterministic readiness,
  polymorphic submissions, multi-tenant schema, per-surface AI routing, varchar enums, split token
  storage, trust-first auto-finalized marking).
- **`docs/volume-1-product-and-ux/01-product-architecture.md`** — the orientation document, read
  before a first change to an unfamiliar area.
- **The volume that owns what you are touching** — `CLAUDE.md` holds the routing table (frontend →
  §03, an endpoint → §05, a migration → §06, and so on). Load the volume; do not work from memory
  of it.

If a file named here doesn't exist, **proceed silently**. Don't flag its absence; don't suggest
creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and
`/improve-codebase-architecture`) creates domain docs lazily, when terms or decisions actually get
resolved.

## File structure

```
/
├── CLAUDE.md                          ← the operating brief + routing table
├── docs/
│   ├── README.md                      ← the index into the constitution
│   ├── governance/glossary.md         ← the vocabulary (this repo's CONTEXT.md)
│   ├── adr/                           ← recorded decisions, 0001…
│   └── volume-1…volume-4/             ← the constitution, by area
├── backend/app/
└── frontend/src/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a
test name), use the term as defined in `docs/governance/glossary.md`. Don't drift to synonyms the
glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language
the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Cite rules by ID

This constitution numbers its rules — `SEC-3`, `API-7`, `DB-11`, `BE-6`. When your output depends on
a convention, cite the rule rather than re-deriving it.
`docs/governance/documentation-authority.md` defines the rule format and the authority hierarchy.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0004 (polymorphic submissions), but worth reopening because…_

The same applies to an Active rule: a change that breaks one either fixes the code, supersedes the
rule, or records a Known Gap — never none of these (`GOV-3`).
