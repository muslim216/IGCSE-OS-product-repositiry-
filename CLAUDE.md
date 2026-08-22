# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

This file is the **operating brief**: the rules that bind every change, and a map into the
detail. It is deliberately short so it can be read in full at the start of every session.

**The full detail lives in `docs/` — the Avora Engineering Constitution.** Load the volume
you need; do not work from memory of it.

## What this is

**Avora by OASIS AI** — an AI Operating System for IGCSE education (formerly **MANARA**, the
"IGCSE Student Operating System"), serving tutors, students, and parents. A Python/FastAPI backend
and a React/Vite frontend live in one repo but deploy as two independent services. The
product's heart is the **Readiness Engine**: every piece of academic evidence feeds
exam-readiness scores that drive every dashboard, recommendation, and report.

Avora is **not** an AI tutor and **not** a homework marker — the platform (Student CRM,
Lessons, Readiness, Knowledge Base *(hidden, `AV-58`)*, Homework, Reports) is the product, with
AI enhancing every layer.

Read `docs/volume-1-product-and-ux/01-product-architecture.md` before your first change.

## Where the detail lives

`docs/README.md` is the index. Load a document when your work touches it:

| Working on… | Read |
|---|---|
| Anything, first | `docs/volume-1-product-and-ux/01-product-architecture.md` |
| UI, styling, accessibility | `docs/volume-1-product-and-ux/02-ux-and-accessibility-standards.md` |
| What a tutor, student or parent sees | `docs/experience-design.md` |
| Building any of that — states, copy, PR order | `docs/experience-implementation-plan.md` |
| `frontend/src/` | `docs/volume-2-application-engineering/03-frontend-engineering.md` |
| `backend/app/` structure, services, jobs | `docs/volume-2-application-engineering/04-backend-engineering.md` |
| An endpoint | `docs/volume-2-application-engineering/05-api-standards.md` |
| A table, column, or migration | `docs/volume-2-application-engineering/06-database-design.md` |
| Auth, uploads, secrets, AI trust | `docs/volume-3-platform-engineering/07-security-architecture.md` |
| Deploy or configuration | `docs/volume-3-platform-engineering/08-infrastructure-and-deployment.md` |
| A model call or a prompt | `docs/volume-3-platform-engineering/09-ai-platform.md` |
| Something slow or expensive | `docs/volume-3-platform-engineering/10-performance-engineering.md` |
| Failure behaviour, logging, health | `docs/volume-4-reliability-and-operations/11-reliability-sre.md` |
| Tests | `docs/volume-4-reliability-and-operations/12-quality-engineering.md` |
| Style, comments, git | `docs/volume-4-reliability-and-operations/13-coding-standards.md` |
| Something is broken in production | `docs/volume-4-reliability-and-operations/14-operations-runbooks.md` |
| Why a decision was made | `docs/adr/` |
| A term you are unsure of | `docs/governance/glossary.md` |
| A decision no rule covers | `docs/governance/engineering-philosophy.md` |
| Proposing or changing a standard | `docs/governance/change-process.md` |

Rules are cited by ID — `SEC-3`, `API-7`, `DB-11`. Cite them rather than re-deriving the
convention. `docs/governance/documentation-authority.md` defines the rule format, the
authority hierarchy, and how rules are deprecated.

**`docs/avora-architecture.md` is the design spec** for the Avora update — the target state.
**`docs/experience-design.md` is the experience spec** — what each role sees, the shared grade
and readiness vocabulary, and the cold start. The constitution documents the system **as
built**. Where they differ they are answering different questions; the constitution tells you
what your code will run against.

## How work reaches production

**`main` is the only branch anything deploys from.** Render (API) and Vercel (frontend) both
build from it and nothing else. It is the sole *source* of what the user is running, not a
guarantee of what they are running: a deploy can fail or lag, and a failed one leaves the
previous revision serving while `main` has already moved. **Treat a commit as live only once
its deploy is confirmed green** — `alembic upgrade head` failing mid-chain is a real outcome
(`INF-1`, `INF-3`; runbooks R2 and R4).

