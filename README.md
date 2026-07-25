# IGCSE Student Operating System

An Aacademic intelligence platform for IGCSE students, tutors, and parents. Its core is the
**Readiness Engine**: every piece of academic evidence (homework, mocks, tutor observations)
feeds topic-level exam-readiness scores, which drive dashboards, recommendations, and reports.

- **Tutors** create groups, assign homework from classified PDFs, review AI-drafted marking
  (the tutor always has final authority), record mock results, and track analytics.
- **Students** submit photos/PDFs of handwritten work, see their readiness (% + predicted
  grade), weak topics, upcoming lessons, and chat with an AI academic mentor.
- **Parents** get plain-language progress views and reports.

## Stack

| Part | Tech |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, TanStack Query |
| AI | Anthropic API (`claude-opus-4-8`) — marking, extraction, chat, reports |
| Deploy | Render blueprint (`render.yaml`); Docker for local dev |

## Local development

Prerequisites: Python 3.11+, Node 20+, Docker.

```bash
# 1. Database
docker compose up -d db

# 2. Backend (http://localhost:8000, docs at /docs)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then set JWT_SECRET and ANTHROPIC_API_KEY
alembic upgrade head
uvicorn app.main:app --reload

# 3. Frontend (http://localhost:5173, proxies /api to the backend)
cd frontend
npm install
npm run dev
```

### Tests

```bash
cd backend && .venv/bin/python -m pytest        # backend (runs on SQLite, no DB needed)
cd frontend && npm test                          # frontend
```

## Deployment

### Render (recommended)

