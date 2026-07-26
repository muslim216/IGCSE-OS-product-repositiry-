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
| AI | Routed per surface: Gemini for marking/extraction/syllabus, Anthropic for chat/reports/readiness |
| Deploy | API on Render (`render.yaml` blueprint), frontend on Vercel (`frontend/vercel.json`); Docker for local dev |

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

The live setup is **the API on Render and the frontend on Vercel**
(`igcse-os-product-repositiry.vercel.app`) — one host each, no overlap. Vercel serves the
only copy of the app users visit, so `GOOGLE_REDIRECT_URI` is the full callback URL on
that origin (`https://…vercel.app/settings/classroom/callback`, path included) and must be
registered verbatim on the Google OAuth client. Render runs the API, the database and the
uploads disk, and users never open its URL directly.

Both hosts build from the repository's **default branch**. A branch that is pushed but not
merged into it does not deploy, however green its tests are.

### Render (API + database)

1. Push this repo to GitHub.
2. In the [Render dashboard](https://dashboard.render.com), choose **New → Blueprint** and
   connect the repo. `render.yaml` provisions the Postgres database and the API. The
   frontend is not provisioned here — Vercel serves it, and `frontend/vercel.json` holds
   the `/api/*` rewrite that points it at this backend.
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
6. If your URLs differ, the three values change independently. A different **backend**
   URL is only the rewrite destination in `frontend/vercel.json`. A different **frontend**
   origin is `CORS_ORIGINS` (origin only, no path) *and* `GOOGLE_REDIRECT_URI` (the full
   callback URL, path included) — `GOOGLE_REDIRECT_URI` otherwise stays put, since the
   backend never appears in it.
   `GOOGLE_REDIRECT_URI` must also be registered verbatim as an authorized redirect URI
   on the Google Cloud OAuth client, or the Classroom connect flow fails.

### Vercel (frontend)

1. Set the Vercel project's root directory to `frontend`. Vite is detected automatically;
   no build command needs setting.
2. `frontend/vercel.json` rewrites `/api/*` to the Render backend and falls back to
   `index.html` for the SPA — update the destination URL in that file if your backend's
   Render URL differs from `igcse-os-api.onrender.com`.
3. The same file sets the app's response headers, and it is the only place they are set
   now that Vercel is the sole frontend host. The frontend holds an access token in
   `localStorage`, so `script-src 'self'` (no CDN, no inline script) is what makes an
   injected script expensive — do not loosen it without a reason.
4. **Keep the API same-origin.** The `/api/*` rewrite is what lets the httpOnly refresh
   cookie work — the browser sees one origin, and Vercel proxies to Render server-side.
   Setting `VITE_API_BASE_URL` to the backend's URL instead makes the calls cross-origin,
   which needs the Vercel domain in the backend's `CORS_ORIGINS` **and** a `connect-src`
   change in the CSP, and still leaves sessions unable to refresh — a `SameSite=Lax`
   cookie is not sent cross-site. Prefer the rewrite.

## Configuration

All backend settings come from environment variables (see `backend/.env.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (`postgres://…` URLs are auto-adapted) |
| `JWT_SECRET` | Signing key for access/refresh tokens |
| `ANTHROPIC_API_KEY` | Chat, reports, readiness synthesis, class briefs |
| `GEMINI_API_KEY` | Marking, question extraction, syllabus extraction — the homework pipeline |
| `GEMINI_MODEL` | The Gemini model id your account has; the code default is a placeholder |
| `AI_MODEL_PRICING` | Per-token prices for cost analytics; `{}` reports calls as unpriced |
| `READINESS_V2_SHADOW_ENABLED` | Kill switch for Readiness v2; `false` falls back to the v1 engine |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | Google Classroom; unset means the feature reports "not configured" |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `REFRESH_COOKIE_SECURE` | Default `true`; set `false` only for plain-HTTP local dev — the refresh-token cookie is `Secure` and browsers drop it over `http://` otherwise |

Frontend build-time variable (optional, see `frontend/.env` or your host's env settings):

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Full backend URL to call directly instead of same-origin `/api/*` (bypasses the need for a rewrite proxy) |

### Auth

Access tokens are short-lived Bearer tokens sent in the `Authorization` header. Refresh
tokens are set as an httpOnly `SameSite=Lax` cookie scoped to `/api/v1/auth`, so
`POST /api/v1/auth/refresh` works with either the cookie or a JSON body (back-compat).
Every token embeds the user's `token_version`; `POST /api/v1/auth/logout` requires a valid
access token, bumps that user's `token_version`, and clears the cookie — this immediately
invalidates every access/refresh token issued before the logout, closing the window a
stolen token would otherwise have for its full lifetime.

The same revocation runs when a tutor resets a student's password
(`POST /groups/{id}/students/{id}/reset-password`). A reset is how a tutor evicts whoever
else has been using a shared account, so it has to end the sessions that account already
has, not just change what a new sign-in needs.

**The browser stores the access token only.** `frontend/src/api/client.ts` deliberately
does not persist `refresh_token`; the cookie is the only copy, and script on the page
can't read it. That means refresh needs the API to be same-origin — both supported deploys
proxy `/api/*` to the backend, so this holds — but a cross-origin `VITE_API_BASE_URL`
build won't send a `SameSite=Lax` cookie and its sessions will end at the access token's
expiry instead of refreshing.

Other limits worth knowing: failed logins are throttled per identifier (10 per 15 minutes,
in-process — see `services/rate_limit.py` for why that's per-instance and when it needs
to move), and invite codes expire after 14 days, with parent-link codes single-use
(`services/invites.py`).

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
