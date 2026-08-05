# 13. Coding Standards

> **Volume 4 — Reliability & Operations** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> Governs how code is written, commented, and delivered.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
  - [Python as written](#python-as-written)
  - [TypeScript as written](#typescript-as-written)
  - [The comment culture](#the-comment-culture)
  - [Git and delivery](#git-and-delivery)
  - [Tooling](#tooling)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Answers *how do I write code that looks like it belongs here*. The codebase has a strong,
consistent style that no tool enforces — which means it survives only as long as it is written
down and followed deliberately.

One element of that style is unusual enough to be worth protecting explicitly: the comments in
this repository explain **why**, not what, and several of them encode reasoning that would
otherwise be lost.

## Scope

**In scope:** Python and TypeScript conventions; naming; typing; error handling; comment
philosophy; file organization; git workflow, branch naming, and commit messages; the
documentation-only exception; the intended toolchain.

**Out of scope:** architectural placement (§04, §03); the API contract (§05); schema conventions
(§06); testing (§12).

### Non-goals

- **No custom style guide beyond what is written here.** Where this document is silent, match
  the surrounding code.
- **No enforced line length.** Existing code sits around 100 characters; nothing checks it.
- **No mandatory docstring on every function.** Docstrings are for non-obvious behaviour, and
  a docstring restating the signature is noise.
- **No type annotations on every local variable.** Signatures are typed; locals are inferred.
- **No comment-density target.** Match the surrounding file.

## Sources

Written from: a repository-wide reading of `backend/app/` and `frontend/src/`;
`backend/pyproject.toml`; `frontend/tsconfig.json`; `frontend/package.json`;
`CLAUDE.md`; the repository's commit history.

---

## Principles

**P1 — Write code that reads like the code around it.** Consistency is worth more than any
individual preference. A file that looks foreign costs every future reader.

**P2 — Comments explain why.** What the code does is in the code. Why it does that — the
constraint, the bug it prevents, the alternative that failed — exists nowhere else.

**P3 — Types are the cheapest documentation.** Both languages are typed; use them at the
boundaries where a reader needs them.

**P4 — Make the safe thing the easy thing.** Prefer constructs that fail closed. A dependency
in a signature beats a call in a body; a database constraint beats a code check.

**P5 — Small, reviewable changes.** `main` deploys on merge, so the diff a reviewer can hold
in their head is the diff that gets reviewed properly.

---

## Current Reality

### Python as written

**Version and style.** Python 3.11+. Roughly 100-character lines, four-space indent, double
quotes. Modern typing syntax throughout — `str | None`, `list[dict]`, `dict[str, float]`, and
`Annotated` for FastAPI dependencies. No `typing.Optional`, no `typing.List`.

**Typing.** Function signatures are annotated, including return types. Locals are not. Models
use SQLAlchemy 2.0's `Mapped[...]` / `mapped_column(...)`. Dataclasses carry field types, and
the pure scoring types are `@dataclass(frozen=True)`.

**Naming.**

| Kind | Convention | Examples |
|---|---|---|
| Modules | lowercase, singular or domain-plural | `marking.py`, `readiness_v2_ai.py`, `past_papers.py` |
| Module-private helpers | leading underscore | `_owned_group`, `_out`, `_decay`, `_write` |
| Constants | upper snake | `MAX_ATTEMPTS`, `HALF_LIFE_DAYS`, `SOURCE_WEIGHTS`, `ALLOWED_MIMES` |
| Enums | `str, enum.Enum`, lowercase members | `UserRole.tutor`, `MarkConfidence.high` |
| Pydantic schemas | `XCreate` / `XUpdate` / `XOut` / `XDetail` / `XIn` / `XSummary` | §05 |
| Booleans | read as a predicate | `is_limited`, `has_mark_scheme`, `needs_review` |

**Async.** Everything is `async def`. Database access is `await session.execute(...)` /
`await session.scalar(...)` with SQLAlchemy 2.0 `select()`. No sync drivers anywhere.

**Error handling.** Routers raise `HTTPException(status, "message")` with a message written for
the reader. Services raise domain exceptions — `AIUnavailableError`,
`GoogleClassroomUnavailableError` — or `ValueError` when the caller may be a job rather than a
request (`services/storage.py:save_bytes` says so explicitly). Bare `except Exception` appears
in exactly three places, all in the worker and chat streaming, all where the process must
survive any error, and all annotated.

**Purity.** Decision math takes plain dataclasses and touches no database:
`services/readiness_factors.py`, `services/readiness.py`'s scoring functions,
`services/grades.py`, and `FixedWindowLimiter` — which is described in its own docstring as
"pure and clock-injectable so the policy is unit-testable without sleeping."

### TypeScript as written

**Configuration.** One `tsconfig.json`, genuinely strict: `strict`, `noUnusedLocals`,
`noUnusedParameters`, `noFallthroughCasesInSwitch`, `isolatedModules`, `noEmit`, ES2022,
`moduleResolution: "bundler"`, `skipLibCheck: true`.

**Components.** Function components with inline prop types:

```tsx
export function StatusBadge({ status }: { status: ReadinessStatus }) { … }
```

Named exports, not default. `PascalCase` files for components, `camelCase` for modules
(`readiness.ts`, `pastPapers.ts`).

**Types.** `interface` for API response shapes, `type` for unions and aliases. Unions with
lookup maps are the house pattern for variant styling — `ReadinessStatus` with `STATUS_STYLES`
and `BAR_FILLS`.

**Data access.** Every module in `api/` exports thin typed functions wrapping `api<T>()`, most
one line. Components call those, never a path literal.

### The comment culture

This is the codebase's most distinctive quality and the easiest to erode.

Comments do not describe what the line does. They record the constraint, the bug, or the
rejected alternative:

- `services/rate_limit.py` — why the counter is per-identifier rather than per-IP (a proxy
  would make it a global lockout), why the window is fixed rather than sliding (an accepted
  trade), and the exact moment it stops being correct.
- `services/storage.py` — why the size check precedes the transcode (checking afterwards feeds
  the decoder an arbitrarily large image and then measures the smaller output).
- `frontend/src/api/client.ts` — why the refresh token is not persisted, and why unparseable
  storage is discarded rather than thrown on.
- `frontend/src/index.css` — why the retarget block must stay unlayered.
- `backend/app/main.py` — why `/docs` is exempt from the CSP.
- `backend/app/security.py` — why the server verifies OAuth `state` even though the client
  also compares it.

Several of these are the only surviving record of a decision. Deleting one loses knowledge that
is not anywhere else.

The `#:` prefix marks a comment documenting the constant that follows — used for
`SECURITY_HEADERS`, `STATE_TOKEN_TTL`, `SOURCE_WEIGHTS`, `_MAGIC`, and
`LOGIN_FAILURE_LIMIT`.

### Git and delivery

**`main` is the only branch anything deploys from**, and a merge ships immediately. The flow:

1. Branch off the latest `main`, named for the work — `fix/…`, `feat/…`, `chore/…`, `docs/…`.
2. Build it there; run both suites locally.
3. Open a pull request into `main`.
4. Merge once green **and** the owner approves — the merge button is theirs unless they have
   said otherwise for that change.
5. Delete the branch on merge. Render and Vercel redeploy on their own.

**The only edits that may go straight to `main` are documentation-only** — prose in
`README.md`, `CLAUDE.md`, or `docs/`. **A code comment is not a documentation change**, because
it lives in a file that ships. Anything under `backend/`, `frontend/`, or `alembic/versions/`
goes through a pull request however small, a one-character edit included, because the deploy
that carries it is the same size either way.

**Branches are disposable and short-lived.** At any moment the repository should hold `main`,
whatever single branch is in flight, and the `archive/*` branches preserving superseded work. A
merged branch is finished — never reopen or stack new work on it.

Commit messages in this repository explain the change and its reasoning in the body, not just
its mechanics. Subject lines are lowercase, imperative, and scoped where it helps
(`docs:`, `fix(migrations):`, `chore:`).

### Tooling

**None.** No ruff, black, isort, flake8, mypy, pyright, ESLint, Prettier, EditorConfig, or
pre-commit. `pyproject.toml` holds two lines of pytest configuration and nothing else;
`package.json` has no lint script.

The `# noqa: BLE001` comments in `workers/jobs.py` and `api/chat.py` were written for a linter
that does not exist here.

`tsc -b` inside `npm run build` is the only static check in the repository, and no automation
runs it (§12).

---

## Standards

### Python

**`CODE-1` — MUST · Important · Active**
Annotate function signatures, including return types. Use modern syntax — `str | None`,
`list[dict]` — never `typing.Optional` or `typing.List`.
*Rationale:* P3, and consistency with every existing module.

**`CODE-2` — MUST · Important · Active**
All I/O is `async`. Never introduce a synchronous database driver, HTTP client, or file read on
a request or job path.
*Rationale:* `BE-13` and `PERF-1` — the worker shares the API's event loop, so one blocking
call stalls every user.

**`CODE-3` — MUST · Important · Active**
Keep decision math pure: plain dataclasses in, values out, no session, no clock read that
cannot be injected.
*Rationale:* `BE-4`, `QA-3`. It is what makes the readiness engine and the rate limiter
testable without fixtures.

**`CODE-4` — MUST NOT · Important · Active**
Do not catch bare `Exception` except where the process must survive any error — the worker loop
and stream handling. Annotate every such site with why.
*Rationale:* a swallowed exception is a silent failure, and §11 already has too many.

**`CODE-5` — MUST · Important · Active**
Raise the specific exception the caller can act on: `HTTPException` in routers, a domain
exception in services, `ValueError` where the caller may be a job rather than a request.
*Rationale:* a job cannot handle an `HTTPException` meaningfully; `save_bytes` documents this
distinction explicitly.

**`CODE-6` — SHOULD · Recommended · Active**
Prefix module-private helpers with `_`. Name booleans as predicates. Name constants in upper
snake at module level.
*Rationale:* P1 — these are the existing conventions, stated so they persist.

**`CODE-7` — SHOULD · Recommended · Active**
Write a docstring where behaviour is non-obvious, has a constraint, or has an ordering
requirement. Do not write one that restates the signature.
*Rationale:* the best docstrings here — `build_homework_evidence`, `save_bytes`,
`FixedWindowLimiter` — all record something the signature cannot.

### TypeScript

**`CODE-8` — MUST · Important · Active**
Keep `tsconfig.json` strict. Never weaken `strict`, `noUnusedLocals`, `noUnusedParameters`, or
`noFallthroughCasesInSwitch` to make a change compile.
*Rationale:* it is the only static analysis in the repository.

**`CODE-9` — MUST NOT · Important · Active**
Do not use `any`. Prefer a precise type; use `unknown` with narrowing where a value genuinely
is not known.
*Rationale:* `any` silently disables the one check that runs.

**`CODE-10` — MUST · Recommended · Active**
Function components with inline prop types, named exports, `PascalCase` component files and
`camelCase` module files.
*Rationale:* P1 — universal in the existing code.

**`CODE-11` — SHOULD · Recommended · Active**
Model variants as a union with a lookup map rather than conditional chains.
*Rationale:* `ReadinessStatus` with `STATUS_STYLES`/`BAR_FILLS` is the pattern, and
`noFallthroughCasesInSwitch` plus exhaustiveness makes a missed variant a type error.

### Comments

**`CODE-12` — MUST · Critical · Active**
Comments explain **why**, not what. A comment restating the code is deleted; a comment
recording a constraint, a prevented bug, or a rejected alternative is kept.
*Rationale:* P2. Several comments in this repository are the only surviving record of a
decision — see the list above.

**`CODE-13` — MUST NOT · Critical · Active**
Never delete a comment recording a constraint or a rejected alternative without confirming the
reasoning no longer holds. If it no longer holds, say so in the commit message.
*Rationale:* the knowledge is not anywhere else, and the cost of losing it is paid by someone
who rediscovers the bug.

**`CODE-14` — MUST · Important · Active**
Match the comment density of the surrounding file.
*Rationale:* P1. Density varies deliberately here — `storage.py` and `rate_limit.py` are dense
because their invariants are subtle; a CRUD router is not.

**`CODE-15` — SHOULD · Recommended · Active**
When code exists because of an architectural decision, cite the ADR or the rule rather than
re-deriving the argument inline.
*Rationale:* `GOV-5` — the reasoning belongs in one place, and a rule ID is stable.

### Git and delivery

**`CODE-16` — MUST · Critical · Active**
Never commit code directly to the default branch. Every change to `backend/`, `frontend/`, or
`alembic/versions/` goes through a pull request, however small.
*Rationale:* a merge deploys immediately with no further gate; the deploy carrying a
one-character change is the same size as any other.

**`CODE-17` — MUST · Critical · Active**
The documentation-only exception covers prose in `README.md`, `CLAUDE.md`, and `docs/`. **A
code comment is not a documentation change.**
*Rationale:* a comment lives in a file that ships, so changing one triggers a deploy.

**`CODE-18` — MUST · Important · Active**
Branch from the latest default branch, named for the work with a `fix/`, `feat/`, `chore/`, or
`docs/` prefix. Delete the branch on merge, and never stack new work on a merged branch.
*Rationale:* the repository should hold the default branch, one branch in flight, and archives.

**`CODE-19` — MUST · Important · Active**
A commit message explains **what changed and why**, not only what. The subject is lowercase and
imperative; the body carries the reasoning.
*Rationale:* the commit log is the only record of reasoning for changes too small to warrant an
ADR.

**`CODE-20` — SHOULD · Important · Active**
Keep pull requests small enough to review in one sitting. Split unrelated changes.
*Rationale:* P5 — `main` deploys on merge, so an unreviewable diff is an unreviewed deploy.

**`CODE-21` — MUST · Critical · Active**
A pull request that changes behaviour a constitution document describes updates that document
in the same pull request.
*Rationale:* `GOV-1`, restated here because this is the document engineers read before opening
one.

**`CODE-22` — MUST NOT · Critical · Active**
Never commit a secret, a credential, or a `.env` file.
*Rationale:* `SEC-24`. Repository history is permanent; a committed key is rotated, not
deleted.

### Tooling

**`CODE-23` — SHOULD · Important · Draft**
Python is formatted and linted by **ruff**, configured in `pyproject.toml`, enforced in CI.
*Rationale:* every rule above is currently enforced by review alone. **Draft** because adding
the configuration is a code change outside this documentation branch. Pairs with `QA-20`.

**`CODE-24` — SHOULD · Important · Draft**
TypeScript is linted by **ESLint** with the React hooks plugin and formatted by **Prettier**,
enforced in CI.
*Rationale:* hook-dependency mistakes are invisible today, and `noUnusedLocals` only fires at
build time. **Draft** — same reason.

**`CODE-25` — SHOULD · Recommended · Draft**
An import-direction check enforces the layering — `models/` importing nothing from `services/`,
`services/` nothing from `api/`.
*Rationale:* `BE-1` and `GOV-7` are Critical rules with no mechanism. **Draft** — needs a
linter first.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **No linter or formatter for Python.** No ruff, black, isort, flake8, mypy. `pyproject.toml` still holds two lines of pytest config. | Every `CODE-*` Python rule is enforced by a human remembering. CI now gates tests, types and migrations, so this is the whole of what `RISK-2` still covers. Blocks `CODE-23`. | `blocking` |
| **No ESLint or Prettier.** `package.json` has no lint script. | Hook-dependency mistakes and unused imports are invisible until a build somebody may not run. Blocks `CODE-24`. | `blocking` |
| **`# noqa: BLE001` comments exist for a linter that does not.** | Harmless, but evidence the toolchain was assumed rather than configured — worth removing or making true. | `nice to have` |
| **Nothing enforces the layering.** `BE-1` and `GOV-7` are Critical with no mechanism. | An import from `services/` into `models/` would pass review only by being noticed. Blocks `CODE-25`. | `before scale` |
| **No `.editorconfig`.** | Indentation and line endings depend on each contributor's editor. | `nice to have` |
| **No commit-message or branch-name check.** | `CODE-18` and `CODE-19` are conventions only. | `nice to have` |
| **No type checker for Python.** `mypy`/`pyright` would catch the `Optional`-handling class of bug that `API-20`'s polymorphic trap belongs to. | A `None` reached inside an authorization check is exactly what a type checker exists to find. | `before scale` |

---

## Review Triggers

Update this document when:

- A linter, formatter, or type checker is configured — most Draft rules become Active together.
- The Python or TypeScript version changes, or `tsconfig.json` strictness changes.
- The branch or deploy workflow changes, including the documentation-only exception.
- A new language or runtime enters the repository.
- A convention emerges in new code that is not written here — either adopt it as a rule or stop
  doing it.
