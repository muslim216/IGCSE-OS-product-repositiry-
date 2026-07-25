# MANARA by OASIS AI — Core Architecture

MANARA is an **AI Operating System for IGCSE education**: it helps tutors and students
understand performance, personalize learning, and improve exam outcomes. Long-term it
expands beyond IGCSE to any curriculum, school, or tutoring institution. This document is
the target architecture for the MANARA update of the existing IGCSE Student OS codebase —
what gets built, what it supersedes, and in what order.

MANARA is *not* an AI tutor or a homework marker. The platform is the product — Student
CRM, Lessons, Readiness Engine, Knowledge Base, Homework, Reports — with AI enhancing
every layer. Everything revolves around **Lessons**, and the core operating loop is:

> Teach → Assign → Submit → AI Analyze → Update Student CRM & Readiness → Review Insights → Plan Next Lesson

## Product decisions (locked)

- **Scope of this milestone**: development priorities 1–6 — Student CRM, Tutor Knowledge
  Base, KB→AI connection, Lessons as core entity, Readiness Engine v2, Google Classroom —
  plus a multi-tenant backbone and AI-usage metering.
- **Readiness**: the AI computes the final readiness score from seven tutor-weighted
  factors: Topic Mastery, Past Paper Performance, Homework Performance, Assessment
  Performance, Syllabus Coverage, Mistake Analysis, Consistency.
- **Tenancy**: the backend is multi-tenant (Organization entity) from the start; the
  product experience stays single-tutor for now, and flipping to organization-level
  (tutoring centers, schools) must be a simple change, not a migration.
- **Business model**: tutors pay for the platform, student management, readiness engine,
  and an AI allowance; students who exceed the tutor's allowance buy additional AI usage
  themselves. This milestone builds the *metering foundation* only — no payments.
- **Grade boundaries**: CIE and Edexcel; entered manually by the tutor per subject during
  onboarding, editable in Settings. Boundaries influence readiness (70% can already be an
  A*/9 depending on the subject).
- **Question difficulty**: AI-assigned during extraction, tutor override.
- **Data philosophy**: no metric exists unless MANARA can explain where it came from.
  Every metric is manual (tutor-entered), imported (Classroom, past-paper marks), or
  calculated (readiness, mastery, trends) — and traceable to its source.
- **IGCSE domain note**: *classifieds* — compilations of past-paper questions organized
  per subject per topic, with structures that vary by tutor — are the main practice
  source for most of the academic year. Full past papers start later in the year. These
  are two distinct evidence streams and are modeled separately.

## Architecture

### 1. Multi-tenancy — Organization

- New `organizations` table (`models/orgs.py`): id, name, timestamps.
- `users.organization_id` FK. On tutor signup a personal organization is auto-created —
  this keeps the UX single-tutor while the data model is org-scoped. Students and parents
  inherit their creating tutor's organization.
- Scoping rule: every top-level aggregate carries `organization_id` (student profiles,
  groups, lessons, classifieds, knowledge entries, grade boundaries, readiness weights,
  AI usage events). Child rows scope through their parent.
- `api/deps.py` gains a `CurrentOrg` dependency derived from `CurrentUser`; services
  filter by org id. "Org mode" later = multiple tutors per org + an `org_admin` role —
  no schema change required.

### 2. Student CRM

The student's complete, continuously-updating academic record — the foundation of MANARA.

- `student_profiles` (`models/crm.py`): user_id (unique FK), organization_id, school,
  grade/year, parent contact info.
- `student_subjects` (enrollment): student_id, subject_id, target_grade. The exam board
  lives on the Subject — "CIE Maths" and "Edexcel Maths" are separate subjects with
  separate topic trees.
- `tutor_notes`: a timestamped notes timeline per student.
- `parent_communications`: a log of parent contact per student.
- One CRM aggregation endpoint — `GET /api/v1/students/{id}/crm` — returns profile,
  enrollments, lesson history, homework history, readiness, notes, and communications.
  `services/student_context.py` (AI grounding) reads from the same aggregation service,
  so the AI and the UI share one source of truth.

### 3. Lessons — the core entity

- The existing schedule `Lesson` (weekday + time template on a group) is renamed
  `ScheduleSlot`; the name `Lesson` goes to the new entity.
