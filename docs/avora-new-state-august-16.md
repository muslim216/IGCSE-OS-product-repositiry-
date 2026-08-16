# Avora New State — August 16

The engineering plan to take Avora from what is built today to a complete, ready-to-sell
product. Written to be executed by AI agents (single-task and parallel) and human engineers.

> **Revision 2** — incorporates the SWE audit of revision 1. Changes: a new **Phase 1 (Scale
> foundation)** before any product work · phases **reordered** so marking and evidence settle
> before mistakes and readiness · **v1 readiness is now deleted outright** (supersedes D28) ·
> **per-subject marking rules** and a **marking-context precedence rule** added · **type
> checking and generated API types** added · a new **Phase 11 (Scale hardening)** at the end.

---

## 1. Context

Avora is an academic operating system for tutors and their students. Its promise is a
continuous loop: **Configure → Teach → Assign → Solve → Assess → Understand → Act → Report →
Repeat.**

An audit of the repository against that target state (16 Aug) found: 8 of 17 stages built, 6
partial, 2 absent, and one scoring defect. Two findings are load-bearing:

1. **Readiness v2 cannot see the marking pipeline's default output.** `marking.py:336` settles
   confident, scheme-backed work as `auto_finalized` — terminal, no tutor step, by design
   (ADR-0009). But three v2 gatherers filter `Submission.status == finalized`, so that work is
   invisible to Topic Mastery, and Homework Performance counts it as *not submitted*. v1's
   `build_homework_evidence` has no such filter, so the two engines read different halves of
   the same table.
2. **`Mistake` has a consumer and a scorer but no producer.** The only `Mistake(...)`
   construction in the repo is a test fixture. In production `mistake_analysis()` returns a
   confident `100.0` from an empty table, as one of seven weighted factors.

Beyond the defects, the product model itself is changing: subjects become tutor-owned and
open to any board across IGCSE / O Level / A Level, the syllabus gains a chapter level, and a
new **teaching plan** subsystem — which does not exist in any form today — becomes the spine
that drives lessons, material uploads and pacing.

**There are no production users yet.** Every change in this plan can be destructive. No
backfill announcements, no migration windows, no backwards compatibility with live data.

**Outcome:** a product a solo tutor can sign up for, set up in one guided pass, and run a full
academic year on — where every number traces to evidence and the loop closes.

---

## 2. How to use this plan

**Agents working one task at a time.** Each task in §7 is self-contained: it names its files,
the constitution rules it must honour, the tests it must add, and how to verify it. Read
`CLAUDE.md` and the linked `docs/` volume first, then execute exactly one task ID.

**Agents working in parallel.** Tasks marked `∥` touch disjoint files and may run concurrently
within their phase. Tasks marked `→` are serial. Never run two tasks that list the same file.

**Phases are strictly ordered** unless the dependency map (§6) shows them side by side.

**Non-negotiable process** (from `CLAUDE.md`):

- Branch off the default branch per task: `feat/…`, `fix/…`, `chore/…`, `docs/…`.
- Nothing under `backend/`, `frontend/`, `alembic/versions/` reaches the default branch without
  a PR — a one-character edit included (`CODE-16`, `CODE-17`).
- Run `pytest`, `npm test`, `ruff check`, `ruff format --check`, `eslint --max-warnings 0` and
  `npm run build` locally before opening a PR. CI is a backstop.
- A PR changing behaviour a constitution document describes updates that document in the same
  PR (`GOV-1`). A PR breaking an Active rule fixes the code, supersedes the rule, or records a
  Known Gap (`GOV-3`).
- Migrations are hand-written, sequentially numbered, with a working `downgrade()` verified
  up → down → up (`DB-15`, `DB-16`), and use `batch_alter_table(..., naming_convention=NAMING)`
  when altering an existing table (`DB-17`).
- Every model is re-exported from `models/__init__.py` or it silently gets no table in tests
  (`BE-3`).

**Effort sizes:** `S` ≈ one focused session · `M` ≈ one to two days · `L` ≈ multi-day.

---

## 3. Product decisions register

Every decision below was made by the product manager. **They are the source of truth. Do not
re-derive, re-litigate, or "improve" any of them.** If a task appears to conflict with one,
stop and raise it rather than choosing.

### Customer and commercial

| # | Decision |
|---|---|
| D1 | **Solo tutor** is the customer. One tutor per account. No multi-tutor centre, no owner role. |
| D2 | **Usage tracking, no payment.** Measure AI spend, students/classes, storage, and activity per account. No payment provider, no plan limits. |
| D3 | The **product owner sees every account's usage** without asking the tutor; the tutor sees their own. |
| D4 | **Rename everything to Avora** — user-facing text, docs, internal code, and the GitHub repository. |
| D5 | **No fixed deadline.** Sequence by dependency and risk, not by date. |

### Subjects and syllabus

| # | Decision |
|---|---|
| D6 | **Subjects are owned by each tutor**, private to their account. Any exam board. |
| D7 | Levels covered: **IGCSE, O Level, A Level**. Nothing may assume an IGCSE-shaped world. |
| D8 | **Delete the five built-in seeded syllabuses.** Every tutor creates their own. |
| D9 | Syllabus tree is **Subject → Chapter → Topic**. Chapters contain topics. Marks, mistakes and readiness attach at **topic** level; a chapter's score is rolled up from its topics. |
| D10 | Setup materials collected per subject: **the syllabus document** and **teaching guidance / scheme of work**. |
| D11 | **Grade boundaries are entered by the tutor.** No AI drafting, no defaults. |

### Teaching plan

| # | Decision |
|---|---|
| D12 | **The tutor sets exam dates for their class.** |
| D13 | The plan is **per class**, **AI-drafted**, and **the tutor must accept it** before it is live. The tutor can edit anything at any point in the year. |
| D14 | It is a **full schedule to exam day**, scheduling **each week and every lesson**, derived from lessons per week. The AI uses the uploaded teaching guidance to judge which chapters are harder or slower and weights time accordingly. |
| D15 | Plan inputs at onboarding: **exam date · lessons per week and lesson length · when to start past papers · holidays and term breaks**. |
| D16 | Teaching and past-paper phases **may overlap**. |
| D17 | **The plan suggests, the tutor confirms each lesson.** Lessons are not auto-created. |
| D18 | When a class falls behind: **flag it and offer a one-click re-plan** the tutor accepts. Nothing reschedules itself. |
| D19 | **The plan and the exam countdown are tutor-only.** Students and parents see neither. |

### Marking and materials

| # | Decision |
|---|---|
| D20 | **Classifieds are chapter-scoped**, uploaded when the tutor starts that chapter. Each carries its **mark scheme** and **chapter-specific notes**. |
| D21 | Those notes are **marking context for the AI**. |
| D22 | The system **prompts the tutor to upload the classified when the plan reaches a new chapter**. Non-blocking. |
| D23 | Homework continues to be created from classifieds. No change to the creation flow beyond chapter scoping. |
| D24 | Pass the **exam board and level into the marking prompt**. |
| D25 | **The auto-finalize rule is unchanged**: an official mark scheme covered the question AND the AI was confident. No new variables. |
| D26 | **Assessments stay**, and **mocks may be uploaded and AI-marked** through the normal pipeline. |
| D27 | Past papers are **a phase after the syllabus is taught** (overlapping allowed). The existing past-paper module is retained. |
| **D75** | **Per-subject marking rules.** The tutor writes marking rules once for a subject and they apply to every chapter, classified and piece of work in it. **In addition to** board, level and chapter notes — none of those are removed. No account-wide layer. |
| **D76** | **Marking-context precedence.** The official mark scheme is **absolute and never overridden**. Below it, the tutor's rules beat exam-board convention, and more specific tutor rules beat broader ones. Resolution order: mark scheme → chapter notes → subject rules → exam board and level. |
| **D80** | **The AI agreement rate stays as it is calculated today.** No change. |