> Until the GitHub rename lands, the default branch is still literally named
> `claude/igcse-os-planning-q8be0t`. Read "`main`" here as "the default branch", whatever it is
> currently called, and delete this note once it is renamed.

**Nothing is committed directly to `main`.** A merge there ships immediately — it triggers the
deploy with no further gate. Every change:

1. Branch off the latest `main`, named for the work — `fix/…`, `feat/…`, `chore/…`, `docs/…`.
2. Build it there; run the backend and frontend suites locally (`pytest`, `npm test`).
3. Open a PR into `main`.
4. Merge once green **and** the tutor/owner approves — the merge button is theirs, not the
   agent's, unless they have said otherwise for that change.
5. Delete the branch on merge. Render and Vercel redeploy from `main` on their own.

**The only edits that may go straight to `main` are documentation-only** — prose in
`README.md`, this file, or `docs/`. **A code comment is not a documentation change**, because
it lives in a file that ships. Anything under `backend/`, `frontend/`, or `alembic/versions/`
goes through a PR however small it looks, a one-character edit included (`CODE-16`,
`CODE-17`).

**Branches are disposable and short-lived.** At any moment the repo should hold `main`,
whatever single branch is actively in flight, and the `archive/*` branches preserving
superseded UI experiments and the original build history. A branch that has merged is finished
— **never reopen or stack new work on it**; start again from `main`.

> **CI, accurately:** `.github/workflows/ci.yml` runs on every pull request in four jobs —
> `ruff check` + `ruff format --check`, `mypy app/services app/schemas`, `eslint
> --max-warnings 0` and `prettier --check`; `pytest`; `vitest`, an API-type freshness check
> and `npm run build` (the only *frontend* type check); and an Alembic
> `upgrade head` → `downgrade base` → `upgrade head` against a real Postgres 16. **Still run
> both suites and both linters locally before opening a PR**; CI is a backstop, not a
> substitute for knowing your change works. Note the shape of the Python type checking added
> in task 0.8: **`packages = ["app.services", "app.schemas"]` is the explicit mypy scope** —
> but mypy's default `follow_imports=normal` checks every module those two packages import,
> so `app/models` (imported by nearly every service) and `app/workers/jobs.py` (imported for
> `enqueue`) are verified too, in practice. `app/api`, `app/security.py` and `app/main.py`
> are genuinely unchecked — nothing in `app/services` or `app/schemas` imports any of them
> (`BE-1` keeps the routers and the entrypoint from being imported by a lower layer). Widening
> the *explicit* scope to any of them is still a per-module ratchet, not a flag flip. CodeQL, Vercel preview builds,
> and CodeRabbit are GitHub Apps and may also run; nothing in the repo evidences them.

## Common commands

Backend (run from `backend/`, Python 3.11+):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set JWT_SECRET and the AI keys
docker compose up -d db              # Postgres for local dev (from repo root)
alembic upgrade head                 # apply migrations
uvicorn app.main:app --reload        # http://localhost:8000, OpenAPI docs at /docs

.venv/bin/python -m pytest                          # full suite (SQLite in-memory, no DB or API key)
.venv/bin/python -m pytest tests/test_readiness_engine.py          # one file
.venv/bin/python -m pytest tests/test_homework.py::test_name -q    # one test

.venv/bin/ruff check .               # lint — same command CI runs
.venv/bin/ruff check --fix .         # and fix what is mechanical
.venv/bin/ruff format .              # format (CI runs `--check`, which never writes)

python -m seed.load_syllabus         # load the 5 built-in subject topic trees
python -m seed.demo                  # idempotent demo tutor/students/parent with ~90d of data
```

Frontend (run from `frontend/`, Node 20+):

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> localhost:8000 (vite.config.ts)
npm run build      # tsc -b && vite build — the ONLY type check anywhere
npm test           # vitest run (does NOT type-check)
npm run lint       # eslint (CI adds --max-warnings 0)
npm run format     # prettier --write (CI runs format:check, which never writes)
```