- New `lessons` table: org, group_id, date, duration, markdown notes, optional source
  slot. Created from a slot or ad hoc.
- `lesson_topics` (lesson ↔ topic): a topic covered in a lesson becomes **taught** for
  every student in the group as of the lesson date — the evidence-based root of Syllabus
  Coverage. No manual coverage tracking.
- `lesson_observations`: per-student observations recorded on a lesson (optional
  topic_id); they feed `Evidence` (source `observation`).
- `assignments.lesson_id` (nullable FK): homework hangs off the lesson that assigned it;
  lesson-less assignments remain possible.

### 4. Tutor Knowledge Base

Stores tutor-specific knowledge so the AI behaves like *that* tutor.

- `knowledge_entries` (`models/knowledge.py`): org, tutor_id, kind
  (`teaching_method` | `solving_approach` | `resource` | `marking_preference` |
  `ai_instruction` | `note`), title, markdown body, optional file (existing storage
  service), optional subject_id.
- `services/knowledge.py` → `build_tutor_context(tutor_id, subject_id)` compiles entries
  into a prompt block, using Anthropic prompt caching (same `cache=True` pattern as
  `file_block()`).
- Injected into **every** AI surface: marking, tutor chat, the student AI assistant,
  report generation, and extraction.

### 5. Readiness Engine v2 — two layers

> **Status: built and shadow-running, not yet the system of record.** Every piece below
> is implemented (Layer 1, Layer 2, the new tables, a read-only `GET
> /readiness/v2/students/{id}`), but v1 (`services/readiness.py`,
> `TopicReadiness`/`ReadinessHistory`/`TutorPreferences`) is still what every existing
> endpoint and the UI actually serve. Setting `READINESS_V2_SHADOW_ENABLED=true` makes
> v2 compute alongside v1 on every evidence change so its output can be compared before
> anything switches over. Two refinements vs. the original sketch below: the deterministic
> layer writes one **`factor_evaluations`** row per factor per run (not a single JSON blob
> on the snapshot), and the AI-synthesis job is named **`compute_readiness_v2`** (not
> `compute_readiness`) so it can run independently of v1's `recompute_readiness` during
> the shadow period. See CLAUDE.md's "Readiness v2" note for the current split.

**Layer 1 — deterministic factor sub-scores** (`services/readiness_factors.py` for the
pure scoring math, `services/readiness_v2.py` for the DB-facing gathering that calls it).
Each of the seven factors is computed by explainable code from stored evidence, reusing
the v1 engine's pure-function math (exponential decay, weighted averages) as an internal
library:

| Factor | Source |
|---|---|
| Topic Mastery | Question-level marks bucketed by difficulty (easy/medium/hard + unseen flag); mastered = solid performance across tiers, not familiarity |
| Past Paper Performance | `past_paper_attempts`: percentage, boundary-adjusted grade, timed flag, trend |
| Homework Performance | Accuracy, quality, completion and timeliness from submissions |
| Assessment Performance | Quizzes, topic tests, mocks (existing assessments flow) |
| Syllabus Coverage | Per subject: % topics taught (lessons) → practiced (evidence) → mastered |
| Mistake Analysis | Frequency and severity of recurring mistake categories |
| Consistency | Homework completion streaks and timeliness |

**Layer 2 — AI synthesis** (`services/readiness_v2_ai.py`, job `compute_readiness_v2`;
will replace `recompute_readiness` at cutover, running alongside it during the shadow
period). The AI receives the factor sub-scores, the tutor's weights, and the tutor's
Knowledge Base context; it returns the overall readiness score, weak topics, and a
written rationale + revision plan, with the predicted grade computed deterministically
from the score via `predict_grade()` — the AI is never asked to invent a grade. Every
run gets a shared `evaluation_run_id` linking its `factor_evaluations` rows to the final
`readiness_snapshots` row, so even though the final number is AI-produced, every input is
traceable. Factors with no evidence are passed as "no data" and reported as such — never
fabricated (the v1 "not enough data yet" principle, per factor). If the AI call fails,
the already-computed `factor_evaluations` rows are kept and the snapshot is written with
`status="failed"` rather than losing the evaluation.

New/changed tables:

- `assignment_questions.difficulty` (easy/medium/hard; AI-assigned at extraction, tutor
  override in the review UI) plus an `unseen` flag.