### Readiness

| # | Decision |
|---|---|
| ~~D28~~ | ~~Repoint readers to v2; v1 keeps being written.~~ **Superseded by D78.** |
| **D78** | **Delete readiness v1 outright.** Repoint `analytics.py`, `reports.py` and `student_crm.py` to v2, stop the v1 writes, and drop `topic_readiness`, `readiness_history` and `tutor_preferences` in the same change. v2 is the single source of truth. |
| D29 | **Fix the `auto_finalized` exclusion and fully recompute every snapshot.** No users, so no announcement or phased rollout. |
| D30 | **Drop `consistency`** from the factor set. |
| D31 | **Past-paper performance counts only once the past-paper phase has started** for that class. |
| D32 | **Homework performance is accuracy only.** Completion is shown separately as a fact, never inside the score. |
| D33 | **Readiness stays purely evidence-based.** Exam proximity and being behind schedule do not move it. |
| D34 | **The tutor can re-weight factors, switch them off, and add their own criteria.** A custom criterion is **invented and hand-scored by the tutor** per student. |
| D35 | That configuration applies **per account, with subject overrides**. |
| D36 | **Cold start: show a score from the first marked work**, labelled with the evidence behind it. |

### Mistakes

| # | Decision |
|---|---|
| D37 | **The AI records why each wrong answer was wrong**, at marking time. It counts immediately. |
| D38 | **The tutor may revise any of them but is never prompted to.** No review queue, no blocking step. |
| D39 | **Mistake categories are defined by the tutor.** At subject setup they are shown a suggested list they can accept, edit, or replace entirely. |
| D40 | Mistakes are stored and shown **per topic and per chapter** on the student's profile (tutor-facing). |
| D41 | The student sees their own mistake pattern **in the homework tab**, not on their general profile. |
| D69 | **Mistake severity stays AI-assigned on the existing 1–3 scale.** Tutors define categories, not severity. |

### Weak topics

| # | Decision |
|---|---|
| D42 | **Detect, store, and show. Never auto-assign.** No generated practice, no "do this now". |
| D43 | Shown to the **student as information**, and to the **tutor in their class view**. |
| D74 | **The tutor sets the weak-topic threshold**, as part of onboarding. |

### People and surfaces

| # | Decision |
|---|---|
| D44 | **Attendance is tracked per lesson** and visible to tutor, parent, student, and in reports. |
| D45 | **The student sees**: readiness score, predicted grade, weak topics, their own attendance — and their mistake pattern in the homework tab. |
| D46 | **The parent sees**: the weekly send, readiness and predicted grade, and attendance. Not the tutor's report. |
| D47 | **The tutor's home** shows a compact overview of: work awaiting review · plan progress per class · upload prompts · weak topics across classes. |
| D48 | **The tutor's home always carries one piece of good news: the marking the AI handled for them.** Other positives live in the class and module screens. |
| D72 | **One subject per class.** |
| D73 | Students submit **files or typed answers**. |

### Intelligence and communication

| # | Decision |
|---|---|
| D49 | **A weekly send for tutors, students and parents.** |
| D50 | Composed as **fixed facts plus one AI paragraph**. Every figure verifiable. |
| D51 | It appears on **each role's home page** and is emailed. |
| D52 | **It replaces the existing narrative system**, which is removed. |
| D53 | **Tutor reports: on demand and weekly.** Content: chapter and topic breakdown · mistake patterns · plan progress and countdown · attendance. |
| D54 | **Email triggers**: weekly send · homework set · homework due · marked work ready · account and invite emails. |
| D55 | **WhatsApp is future scope**, not in this plan. |
| D62 | The weekly send goes out **automatically to all three roles**. The tutor can read it but does not gate or edit it. |
| D63 | **The parent's report is their weekly send** — one artifact, not two. |
| D64 | **The parent's report differs from the tutor's**: readiness and predicted grade · attendance and homework record. **Not** the chapter/topic breakdown, **not** mistake patterns. |
| D65 | Parent reports send **automatically**. No tutor release step. |
| D66 | **English UI. The AI writes in the tutor's chosen language.** |

### Onboarding, removals, platform

| # | Decision |
|---|---|
| D56 | **Onboarding is a step-by-step flow the tutor must finish.** |
| D57 | **Delete completely**: student AI chat, peer improvement ranking. |
| D58 | **Hide from the product, keep the code**: Google Classroom sync, knowledge base. |
| D59 | **Keep**: files and recordings shared with a class (`GroupResource`). |
| D60 | Onboarding **must reach an accepted teaching plan**. Adding students is **optional**. |
| D61 | Students and parents join by **invite link**; the tutor supplies their email addresses. |
| D67 | **The tutor sets the account's time zone; students and parents may change their own.** |
| D68 | A **syllabus edit reflows the plan automatically**. |
| D77 | **Hand-edited plan slots are preserved through a reflow.** Only untouched generated future slots are eligible. |
| D70 | **Account deletion and data export are in scope.** |
| D71 | **The owner's cross-account usage view is a separate internal tool**, outside the tutor-facing product. |
| **D79** | **Add both** a Python type checker at service boundaries **and** TypeScript API types generated from the backend schema. |
| **D81** | **Sequencing**: marking and evidence → mistakes → readiness, in that order. The teaching plan runs in parallel. |
| **D82** | **Scalability**: object storage and the worker split come **before** the product phases. The rest comes after. |
| **D83** | **Redis** is the shared store for rate limiting. |
| **D84** | **Correctness first**: prove two API instances and two workers behave together. **One load test at 1,000 students** to find the first bottleneck. Defer the full 5,000/10,000 ladder. |
| **D85** | **Build multi-instance capability in Phase 1, but keep running a single instance** until the Phase 11 concurrency audit (11.2) is complete. 11.2 is the gate on scaling out. |
| **D86** | **The load test runs at the very end**, against the finished product. |
| **D87** | **Per-subject marking rules are offered during onboarding but skippable.** |
| **D88** | **The tutor chooses which day their account's weekly send goes out.** |
| **D89** | That day is **set in onboarding step 1, pre-filled with a default** — a glance, not a decision. |
| **D90** | The send follows **the tutor's clock**; every recipient gets it at the same moment, whatever time zone they set for themselves. |

> **Deliberate asymmetry — do not "fix" it.** D18: a *behind-schedule* re-plan waits for tutor
> acceptance. D68: a *syllabus edit* reflows automatically. Both stand as written.

> **Deliberate difference — do not harmonise.** D46 keeps homework completion detail out of the
> parent's day-to-day view; D64 puts an attendance and homework record in the parent's report.