Demo login after seeding: `demo-tutor@example.com` / `demo1234`.

## The binding rules

Keep these loaded. Each cites the document holding its full reasoning.

### Product and data

- **No metric exists unless Avora can explain where it came from.** Every value is manual,
  imported, or calculated — and traceable to the rows that produced it. (`PROD-1`, §01)
- **Never render a missing measurement as `0`, `0%`, or an empty bar.** Absent data is shown
  as absent — "not enough data yet", "no data". A factor without evidence is **omitted**, never
  fabricated. (`PROD-2`, `UX-19`)
- **Only finalized outcomes become `Evidence`.** Nothing provisional influences readiness.
  (`PROD-5`)
- **No model is ever asked to produce a grade.** `predict_grade()` maps a score through
  tutor-entered boundaries. (`PROD-6`)
- **The tutor has final authority over everything the AI produces**, and every override writes
  an append-only audit row with no API to edit or delete it. (`PROD-7`, `AI-12`)
- **Self-declared data is labelled as self-declared** wherever shown — past-paper `timed`,
  `time_taken_minutes`, `attempted_at`. (`PROD-8`, `UX-20`)
- **Do not add a parallel code path for past papers.** They are `Submission` + `QuestionMark`
  rows and go through the homework pipeline. (`PROD-9`, `ADR-0004`)
- **A new evidence source is added to `EvidenceSource` and given a weight in `SOURCE_WEIGHTS`
  in the same change.** (`PROD-10`)
- **Syllabus coverage is derived from `lesson_topics`** — do not add a manual mechanism.
  (`PROD-14`)

### Tenancy and authorization

- **Every new top-level aggregate carries `organization_id`.** (`PROD-3`, `DB-2`)
- **Every query returning tenant data filters by organization**, derived from the
  authenticated user — never from a path or body parameter. (`PROD-4`, `SEC-7`)
- **Student-visible material is scoped by (organization, subject)**, never subject alone —
  subjects are global, so subject-only scoping leaks across tenants. `_enrolled_scope` in
  `api/past_papers.py` is the reference. (`SEC-8`)
- **Return `404`, not `403`**, for anything the caller may not know exists. Integer keys are
  enumerable. (`API-7`, `SEC-9`)
- **Never treat a frontend role gate as an authorization control.** (`SEC-10`)
- **`Submission` is polymorphic — never read `assignment_id` unconditionally.** A past-paper
  submission has it as `None`, and reading it raises *inside* an authorization check.
  `_tutor_owns()` in `api/submissions.py` is the one place that branch lives. (`API-20`)

- **A role gate goes in the signature, never in the handler body.** `user: TutorUser` or
  `user: StudentUser` from `api/deps.py` — 45 routes carry a tutor gate and 14 a student gate
  this way; 34 of the tutor-gated ones are reachable, the other 11 sitting on the two routers
  `AV-58` hides. A dependency cannot be forgotten; an imperative call can, and omitting it fails
  **open** with nothing to detect it. That was the real state of this codebase until
  recently: eleven hand-copied `_require_tutor`/`_require_student` helpers called in 35
  handler bodies (`BE-17`, `SEC-11`, `RISK-7`). `tests/test_authorization.py` fails if any
  route loses its gate or becomes reachable without a token.
- **Ownership helpers below the routing layer call `assert_tutor()`**, not their own copy of
  the condition — `_owned_group`, `_tutor_submission` and five others take a plain `User`.

> **Still divergent:** `get_current_org_id` and `CurrentOrg` remain **unused**. Organization
> scoping is applied per query against `user.organization_id`, which is what `SEC-7` requires;
> the dependency is simply not the mechanism. Do not cite it as one.

### Auth

- **Anything that invalidates a credential bumps `users.token_version`.** Logout does; so does
  a tutor resetting a student's password. Any future password-change or account-disable
  endpoint must too — without it, an old refresh token keeps minting access tokens for its full
  30 days, which is exactly the case a reset exists to stop. (`SEC-1`, `ADR-0008`)