- `mistakes`: student, question-mark ref, topic, category (`misread` | `content_gap` |
  `careless` | `calculation` | `time_management`), severity (1-3); AI-tagged during
  marking, tutor confirms/overrides alongside marks. Recurring mistakes reduce readiness.
- `past_papers` (org, subject, session label, paper number) and `past_paper_attempts`
  (student, raw marks, timed flag, date).
- `grade_boundaries`: org, subject, grade label, minimum percentage — overrides the
  shared `Subject.grade_boundaries` default when present.
- `readiness_weights`: one weight per factor, per org/tutor — **supersedes**
  `TutorPreferences` source weights; half-life survives as an advanced decay setting.
- `factor_evaluations`: append-only, one row per factor per `evaluation_run_id`
  (topic-scoped for Topic Mastery, subject-scoped for the rest) — score, confidence,
  evidence count, and a JSON detail breakdown.
- `readiness_snapshots`: student, subject, `evaluation_run_id`, status (ready/failed),
  score, predicted grade, weak topics, rationale, recommended revision, error — together
  with `factor_evaluations`, **supersedes** `TopicReadiness` + `ReadinessHistory`.

A `factor_evaluations` row is written on every run and never updated — expect to add a
retention/archival policy (e.g. prune runs older than N months, keeping only the most
recent few snapshots per subject) before this runs at real scale; not needed yet at
current data volumes.

### 6. Classifieds vs past papers

- `Classified` remains the ingestion vehicle, reframed as what it is in IGCSE practice: a
  topic-organized compilation of past-paper questions. Extraction now also proposes a
  syllabus topic and a difficulty per question — AI proposal, tutor confirmation (the
  same trust-first pattern as marking). Tutor-specific structures are handled by keeping
  topic mapping a proposal, never an assumption.
- Evidence taxonomy: classified-derived homework feeds the Topic Mastery and Homework
  factors; full past papers feed the Past Paper factor. Early in the year readiness
  legitimately runs on classifieds; the Past Paper factor reports "no data" until
  attempts exist.

### 7. Google Classroom (built)

Classroom reduces friction; it never replaces MANARA, and direct upload stays fully
supported — both paths feed the same marking pipeline.

