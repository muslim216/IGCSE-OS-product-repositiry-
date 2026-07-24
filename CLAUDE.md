# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**MANARA by OASIS AI** — an AI Operating System for IGCSE education (formerly the "IGCSE
Student Operating System"), serving tutors, students, and parents. A Python/FastAPI
backend and a React/Vite frontend live in one repo but deploy as two independent
services. The product's heart is the **Readiness Engine**: every piece of academic
evidence feeds exam-readiness scores that drive every dashboard, recommendation, and
report. MANARA is not an AI tutor or a homework marker — the platform (Student CRM,
Lessons, Readiness, Knowledge Base, Homework, Reports) is the product, with AI enhancing
every layer.

The codebase is mid-transition to the MANARA target architecture — see
`docs/manara-architecture.md` and "The MANARA update" below. Sections that follow
describe the code **as it exists today**; build new work toward the target.

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

## The MANARA update (target architecture — in progress)

`docs/manara-architecture.md` is the authoritative design; these are the rules that bind
all new work:

- **Lessons are the core entity.** The operating loop is Teach → Assign → Submit → AI
  Analyze → Update CRM & Readiness → Review → Plan next lesson. The old schedule
  template model lives on as `ScheduleSlot` (table `schedule_slots`, still what
  `/groups/{id}/lessons` manages); `Lesson` (`models/lessons.py`) is the real dated event —
  date, notes, `lesson_topics` (syllabus coverage), `lesson_observations`, and an optional
  `assignments.lesson_id` link. Own router: `api/lessons.py`.
- **Multi-tenant backend, single-tutor UX.** An `Organization` is auto-created per tutor
  at signup; every top-level aggregate carries `organization_id`. Going org-level later
  (tutoring centers) must be a role/UI change, never a schema migration.
- **Student CRM** (`student_profiles`, `student_subjects` enrollments with target
  grades, `tutor_notes`, `parent_communications`) is the student's complete academic
  record; `services/student_crm.py`'s aggregation feeds both `GET /students/{id}/crm`
  and AI grounding (`services/student_context.py` reads from the same function).
- **Tutor Knowledge Base** (`knowledge_entries` + `services/knowledge.py`'s
  `build_tutor_context()`) is injected into every AI surface — marking, extraction,
  report generation, tutor chat — so the AI behaves like that specific tutor.
- **Readiness v2 is built and shadow-running, not yet authoritative.** Layer 1
  (`services/readiness_factors.py` + `services/readiness_v2.py`) computes seven
  tutor-weighted, explainable factor sub-scores (Topic Mastery, Past Paper Performance,
  Homework Performance, Assessment Performance, Syllabus Coverage, Mistake Analysis,
  Consistency) as append-only `factor_evaluations` rows. Layer 2
  (`services/readiness_v2_ai.py`, job `compute_readiness_v2`) synthesizes them + the
  org's `readiness_weights` into a `readiness_snapshots` row, both tagged with a shared
  `evaluation_run_id` so a score always traces back to its deterministic inputs; an AI
  failure still keeps the Layer 1 rows and writes `status="failed"` rather than losing
  the evaluation. **v1 (`services/readiness.py`, `TopicReadiness`/`ReadinessHistory`/
  `TutorPreferences`) is still what every existing endpoint and the UI actually serve.**
  Setting `READINESS_V2_SHADOW_ENABLED=true` makes every place v1 recomputes also
  enqueue `compute_readiness_v2` (`enqueue_v2_shadow()`), so v2 accumulates snapshots
  for comparison, readable read-only at `GET /readiness/v2/students/{id}` — that
  endpoint never triggers a computation itself. Flipping the UI/API over to v2 as the
  source of truth, and retiring v1, is a deliberate later step once v2's output has
  been validated, not part of this milestone. No metric may exist that can't explain
  its source; factors without evidence report "no data", never a fabricated number.
  `factor_evaluations` is a detailed, append-only audit trail — expect to add a
  retention/archival policy (e.g. prune runs older than N months once older than the
  last few snapshots per subject are no longer useful) before this runs at real scale.
- **Classifieds ≠ past papers.** Classifieds (topic-organized past-paper question
  compilations, tutor-specific structures) are the main evidence source most of the
  year and feed Topic Mastery; full past papers (`past_papers` + `past_paper_attempts`,
  with `grade_boundaries` entered by the tutor per subject/org at onboarding, and timed
  conditions) are a separate entity feeding the Past Paper Performance factor. Question
  difficulty (`assignment_questions.difficulty`) is AI-assigned at extraction with
  tutor override.
- **Google Classroom** integrates via per-tutor OAuth (`GoogleAccount`, refresh token
  encrypted at rest — `services/google_classroom.py`) and a `sync_classroom` job that
  imports courseWork as draft `Assignment`s and turned-in student submissions (PDF/image
  attachments only; other Drive types are skipped) into the standard `mark_submission`
  pipeline. A tutor links a `Group` to one Classroom course (`ClassroomCourseLink`);
  `ClassroomWorkLink` keeps re-syncs idempotent. Submissions match Classroom's roster
  email to a MANARA student account — unmatched students are skipped, not guessed. The
  sync runs on demand today (`POST /classroom/sync`); a scheduler could call the same
  job type periodically with no handler changes. Classroom reduces friction, it never
  replaces direct upload — both paths feed the same marking pipeline. Gracefully
  degrades (a clear "not configured" state) without `GOOGLE_CLIENT_ID`/
  `GOOGLE_CLIENT_SECRET` set, same pattern as `ANTHROPIC_API_KEY`.
