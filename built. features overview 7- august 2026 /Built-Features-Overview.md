# Avora / IGCSE-OS — What Is Actually Built

*Generated 2026-08-06 from the code at `IGCSE-OS-product-repositiry-` @ `a568533` (85 commits).*
*Everything below was verified against source files, not against the docs.*

---

## 1. What the product is

An academic intelligence platform for IGCSE tutors, students and parents. The centre of
gravity is the **Readiness Engine**: every piece of academic evidence (homework, mocks, past
papers, tutor observations) is converted into topic-level exam-readiness scores, which then
drive every dashboard, recommendation and report in the product.

Three roles, one FastAPI app, one React app.

| Part | Tech | Size |
|---|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres | ~12,750 LOC |
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query | ~9,800 LOC |
| Tests | pytest (SQLite) + Vitest | 275 backend + 40 frontend |
| AI | Per-surface routing: Gemini for marking/extraction/syllabus, Anthropic for chat/reports/readiness | — |
| Deploy | API + Postgres + disk on Render (`render.yaml`), frontend on Vercel | — |

**23 API routers · ~120 endpoints · 52 database tables · 21 Alembic migrations.**

---

## 2. Core features that are built and working

### 2.1 Readiness Engine v1 — deterministic scoring
`backend/app/services/readiness.py`

- Pure-Python, **no ML**, fully explainable. Every topic score is a weighted average of
  evidence points.
- **Source weighting**: past paper 1.8 · mock 1.5 · homework 1.0 · quiz 0.8 · observation 0.5.
- **Exponential time decay**, half-life 45 days (tutor-configurable) — recent evidence
  dominates.
- **Confidence levels** (none/low/medium/high) derived from decay-weighted evidence volume;
  low-confidence topics render as "not enough data yet" rather than a false-precise number.
- Scoring functions are pure over dataclasses, so they unit-test with no DB.
- `recompute_student()` runs from the job worker after marks finalize or observations land.
- Predicted grades come from editable per-subject grade boundaries (`services/grades.py`).

### 2.2 Readiness Engine v2 — seven factors + AI synthesis (live, with v1 fallback)
`services/readiness_factors.py` (Layer 1 pure) → `services/readiness_v2.py` (Layer 1 DB) →
`services/readiness_v2_ai.py` (Layer 2 AI) → `services/readiness_summary_v2.py` (serving)

Seven deterministic factors, each producing a score + confidence + evidence count + JSON detail:

1. Topic Mastery (per topic) 2. Past Paper Performance 3. Homework Performance
4. Assessment Performance 5. Syllabus Coverage 6. Mistake Analysis 7. Consistency

- `factor_evaluations` rows are **append-only** — a historical AI synthesis can always be
  reconstructed from the exact deterministic inputs it was built from.
- Layer 2 asks the AI to synthesise those factors into a `readiness_snapshot`, weighted by
  per-organization `readiness_weights` (7 tunable weights + half-life, editable via
  `/readiness/weights`).
- **Cutover is already done**: v2 is the system of record for the UI, falling back to v1 for
  any (student, subject) with no snapshot yet. v1 tables are still maintained, so the fallback
  is real data, not a placeholder.
- If AI synthesis fails, the deterministic layer survives — the snapshot carries an explicit
  status instead of the whole evaluation being lost.
- Runs are enqueued **debounced per (student, subject)** (600s coalesce window), so a burst of
  auto-finalized submissions costs one synthesis, not one each.
- "Recalculating" state in the UI is derived from the job queue, not from a snapshot row.

### 2.3 Homework pipeline — upload → extract → assign → submit → AI-mark → review
`api/assignments.py`, `api/submissions.py`, `services/extraction.py`, `services/marking.py`

The single most complete flow in the product:

1. Tutor uploads a **classified PDF** (+ optional mark scheme) — stored on disk, path only in DB.
2. Background job **AI-extracts the question list** (marks, numbering) for tutor review; there's
   a retry endpoint and a manual question-editing endpoint for when extraction is imperfect.
3. Tutor publishes the assignment to a group, with a due date and instructions.
4. Student submits **photos or PDFs of handwritten work** from the phone.
5. Background job **AI-marks every question** against the mark scheme.
6. **Trust-first auto-finalization** (ADR-0009): a mark the AI is confident about *and* that an
   official mark scheme covers is finalized immediately — visible to the student, counted as
   readiness evidence, no tutor action. Everything else (no scheme, low confidence, unanswered)
   goes into the **tutor review queue** with the AI's suggestion pre-filled.
7. Tutor keeps override authority over any mark at any time; **every override is audited**
   (`mark_override_audit`), and students can contest a finalized mark via a **remark request**.