- Per-tutor Google OAuth (`services/google_classroom.py`): `google_accounts`
  (tutor_id, encrypted refresh token, scopes). Settings: `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, an optional
  `GOOGLE_TOKEN_ENCRYPTION_KEY` (falls back to a key derived from `JWT_SECRET`). Like
  `ANTHROPIC_API_KEY`, both unset means the feature reports "not configured" and the
  app runs fine without it — `GoogleClassroomUnavailableError` mirrors
  `AIUnavailableError`. Every Google API call goes through small, individually-mockable
  wrapper functions, so the OAuth flow and sync job are fully unit-tested without real
  Google credentials (`tests/test_classroom.py`).
- Link tables: `classroom_course_links` (group ↔ Classroom course, one course per
  group) and `classroom_work_links` (assignment ↔ courseWork), which is what makes
  re-polling idempotent — a courseWork item already imported is updated in place, never
  duplicated.
- `sync_classroom` job (`workers/jobs.py` handler, enqueued on demand today via
  `POST /classroom/sync`; a scheduler could call the same job type periodically with no
  handler changes): imports courseWork as draft Assignments (status `review` — the
  tutor still adds questions before publishing, since Classroom's courseWork isn't a
  question booklet); imports turned-in student submissions, matching Classroom's
  roster email to a MANARA student account (unmatched students are skipped, not
  guessed); downloads PDF/JPEG/PNG/WebP Drive attachments into the storage service
  (other Drive types, e.g. native Google Docs, are skipped — the tutor uploads those
  directly) and enqueues the standard `mark_submission` job, so an imported submission
  goes through the exact same trust-first AI marking → tutor review → evidence →
  readiness pipeline as a direct upload.
- `api/classroom.py`: `GET /status`, `GET /auth-url`, `POST /connect`,
  `DELETE /account`, `GET /courses` (live from Classroom), `GET`/`POST`/`DELETE
  /links`, `POST /sync`. All tutor-only, org-scoped.

### 8. AI metering

- `ai_usage_events`: org, tutor_id, optional student_id, feature (marking / chat /
  report / extraction / readiness), model, input_tokens, output_tokens, timestamp.
- Recorded inside `services/ai.py` at the single client choke point, so every AI call is
  metered automatically. No enforcement or payments this milestone; a usage view appears
  under Settings. This is the foundation for tutor allowances and student top-ups.

## The AI Suite (mapped to code)

| AI system | Where it lives |
|---|---|
| AI Homework Analyzer | `services/marking.py` + `extraction.py` (+ mistake tagging, difficulty) |
| AI Learning Assistant | student chat (`services/tutor_chat.py` lineage) + KB + mistake history |
| AI Readiness Engine | `compute_readiness_v2` job (Layer 2 synthesis) — shadow-running, see §5 |
| AI Report Generator | `services/reports.py` + KB context |
| AI Teaching Assistant | future: worksheets/quizzes/lesson plans grounded in CRM + KB |
| AI Academic Intelligence | future: cross-student queries over CRM + readiness snapshots |

## Impact on the current codebase

**Unchanged**: auth/JWT design, the DB-backed job system (`workers/jobs.py`), storage
service, api → services → models layering, trust-first marking flow, SSE chat transport,
frontend `api/client.ts`.

**Renamed/reframed**: schedule `Lesson` → `ScheduleSlot`; `Classified` gains
topic+difficulty extraction; `TutorPreferences` → `readiness_weights`.

**Superseded (pending cutover)**: readiness v1's decay/confidence math is reused as
Layer 1's internal library; `TopicReadiness`/`ReadinessHistory` are designed to be
replaced by `factor_evaluations` + `readiness_snapshots`, and `recompute_readiness` by
the two-layer `compute_readiness_v2` — but as of this writing v2 only shadow-runs
(behind `READINESS_V2_SHADOW_ENABLED`) and v1's tables/job are still what the app
actually serves. Nothing is deleted until v2 is validated.

**Cross-cutting**: every tenant table gains `organization_id`; `api/deps.py` gains org
scoping; migrations continue the hand-written sequence from 0012.

**Frontend restructure**: the tutor experience becomes the eight MANARA sections —
Dashboard, Lessons, Students (CRM), Homework, Readiness, Reports, Knowledge Base,
Settings. Existing pages map into them (TodayPage → Dashboard, StudentDetailPage → CRM
record, MocksPage → Readiness/assessments, PreferencesPage → Settings).

## Build order

1. ✅ **Organization + tenancy plumbing** — migration, models, deps, scoping.
2. ✅ **Student CRM** — profiles, enrollments, notes, communications, CRM endpoint.
3. ✅ **Lessons core entity** — schedule slot rename, lessons, lesson_topics,
   observations, assignment link.
4. ✅ **Knowledge Base + AI injection** — entries CRUD, `build_tutor_context`, wired into
   marking/extraction/reports/chat. AI metering landed alongside it.
5. ✅ **Readiness v2** (built, shadow-running — see §5's status note): schema, factor
   services, AI synthesis job, shadow dual-enqueue, read-only `/readiness/v2` endpoint.
   Not yet: the actual cutover (v1 retirement, frontend reading from v2, difficulty/topic
   proposals wired into the extraction review UI, a `factor_evaluations` retention job).
6. ✅ **Google Classroom** — OAuth, link tables, `sync_classroom` job, API. Fully built
   and tested against mocked Google API calls; no real Google Cloud OAuth credentials
   are configured in any environment yet (see §7) — connecting a live account is a
   config step, not a code gap. Settings UI (frontend) is the remaining piece.

Each step ships as migration + models (re-exported from `models/__init__.py`) + services
+ API + tests, keeping the suite green throughout. The frontend restructure lands
incrementally with steps 2–5 (nav first, then each section); Classroom's Settings UI
follows the same pattern once a real Google Cloud project is available to test against.

## Design assumptions

- Exam board is a property of the Subject (separate topic trees per board), not of the
  student.
- Lessons are group-level events; 1:1 tutoring is a group of one, with per-student detail
  in observations.
- Classroom sync is polling-based initially (no Google Pub/Sub push infrastructure).
- AI synthesis is constrained: factor sub-scores and tutor weights are its mandated
  inputs, and every snapshot stores the breakdown + rationale for auditability.
