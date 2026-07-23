# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **IGCSE Student Operating System** — an academic-intelligence platform for IGCSE
tutors, students, and parents. A Python/FastAPI backend and a React/Vite frontend live in
one repo but deploy as two independent services. The product's heart is the **Readiness
Engine**: every piece of academic evidence (homework, mocks, tutor observations) feeds
topic-level exam-readiness scores that drive every dashboard, recommendation, and report.

## Common commands

Backend (run from `backend/`, Python 3.11+):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                 # set JWT_SECRET and ANTHROPIC_API_KEY
docker compose up -d db              # Postgres for local dev (from repo root)
alembic upgrade head                 # apply migrations
uvicorn app.main:app --reload        # http://localhost:8000, OpenAPI docs at /docs

.venv/bin/python -m pytest                            # full test suite (SQLite in-memory, no DB/API key needed)
.venv/bin/python -m pytest tests/test_readiness_engine.py            # one file
.venv/bin/python -m pytest tests/test_homework.py::test_name -q      # one test

python -m seed.load_syllabus         # load the 5 built-in subject topic trees
python -m seed.demo                  # idempotent demo tutor/students/parent with ~90d of data
```

Frontend (run from `frontend/`, Node 20+):

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> localhost:8000 (vite.config.ts)
npm run build      # tsc -b && vite build
npm test           # vitest run
```

Demo login after seeding: `demo-tutor@example.com` / `demo1234`.

## Architecture

### Backend layering (`backend/app/`)

Requests flow `api/` → `services/` → `models/`, with `schemas/` (Pydantic) as the
request/response contract. Keep business logic in `services/`; routers stay thin.

- **`api/`** — FastAPI routers, one per domain, all mounted under `/api/v1` in `main.py`.
  Shared dependencies live in `api/deps.py`: `DbSession` (async session), `CurrentUser`
  (validated JWT → `User`), and `require_role(*roles)` for RBAC.
- **`services/`** — the real work: the Readiness Engine, AI marking/extraction/chat/reports,
  grades, evidence, storage.
- **`models/`** — SQLAlchemy 2.0 async ORM. **Every model must be re-exported from
  `models/__init__.py`** — Alembic's `env.py` and the app import from there.
- **`workers/jobs.py`** — the background job system (see below).

Roles are `student`, `tutor`, `parent`, `admin` (`UserRole`). The tutor always has final
authority over anything the AI produces.

### The Readiness Engine (`services/readiness.py`)

Deterministic and explainable — **no ML**. A topic's score is a weighted average of its
`Evidence` points, each weighted by source (`mock` > `homework` > `quiz` > `observation`)
and exponential time decay (~45-day half-life). Confidence reflects how much recent evidence
backs a score; topics with none are shown as "not enough data yet", never a fake `0`.

- The scoring functions (`compute_topic`, `subject_readiness`, `_confidence`) are **pure** —
  they take plain dataclasses so they unit-test without a database. Keep them that way.
- `recompute_student()` is the DB entry point, run from the job worker after marks are
  finalized or observations added. It writes `TopicReadiness` snapshots and appends
  `ReadinessHistory`.
- A tutor's `TutorPreferences` (weight sliders + half-life) override the default source
  weights per student.

### Background jobs (`workers/jobs.py`)