- **Never write `refresh_token` to `localStorage`** or any script-readable store. The httpOnly
  cookie scoped to `/api/v1/auth` is the only copy; `refreshTokens()` sends an empty body and
  lets the cookie carry it. (`SEC-2`, `FE-2`)
- **Every token verification checks the token `type`.** (`SEC-3`)
- **Invite codes are bounded** — everything expires at 14 days, and parent-link codes are
  single-use because one exposes a named child's entire record. Mint with `build_invite()` and
  validate with `check_usable()` rather than constructing an `Invite` directly. (`SEC-12`,
  `SEC-13`)
- **Failed logins are throttled per identifier, not per IP** — the API sits behind a proxy
  where one shared address would mean a global lockout. The counter is in-process and correct
  only while the API runs a single instance. (`SEC-14`)

### Uploads

- **Uploads are validated by magic bytes**, not the client's `Content-Type`
  (`services/storage.py:content_matches_mime`). An unknown MIME matches nothing and fails.
  (`SEC-15`)
- **Stored filenames are server-generated**; the client's filename is metadata only.
  (`SEC-16`)
- **Enforce the size limit on the source bytes, before any decode or transcode.** (`SEC-17`)
- **OAuth `state` is verified server-side** (`security.create_state_token` /
  `verify_state_token`), bound to the tutor who started the flow. The browser's sessionStorage
  comparison is a second check, not the check. (§07)

### Backend structure

- **`api/ → services/ → models/`. A lower layer never imports from a higher one.** (`BE-1`,
  `GOV-7`)
- **Business logic lives in `services/`**; routers stay thin. Every AI workflow is a job
  handler, and a handler cannot call a router. (`BE-2`)
- **Every model is re-exported from `models/__init__.py`.** Alembic's `env.py` and the test
  schema both build from that barrel — a missing model silently gets **no table in tests**.
  (`BE-3`)
- **Every job handler must be safe to re-run on the same payload.** Delivery is at-least-once:
  the worker retries once, after a 60s backoff carried by `run_after` — the same field that
  makes deliberate re-scheduling routine. `extract_assignment`
  *replaces* the question list rather than appending; `mark_submission` updates existing
  `QuestionMark` drafts in place, **never overwrites a tutor-finalized mark**, and skips the AI
  call entirely when every question is already decided; `compute_readiness_v2` is deliberately
  append-only; `build_homework_evidence` is idempotent by `source_ref`. (`BE-6`, `BE-7`)
- **Job payloads carry identifiers, not objects** — handlers re-read current state. (`BE-9`)
- **Never make a blocking call** in a request handler, service, or job handler — the worker
  shares the API's event loop, so one blocking call stalls request serving for every user.
  (`BE-13`, `PERF-1`)
- **Keep decision math pure** — plain dataclasses in, values out, no session. (`BE-4`,
  `CODE-3`)
- **Read configuration through `get_settings()`**, never `os.environ`. (`BE-15`)

### Database

- **Migrations are hand-written and sequentially numbered** (`NNNN_short_name.py`), with
  `down_revision` chained to the previous revision. Autogenerate may seed a draft; its output
  is never the migration. (`DB-15`)
- **Every migration has a working `downgrade()`, verified up → down → up.** (`DB-16`)
- **A migration altering an existing table uses `batch_alter_table(...,
  naming_convention=NAMING)`** with the convention from `0020_past_papers.py`, and names new
  ForeignKeys explicitly — SQLite rebuilds tables on `ALTER` and refuses unnamed reflected
  constraints. (`DB-17`)
- **Enums are `Enum(X, native_enum=False, length=N)`**, so adding a member needs no migration —
  which also means nothing forces you to audit the `if`/`match` chains over it. (`DB-5`,
  `DB-6`, `ADR-0007`)
