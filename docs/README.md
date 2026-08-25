# The Avora Engineering Constitution

**Version 1.5** · Status: Active

This is the source of truth for how Avora by OASIS AI is built. Four volumes of fourteen
numbered documents describe the system and the standards that govern it, sitting on a
governance layer that says which document wins when two disagree and how the standards
themselves change.

It exists because Avora outgrew the four markdown files that used to hold everything. The
product is ~12,400 lines of Python and ~9,800 lines of TypeScript: 51 tables, 23 routers, 24
services, 21 migrations, 8 background job handlers, 60+ React pages. No one holds that in
their head, and the next engineer to touch it should not have to.

It is written to be read by humans and by AI agents equally. Every rule has a stable
identifier, every document has the same shape, and every claim names the file it was read
from.

---

## Start here

| If you are… | Read |
|---|---|
| New to the codebase | `README.md` (root), then §01, then the [reading order](#reading-order) |
| About to write code | §13 Coding Standards and the document for your layer |
| About to change a standard | `governance/change-process.md` |
| Trying to decide something no rule covers | `governance/engineering-philosophy.md` |
| Unsure what a word means here | `governance/glossary.md` |
| Responding to an incident | §14 Operations Runbooks |
| Wondering why something is built this way | `adr/` |

## The governance layer

These five documents govern the constitution itself. They bind the fourteen numbered
documents and each other.

| Document | What it settles |
|---|---|
| [`governance/engineering-philosophy.md`](governance/engineering-philosophy.md) | The eight ordered principles that decide cases no rule covers |
| [`governance/documentation-authority.md`](governance/documentation-authority.md) | The authority hierarchy, the rule format, rule classification and lifecycle, document structure, versioning |
| [`governance/change-process.md`](governance/change-process.md) | How rules are proposed, changed, deprecated, superseded; when an ADR is required; the `GOV-*` documentation obligations |
| [`governance/non-goals.md`](governance/non-goals.md) | What Avora deliberately does not do and is not built with — and the trigger that would revisit each |
| [`governance/glossary.md`](governance/glossary.md) | Domain terminology, defined once |
| [`governance/ownership.md`](governance/ownership.md) | Who owns each subsystem and document, plus the dependency map |
| [`governance/risk-register.md`](governance/risk-register.md) | Standing architectural risks with likelihood, impact, and mitigation |
| [`adr/`](adr/README.md) | Architecture Decision Records — why each structural decision was made, and what it cost |

### The authority hierarchy, in brief

1. **Engineering Constitution** (`docs/governance/` + the 14 numbered documents)
2. **Architecture Specifications** (`docs/avora-architecture.md`, `docs/adr/`)
3. **`CLAUDE.md`**
4. **`README.md`**
5. **Inline documentation**
6. **Comments**
7. **Examples**

A lower tier may clarify a higher one. **It may never contradict one.** Full rules,
including how to resolve a conflict, in `governance/documentation-authority.md`.

## The fourteen documents

### Volume 1 — Product & UX

| # | Document | Read this when… |
|---|---|---|
| 01 | [Product Architecture](volume-1-product-and-ux/01-product-architecture.md) | You need the system map: the six surfaces, the operating loop, the roles, and how evidence becomes a readiness score. **Start here.** |
| 02 | [UX & Accessibility Standards](volume-1-product-and-ux/02-ux-and-accessibility-standards.md) | You are writing any interface. Holds the Avora design system — which lived only in `frontend/src/index.css` until now — and the accessibility standard. |

### Volume 2 — Application Engineering

| # | Document | Read this when… |
|---|---|---|
| 03 | [Frontend Engineering](volume-2-application-engineering/03-frontend-engineering.md) | You are adding a page, a query, or an API wrapper in `frontend/src/`. |
| 04 | [Backend Engineering](volume-2-application-engineering/04-backend-engineering.md) | You are adding a router, a service, or a background job in `backend/app/`. |
| 05 | [API Standards](volume-2-application-engineering/05-api-standards.md) | You are designing or changing an endpoint. |
| 06 | [Database Design](volume-2-application-engineering/06-database-design.md) | You are adding a table, a column, or a migration. |

### Volume 3 — Platform Engineering

| # | Document | Read this when… |
|---|---|---|
| 07 | [Security Architecture](volume-3-platform-engineering/07-security-architecture.md) | You are touching auth, authorization, uploads, secrets, or AI trust boundaries. **Its invariants are load-bearing.** |
| 08 | [Infrastructure & Deployment](volume-3-platform-engineering/08-infrastructure-and-deployment.md) | You are deploying, changing configuration, or wondering why production is shaped this way. |
| 09 | [AI Platform](volume-3-platform-engineering/09-ai-platform.md) | You are calling a model, writing a prompt, or changing how AI output is trusted. |
| 10 | [Performance Engineering](volume-3-platform-engineering/10-performance-engineering.md) | Something is slow, or you are about to write a query that will be. |

### Volume 4 — Reliability & Operations

| # | Document | Read this when… |
|---|---|---|
| 11 | [Reliability (SRE)](volume-4-reliability-and-operations/11-reliability-sre.md) | You are thinking about failure: what breaks, what it takes with it, and how we would know. |
| 12 | [Quality Engineering](volume-4-reliability-and-operations/12-quality-engineering.md) | You are writing tests, or deciding whether a change is done. |
| 13 | [Coding Standards](volume-4-reliability-and-operations/13-coding-standards.md) | You are writing code, or reviewing someone who did. |
| 14 | [Operations Runbooks](volume-4-reliability-and-operations/14-operations-runbooks.md) | Something is broken right now. **Bookmark this one.** |

## Reading order

Roughly a day, in this order:

1. **`README.md`** (repository root) — what the product is, and how to run it.
2. **§01 Product Architecture** — the map. Nothing else makes sense without it.
3. **`governance/glossary.md`** — skim it. Several ordinary words mean something specific here.
4. **§13 Coding Standards** and **§05 API Standards** — the two you will breach first.
5. **§04 Backend** or **§03 Frontend** — whichever you are touching.
6. **§07 Security Architecture** — before your first pull request, not after.
7. **§12 Quality Engineering** — how to prove your change works.
8. **§14 Operations Runbooks** — skim it now so you know it exists at 3am.

Then, when the work reaches them: §02, §06, §08, §09, §10, §11, and the ADRs behind whatever
you are changing.

## How a document is structured

All fourteen follow the same nine-part shape. Full specification in
`governance/documentation-authority.md`.

**Header · Purpose · Scope (including non-goals) · Sources · Principles · Current Reality ·
Standards · Known Gaps · Review Triggers**

**Current Reality, Standards, and Known Gaps are never mixed.** Current Reality is what you
will find when you open the code, warts included. Standards are what to do. Known Gaps are
the distance between them. Blending the three produces a document that reads as though the
system already works the way we wish it did — which is exactly how the previous
documentation came to describe an RBAC mechanism that nothing calls.

## How a rule is written

```
**`PREFIX-N` — VERB · Class · Status**
The rule, as a single declarative sentence.
*Rationale:* why it exists.
```

- **VERB** — RFC 2119: MUST / MUST NOT / SHOULD / SHOULD NOT / MAY.
- **Class** — Critical (blocks merge), Important (blocks unless justified), Recommended
  (reviewer discretion).
- **Status** — Draft / Active / Deprecated / Superseded.

**Every rule has a rationale.** **IDs are never reused.** **Rules are never silently
deleted** — they are deprecated or superseded in place.

### Rule registry

Each prefix is owned by exactly one document. Other documents cite rules; they never restate
them.

| Prefix | Document | Prefix | Document |
|---|---|---|---|
| `GOV` | `governance/change-process.md`, `governance/ownership.md` | `SEC` | §07 Security Architecture |
| `PROD` | §01 Product Architecture | `INF` | §08 Infrastructure & Deployment |
| `UX` | §02 UX & Accessibility Standards | `AI` | §09 AI Platform |
| `FE` | §03 Frontend Engineering | `PERF` | §10 Performance Engineering |
| `BE` | §04 Backend Engineering | `REL` | §11 Reliability (SRE) |
| `API` | §05 API Standards | `QA` | §12 Quality Engineering |
| `DB` | §06 Database Design | `CODE` | §13 Coding Standards |
| | | `OPS` | §14 Operations Runbooks |

Risks are `RISK-N` in `governance/risk-register.md`. Decisions are `ADR-NNNN` in `adr/`.
Principles are `P1`…`Pn` within a document, cited as `§01 P3`.

## The obligations that keep this true

**`GOV-1` through `GOV-6` are defined in
[`governance/change-process.md`](governance/change-process.md)** — that document is
authoritative for their wording. What follows is a one-line index so you know which rule to
look up, not a second copy of them.

| Rule | Subject |
|---|---|
| `GOV-1` | Changing documented behaviour updates the document, same pull request |
| `GOV-2` | Closing a gap removes its entry |
| `GOV-3` | Breaking an Active rule: fix, supersede, or record — never none |
| `GOV-4` | Rules cite what motivated them; claims cite their source file |
| `GOV-5` | Cite a rule; do not restate it |
| `GOV-6` | Glossary terms carry their glossary meaning |

## Honesty policy

These documents record things that are broken, missing, or contradicted by the code. That is
deliberate, and it is the property that makes the rest believable.

Severity in a Known Gaps table:

| Severity | Meaning |
|---|---|
| **`blocking`** | Costs correctness, security, or velocity now. Fix next. |
| **`before scale`** | Fine at current volume, breaks at the next order of magnitude. Trigger named. |
| **`nice to have`** | Real, but leaving it costs nothing important. |

Gaps are **recorded** here, not fixed here. Closing one is a code change through the normal
pull-request flow in `CLAUDE.md`.

Architectural **risks** are different from gaps and live in `governance/risk-register.md`: a
gap is something wrong now and has a fix; a risk is a way the system could fail later, and
may only have a mitigation.

## The other documents in this repository

| File | What it is | Maintained? |
|---|---|---|
| `README.md` (root) | Product introduction, local setup, deploy walkthrough | Yes |
| `CLAUDE.md` (root) | The agent-facing brief: binding rules plus a map into this constitution | Yes |
| `docs/avora-architecture.md` | The **design spec** for the Avora update — target state, product decisions, build order | Yes, as a design document |
| [`docs/experience-design.md`](experience-design.md) | The **experience spec** — what the tutor, student and parent each see, in what order and in what states; the shared grade and readiness vocabulary; the cold start | Yes, as a design document |
| [`docs/experience-implementation-plan.md`](experience-implementation-plan.md) | The **delivery plan** for that spec — every state each surface can be in, the copy it says in each, and the 30 pull requests that build it, in order | Yes, until Stage 9 lands |
| [`docs/avora-visual-identity.md`](avora-visual-identity.md) | The **visual identity spec** — the Avora art direction (parchment / espresso / terracotta, Lora + Inter, motifs) applied over the settled experience. Phase 2 under `experience-design.md` §11; visual only, never IA | Yes, as a design document |
| `docs/archive/` | Point-in-time records kept for history | No, deliberately |

The distinction between the two design documents — `docs/avora-architecture.md` and
`docs/experience-design.md` — and this constitution matters: **those documents say what Avora
is being built toward; these say what Avora is.** Where the two disagree, neither is wrong —
they answer different questions. But only one tells you what your code will run against.

## Version history

| Version | Date | Change |
|---|---|---|
| **1.5** | 2026-08 | **MANARA → Avora across the prose, and the type checking that was missing** (tasks 0.6–0.10). The rename `1.4` deferred is done: code, docs, package names and the localStorage key, which now migrates a signed-in session across rather than silently ending it. **The accepted ADRs are deliberately not renamed** — `docs/adr/README.md` forbids editing an accepted record, and a rename earns no superseding ADR; the same reasoning holds the `1.4` row above and `docs/archive/` at their historical wording. `mypy app/services app/schemas` and an OpenAPI → TypeScript pipeline both run in CI, narrowing `RISK-2` to the packages mypy does not cover and `RISK-6` to the per-domain wrappers still hand-writing their interfaces. §03, §06 and §12 corrected where they described tooling that now exists or counts that had moved; §06's chain now runs to `0025_user_time_zone`, the per-user time zone (`AV-67`) this work adds, and gained the rule for landing a migration around an already-deployed one. |
| **1.4** | 2026-08 | **The Avora visual identity.** The product's dark "MANARA" midnight theme is inverted to the Avora light identity — a warm parchment canvas, espresso ink, a restrained terracotta accent, and self-hosted Lora + Inter. `§02` rewritten: colour-token table, typography, measured-contrast table, and the `UX-4`/`UX-8`/`UX-9`/`UX-10` examples all re-keyed to the new palette; the "No light mode" and "No webfonts" non-goals superseded with rationale. New design document `docs/avora-visual-identity.md` added (Phase 2 under `experience-design.md` §11; visual only, no IA change). The visible wordmark is renamed `MANARA` → `avora`; the docs-wide prose rename is deferred. |
| **1.3** | 2026-08 | Linting and formatting configured on both languages, closing the last of `RISK-2` except a Python type checker. `CODE-23`, `CODE-24` and `QA-20` promoted Draft → Active; `CODE-26` (a suppression carries its reason) and `QA-22` (formatting commits stand alone) added; `CODE-25` kept Draft with its blocker corrected — the linter now exists, only the layering rule is unwritten. `RISK-2` re-ranked P3 → P4. **`RISK-11` raised to P1**: the first `npm audit` anyone ran reported a critical (`vitest`) and a high (`vite`) advisory, making it the only entry in the register whose trigger has actually fired. §12 and §13 static-analysis sections rewritten from "none" to what is configured and why each exclusion is excluded. |
| **1.2** | 2026-08 | The two user-visible defects fixed. `API-11` promoted Draft → Active — `client.ts` reads FastAPI's 422 list, so a field mistake names the field instead of saying "Unprocessable Entity". `UX-8` and `UX-9` rewritten against a changed palette: `--color-ink-400` removed as unusable (it failed AA on every surface and could not be retuned without becoming `ink-500`), and `--color-line-control` added because nothing existing met WCAG 1.4.11 for a control boundary. §02 contrast table, §03 error handling, §05 error shape and §12 suite counts updated. |
| **1.1** | 2026-08 | Four P1 risks fixed in code and the constitution brought back into agreement with it. `BE-17`, `SEC-11`, `REL-5`, `REL-6`, `QA-19` and `INF-16` promoted Draft → Active; `BE-18` added. `RISK-2`, `RISK-3`, `RISK-4` and `RISK-7` reduced from P1 to residual entries with their remaining gaps named. Current Reality rewritten in §01, §04, §05, §06, §07, §08, §10, §11, §12, §13, §14 and `ADR-0002`. |
| **1.0** | 2026-08 | Initial constitution: governance layer, 14 numbered documents, 9 seed ADRs, risk register. Establishes the authority hierarchy, rule format, and change process. |

Versioning rules — what constitutes a minor versus major bump — are in
`governance/documentation-authority.md`.
