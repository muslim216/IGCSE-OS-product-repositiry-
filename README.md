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