Only finalized marks become evidence — nothing provisional ever influences readiness
(`services/evidence.py`).

### 2.4 Past papers — sit under exam conditions
`api/past_papers.py`, `models/readiness_v2.py`, `student/SitPastPaperPage.tsx`

- Tutor uploads a full past paper booklet + mark scheme; the **same extractor** as classifieds
  parses it into questions mapped to topics.
- Student sits it (timed, `time_allowed` minutes), submits, gets it AI-marked through the same
  marking pipeline.
- Attempts feed the highest-weighted evidence source (1.8×) and the Past Paper Performance factor.

### 2.5 Mistake analysis
`models/readiness_v2.py::Mistake`

AI tags each marked question with a recurring-mistake category — misread / content gap /
careless / calculation / time management — tutor-confirmable, feeding the Mistake Analysis
readiness factor. This is what turns "68%" into "you lose marks to careless arithmetic, not
to not knowing it".

### 2.6 AI Academic Tutor chat (streaming)
`services/tutor_chat.py`, `api/chat.py`, `student/TutorChatPage.tsx`

- **Streaming** replies (SSE), persisted conversations, multi-conversation with delete.
- **Grounded** in the student's real readiness + workload via `services/student_context.py`,
  which reads the same CRM aggregation the UI reads — so the AI and the UI can never show
  different numbers.
- **Guardrailed**: teaches and guides, never hands over complete homework answers.
- Injects the tutor's Knowledge Base as its own cached system block, so the AI behaves like
  *that specific tutor*.

### 2.7 Tutor Knowledge Base
`services/knowledge.py`, `api/knowledge.py`

Tutor-authored teaching methods, preferred solving approaches, resources, marking preferences,
direct AI instructions and notes — compiled into one prompt block and injected into **every**
AI surface (marking, chat, reports, extraction). Full CRUD.

### 2.8 Syllabus ingestion
`services/syllabus_extraction.py`, `api/syllabus_uploads.py`, `tutor/SyllabusUploadPage.tsx`

Upload a syllabus document → AI drafts the **topic tree with weights and grade boundaries** →
tutor edits the draft → applies it as a real Subject the platform can assign homework and track
readiness against. Includes draft editing, retry, and status polling.

### 2.9 Reports
`services/reports.py`, `api/reports.py`, `components/ReportsPanel.tsx`

Audience-specific narrative reports (student / parent / tutor) generated as background jobs.
The AI writes prose **strictly from a factual block built from the data** and is instructed
never to invent marks, grades, or facts. Reports are stored, listed and retrievable.

### 2.10 Google Classroom integration
`services/google_classroom.py`, `api/classroom.py`

- Per-tutor **OAuth** with encrypted token storage (split token storage, ADR-0008).
- Course listing, per-course linking/unlinking, account disconnect.
- **Polling sync job** imports `courseWork` as draft Assignments and turned-in student
  submissions straight into the standard marking pipeline.
- Degrades gracefully with no `GOOGLE_CLIENT_ID`/`SECRET`; every Google call goes through
  individually-mockable functions so the whole flow is testable without real credentials.
- Never replaces direct upload — both paths stay fully supported.

### 2.11 Student CRM
`services/student_crm.py`, `api/students.py`, `tutor/StudentDetailPage.tsx`

Continuously-updating academic record per student: profile, per-subject enrolment and targets,
tutor notes, parent communications log. Single source of truth for both the CRM UI and the AI's
grounding context.

### 2.12 Groups, lessons, scheduling, resources
`api/groups.py`, `api/lessons.py`, `api/resources.py`

- Groups (classes) with members, invites, and a recurring **schedule** of slots.
- Lessons with **topic tagging** and **lesson observations** (which become readiness evidence).
- Per-group resource library (files + links).
- **AI class brief** endpoint (`POST /groups/{id}/brief`) — a pre-lesson summary of where the
  class stands.
- Group analytics endpoint + page.

### 2.13 Auth, roles, multi-tenancy
`app/security.py`, `api/deps.py`, `api/auth.py`, `services/invites.py`

- JWT access + refresh tokens carrying a **`token_version`** claim, so a user's sessions can be
  revoked server-side in one write.
- Four roles: tutor, student, parent (+ org scoping). One converged role-check dependency —
  eleven duplicated copies were collapsed into it.