- **An index is declared in the model as well as created in the migration.** Four of the five
  existing indexes exist only in migrations, so the test schema differs from production.
  (`DB-12`)
- `config.py` **rewrites `postgres://` / `postgresql://` to `postgresql+asyncpg://`**
  automatically — hosting providers hand out the bare scheme. Don't fight this.

### AI

- **All model calls go through `services/ai.py`.** No other module imports a vendor SDK or
  constructs a client. (`AI-1`)
- **Call sites name a surface, never a model.** (`AI-2`, `ADR-0006`)
- **Prompts live only in `services/prompts.py`, with a `version` bumped whenever the text
  changes meaningfully.** (`AI-6`, `AI-7`)
- **The student's pages are untrusted input to the marking prompt.** Auto-finalize means a mark
  can count with no human in the loop, and the student controls what is written on the page —
  so the prompt states that page content is data, never instructions, and that anything
  addressing the marker is flagged with confidence `low` for a tutor rather than acted on.
  **Keep that rule if the prompt is rewritten, and bump its version.** (`SEC-20`, `SEC-21`,
  `AI-8`)
- **A mark auto-finalizes only if it is both scheme-backed and confident** (`high`/`medium`).
  Everything else — no official scheme, low confidence, a skipped question — sets
  `needs_review` and waits in the tutor's queue. Proposed marks are always clamped to range,
  and a "no data" question is never silently scored 0. (`AI-11`, `AI-12`, `ADR-0009`)
- **A remark request is never resolved by AI** — it routes to the tutor's review queue with the
  AI's original reasoning attached, and there is **one request per question, ever** (DB-level
  unique constraint). (`AI-15`)
- **Never invent a price.** `AI_MODEL_PRICING` is empty by default; a model with no entry
  records `cost_usd = NULL` and reports as `unpriced_call_count`, never `$0`. (`AI-17`)
- **A missing key degrades that surface with a clear message and never blocks startup.**
  (`AI-20`, `INF-9`)

### Frontend

- **`api/client.ts` is the one HTTP entry point.** It attaches the bearer token and on a `401`
  transparently calls `/auth/refresh` once and retries. The only sanctioned bypasses are
  `fetchFileUrl()` for blob downloads and `streamMessage()` for SSE. (`FE-1`)
- **A backend response-schema change is regenerated into the frontend types in the same PR** —
  from `backend/`, `python -c "import json;from app.main import
  app;print(json.dumps(app.openapi(),indent=2))" > ../frontend/openapi.json`, then
  `npm run generate:api` from `frontend/`. Both paths assume those working directories. The types in `api/client.ts` alias
  `components["schemas"][...]` from the generated `schema.d.ts`; **do not reintroduce a
  hand-written interface**. Two CI checks keep the pair honest —
  `backend/tests/test_openapi_snapshot.py` proves `openapi.json` matches the running app, and the
  frontend job regenerates `schema.d.ts` and fails on a diff. (`FE-4`, `API-15`, `RISK-6`)
- **Server data lives in TanStack Query, not copied into `useState`.** (`FE-6`)
- **Use semantic token classes** (`bg-surface`, `text-ink-700`, `border-line`), not stock
  Tailwind palette names — `bg-white` is silently retargeted and is not white. (`UX-2`)
- **Never wrap the retarget block in `frontend/src/index.css` in an `@layer`** — it wins the
  cascade only by being unlayered. (`UX-1`)

### Tests

- **Drive jobs synchronously with `process_one_job()`**; never start `worker_loop()`. (`QA-6`)
- **Monkeypatch the *calling* module's `structured_complete`** with the `fake_ai` fixture, not
  `app.services.ai` — services import the helper into their own namespace, so patching the
  source module does nothing. (`QA-7`)
- **Never call a real AI provider from a test.** (`QA-8`)
- **A change touching auth ships with a test asserting the negative case** — wrong role,
  another organization's row, a revoked token. (`QA-12`)