All AI work is asynchronous. Jobs are **persisted to the DB** (`Job` table) so nothing is
lost on restart. An in-process asyncio worker (started in `main.py`'s lifespan) claims the
oldest pending job, runs its registered handler, and retries once on failure.

- Handlers are registered by string type at the top of `main.py`
  (`extract_assignment`, `mark_submission`, `recompute_readiness`, `generate_report`,
  `extract_syllabus`). Adding an async workflow = write a handler + `register_handler` + a
  caller that `enqueue()`s it.
- **Tests drive jobs synchronously** by calling `process_one_job()` — they don't run the
  loop. Follow that pattern when testing AI-triggered flows.

### AI integration (`services/ai.py` + callers)

Anthropic API via the `anthropic` SDK; model id comes from `settings.anthropic_model`
(`claude-opus-4-8`).

- `get_client()` raises `AIUnavailableError` when `ANTHROPIC_API_KEY` is unset — **the app
  runs fine without a key; AI jobs just fail with a clear, user-facing message.** Preserve
  this graceful degradation.
- `file_block()` builds document (PDF) / image content blocks from stored bytes, with
  optional prompt caching (`cache=True`) — used to reuse the shared mark scheme across a
  batch of submissions.
- Structured outputs use `client.messages.parse(..., output_format=PydanticModel)`.
- **Trust-first marking** (`services/marking.py`): the AI drafts transcription + proposed
  marks + confidence, but for any question without official mark-scheme coverage it *must*
  return `proposed_marks=null` / confidence `tutor_only`. Proposed marks are clamped to the
  question's range. A tutor reviews and finalizes every mark before it becomes evidence.
- Tutor chat (`api/chat.py` + `services/tutor_chat.py`) streams Server-Sent Events, grounds
  replies in `build_student_context()`, enforces anti-cheating guardrails and a rolling
  24h per-student message cap.

### The homework → readiness loop

`Classified` (uploaded question booklet + optional mark scheme) → `extract_assignment` job
pulls questions → tutor publishes an `Assignment` → student uploads a `Submission` →
`mark_submission` job drafts `QuestionMark`s → tutor reviews side-by-side and finalizes →
finalized marks become `Evidence` → `recompute_readiness` job updates scores. `classified_id`
on an assignment is optional (homework can exist without a PDF booklet).

### Auth

JWT access tokens (short-lived, `Authorization: Bearer`) + refresh tokens (30d), the latter
also set as an httpOnly `SameSite=Lax` cookie scoped to `/api/v1/auth`. Every token embeds
the user's `token_version`; `POST /api/v1/auth/logout` bumps it, instantly revoking every
outstanding token. `deps.get_current_user` re-checks `token_version` on every request.

### Frontend (`frontend/src/`)

React 18 + TypeScript + React Router v6 + TanStack Query + Tailwind v4 (via
`@tailwindcss/vite`). Structure is role-oriented: `auth/`, `tutor/`, `student/`, `parent/`,
plus shared `components/` and per-domain `api/` wrappers.

- Routing in `App.tsx`: role-gated route groups (`ProtectedRoute roles={[...]}`) wrap an
  `AppShell` with a per-role nav array. Add a page = add its route inside the right group
  and, if it's top-level, its nav entry.
- **`api/client.ts` is the one HTTP entry point.** `api<T>()` attaches the bearer token,
  and on a `401` transparently calls `/auth/refresh` once and retries. New endpoints should
  go through it, not raw `fetch`. Same-origin `/api/*` is proxied in dev and rewritten in
  prod; `VITE_API_BASE_URL` is the cross-origin escape hatch.

## Conventions & gotchas

- **Migrations are hand-written and sequentially numbered** (`alembic/versions/0001_…` →
  `0011_…`), not autogenerated in practice — match that `NNNN_short_name.py` naming and set
  `down_revision` to the previous number.
- `config.py` **rewrites `postgres://` / `postgresql://` URLs to `postgresql+asyncpg://`**
  automatically (hosting providers hand out the bare scheme). Don't fight this.
- Tests force `DATABASE_URL=sqlite+aiosqlite:///:memory:` in `conftest.py` (before any app
  import) with a `StaticPool` shared connection; the schema is created from
  `Base.metadata`, so a model missing from `models/__init__.py` silently won't get a table.
- File storage (`services/storage.py`) is local disk; DB rows store paths *relative* to
  `UPLOAD_DIR` so the folder can move to S3 later without touching data. 20 MB cap;
  PDF/JPEG/PNG/WebP only.
- Config is env-only (`config.py` / `.env.example`): `DATABASE_URL`, `JWT_SECRET`,
  `ANTHROPIC_API_KEY`, `CORS_ORIGINS`, `REFRESH_COOKIE_SECURE` (set `false` only for
  plain-HTTP local dev, or the refresh cookie is dropped).

## Deployment

`render.yaml` is a Render Blueprint provisioning the Postgres DB, the Dockerized API
(`backend/Dockerfile` runs `alembic upgrade head` then uvicorn on start), and the static
frontend with the `/api/*` → backend rewrite. The frontend can alternatively deploy on
Vercel (`frontend/vercel.json`). See `README.md` for the full deploy walkthrough.