1. Push this repo to GitHub.
2. In the [Render dashboard](https://dashboard.render.com), choose **New → Blueprint** and
   connect the repo. `render.yaml` provisions the Postgres database, the API, and the
   static frontend, including the `/api/*` rewrite from the frontend to the backend.
3. Fill in the values the blueprint marks `sync: false` — Render prompts for them on the
   first sync and lists them under the service's **Environment** tab afterwards:

   | Variable | Needed for |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | chat, reports, readiness synthesis, class briefs |
   | `GEMINI_API_KEY` | marking, question extraction, syllabus extraction |
   | `GEMINI_MODEL` | the real Gemini model id your account has access to — the code default is a placeholder |
   | `AI_MODEL_PRICING` | cost analytics; `{}` is valid and reports calls as unpriced |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google Classroom; leave unset to run without it |

   `JWT_SECRET` and `GOOGLE_TOKEN_ENCRYPTION_KEY` are generated automatically.
   Every AI surface degrades gracefully when its provider key is missing, so a partial
   deploy still runs — but marking and extraction default to Gemini, so without
   `GEMINI_API_KEY` the homework pipeline fails. To stage without a Gemini key, set
   `AI_MARKING_PROVIDER`, `AI_EXTRACTION_PROVIDER` and `AI_SYLLABUS_PROVIDER` to
   `anthropic`.
4. **Uploads need the persistent disk.** The blueprint mounts one at `/data` and sets
   `UPLOAD_DIR=/data/uploads`. Uploaded booklets, mark schemes and submissions are stored
   on the filesystem with only their relative paths in the database, so without the disk
   every deploy replaces the container and orphans those rows. A service with a disk runs
   a single instance; moving `services/storage.py` to S3 later is what lifts that.
5. Alembic migrations run automatically on deploy (`alembic upgrade head` in the backend
   start command) — confirm this in the Dockerfile/start command if you change it.
6. If your service names/URLs differ, update the `routes` destinations in `render.yaml`,
   and the `CORS_ORIGINS` and `GOOGLE_REDIRECT_URI` env vars accordingly.
   `GOOGLE_REDIRECT_URI` must also be registered verbatim as an authorized redirect URI
   on the Google Cloud OAuth client, or the Classroom connect flow fails.

### Vercel (frontend only)

If you deploy the frontend separately on Vercel instead of/alongside Render:

1. Set the Vercel project's root directory to `frontend`.
2. `frontend/vercel.json` rewrites `/api/*` to the Render backend and falls back to
   `index.html` for the SPA — update the destination URL in that file if your backend's
   Render URL differs from `igcse-os-api.onrender.com`.
3. Alternatively, set `VITE_API_BASE_URL` to the backend's full URL at build time to call
   it directly (cross-origin) instead of relying on the rewrite — in that case also add the
   Vercel domain to the backend's `CORS_ORIGINS`.

## Configuration

All backend settings come from environment variables (see `backend/.env.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (`postgres://…` URLs are auto-adapted) |
| `JWT_SECRET` | Signing key for access/refresh tokens |
| `ANTHROPIC_API_KEY` | Enables AI marking, extraction, chat, and reports |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `REFRESH_COOKIE_SECURE` | Default `true`; set `false` only for plain-HTTP local dev — the refresh-token cookie is `Secure` and browsers drop it over `http://` otherwise |

Frontend build-time variable (optional, see `frontend/.env` or your host's env settings):

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Full backend URL to call directly instead of same-origin `/api/*` (bypasses the need for a rewrite proxy) |

### Auth

Access tokens are short-lived Bearer tokens sent in the `Authorization` header, unchanged
from before. Refresh tokens are now also set as an httpOnly `SameSite=Lax` cookie scoped to
`/api/v1/auth`, so `POST /api/v1/auth/refresh` works with either the cookie or a JSON body
(back-compat). Every token embeds the user's `token_version`; `POST /api/v1/auth/logout`
requires a valid access token, bumps that user's `token_version`, and clears the cookie —
this immediately invalidates every access/refresh token issued before the logout, closing
the window a stolen token would otherwise have for its full lifetime.

## Project status

The core-loop MVP (plus parents & reports) is complete. Built in phases, each
runnable end-to-end:

- [x] **A — Scaffolding:** auth (tutor signup, email/username login, JWT, roles), deploy config
- [x] **B — Groups, syllabus & lessons:** invites, tutor-created student accounts, parent linking, timetable, syllabus seeds (Edexcel 4MA1/4CH1/4BI1, Cambridge 5070/5090)
- [x] **C — Homework lifecycle:** classified upload → AI question extraction → student submission → AI marking draft → tutor side-by-side review → finalize
- [x] **D — Readiness Engine:** evidence, topic readiness + predicted grades, mock/observation entry, student & tutor dashboards, analytics, agreement rate
- [x] **E — AI tutor chat:** streaming mentor grounded in the student's readiness/workload, anti-cheating guardrails, daily message cap
- [x] **F — Parents & reports:** parent dashboard with per-child readiness; audience-specific AI reports (student / tutor / parent) generated strictly from the student's data

### Planned next (designed for, not yet built)

Study planner (incl. prayer times), AI quiz generator, notifications/reminders,
admin console, Stripe subscriptions, S3 storage, email delivery, mobile app.

### Seeding syllabus & demo data

```bash
cd backend
python -m seed.load_syllabus   # loads the five subject topic trees
python -m seed.demo            # optional: demo tutor/student/parent accounts
```

`seed.demo` (idempotent — safe to re-run) creates a tutor, two students, and a parent with a
full working dataset so every dashboard has real data on first login: ~90 days of evidence
per student, a published assignment with a finalized submission, a mock exam with per-topic
scores, a lesson scheduled for today, two group resources (a file and a recording link), and
default tutor preferences. Sign in as `demo-tutor@example.com` / `demo1234`.

## New API surface (tabs & preferences)

| Endpoint | Roles | Purpose |
|---|---|---|
| `POST/GET /api/v1/groups/{id}/resources`, `GET /api/v1/resources/{id}/file`, `DELETE /api/v1/resources/{id}` | tutor upload/delete; tutor + group students view | Files & Recordings tabs |
| `GET/PUT /api/v1/me/preferences` | tutor | Readiness weight sliders + recency half-life |
| `GET /api/v1/me/assessments` | student | Exams tab (own mock/test scores) |
| `GET /api/v1/me/today-lessons` | tutor | Today tab schedule |
| `POST /api/v1/groups/{id}/brief` | tutor | AI-written pre-lesson class brief (basic version — no learning-style detection or historical trends yet) |
| `GET /api/v1/assignments/attention` | tutor | Homework tab's "needs attention" list |
| `POST /api/v1/assignments` | tutor | `classified_id` is now optional — omit it to create homework without a PDF booklet |
| `POST /api/v1/reports/generate` | tutor/admin only now | Students and parents can view but no longer generate reports |
| `POST /api/v1/syllabus-uploads` (+ `GET`, `GET /{id}`, `PUT /{id}/draft`, `POST /{id}/retry`, `POST /{id}/apply`) | tutor | Syllabuses tab — upload any exam board's syllabus PDF, the AI drafts the topic tree, the tutor reviews/edits it, then applies it as a new Subject (alongside the 5 built-in syllabuses) available for groups and homework |