- Tests force `DATABASE_URL=sqlite+aiosqlite:///:memory:` in `conftest.py` **before any app
  import**, with a `StaticPool` shared connection, and build the schema from `Base.metadata` —
  so **the suite still never runs a migration.** Alembic is exercised by CI's `migrations`
  job instead (up → down → up on Postgres 16), which is what makes `QA-11` a real check
  rather than a request. A migration that is correct on SQLite and wrong on Postgres is the
  failure that has actually happened here (`RISK-3`).

### Documentation

- **A PR that changes behaviour a constitution document describes updates that document in the
  same PR.** (`GOV-1`, `CODE-21`)
- **A PR that breaks an Active rule either fixes the code, supersedes the rule, or records a
  Known Gap.** Never none of these. (`GOV-3`)
- **Comments explain *why*, not what.** Several comments in this repo are the only surviving
  record of a decision — **never delete one** without confirming the reasoning no longer holds.
  (`CODE-12`, `CODE-13`)

## Architecture at a glance

Full detail in §01 and §04; this is orientation only.

- **Backend** (`backend/app/`): `api/` (27 router modules, 25 of them mounted under `/api/v1`
  in `main.py` — `classroom` and `knowledge` are deliberately not, being hidden rather than
  deleted (`AV-58`); shared dependencies in `api/deps.py`), `services/` (31 modules — the real
  work), `models/` (52 tables, SQLAlchemy 2.0 async), `schemas/` (Pydantic contracts),
  `workers/jobs.py` (DB-backed job queue, in-process worker started in `main.py`'s
  `lifespan`). Roles are `student`, `tutor`, `parent`, `admin`.
- **Frontend** (`frontend/src/`): React 18 + TypeScript + React Router v6 + TanStack Query +
  Tailwind v4. Role-oriented folders (`auth/`, `tutor/`, `student/`, `parent/`) plus shared
  `components/` and per-domain `api/` wrappers. Routes and role gates live in `App.tsx`.
- **The homework loop**: `Classified` → `extract_assignment` job → tutor publishes an
  `Assignment` → student uploads a `Submission` → `mark_submission` drafts `QuestionMark`s →
  auto-finalize or tutor review → finalized marks become `Evidence` → readiness recomputes.
- **Readiness**: two engines coexist. `/readiness/*` serves v2 snapshots
  (`services/readiness_summary_v2.py`) with per-subject fallback to v1, reporting
  `engine: "v1"` when it falls back. `analytics.py`, `reports.py` and `student_crm.py` still
  read v1 tables directly, so numbers can disagree (`RISK-5`). `READINESS_V2_SHADOW_ENABLED` is
  a **kill switch**, not a shadow flag.
- **AI**: seven surfaces routed independently to Anthropic or Gemini. Bulk document work
  (marking, extraction, syllabus) → Gemini; chat → Haiku; reports, readiness, class brief →
  Opus. Every call is metered into `ai_usage_events`.
- **Storage**: local disk, paths stored relative to `UPLOAD_DIR` so the folder can move to S3
  later without touching data. 20 MB cap; PDF/JPEG/PNG/WebP, with HEIC transcoded to JPEG on
  the way in.
- **Deployment**: API on Render (Docker, `alembic upgrade head` then uvicorn, persistent disk
  at `/data`), frontend on Vercel (`frontend/vercel.json` holds the `/api/*` rewrite and the
  app's security headers). Render deliberately does not serve a second copy — a duplicate
  origin would not match `GOOGLE_REDIRECT_URI`, so Classroom would fail for anyone who landed
  on it while everything else appeared to work. **That reason is dormant since Classroom was
  hidden (`AV-58`)**, which is what lets Phase 1 scale out; the deployment itself is unchanged
  and `INF-5` is still Active (§08).

**The API is pinned to a single instance** by three things at once — the uploads disk, the
in-process worker, and the in-process rate limiter. Scaling out is a correctness change, not a
configuration change (`RISK-1`, §08).


PLugins / ECC 
whenever you do any job use  everything you would need from ECC so hooks rules subagents anything that would imrpove the output you can give 