- **Every AI call is metered** (`ai_usage_events`, recorded via `services/ai.py`'s
  `record_usage()`) as the foundation for tutor AI allowances + student top-ups. No
  payments yet. Usage view: `GET /ai-usage/summary`; spend by feature / provider / month:
  `GET /ai-usage/analytics?group_by=feature|provider|month`.

Build order: tenancy → Student CRM → Lessons → Knowledge Base (+metering) →
Readiness v2 → Classroom. All six steps are built. Readiness v2 is shadow-running (see
above) but not yet the system of record — the deliberate v1→v2 cutover is still ahead.
Classroom is built and testable end-to-end with mocked Google API calls, but has no
real Google Cloud OAuth credentials configured in any environment yet — set
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (see `.env.example`) to connect a real
account. Keep the test suite green at every step.

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
- **Every handler must be safe to re-run on the same payload.** The worker retries once on
  failure, and `run_after` makes deliberate re-scheduling routine. `extract_assignment`
  *replaces* an assignment's question list rather than appending; `mark_submission`
  updates existing `QuestionMark` drafts in place, never overwrites a mark the tutor has
  finalized, and skips the AI call entirely when every question is already decided;
  `build_homework_evidence` is idempotent by `source_ref`. `compute_readiness_v2` is
  deliberately append-only (a re-run is a new audited evaluation, not a duplicate).
- **`Job.run_after`** (nullable) holds a job until a future time; the worker's claim query
  filters on it. This is what readiness-synthesis coalescing is built on — see
  `enqueue_readiness_v2_debounced()`, which no-ops if a run for that (student, subject) is
  already pending and otherwise schedules one `READINESS_V2_COALESCE_SECONDS` out, so a
  burst of auto-finalized submissions costs one synthesis call instead of one per
  submission.
- **Tests drive jobs synchronously** by calling `process_one_job()` — they don't run the
  loop. Follow that pattern when testing AI-triggered flows. To exercise a real AI service
  path without the network, monkeypatch the *calling module's* `structured_complete` with
  the `fake_ai` fixture (`tests/conftest.py`).

### AI integration (`services/ai.py` + callers)

**Two providers, routed per surface.** `services/ai.py` is the only place either SDK is
touched. A *surface* (`marking`, `extraction`, `syllabus`, `reports`, `readiness`, `chat`,
`class_brief`) resolves independently to a provider and model via `resolve_surface()`,
reading `AI_<SURFACE>_PROVIDER` / `AI_<SURFACE>_MODEL` from config. Defaults: bulk
document work (marking, question extraction, syllabus extraction) → **Gemini**
(`google-genai`); chat → **Claude Haiku 4.5**; reports, readiness synthesis, class brief →
**Claude Opus**. **Call sites name a surface, never a model.**

- Three helpers cover every call: `structured_complete()` (schema-constrained, both
  providers), `text_complete()` (prose, both providers), `stream_complete()`
  (**Anthropic-only** — chat is the sole streaming surface; a gemini-routed chat raises).
  All three return a normalized `AiResponse{provider, model, prompt_version, parsed, text,
  input_tokens, output_tokens}`, so nothing downstream branches on vendor.
- `get_client()` / `get_gemini_client()` raise `AIUnavailableError` when their key is
  unset — **the app runs fine without either key; the surfaces routed to that provider
  just fail with a clear, user-facing message.** Preserve this graceful degradation.
- `file_block()` builds document (PDF) / image content blocks from stored bytes in
  Anthropic's shape — **the neutral wire format across the app**. `_gemini_parts()`
  translates it. `cache=True` (prompt caching, used to reuse a shared mark scheme across a
  batch) is Anthropic-only and a no-op on Gemini.
- **Prompts live in `services/prompts.py`**, not in the service that calls the AI — one
  `PROMPTS` dict keyed by surface, each with a `version`. The helpers look the prompt up
  and stamp its version onto the `AiResponse`. Bump the version whenever the text changes
  meaningfully.
- **Every AI-generated record records what produced it.** `record_usage()` writes
  `provider` / `model` / `prompt_version` / estimated `cost_usd` to `ai_usage_events`, and
  `QuestionMark` carries `ai_model` / `ai_prompt_version` on the mark itself. Costs come
  from `AI_MODEL_PRICING` (JSON env), which is **empty by default** — a model with no
  configured price records `cost_usd = NULL`, and `GET /ai-usage/analytics` reports those
  calls as `unpriced_call_count` rather than folding unknown spend in as zero. Never
  invent a price.
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
  `0018_…`), not autogenerated in practice — match that `NNNN_short_name.py` naming and set
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