---

## 4. Engineering decisions

Mine, not the product manager's. Flagged so they can be vetoed.

| # | Decision | Why |
|---|---|---|
| E1 | Introduce a **`Chapter` table**, not `Topic.parent_id`. | A chapter is scheduled by the plan, owns a classified, and carries its own rollup. `Topic.parent_id` stays for genuine sub-topics. |
| E2 | Add `SETTLED_STATUSES` to `models/homework.py`, export from the barrel, repoint the four modules that each declare a copy. | Four correct copies exist (`activity.py:32`, `averaging.py:34`, `api/past_papers.py:49`, `api/submissions.py:51`); three sites restate it wrongly. One definition ends the bug class. |
| E3 | **Leave `api/analytics.py:101` entirely unchanged** except for a comment explaining why it is deliberately `finalized`-only. | Per D80. Auto-finalized marks have `final_marks = ai_marks` by construction (`marking.py:303`), which is why the filter is there. The comment prevents the next engineer "fixing" it. |
| E4 | The recompute runner is `python -m seed.recompute_readiness`, reusing `enqueue_readiness_v2_debounced` with staggered `run_after`. | Mirrors `python -m seed.load_syllabus`. No new endpoint to secure; the existing debounce prevents duplicates. |
| E5 | The plan's schedule is **generated deterministically from AI-supplied chapter weights**, never emitted wholesale by the model. | The AI is good at "Chapter 7 is dense, give it 1.6× time"; bad at arithmetic over a calendar with holidays. Keeps it explainable (`PROD-1`). |
| E6 | Mocks reuse the polymorphic `Submission` path. | `PROD-9` / `ADR-0004` — no parallel code path. |
| E7 | Chapter readiness is **stored**, not computed on read. | Reports, weekly sends and the tutor home all need it; per-request computation puts N queries in a request path (`PERF-1`). |
| E8 | Custom criteria are **a distinct model**, not `ReadinessFactor` members. | `ReadinessFactor` is a non-native enum matched in `if`/`match` chains (`DB-5`, `DB-6`). Tutor-created values cannot be enum members. |
| E9 | Email goes through **one provider module in `services/`**, all templates in one place. | Mirrors `services/ai.py` as sole vendor entry point (`AI-1`). |
| E10 | The repository rename (D4) is a **manual GitHub action for the owner**. | An agent cannot rename a repo it does not own. |
| E11 | Store `time_zone` on the user, defaulted from the tutor. **Every stored timestamp stays UTC**; convert at the edges. | Storing local times is how "due Friday" becomes two different days. Columns are already `DateTime(timezone=True)`. |
| E12 | The owner's usage tool (D71) is a **separate deployable**, not a route in the API. | It is the one deliberate cross-account read. Keeping it outside means `PROD-4`/`SEC-7` stays true without exception inside the product. |
| E13 | The plan's automatic reflow (D68) runs as a **job**, not inline in the edit request. | Rescheduling a year of slots is not request-path work (`BE-13`, `PERF-1`). |
| **E14** | **Invariant: one Avora account = one organization = one tenant = (today) exactly one tutor.** Use `organization_id` as the tenant column everywhere; do not introduce a second "account" concept. | The audit flagged the terminology clash between D1 and the existing org-scoped model. This resolves it without a migration — solo-tutor is a *policy* on top of the tenant model, not a different model. |
| **E15** | **Invariant: a `PlanSlot` is a planned occurrence; a `Lesson` is the confirmed actual occurrence.** Slots carry provenance — `generated` · `manually_modified` · `confirmed` · `completed`. | Makes D77 enforceable: only `generated` future slots are eligible for automatic reflow. Without provenance there is no way to tell a tutor's edit from the generator's output. |
| **E16** | **Marking context is assembled in exactly one function**, which applies D76's precedence and is the only place that knows the order. | Precedence spread across call sites is precedence that drifts. One function, one test per conflict pair. |
| **E17** | **Invariant: AI-generated mistakes are replaceable on re-run; a tutor-revised mistake is never overwritten.** | Same contract `mark_submission` already honours for marks (`marking.py:272`). Extends `BE-6` to the new job. |
| **E18** | Redis (D83) is used **only** for rate-limit counters. **Postgres remains the source of truth for all application state.** | Prevents Redis quietly becoming a second database. If a second use appears, it gets its own decision. |
| **E19** | Worker liveness state moves **into the database** as part of the worker split. | `jobs.py:62-69` keeps `_started_at`, `_last_loop_at`, `_job_started_at`, `_restart_times` as module state read by the health endpoint. The code comment already says this must move. Split the worker without it and the health check silently lies. |

---

## 5. The SWE audit, resolved

The audit of revision 1 raised 17 items. Recorded here so no agent re-raises them.

**Already built — do not rebuild.** Verified in code:

| Audit item | Reality |
|---|---|
| "Replace in-process jobs with a shared queue" | The queue **is** already shared and DB-backed (`Job` rows, `app/workers/jobs.py`). Only the *worker* is in-process. |
| "Prevent duplicate worker execution" | Already done — `jobs.py:184` claims with `.with_for_update(skip_locked=True)`, the exact atomic pattern demanded. **Needs a test, not an implementation.** |
| "Add retries, backoff, dead-letter" | `MAX_ATTEMPTS = 2`, a deliberate 60s `run_after` backoff, and a terminal `failed` state all exist. **What is missing is that nothing watches `failed`** (`jobs.py:229`). |
| "Add an `idempotency_key` column" | **Rejected.** Handlers are idempotent by *natural* key — `build_homework_evidence` by `source_ref`, `mark_submission` by skipping decided questions. Stronger than a generic key, because it survives re-enqueue. New job types get an idempotency **audit**, not a column. |
| "AI must not own the calendar" | Already E5. |
| "Mistake lifecycle invariants" | Already in Phase 4; now formalised as E17. |

**Resolved by decision:** marking-context layers (D75) · precedence (D76) · v1 retirement (D78) ·
reflow protection (D77) · type safety (D79) · sequencing (D81) · scale timing (D82) · Redis
(D83) · load testing (D84) · account/organization terminology (E14) · PlanSlot vs Lesson (E15).