- Registration paths for tutor (self-signup), student (invite code), parent (single-use link).
- **Invite policy is centralized**: everything expires; parent links are single-use (they grant
  a stranger a named child's complete record); group-join codes stay multi-use by design.
- Login throttling via a fixed-window in-process counter.
- Organizations table gives multi-tenant schema under a single-tutor UX (ADR-0005).

### 2.14 Activity feed
`services/activity.py`

"What needs your attention right now", derived **entirely from existing rows** — no read/unread
table to keep in sync. Tutors see work waiting on them; students and parents see recent results.

### 2.15 AI cost metering
`services/ai.py`, `api/ai_usage.py`, `models/ai_usage.py`

Every AI call routes through one choke point that (a) resolves surface → provider + model from
settings, and (b) writes a normalized usage event with provider, model, prompt version, token
counts and an estimated `cost_usd` from configured pricing. Summary + analytics endpoints on top.

### 2.16 Background job system
`workers/jobs.py`, `main.py`

- Postgres-backed queue (ADR-0002) using `FOR UPDATE SKIP LOCKED` — already safe for multiple
  workers even though only one runs today.
- Eight registered handlers: assignment extraction, past-paper extraction, marking, readiness v1
  recompute, readiness v2 compute, report generation, sylla/ثطbus extraction, Classroom sync.
- **Supervised worker**: the loop is restarted on any exception with a backoff, restarts are
  *counted* (not just logged), and `/health/ready` returns 503 when the worker is dead or the
  DB is unreachable. Both `/health` (shallow liveness, what Render polls) and `/health/ready`
  (deep, with queue depth and oldest-pending age) exist and are distinct on purpose.

### 2.17 Frontend surfaces
`frontend/src` — 45 route-level pages/components across three role shells

- **Tutor (18 routes)**: Today dashboard (activity, teaching rhythm, evidence→action,
  create-lesson), classes, per-group tabs (homework / students / syllabus / schedule / resources
  / analytics), class readiness, homework overview, assignment detail, submission review,
  student detail, mocks + mock entry, past papers, syllabuses, preferences, Classroom settings.
- **Student (10 routes)**: home, readiness dashboard, homework list + submit, past papers + sit,
  exams, files, recordings, AI tutor chat.
- **Parent**: dashboard with plain-language progress.
- Plus marketing landing page, login, tutor signup, student join, parent join.

---

## 3. Engineering quality signals that are real

- **CI exists and gates PRs** (`.github/workflows/ci.yml`), four separate jobs so a red run
  names the failure: ruff check + ruff format, ESLint (`--max-warnings 0`), pytest, Vitest +
  `tsc -b && vite build` (the only type check in the repo), and an Alembic
  `upgrade → downgrade base → upgrade` round-trip against Postgres 16.
- **315 tests total**, including dedicated suites for authorization, security hardening,
  readiness cutover, readiness v2 shadow mode, and AI provider routing.
- **Security headers** on every response (nosniff, frame-ancestors CSP, DENY, no-referrer),
  with a documented Swagger exemption.
- **A 14-document engineering constitution** in `docs/` across four volumes, plus 9 ADRs, a
  glossary, non-goals, ownership, change process and a live risk register.
- **No TODOs, FIXMEs, or `NotImplementedError` anywhere in `backend/app` or `frontend/src`.**
  Nothing in the feature set above is a stub.

---

## 4. Known constraints (built this way on purpose, documented as risks)

These are not bugs — they are recorded trade-offs. Listed so the overview is honest.

| Constraint | Where | Why it's accepted |
|---|---|---|
| **Single instance only** — three things pin it: local-disk uploads on a Render disk, the job worker running inside the API process, and an in-process rate-limit dict | RISK-1, P2 | Current volume is one tutor's practice; the migration order (S3 → separate worker service → Postgres/Redis limiter) is documented and the job queue's locking is already built for it |
| No Redis / external queue / message broker | non-goals | One datastore to back up, restore and reason about; a job is a row you can `SELECT` |
| No microservices, no Kubernetes | ADR-0001, non-goals | ~12.7k lines serving a single-tutor product; `api/ → services/ → models/` already provides the boundaries |
| Marks auto-finalize without tutor review | ADR-0009 | A tutor cannot review every mark for every student, and an unconfirmed mark never becomes evidence — which leaves readiness empty. Mitigated by override authority, an audit trail, and remark requests |
| VARCHAR enums rather than native DB enums | ADR-0007 | Migration cost of native enums vs. app-level validation |
| Default branch is still literally named `claude/igcse-os-planning-q8be0t` | ci.yml | Rename pending; CI lists both names so it doesn't silently stop running |
| `GEMINI_MODEL` default is a placeholder | README | Must be set to a model id the account actually has |

---

## 5. Repository note

`avora/` contains **two clones of the same repository**:

- `IGCSE-OS-product-repositiry-/` @ `a568533` — 85 commits, current
- `repo/` @ `f2c1aaa` — 84 commits, one behind (missing only "Test Git integration")

They are otherwise identical. `IGCSE-OS-product-repositiry-` is the one to work in; `repo/` can
be deleted once you've confirmed it holds nothing local.
