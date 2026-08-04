# The MANARA Engineering Handbook

This is the constitution for MANARA by OASIS AI. Fourteen documents in four volumes
describe how the system is built, what every engineer — human or AI — must do when
building on it, and where it currently falls short.

It exists because MANARA outgrew the four markdown files that used to hold everything.
The product is ~12,400 lines of Python and ~9,800 lines of TypeScript: 52 tables, 23
routers, 24 services, 21 migrations, 8 background job handlers, 60+ React pages. No one
holds that in their head, and the next engineer to touch it should not have to.

## The one rule that keeps this true

> **A pull request that changes behaviour a document describes MUST update that document
> in the same pull request.**

Documentation that drifts is worse than no documentation, because it is trusted. Several
findings in these pages exist precisely because the old docs described a system that had
stopped being real — an authorization helper presented as the RBAC mechanism that nothing
calls, a CI gate with no configuration in the repository. Each document ends with **Review
triggers**: the specific events that oblige someone to come back and edit it.

## How these documents are written

Every one of the fourteen has the same seven-part shape, so you always know where to look:

| Section | What it holds |
|---|---|
| Header | Volume, purpose, who it applies to, and the **Sources** it was written from |
| Contents | In-page table of contents |
| Principles | Short, quotable articles — the constitutional layer |
| How it works today | The **descriptive** half: real paths, real names, warts included |
| Standards | The **prescriptive** half: numbered, citable rules |
| Known gaps | What is missing, why it matters, and how bad it is |
| Review triggers | When this document must be updated |

**"How it works today" and "Standards" are deliberately separate.** The first tells you
what you will find when you open the code. The second tells you what to do. Where they
disagree, the gap is named rather than smoothed over — that divergence is the most useful
thing a handbook can record.

### Citing a rule

Every standard carries an ID: `SEC-3`, `API-7`, `DB-11`. Cite them in review comments,
commit messages, and agent instructions rather than re-arguing the convention. IDs are
stable and never reused; a withdrawn rule is struck through, not deleted.

| Prefix | Document | Prefix | Document |
|---|---|---|---|
| `PROD` | §01 Product Architecture | `INF` | §08 Infrastructure & Deployment |
| `UX` | §02 UX & Accessibility Standards | `AI` | §09 AI Platform |
| `FE` | §03 Frontend Engineering | `PERF` | §10 Performance Engineering |
| `BE` | §04 Backend Engineering | `REL` | §11 Reliability (SRE) |
| `API` | §05 API Standards | `QA` | §12 Quality Engineering |
| `DB` | §06 Database Design | `CODE` | §13 Coding Standards |
| `SEC` | §07 Security Architecture | `OPS` | §14 Operations Runbooks |

Rules use RFC 2119 verbs. **MUST** and **MUST NOT** are binding: breaking one is a defect,
and a reviewer may block on it alone. **SHOULD** and **SHOULD NOT** carry real weight and
need a stated reason to depart from. **MAY** is genuinely optional.

## The documents

### Volume 1 — Product & UX

| # | Document | Read this when… |
|---|---|---|
| 01 | `volume-1-product-and-ux/01-product-architecture.md` | You need the system map: the six surfaces, the operating loop, the roles, and how evidence becomes a readiness score. **Start here.** |
| 02 | `volume-1-product-and-ux/02-ux-and-accessibility-standards.md` | You are writing any UI. Holds the MANARA design system — which lived only in `frontend/src/index.css` until now — and the accessibility standard. |

### Volume 2 — Application Engineering

| # | Document | Read this when… |
|---|---|---|
| 03 | `volume-2-application-engineering/03-frontend-engineering.md` | You are adding a page, a query, or an API wrapper in `frontend/src/`. |
| 04 | `volume-2-application-engineering/04-backend-engineering.md` | You are adding a router, a service, or a background job in `backend/app/`. |
| 05 | `volume-2-application-engineering/05-api-standards.md` | You are designing or changing an endpoint. Covers naming, status codes, errors, pagination, and versioning. |
| 06 | `volume-2-application-engineering/06-database-design.md` | You are adding a table, a column, or a migration. Holds the full schema and the migration convention. |

### Volume 3 — Platform Engineering

| # | Document | Read this when… |
|---|---|---|
| 07 | `volume-3-platform-engineering/07-security-architecture.md` | You are touching auth, authorization, uploads, secrets, or anything an attacker would enjoy. **Its invariants are load-bearing.** |
| 08 | `volume-3-platform-engineering/08-infrastructure-and-deployment.md` | You are deploying, changing configuration, or wondering why the app is shaped the way it is in production. |
| 09 | `volume-3-platform-engineering/09-ai-platform.md` | You are calling a model, writing a prompt, or changing how AI output is trusted. |
| 10 | `volume-3-platform-engineering/10-performance-engineering.md` | Something is slow, or you are about to write a query that will be. |

### Volume 4 — Reliability & Operations

| # | Document | Read this when… |
|---|---|---|
| 11 | `volume-4-reliability-and-operations/11-reliability-sre.md` | You are thinking about failure: what breaks, what it takes down with it, and how we would know. |
| 12 | `volume-4-reliability-and-operations/12-quality-engineering.md` | You are writing tests, or deciding whether a change is done. |
| 13 | `volume-4-reliability-and-operations/13-coding-standards.md` | You are writing code and want to match the house style, or you are reviewing someone who did not. |
| 14 | `volume-4-reliability-and-operations/14-operations-runbooks.md` | Something is broken right now. Symptoms → diagnosis → action → verification. **Bookmark this one.** |

## Reading order for a new engineer

Roughly a day, in this order:

1. **`README.md`** (repository root) — what the product is, and how to run it locally.
2. **§01 Product Architecture** — the map. Nothing else makes sense without it.
3. **§13 Coding Standards** and **§05 API Standards** — the two you will breach first.
4. **§04 Backend Engineering** or **§03 Frontend Engineering** — whichever you are touching.
5. **§07 Security Architecture** — before your first pull request, not after.
6. **§12 Quality Engineering** — how to prove your change works.
7. **§14 Operations Runbooks** — skim it now so you know it exists at 3am.

Volumes 3 and 4 are reference material. Read §06, §09, §10 and §11 when the work reaches
them.

## The other documents in this repository

| File | What it is | Maintained? |
|---|---|---|
| `README.md` (root) | Product introduction, local setup, deploy walkthrough | Yes |
| `CLAUDE.md` (root) | The agent-facing brief: binding rules plus a map into this handbook | Yes |
| `docs/manara-architecture.md` | The **design spec** for the MANARA update — target state, product decisions, build order | Yes, as a design document |
| `docs/archive/` | Point-in-time records kept for history | No, deliberately |

The distinction between `docs/manara-architecture.md` and this handbook matters:
**that document says what MANARA is being built toward; these say what MANARA is.** Where
the two disagree, the handbook describes reality and the architecture document describes
intent. Neither is wrong — but only one of them tells you what your code will run against.

## Honesty policy

These documents record several things that are broken, missing, or contradicted by the
code. That is deliberate. A "Known gaps" section with a severity is more useful than a
confident description of a system nobody built, and it turns tacit knowledge — the kind
that currently lives in one person's memory — into a list someone else can work through.

Severity means:

- **`blocking`** — actively costs us correctness, security, or velocity now. Fix next.
- **`before scale`** — fine at current volume, breaks at the next order of magnitude, and
  the trigger is named.
- **`nice to have`** — real, but the cost of leaving it exceeds nothing important.

Gaps are recorded here, not fixed here. Closing one is a code change and goes through the
normal pull-request flow in `CLAUDE.md`.