**Rejected:** the `idempotency_key` column, and adding Redis for anything beyond rate limiting
(the audit's own §8 forbids a second application datastore; E18 holds the line).

**Additional findings the audit missed**, folded into Phase 1:

- **HEIC transcoding is CPU-bound and runs in-process** (`storage.py:_to_jpeg`), blocking the
  event loop for every iPhone photo a student uploads — already a `BE-13`/`PERF-1` violation.
- **`fetchFileUrl()` is a sanctioned bypass of the single API client** (`FE-1`); signed URLs
  change that contract and the frontend must move with it.
- **The single-origin deployment constraint comes from Google Classroom's OAuth redirect** —
  and Classroom is being hidden (D58), which lifts it.
- **The test suite never runs a migration** (SQLite in-memory, schema from `Base.metadata`), so
  every new database constraint is only exercised by CI's Postgres job. `RISK-3` is the failure
  that has already happened here.

---

## 6. Dependency map

```
Phase 0   Truth and hygiene
                    │   (serial — 0.6's rename and 1.2's object storage
                    │    both rewrite services/storage.py)
                    ▼
Phase 1   Scale foundation
                    │
                    ▼
Phase 2   Subjects, chapters, syllabus
                    │
        ┌───────────┴───────────────────────────┐
        ▼                                       ▼
Phase 3  Marking and evidence            Phase 6  Teaching plan
        │                                       │   (parallel — consumes
        ▼                                        │    chapters and lessons,
Phase 4  Mistakes                                │    not the evidence contract)
        │                                       │
        ▼                                       │
Phase 5  Readiness                              │
        └───────────┬───────────────────────────┘
                    ▼
Phase 7  Attendance   ∥   Phase 8  Intelligence and communication
                    │
                    ▼
Phase 9  Onboarding and tutor home
                    │
                    ▼
Phase 10 Usage and sell-readiness
                    │
                    ▼
Phase 11 Scale hardening
```

Phases 3 → 4 → 5 are **serial by decision** (D81): marking produces the evidence and mistake
rows both later phases consume, so their contracts settle first. Phase 6 runs alongside them.

---

## 7. Tasks

### Phase 0 — Truth and hygiene

| ID | Task | Size | Mode |
|---|---|---|---|
| **0.1** | Shared `SETTLED_STATUSES` + fix the v2 gatherers | S | → |
| **0.2** | Recompute runner and full backfill | S | after 0.1 |
| **0.3** | Delete student AI chat | S | ∥ |
| **0.4** | Delete peer improvement ranking | S | ∥ |
| **0.5** | Hide Google Classroom sync and knowledge base | S | ∥ |
| **0.6** | Rename MANARA / IGCSE-OS → Avora | M | ∥ |
| **0.7** | Time zones | S | ∥ |
| **0.8** | Python type checker + generated API types | M | ∥ |

**0.1 — Shared `SETTLED_STATUSES` + fix the v2 gatherers** *(D29, E2, E3)*

- Define `SETTLED_STATUSES = (SubmissionStatus.finalized, SubmissionStatus.auto_finalized)` in
  `backend/app/models/homework.py`; export from `models/__init__.py`.
- Repoint the four existing copies (`services/activity.py`, `services/averaging.py`,
  `api/past_papers.py`, `api/submissions.py`). Behaviour unchanged.
- Fix the three wrong sites in `services/readiness_v2.py` — `_marked_questions_for_topic`,
  `_homework_points`, `_mistake_points_and_total` — and `services/student_crm.py:129`.
- **Leave `api/analytics.py:101` alone** (D80, E3); add only the comment explaining why.
- Tests (`tests/test_readiness_v2.py`): auto-finalized homework contributes to Topic Mastery ·
  counts as submitted in Homework Performance · counts toward Mistake Analysis'
  `total_questions`. Mirror `test_averaging.py::test_auto_finalized_work_counts`.

**0.2 — Recompute runner** *(D29, E4)* — `backend/seed/recompute_readiness.py`, run as
`python -m seed.recompute_readiness`. Walks every (student, subject) with evidence and calls
`enqueue_readiness_v2_debounced` with increasing `run_after`. Document in runbook §14.

**0.3 / 0.4 — Deletions** *(D57)* — Chat is student-gated on every route (`api/chat.py`), so
removal is clean. Remove routes, services, models, frontend screens, API wrappers, tests, and a
migration dropping the tables. Same for `api/improvement.py` / `services/improvement.py`. Check
`App.tsx` for orphaned routes and `main.py` for orphaned mounts and handlers.

**0.5 — Hide Classroom and knowledge base** *(D58)* — Remove routes and frontend surfaces;
leave services, models and tables. Comment each entry point so it is not read as dead code.
**Removing the Classroom surface lifts the single-origin deployment constraint** — record that
in §08, and Phase 1 depends on it.

**0.6 — Rename to Avora** *(D4, E10)* — User-facing strings, `docs/`, docstrings, `README.md`,
`CLAUDE.md`, package names, demo seed. One PR. **The GitHub repo rename is manual** — flag it.

**0.7 — Time zones** *(D67, E11)* — `time_zone` on `User`, defaulted from the tutor. Timestamps
stay UTC; convert at render and at the scheduling boundary. Lands early because Phase 6 (plan
weeks), Phase 7 (lesson dates) and Phase 8 (the weekly send) all need it.

**0.8 — Type safety** *(D79)* — Add a Python type checker (mypy or pyright) wired into CI,
enforced at service boundaries first rather than repo-wide on day one; there is **no Python type
checking at all** today, so expect a backlog. Add TypeScript API types generated from FastAPI's
OpenAPI schema, replacing the hand-mirrored interfaces in `frontend/src/api/*.ts`. This lands in
Phase 0 so everything built afterwards is checked. **Closes `RISK-6`.**

---

### Phase 1 — Scale foundation *(D82)*

**Runs after Phase 0, not alongside it** — 0.6's rename and 1.2's object storage both rewrite
`services/storage.py`. These are the two pieces that get materially harder to retrofit, plus the
prerequisites for a second API instance. Everything built after this is written for a
multi-instance world.

> **Deployment stays single-instance until Phase 11 (D85).** Phase 1 makes scaling out
> *possible* and proves it in tests; the systematic concurrency audit (11.2) is what makes it
> *safe*. **Do not deploy a second instance before 11.2 is complete** — the two-instance
> correctness suite covers known cases, not every read-modify-write in the codebase.

| ID | Task | Size | Mode |
|---|---|---|---|
| **1.1** | Architecture-impact report | S | → |
| **1.2** | Object storage | L | after 1.1 |
| **1.3** | Worker as a separate process | L | after 1.1 |
| **1.4** | Shared rate limiting on Redis | S | after 1.1 |
| **1.5** | Two-instance correctness suite | M | after 1.2–1.4 |

**1.1 — Architecture-impact report**

Before changing code, sweep the repository for every local-filesystem dependency, module-level
mutable state, process-local lock or counter, and single-process assumption. Classify each as
`SAFE_PROCESS_LOCAL` · `SHARED_STATE_REQUIRED` · `PERSISTENT_STORAGE_REQUIRED`. Known starting
points: `services/storage.py`, `services/rate_limit.py`, `workers/jobs.py:62-69`.

**1.2 — Object storage** *(§2 of the scalability brief)*

- A `StorageService` abstraction — `upload` / `download` / `delete` / `exists` /
  `get_signed_url` — replacing direct filesystem access for all persistent uploads: syllabus
  files, teaching guidance, classifieds, mark schemes, student submissions, group resources.
- The database stores metadata and object keys, never bytes. **Object keys are tenant-scoped,
  server-generated, and never contain user-controlled path fragments** (`SEC-16`).
- Keep the existing validation contract: magic-byte checking, not `Content-Type` (`SEC-15`); the
  size limit enforced on source bytes before any decode (`SEC-17`).
- **Move HEIC transcoding off the event loop** (`storage.py:_to_jpeg`) — it is CPU-bound and
  currently blocks request serving for every iPhone photo (`BE-13`, `PERF-1`).
- Signed URLs change `fetchFileUrl()`'s contract, which is a sanctioned bypass of the single API
  client (`FE-1`). Update both sides together.
- Do not hardcode a vendor; the interface is the contract.

**1.3 — Worker as a separate process** *(§6)*

- Split the worker out of the API's `lifespan` into its own entry point, so API and worker
  capacity scale independently.
- **Move worker liveness state into the database** (E19) — `_started_at`, `_last_loop_at`,
  `_job_started_at`, `_restart_times` in `workers/jobs.py`. The health endpoint reads the DB.
- **The claim logic already works** — `.with_for_update(skip_locked=True)` at `jobs.py:184`.
  Do not rewrite it. Add the multi-worker race test instead.
- Deployment: API service and worker service, separately scalable.

**1.4 — Shared rate limiting on Redis** *(D83, E18)*

Move `FixedWindowLimiter`'s counters from process memory into Redis. **Redis is for rate-limit
counters only** — Postgres stays the source of truth for all application state (E18). Failed
logins stay throttled **per identifier, not per IP** — the API sits behind a proxy where one
shared address means a global lockout (`SEC-14`).

**1.5 — Two-instance correctness suite** *(D84, §14)*

A hard acceptance requirement. With API #1, API #2, Worker #1, Worker #2 running:

- Upload through API #1, retrieve and process through API #2.
- Failed logins spread across both APIs still trip one shared limit.
- One submission never produces two marking operations.
- One weekly send produces one email, even when a worker is killed mid-job.
- A worker killed halfway through a job recovers with no duplicate side effects.

---

### Phase 2 — Subjects, chapters, syllabus

| ID | Task | Size | Mode |
|---|---|---|---|
| **2.1** | `Chapter` model, migration, topic reparenting | M | → |
| **2.2** | Tutor-owned subjects, level field, delete seeds | M | after 2.1 |
| **2.3** | Syllabus extraction produces chapters | M | after 2.2 |
| **2.4** | Grade boundaries: one tutor-entered source | S | ∥ after 2.2 |
| **2.5** | Teaching guidance upload | S | ∥ after 2.2 |
| **2.6** | Per-subject marking rules | S | ∥ after 2.2 |

**2.1 — `Chapter`** *(D9, E1)* — `Chapter` in `models/syllabus.py`: `id`, `subject_id`, `code`,
`title`, `position`, `weight`. Add `chapter_id` to `Topic`. Migration uses
`batch_alter_table(..., naming_convention=NAMING)` and names the FK explicitly (`DB-17`);
declare the index in the model as well as the migration (`DB-12`). Re-export (`BE-3`). No
production data, so the migration may be destructive.

**2.2 — Tutor-owned subjects** *(D6, D7, D8, E14)* — Add `organization_id` (`PROD-3`, `DB-2`)
and a `level` enum (`igcse` / `o_level` / `a_level`, `native_enum=False`). Unique constraint
becomes `(organization_id, exam_board, code)`. **Every subject query filters by the
authenticated user's organization** (`PROD-4`, `SEC-7`); student-visible material stays scoped by
*(organization, subject)* (`SEC-8`) — `_enrolled_scope` in `api/past_papers.py` is the reference.
Delete `seed/syllabus/*.json`; `seed/demo.py` creates its own subject. Tests: another
organization's subject returns **`404`, not `403`** (`API-7`, `SEC-9`, `QA-12`).

**2.3 — Syllabus extraction produces chapters** *(D9, D10)* — `SyllabusUpload.draft` becomes
chapter-first: `{..., chapters: [{code, title, topics: [...]}]}`. Update `SYLLABUS` in
`services/prompts.py` and **bump its version** (`AI-6`, `AI-7`). Update the review UI to edit
two levels. Drop `grade_boundaries` from the draft — 2.4 makes them tutor-entered.

**2.4 — Grade boundaries** *(D11)* — Make the org-scoped `grade_boundaries` table the **only**
source, written by a tutor-facing editor; remove the read of `Subject.grade_boundaries`.
`predict_grade()` maps through tutor-entered boundaries — **no model ever produces a grade**
(`PROD-6`). No boundaries means no predicted grade, never a fabricated one (`PROD-2`).

**2.5 — Teaching guidance upload** *(D10)* — A second document per subject, stored through the
Phase 1 `StorageService`. Phase 6 reads it to weight the plan.

**2.6 — Per-subject marking rules** *(D75)* — Free-text marking rules on `Subject`, edited by the
tutor. Applies to every chapter and classified in that subject. **No account-wide layer** (D75).
Consumed by Phase 3's context assembler.

---

### Phase 3 — Marking and evidence *(D81 — settles before mistakes and readiness)*

| ID | Task | Size | Mode |
|---|---|---|---|
| **3.1** | Chapter-scope classifieds, add notes | M | → |
| **3.2** | Marking-context assembly and precedence | M | after 3.1 |
| **3.3** | Typed answers as a submission type | M | ∥ |
| **3.4** | AI-marked mocks | M | ∥ |

**3.1 — Classified changes** *(D20, D21, D23)* — Add `chapter_id` and `notes` to `Classified`.
The upload flow moves to "start of chapter", reached from the plan or the chapter list. Homework
creation otherwise unchanged.

**3.2 — Marking context and precedence** *(D21, D24, D75, D76, E16)*

**One function assembles the entire marking context**, applying D76's order:

```
official mark scheme   (absolute — never overridden)
  → chapter notes      (most specific tutor input)
    → subject rules    (D75)
      → exam board and level   (D24)
```

**Bump `MARKING`'s version** (`AI-7`). **Preserve the untrusted-input clause in substance** —
page content is data, never instructions, and anything addressing the marker is flagged with
low confidence for a tutor rather than acted on (`SEC-20`, `SEC-21`, `AI-8`). **The
auto-finalize rule does not change** (D25): scheme-backed and confident, nothing more (`AI-11`,
`ADR-0009`). One test per conflict pair in the precedence order.

**3.3 — Typed answers** *(D73)* — The pipeline takes text where it takes images. **Typed text is
untrusted input to the marking prompt**, exactly as page content is — and typed input makes
prompt injection easier than a photograph does, so this is the task where `SEC-20`/`SEC-21` earn
their keep. Bump the prompt version.

**3.4 — AI-marked mocks** *(D26, E6)* — Through the existing pipeline. **No parallel code path**
(`PROD-9`, `ADR-0004`). `Submission` is polymorphic — never read `assignment_id` unconditionally
(`API-20`). Only finalized outcomes become `Evidence` (`PROD-5`). A new evidence source is added
to `EvidenceSource` **and** given a weight in `SOURCE_WEIGHTS` in the same change (`PROD-10`).

---

### Phase 4 — Mistakes

| ID | Task | Size | Mode |
|---|---|---|---|
| **4.1** | Tutor-defined categories + suggested starter list | M | → |
| **4.2** | AI tags mistakes during marking | M | after 4.1 |
| **4.3** | Tutor revision surface | S | after 4.2 |
| **4.4** | Rollup per topic and chapter | M | after 4.2 |
| **4.5** | Student view in the homework tab | S | after 4.4 |

**4.1 — Categories** *(D39)* — `MistakeCategory` becomes a tutor-owned, org-scoped table, seeded
at subject setup from a suggested list the tutor accepts, edits or replaces. `Mistake.category`
becomes an FK. **Nothing may branch on a category's value** — no `if category == "careless"`.

**4.2 — AI tagging** *(D37, D38, D69, E17)* — For each question where marks were lost, the AI
returns a category **from this tutor's list** (passed into the prompt) and a severity on the
existing 1–3 scale. Prompt lives only in `services/prompts.py` with a **bumped version**.
Untrusted-input clause preserved (`SEC-20`, `SEC-21`, `AI-8`). **Invariant (E17): AI mistakes are
replaced on re-run, never appended; a tutor-revised mistake is never overwritten** — the same
contract `mark_submission` honours for marks (`BE-6`, `BE-7`). Tests: drive with
`process_one_job()`, never `worker_loop()` (`QA-6`); monkeypatch the **calling module's**
`structured_complete` with `fake_ai` (`QA-7`); never call a real provider (`QA-8`).

**4.3 — Tutor revision** *(D38)* — Editable from the marked-work view. **No prompt, no queue, no
blocking step.** A revision is a tutor override of AI output, so it writes an append-only audit
row with no API to edit or delete it (`PROD-7`, `AI-12`) — `MarkOverrideAudit` is the pattern.

**4.4 / 4.5 — Rollups and student view** *(D40, D41)* — Aggregate per topic and per chapter on
the tutor-facing profile. The student sees their own pattern **in the homework tab only**.

---

### Phase 5 — Readiness

| ID | Task | Size | Mode |
|---|---|---|---|
| **5.1** | Drop consistency; homework becomes accuracy-only | S | → |
| **5.2** | Chapter-level rollup | M | ∥ |
| **5.3** | Delete v1 and repoint every reader | L | → |
| **5.4** | Configurable factor set and custom criteria | L | after 5.3 |
| **5.5** | Cold start from first marked work | S | ∥ |
| **5.6** | Tutor-set weak threshold and weak-topic surfaces | M | after 5.2 |
| **5.7** | Gate past-paper performance on the past-paper phase | S | after 6.1 |

**5.1 — Factor set changes** *(D30, D32)* — Remove `consistency` from `ReadinessFactor` handling,
`FACTOR_WEIGHT_ATTR`, the weights model and `readiness_factors.py`. Enum members are non-native
so no migration is forced — which is exactly why the `if`/`match` chains must be audited by hand
(`DB-6`). `homework_performance()` becomes accuracy only: delete the
`accuracy * 0.7 + completion_rate * 100 * 0.3` blend, but **keep `completion_rate` in `detail`**
so it can be shown as a fact. Surface completion separately on the profile and class view.
Punctuality appears **only in the weekly send** (D32).

**5.2 — Chapter rollup** *(D9, E7)* — One stored row per chapter per run, rolled from its topics'
scores weighted by evidence count, in `evaluate_subject_factors`. Chapter score is `None` when no
topic beneath it has evidence (`PROD-2`).

**5.3 — Delete v1** *(D78)* — Repoint `api/analytics.py`, `services/reports.py` and
`services/student_crm.py` to v2 snapshots; **stop the v1 writes; drop `topic_readiness`,
`readiness_history` and `tutor_preferences`** in the same change. Remove the per-subject v1
fallback and the `engine: "v1"` reporting from `/readiness/*`. **Closes `RISK-5`.** Update
`docs/governance/risk-register.md`, §01's Known Gaps table, and §06.

**5.4 — Configurable factors and custom criteria** *(D34, D35, E8)* — Three capabilities:
**re-weight** (extend `ReadinessWeights`) · **switch off** (a disabled factor is *omitted* from
the weighted set, never zero-weighted) · **add a custom criterion** — `CustomCriterion` (name,
description, weight, scope) plus `CustomCriterionScore` (student, criterion, score, updated_at,
updated_by), **hand-scored by the tutor**, no AI, no derivation. Configuration resolves **per
account with subject overrides** (D35) — one precedence rule, one place, tested both ways. Every
custom score is manual data and is **labelled as tutor-entered wherever shown** (`PROD-1`,
`PROD-8`, `UX-20`), reports and the parent view included.

**5.5 — Cold start** *(D36)* — A score appears from the first marked piece, carrying evidence
count and confidence (already computed by `_confidence_from_count`). "Not enough data yet" still
applies to a factor with *no* evidence (`PROD-2`, `UX-19`).

**5.6 — Weak threshold and surfaces** *(D42, D43, D74)* — Tutor-set, captured at onboarding,
stored per account with the same subject-override precedence as 5.4. **`MASTERY_THRESHOLD = 75.0`
in `services/readiness_v2.py` is a different line** — it decides what counts as mastered for
Syllabus Coverage. Do not conflate them; comment the distinction. Student sees their weak topics
as information; tutor sees them in the class view and aggregated on home. **Nothing is generated,
assigned or suggested as work** (D42).

**5.7 — Past-paper gating** *(D31)* — `past_paper_performance` returns `NO_DATA` until the class's
past-paper phase has started. A factor without evidence is **omitted, never fabricated**
(`PROD-2`) — no zero, no confident empty score.

---

### Phase 6 — Teaching plan *(runs parallel to Phases 3–5)*

| ID | Task | Size | Mode |
|---|---|---|---|
| **6.1** | Plan data model | M | → |
| **6.2** | Plan inputs on the class | S | after 6.1 |
| **6.3** | AI chapter weighting + deterministic scheduler | L | after 6.2 |
| **6.4** | Tutor accept and edit | M | after 6.3 |
| **6.5** | Plan → lesson suggestion | M | after 6.4 |
| **6.6** | Behind-schedule detection + one-click re-plan | M | after 6.5 |
| **6.7** | Chapter-start classified prompt | S | after 6.5 |
| **6.8** | Automatic reflow on syllabus edits | M | after 6.6 |

**6.1 — Data model** *(D13–D16, D72, E15)* — Per class: `TeachingPlan` (group_id, exam_date,
lessons_per_week, lesson_minutes, past_paper_start_date, status `draft`/`accepted`, accepted_at,
accepted_by_id) · `PlanSlot` (plan_id, chapter_id, scheduled_date, sequence, **provenance:
`generated` / `manually_modified` / `confirmed` / `completed`**) · `PlanBreak` (plan_id,
start_date, end_date, label). **Invariant E15: a `PlanSlot` is a planned occurrence; a `Lesson`
is the confirmed actual one.** Teaching and past-paper phases **overlap by design** (D16) — the
model must not assume disjoint intervals.

**6.2 — Inputs** *(D15)* — Exam date, lessons per week, lesson length, past-paper start,
holidays and breaks. Collected in onboarding (Phase 9), editable afterwards from class settings.

**6.3 — Drafting** *(D14, E5)* — Two deliberately separated steps:

1. **AI** — given the chapter list and the uploaded teaching guidance, return a relative weight
   per chapter. New surface in `services/prompts.py` with a `version`; call sites name a
   **surface, never a model** (`AI-2`, `ADR-0006`). A missing key degrades this surface with a
   clear message and never blocks startup (`AI-20`, `INF-9`).
2. **Deterministic scheduler** — a pure function (plain dataclasses in, slots out, no session;
   `BE-4`, `CODE-3`) laying chapters across the real calendar honouring lessons per week, breaks
   and the past-paper start date. **The AI's output is advisory data; the scheduler owns the
   calendar.**

Runs as a job, never in a request path (`BE-13`, `PERF-1`). Payloads carry identifiers, not
objects (`BE-9`).

**6.4 — Accept and edit** *(D13)* — Draft until accepted. **Nothing reads a draft plan** — not
lesson suggestions, not the classified prompt, not the tutor home. Tutor edits any slot at any
time; an edit sets provenance `manually_modified` and does not require re-acceptance.

**6.5 — Plan → lesson** *(D17, E15)* — Creating a lesson pre-selects topics from the next
unstarted slot; the tutor can change them freely. **Lessons are never auto-created.** Confirming
a lesson sets that slot `confirmed`. `lesson_topics` remains the sole source of syllabus coverage
(`PROD-14`).

**6.6 — Behind schedule** *(D18)* — Compare confirmed lessons to scheduled slots; show the gap on
home and the class view; offer a re-plan that **recalculates and waits for acceptance**.

**6.7 — Chapter-start prompt** *(D20, D22)* — When the plan enters a chapter with no classified,
prompt on the tutor's home. **Non-blocking.**

**6.8 — Automatic reflow on syllabus edits** *(D68, D77, E13, E15)* — Adding, splitting,
reordering or removing a chapter **reflows automatically, with no acceptance step**. Runs as a
job. **Only `generated` future slots are eligible** — `manually_modified`, `confirmed` and
`completed` slots are never moved (D77). **This is intentionally different from 6.6**; comment
the branch point (`CODE-12`) so it is not read as a bug.

---

### Phase 7 — Attendance

| ID | Task | Size | Mode |
|---|---|---|---|
| **7.1** | Attendance model and lesson flow | S | → |
| **7.2** | Attendance surfaces | S | after 7.1 |

*(D44)* — `LessonAttendance` (lesson_id, student_id, state, recorded_by_id, recorded_at),
recorded when the tutor confirms a lesson. Shown to tutor, student, parent, and in reports.
Attendance is **not** a readiness factor (D33) — it explains gaps, it does not score them.

---

### Phase 8 — Intelligence and communication

| ID | Task | Size | Mode |
|---|---|---|---|
| **8.1** | Email infrastructure | M | → |
| **8.2** | Weekly send generator (three variants) | L | ∥ |
| **8.3** | Remove the narrative system | S | after 8.2 |
| **8.4** | Weekly send on each role's home | M | after 8.2 |
| **8.5** | Transactional email triggers | M | after 8.1 |
| **8.6** | Tutor reports | M | ∥ |

**8.1 — Email** *(D54, E9)* — One provider module in `services/`, all templates in one place,
unsubscribe and bounce handling. Configuration through `get_settings()`, never `os.environ`
(`BE-15`). A missing key degrades email with a clear message and never blocks startup (`INF-9`).

**8.2 — Weekly send** *(D49, D50, D62–D66)* — **Fixed facts plus one AI paragraph.** Facts are
computed deterministically; the AI writes a short steer and **must never restate a number the
facts do not contain** (`PROD-1`). Generated by a **sweep**, not a self-perpetuating chain — the
comment in `services/narrative.py` explains exactly why, and **that reasoning must be carried
into the replacement, not deleted with it** (`CODE-13`).

Three variants:
- **Tutor** — across their classes. Punctuality appears here and nowhere else (D32).
- **Student** — their own week.
- **Parent** — *is the parent report* (D63): readiness and predicted grade · attendance and
  homework record, plus the AI paragraph. **Not** the chapter/topic breakdown, **not** mistake
  patterns (D64). One weekly artifact for a parent, never two.

**Sends automatically to all three roles** (D62, D65); the tutor reads but does not gate it. The
AI paragraph is written **in the tutor's chosen language** (D66).

**Timing:** on the account's chosen day (D88, D89), fired on **the tutor's clock** — one batch,
one moment, regardless of what time zone a student or parent has set for themselves (D90). This
is the one place a recipient's own time zone is deliberately ignored; say so in a comment
(`CODE-12`) beside the scheduling code, which otherwise converts per viewer (E11).

**8.3 — Remove the narrative system** *(D52)* — Delete `services/narrative.py`,
`models/narrative.py`, `api/narrative.py`, the sweep registration in `main.py`,
`narrative_sweep_interval_hours` in `config.py`, and the surfaces reading it. **Only after 8.2
ships**, so no screen is left blank.

**8.4 — Home surfaces** *(D51)* — Each role's home shows their latest weekly send.

**8.5 — Transactional triggers** *(D54, D61)* — Homework set · homework due · marked work ready ·
account and invite emails. **Students and parents join by invite link sent to an address the
tutor supplies** (D61). Invites stay bounded — 14-day expiry, parent-link codes single-use
because one exposes a named child's entire record; mint with `build_invite()`, validate with
`check_usable()` (`SEC-12`, `SEC-13`). **Anything invalidating a credential bumps
`users.token_version`** (`SEC-1`, `ADR-0008`) — a password-reset flow must, or an old refresh
token keeps minting access tokens for 30 days. Scheduling reads the recipient's time zone (0.7).

**8.6 — Tutor reports** *(D53)* — Chapter and topic breakdown · mistake patterns · plan progress
and countdown · attendance. On demand **and** weekly. **This is the tutor's report**; the
parent's is a different document produced by 8.2 — neither is built by filtering the other.

---

### Phase 9 — Onboarding and tutor home

| ID | Task | Size | Mode |
|---|---|---|---|
| **9.1** | Blocking onboarding flow | L | → |
| **9.2** | Tutor home rework | M | ∥ |

**9.1 — Onboarding** *(D56, D60, D66, D67, D74)* — Step-by-step, in this order:

1. Language, time zone, and weekly send day — the last pre-filled with a default (D66, D67, D89)
2. Subject — exam board and level (D6, D7)
3. Syllabus upload, then review the chapter/topic tree (D9, D10)
4. Teaching guidance upload (D10)
5. Grade boundaries (D11)
6. Per-subject marking rules — **offered, skippable** (D75, D87)
7. Mistake categories — accept, edit or replace the suggested list (D39)
8. Weak-topic threshold (D74)
9. Class — one subject (D72)
10. Exam date, lessons per week and length, past-paper start, holidays (D15)
11. **Accept the teaching plan** — the finish line (D60)

**Adding students is optional and sits outside the flow** (D60). Server-side state, resumable,
**not skippable** up to step 11. A frontend gate is never an authorization control (`SEC-10`).

**9.2 — Tutor home** *(D47, D48)* — Compact overview: work awaiting review · plan progress per
class · upload prompts · weak topics across classes. Plus **one piece of good news: the marking
the AI handled for them** — volume and time saved. Nothing else framed as good news.
`services/today.py` holds the existing aggregation; `_STATUS_ORDER`'s exceptions-first ordering
is the pattern to extend.

---

### Phase 10 — Usage and sell-readiness

| ID | Task | Size | Mode |
|---|---|---|---|
| **10.1** | Usage rollups | M | → |
| **10.2** | Tutor's own usage view | S | after 10.1 |
| **10.3** | Owner internal usage tool | M | after 10.1 |
| **10.4** | Account deletion and data export | L | ∥ |

**10.1 / 10.2** *(D2)* — Roll up per account: AI spend (`ai_usage_events` already meters every
call), students and classes, storage used, activity. **Never invent a price** —
`AI_MODEL_PRICING` is empty by default, and a model with no entry records `cost_usd = NULL` and
reports as `unpriced_call_count`, never `$0` (`AI-17`).

**10.3 — Owner tool** *(D3, D71, E12)* — **A separate internal tool, not a route in the API.**
Keeping it outside the FastAPI app is the point: `PROD-4`/`SEC-7` stays true without exception
inside the product. **Do not build it by relaxing an existing scoping helper.** Record the
boundary in an ADR.

**10.4 — Deletion and export** *(D70)* — Deletion covers every table plus object storage, in
FK-safe order, **verified by a test asserting nothing survives** — not by inspection. Export
produces a readable archive of students, marks, reports and readiness history.

---

### Phase 11 — Scale hardening *(D82 — "the rest")*

| ID | Task | Size | Mode |
|---|---|---|---|
| **11.1** | Statelessness audit and remediation | M | ∥ |
| **11.2** | Concurrency audit | L | → |
| **11.3** | Database constraints for enforceable invariants | M | after 11.2 |
| **11.4** | Structured logging and metrics | M | ∥ |
| **11.5** | Dead-letter visibility and alerting | S | ∥ |
| **11.6** | Load test at 1,000 students | M | last |

**11.2 — Concurrency audit** *(§9)* — With two workers running, every read-modify-write is a
bug waiting to happen. Use transactions, row locks, unique constraints, atomic updates or
optimistic versioning. Named hotspots: **readiness** (two marking jobs must not corrupt state) ·
**mistakes** (two runs must not overwrite a tutor revision — E17) · **teaching plans** (two
reflows must not create conflicting slots) · **invitations** (two requests must not consume one
invite) · **usage counters**.

**11.3 — Database constraints** *(§10)* — Represent enforceable invariants in Postgres, not only
in Python. **Note `RISK-3`:** the test suite builds its schema from `Base.metadata` on SQLite and
**never runs a migration**, so every new constraint is exercised only by CI's Postgres
up → down → up job. A constraint correct on SQLite and wrong on Postgres is a failure that has
already happened here.

**11.4 / 11.5 — Observability** *(§11, §12)* — Structured logs carrying request, organization,
user, job, worker and submission IDs. **Never log** passwords, tokens, private student content,
or full AI prompts and responses. Metrics: API latency and error rate, queue depth, job
processing time and failure rate, worker utilisation, AI call latency and failures, storage
failures, connection-pool saturation, rate-limit events. **Nothing currently watches permanently
failed jobs** — `jobs.py:229` is the only record that a student's work stopped moving. That gets
an alert.

**11.6 — Load test at 1,000 students** *(D84, D86)* — **The last task in the plan**, run against
the finished product so the numbers reflect what you will actually operate. One realistic run.
Measure p50/p95/p99 latency, error rate, database utilisation, queue latency, worker throughput.
**Identify the first bottleneck and fix that** — do not pre-optimise everything. The 5,000 and
10,000 tiers are deferred until real traffic justifies them.

> **11.2 is the gate on scaling out (D85).** Until the concurrency audit is complete, the
> deployment stays on one instance regardless of what Phase 1 made possible.

---

## 8. Verification

**Per task**, before opening a PR:

```bash
# backend, from backend/
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
# plus the type checker added in 0.8

# frontend, from frontend/
npm test && npm run lint && npm run build   # build is the ONLY frontend type check today
```

**Per migration** — CI runs `upgrade head` → `downgrade base` → `upgrade head` against real
Postgres 16, and the suite never runs a migration. Run the cycle locally against
`docker compose up -d db` (`RISK-3`).

**Per phase**, end to end against a seeded demo account:

| Phase | Prove |
|---|---|
| 0 | Auto-finalized homework moves Topic Mastery and counts as submitted; the recompute runner regenerates every snapshot; the type checker and generated API types run in CI |
| 1 | Two APIs and two workers run together: upload via #1 and read via #2, one shared rate limit, one marking operation per submission, one email per send, safe worker restart |
| 2 | A tutor creates a subject from their own syllabus upload and sees chapters containing topics; another tutor gets `404` |
| 3 | Marking receives mark scheme, chapter notes, subject rules, board and level in that precedence; a typed answer marks as safely as a photographed one; a mock becomes evidence |
| 4 | Marking produces mistakes in the tutor's own categories; a tutor revision writes an audit row and survives a re-run |
| 5 | No consistency factor; homework score is accuracy-only; chapters carry scores; **no v1 table exists and every surface agrees** |
| 6 | Onboarding inputs produce a draft plan; accepting it makes lesson suggestions live; skipped lessons flag behind-schedule; a syllabus edit reflows generated slots and leaves hand-edited ones untouched |
| 7 | Attendance recorded at lesson confirmation appears for tutor, student, parent and in reports |
| 8 | Three different weekly artifacts generate and send, on home and by email, in the tutor's language; no narrative rows are read |
| 9 | A brand-new tutor completes onboarding in one pass, with no students, and lands on a home page with a plan, prompts and the marking figure |
| 10 | Usage rolls up per account; the owner tool reads across accounts and **no API route does**; an account deletes completely and exports readably |
| 11 | Concurrency hotspots hold under racing workers; failed jobs raise an alert; the load test names the first bottleneck |

**Whole-plan acceptance:** a new tutor signs up, completes onboarding, accepts a teaching plan,
teaches a lesson from it, uploads a chapter classified, sets homework, has it auto-marked with
mistakes tagged, sees readiness and weak topics move, receives a weekly send by email, and
generates a report — on a two-instance deployment, without an engineer touching anything.

---

## 9. Out of scope

- **WhatsApp integration** (D55) — future scope.
- **Payment and plan limits** (D2) — usage tracking only.
- **Multi-tutor accounts** (D1) — solo tutor; the tenant model supports more later (E14).
- **Generated or auto-assigned practice** (D42) — weak topics are shown, never acted on.
- **The GitHub repository rename** (E10) — manual, for the owner.
- **A translated UI** (D66) — only AI-written prose follows the tutor's language.
- **Monthly intelligence** — weekly only (D49).
- **Multi-subject classes** (D72).
- **Load testing at 5,000 and 10,000 students** (D84) — deferred until traffic justifies it.
- **Redis for anything but rate limiting** (E18).

## 10. Known risks carried

| Risk | State after this plan |
|---|---|
| `RISK-1` — API pinned to one instance | **Capability delivered in Phase 1; risk closed at 11.2.** Phase 1 removes the three named causes — the uploads disk, the in-process worker, the in-process rate limiter — but the deployment deliberately stays single-instance until the concurrency audit completes (D85). Until then the risk is *unrealised*, not gone. |
| `RISK-5` — two readiness engines disagree | **Closed.** D78 deletes v1 outright rather than keeping it written. |
| `RISK-6` — frontend/backend contract drift | **Closed.** Task 0.8 generates TypeScript types from the backend's own schema. |
| No Python type checker | **Closed.** Task 0.8 introduces one at service boundaries. |
| `RISK-3` — a migration correct on SQLite, wrong on Postgres | **Unchanged and more exposed.** This plan adds many migrations and, in 11.3, many constraints. The suite still never runs a migration; CI's Postgres job remains the only check. |
