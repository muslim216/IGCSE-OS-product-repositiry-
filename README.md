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
| Deploy | Vercel (frontend) + Render free tier (backend + Postgres) |

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

## Deployment (Vercel + Render)

The frontend deploys to Vercel (free); the API + Postgres deploy to Render (free tier —
the service sleeps when idle and the free database expires after ~30 days, so this is a
demo setup, not production). Vercel proxies `/api/*` to the Render API so the app behaves
as a single origin.

1. Push this repo to GitHub.
2. **Render (API + database):** in the [Render dashboard](https://dashboard.render.com),
   choose **New → Blueprint**, connect this repo on branch `claude/igcse-os-deploy-hyfe5h`,
   and paste `ANTHROPIC_API_KEY` when prompted (Render generates `JWT_SECRET`
   automatically). Click **Apply**, then copy the API service's URL once it's live
   (e.g. `https://igcse-os-api.onrender.com`).
3. **Vercel (frontend):** choose **Add New → Project**, select the same repo, set
   **Root Directory** to `frontend`, and deploy. Copy the resulting site URL
   (e.g. `https://igcse-os.vercel.app`).
4. Update `frontend/vercel.json`'s rewrite destination with the real Render API URL, and
   `render.yaml`'s `CORS_ORIGINS` with the real Vercel URL, then push — both platforms
   auto-redeploy.
5. Verify: `GET <render-url>/api/v1/health` returns `{"status":"ok"}`, and you can sign in
   on the Vercel URL as `demo-tutor@example.com` / `demo1234`.

## Configuration

All backend settings come from environment variables (see `backend/.env.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (`postgres://…` URLs are auto-adapted) |
| `JWT_SECRET` | Signing key for access/refresh tokens |
| `ANTHROPIC_API_KEY` | Enables AI marking, extraction, chat, and reports |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth client for Google Classroom import |
| `GOOGLE_REDIRECT_URI` | Must match the OAuth client's authorised redirect URI exactly |
| `GOOGLE_TOKEN_KEY` | Fernet key encrypting stored Google refresh tokens |

## Google Classroom import

A tutor connects their own Google account once (not each student — students here
often have no email at all), links a Classroom course to a class and its students to
app accounts, then imports a coursework item. Imported attachments are downloaded
server-side and become ordinary submissions, so they go through exactly the same AI
marking and tutor review as work uploaded in the app. Re-running an import never
duplicates anything, and work already finalised here is never overwritten.

The feature is off until configured — it reports itself as unavailable rather than
failing at the first API call.

**Setting it up** (in the [Google Cloud console](https://console.cloud.google.com)):

1. Create a project, then under **APIs & Services → Library** enable **both** the
   *Google Classroom API* and the *Google Drive API*. Drive is required: Classroom
   returns attachment metadata only, never file contents.
2. Configure the **OAuth consent screen** and add the scopes the app requests
   (courses, coursework, rosters, profile emails, and `drive.readonly`).
3. Create **Credentials → OAuth client ID → Web application**, with the authorised
   redirect URI set to `<api-url>/api/v1/google/oauth/callback`.
4. Put the client ID/secret, that same redirect URI, and a generated
   `GOOGLE_TOKEN_KEY` into the backend environment.

⚠️ **Before opening this to real users:** `drive.readonly` is a *restricted* scope.
Publishing the OAuth app to production requires Google verification plus a
third-party CASA security assessment — budget weeks and a fee. Two ways round it:
keep the consent screen in **Testing** (works immediately, but only for accounts
added as test users, max 100, and refresh tokens expire every 7 days so tutors must
reconnect weekly); or, if your tutors are on a Google Workspace domain you control,
set the consent screen to **Internal**, which needs no verification and no weekly
reconnect.

## Project status

The core-loop MVP (plus parents & reports) is complete. Built in phases, each
runnable end-to-end:

- [x] **A — Scaffolding:** auth (tutor signup, email/username login, JWT, roles), deploy config
- [x] **B — Groups, syllabus & lessons:** invites, tutor-created student accounts, parent linking, timetable, syllabus seeds (Edexcel 4MA1/4CH1/4BI1, Cambridge 5070/5090)
- [x] **C — Homework lifecycle:** classified upload → AI question extraction → student submission → AI marking draft → tutor side-by-side review → finalize
- [x] **D — Readiness Engine:** evidence, topic readiness + predicted grades, mock/observation entry, student & tutor dashboards, analytics, agreement rate
- [x] **E — AI tutor chat:** streaming mentor grounded in the student's readiness/workload, anti-cheating guardrails, daily message cap
- [x] **F — Parents & reports:** parent dashboard with per-child readiness; audience-specific AI reports (student / tutor / parent) generated strictly from the student's data
- [x] **G — Class-centric restructure:** design tokens and shared UI primitives; class cards; every tutor module (homework, students, syllabus, schedule, analytics) nested inside its class; one-step homework upload with auto-publish; landing page, per-role navigation and an activity indicator
- [x] **H — Google Classroom import:** tutor OAuth, course/student linking, and idempotent import of Classroom submissions into the existing AI marking pipeline

### Planned next (designed for, not yet built)

Study planner (incl. prayer times), AI quiz generator, email/push reminders,
admin console, Stripe subscriptions, S3 storage, mobile app.

### Seeding syllabus & demo data

```bash
cd backend
python -m seed.load_syllabus   # loads the five subject topic trees
python -m seed.demo            # optional: demo tutor/student/parent accounts
```
