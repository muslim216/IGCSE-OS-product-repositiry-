# Avora New State — August 16

The engineering plan to take Avora from what is built today to a complete, ready-to-sell
product. Written to be executed by AI agents (single-task and parallel) and human engineers.

> **Revision 2** — incorporates the SWE audit of revision 1. Changes: a new **Phase 1 (Scale
> foundation)** before any product work · phases **reordered** so marking and evidence settle
> before mistakes and readiness · **v1 readiness is now deleted outright** (supersedes AV-28) ·
> **per-subject marking rules** and a **marking-context precedence rule** added · **type
> checking and generated API types** added · a new **Phase 11 (Scale hardening)** at the end.
>
> **Revision 3** — incorporates the security threat review of revision 2. All ten findings are
> resolved: seven by **decisions `AV-91`–`AV-97`**, and each one written as **security acceptance
> criteria inside the task that owns it** rather than left in a review document. One new task
> (**0.9**, the token-revocation regression test). §5b is the map proving none was dropped.
> Nothing else about the plan's shape changed — the pre-work turned out to be decisions and
> acceptance criteria, not a phase of code.
>
> **Revision 5** — incorporates the product manager's navigation spec. Changes: **the tutor's ten
> tabs, the student's six and the parent's four are now settled** (`AV-105`–`AV-122`) and Phase D
> designs to them · homework is **un-folded from Review** · Mocks and Past papers are promoted
> into the nav · a **Students tab** is added · **past-paper booklets** with AI extraction of the
> papers inside · **timed mocks** on a server-side clock · **lesson mode**, with Zoom and Google
> Meet integrations for online attendance · **web push** · and a final **Phase 12: a mobile app**
> for notifications and quick actions only. The student's mistake pattern moves to Progress
> (supersedes `AV-41`).
>
> **Revision 4** — incorporates an engineering audit of revision 3, which found the plan was
> **specifying work that already exists** and **deleting work merged weeks ago** without saying
> so. Changes: a new **task 0.0** auditing what is already built, before anything else · a new
> **Phase D**, a full design pass running parallel to Phase 1 · **the narrative is kept**
> (supersedes `AV-52`) and merged with the weekly send into one writer · six tasks corrected for
> code that already exists · explicit obligations for the demo seed, the existing test suite,
> database backups before destructive steps, constitution updates and ADRs · a task to fill in
> the AI price table · `Classified` finally defined.

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

**Roughly 76 tasks across 14 phases, of which 15 are `L`.** That is the honest shape: this is a
programme, not a sprint. **No completion date is claimed** (AV-5) — sequencing is by dependency and
risk. The longest chain is Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 8 →
Phase 9 → Phase 10 → Phase 11 → Phase 12, with Phase D and Phase 6 running alongside. Anyone
needing a date should estimate that chain rather than the total.

**Three workstreams could be cut without breaking anything else**, if the programme needs to
shrink: the Zoom and Google Meet integrations (7.3), web push (8.7), and the mobile app
(Phase 12). Each is self-contained, each has a working fallback — manual registers, email and
in-app notifications — and together they are a large share of the remaining effort.

### Obligations that apply to every task

These are not optional and they are not owned by a single phase. An earlier revision left them
implicit, which meant nobody owned them.

- **Take a database snapshot before any destructive step** (E25) — `2.1`, `2.2` and `5.3` at
  minimum. "No users yet" makes destruction safe, not reversible; reverting a commit does not
  restore a dropped table. The task states how to restore it.
- **Update `seed/demo.py` in the same phase that changes the data model** (E26). Every phase's
  verification runs against a seeded demo account, and the seed only knows the old shape.
- **Fix the tests you break — never delete the assertion** (E26). Deleting routes breaks
  `test_authorization.py`; dropping `consistency` breaks the readiness tests; deleting v1 makes
  `test_readiness_v2_shadow.py` and `test_readiness_cutover.py` meaningless. A failing test is
  either a real regression or an out-of-date check, and **removing the check to get green
  silently retires a control**.
- **Update the constitution document your change describes, in the same PR** (`GOV-1`,
  `CODE-21`). This plan touches §01, §04, §05, §06, §07, §08, §09, §11, §12 and §14. Budget for
  it — it is roughly a third again on top of the code.
- **Write an ADR for a structural decision.** At minimum this plan owes: deleting readiness v1 ·
  the `Chapter` model · the teaching plan's AI-advises/scheduler-decides split · object storage
  and signed-URL policy · Redis · the separate owner tool · marking-context precedence.

---

## 3. Product decisions register

Every decision below was made by the product manager. **They are the source of truth. Do not
re-derive, re-litigate, or "improve" any of them.** If a task appears to conflict with one,
stop and raise it rather than choosing.

> **On the `AV-` prefix.** `docs/experience-implementation-plan.md` has its own decision register
> numbered `D1`–`D6`, cited in merged PRs and shipped code comments. This document's decisions
> were originally numbered the same way, which meant `D4` meant *"store the organization's
> timezone"* in one document and *"rename everything to Avora"* in the other — and an agent
> following a citation into the wrong document would have got a different decision with nothing
> to flag it. **Every decision here is `AV-n`. Nothing else in the repository uses that prefix.**
> A bare `D`-number always belongs to the older document.

### Customer and commercial

| # | Decision |
|---|---|
| AV-1 | **Solo tutor** is the customer. One tutor per account. No multi-tutor centre, no owner role. |
| AV-2 | **Usage tracking, no payment.** Measure AI spend, students/classes, storage, and activity per account. No payment provider, no plan limits. |
| AV-3 | The **product owner sees every account's usage** without asking the tutor; the tutor sees their own. |
| AV-4 | **Rename everything to Avora** — user-facing text, docs, internal code, and the GitHub repository. |
| AV-5 | **No fixed deadline.** Sequence by dependency and risk, not by date. |

### Subjects and syllabus

| # | Decision |
|---|---|
| AV-6 | **Subjects are owned by each tutor**, private to their account. Any exam board. |
| AV-7 | Levels covered: **IGCSE, O Level, A Level**. Nothing may assume an IGCSE-shaped world. |
| AV-8 | **Delete the five built-in seeded syllabuses.** Every tutor creates their own. |
| AV-9 | Syllabus tree is **Subject → Chapter → Topic**. Chapters contain topics. Marks, mistakes and readiness attach at **topic** level; a chapter's score is rolled up from its topics. |
| AV-10 | Setup materials collected per subject: **the syllabus document** and **teaching guidance / scheme of work**. |
| AV-11 | **Grade boundaries are entered by the tutor.** No AI drafting, no defaults. |

### Teaching plan

| # | Decision |
|---|---|
| AV-12 | **The tutor sets exam dates for their class.** |
| AV-13 | The plan is **per class**, **AI-drafted**, and **the tutor must accept it** before it is live. The tutor can edit anything at any point in the year. |
| AV-14 | It is a **full schedule to exam day**, scheduling **each week and every lesson**, derived from lessons per week. The AI uses the uploaded teaching guidance to judge which chapters are harder or slower and weights time accordingly. |
| AV-15 | Plan inputs at onboarding: **exam date · lessons per week and lesson length · when to start past papers · holidays and term breaks**. |
| AV-16 | Teaching and past-paper phases **may overlap**. |
| AV-17 | **The plan suggests, the tutor confirms each lesson.** Lessons are not auto-created. |
| AV-18 | When a class falls behind: **flag it and offer a one-click re-plan** the tutor accepts. Nothing reschedules itself. |
| AV-19 | **The plan and the exam countdown are tutor-only.** Students and parents see neither. |

### Marking and materials

| # | Decision |
|---|---|
| AV-20 | **Classifieds are chapter-scoped**, uploaded when the tutor starts that chapter. Each carries its **mark scheme** and **chapter-specific notes**. |
| AV-21 | Those notes are **marking context for the AI**. |
| AV-22 | The system **prompts the tutor to upload the classified when the plan reaches a new chapter**. Non-blocking. |
| AV-23 | Homework continues to be created from classifieds. No change to the creation flow beyond chapter scoping. |
| AV-24 | Pass the **exam board and level into the marking prompt**. |
| AV-25 | **The auto-finalize rule is unchanged**: an official mark scheme covered the question AND the AI was confident. No new variables. |
| AV-26 | **Assessments stay**, and **mocks may be uploaded and AI-marked** through the normal pipeline. |
| AV-27 | Past papers are **a phase after the syllabus is taught** (overlapping allowed). The existing past-paper module is retained. |
| **AV-75** | **Per-subject marking rules.** The tutor writes marking rules once for a subject and they apply to every chapter, classified and piece of work in it. **In addition to** board, level and chapter notes — none of those are removed. No account-wide layer. |
| **AV-76** | **Marking-context precedence.** The official mark scheme is **absolute and never overridden**. Below it, the tutor's rules beat exam-board convention, and more specific tutor rules beat broader ones. Resolution order: mark scheme → chapter notes → subject rules → exam board and level. |
| **AV-80** | **The AI agreement rate stays as it is calculated today.** No change. |

### Readiness

| # | Decision |
|---|---|
| ~~AV-28~~ | ~~Repoint readers to v2; v1 keeps being written.~~ **Superseded by AV-78.** |
| **AV-78** | **Delete readiness v1 outright.** Repoint `analytics.py`, `reports.py` and `student_crm.py` to v2, stop the v1 writes, and drop `topic_readiness`, `readiness_history` and `tutor_preferences` in the same change. v2 is the single source of truth. |
| AV-29 | **Fix the `auto_finalized` exclusion and fully recompute every snapshot.** No users, so no announcement or phased rollout. |
| AV-30 | **Drop `consistency`** from the factor set. |
| AV-31 | **Past-paper performance counts only once the past-paper phase has started** for that class. |
| AV-32 | **Homework performance is accuracy only.** Completion is shown separately as a fact, never inside the score. |
| AV-33 | **Readiness stays purely evidence-based.** Exam proximity and being behind schedule do not move it. |
| AV-34 | **The tutor can re-weight factors, switch them off, and add their own criteria.** A custom criterion is **invented and hand-scored by the tutor** per student. |
| AV-35 | That configuration applies **per account, with subject overrides**. |
| AV-36 | **Cold start: show a score from the first marked work**, labelled with the evidence behind it. |

### Mistakes

| # | Decision |
|---|---|
| AV-37 | **The AI records why each wrong answer was wrong**, at marking time. It counts immediately. |
| AV-38 | **The tutor may revise any of them but is never prompted to.** No review queue, no blocking step. |
| AV-39 | **Mistake categories are defined by the tutor.** At subject setup they are shown a suggested list they can accept, edit, or replace entirely. |
| AV-40 | Mistakes are stored and shown **per topic and per chapter** on the student's profile (tutor-facing). |
| AV-41 | The student sees their own mistake pattern **in the homework tab**, not on their general profile. |
| AV-69 | **Mistake severity stays AI-assigned on the existing 1–3 scale.** Tutors define categories, not severity. |

### Weak topics

| # | Decision |
|---|---|
| AV-42 | **Detect, store, and show. Never auto-assign.** No generated practice, no "do this now". |
| AV-43 | Shown to the **student as information**, and to the **tutor in their class view**. |
| AV-74 | **The tutor sets the weak-topic threshold**, as part of onboarding. |

### People and surfaces

| # | Decision |
|---|---|
| AV-44 | **Attendance is tracked per lesson** and visible to tutor, parent, student, and in reports. |
| AV-45 | **The student sees**: readiness score, predicted grade, weak topics, their own attendance — and their mistake pattern in the homework tab. |
| AV-46 | **The parent sees**: the weekly send, readiness and predicted grade, and attendance. Not the tutor's report. |
| AV-47 | **The tutor's home** shows a compact overview of: work awaiting review · plan progress per class · upload prompts · weak topics across classes. |
| AV-48 | **The tutor's home always carries one piece of good news: the marking the AI handled for them.** Other positives live in the class and module screens. |
| AV-72 | **One subject per class.** |
| AV-73 | Students submit **files or typed answers**. |

### Intelligence and communication

| # | Decision |
|---|---|
| AV-49 | **A weekly send for tutors, students and parents.** |
| AV-50 | Composed as **fixed facts plus one AI paragraph**. Every figure verifiable. |
| AV-51 | It appears on **each role's home page** and is emailed. |
| ~~AV-52~~ | ~~It replaces the existing narrative system, which is removed.~~ **Superseded by AV-98.** |
| AV-53 | **Tutor reports: on demand and weekly.** Content: chapter and topic breakdown · mistake patterns · plan progress and countdown · attendance. |
| AV-54 | **Email triggers**: weekly send · homework set · homework due · marked work ready · account and invite emails. |
| AV-55 | **WhatsApp is future scope**, not in this plan. |
| AV-62 | The weekly send goes out **automatically to all three roles**. The tutor can read it but does not gate or edit it. |
| AV-63 | **The parent's report is their weekly send** — one artifact, not two. |
| AV-64 | **The parent's report differs from the tutor's**: readiness and predicted grade · attendance and homework record. **Not** the chapter/topic breakdown, **not** mistake patterns. |
| AV-65 | Parent reports send **automatically**. No tutor release step. |
| AV-66 | **English UI. The AI writes in the tutor's chosen language.** |

### Onboarding, removals, platform

| # | Decision |
|---|---|
| AV-56 | **Onboarding is a step-by-step flow the tutor must finish.** |
| AV-57 | **Delete completely**: student AI chat, peer improvement ranking. |
| AV-58 | **Hide from the product, keep the code**: Google Classroom sync, knowledge base. |
| AV-59 | **Keep**: files and recordings shared with a class (`GroupResource`). |
| AV-60 | Onboarding **must reach an accepted teaching plan**. Adding students is **optional**. |
| AV-61 | Students and parents join by **invite link**; the tutor supplies their email addresses. |
| AV-67 | **The tutor sets the account's time zone; students and parents may change their own.** |
| AV-68 | A **syllabus edit reflows the plan automatically**. |
| AV-77 | **Hand-edited plan slots are preserved through a reflow.** Only untouched generated future slots are eligible. |
| AV-70 | **Account deletion and data export are in scope.** |
| AV-71 | **The owner's cross-account usage view is a separate internal tool**, outside the tutor-facing product. |
| **AV-79** | **Add both** a Python type checker at service boundaries **and** TypeScript API types generated from the backend schema. |
| **AV-81** | **Sequencing**: marking and evidence → mistakes → readiness, in that order. The teaching plan runs in parallel. |
| **AV-82** | **Scalability**: object storage and the worker split come **before** the product phases. The rest comes after. |
| **AV-83** | **Redis** is the shared store for rate limiting. |
| **AV-84** | **Correctness first**: prove two API instances and two workers behave together. **One load test at 1,000 students** to find the first bottleneck. Defer the full 5,000/10,000 ladder. |
| **AV-85** | **Build multi-instance capability in Phase 1, but keep running a single instance** until the Phase 11 concurrency audit (11.2) is complete. 11.2 is the gate on scaling out. |
| **AV-86** | **The load test runs at the very end**, against the finished product. |
| **AV-87** | **Per-subject marking rules are offered during onboarding but skippable.** |
| **AV-88** | **The tutor chooses which day their account's weekly send goes out.** |
| **AV-89** | That day is **set in onboarding step 1, pre-filled with a default** — a glance, not a decision. |
| **AV-90** | The send follows **the tutor's clock**; every recipient gets it at the same moment, whatever time zone they set for themselves. |

### Security (settled from the threat review, 19 Aug)

| # | Decision |
|---|---|
| **AV-91** | **Typed answers auto-finalize like photographed work.** The trust rule does not change by submission channel. |
| **AV-92** | **No feedback is shown while a student is still working.** Marks and feedback appear only once they have submitted. |
| **AV-93** | **A deterministic text scan runs before the marking call.** A hit routes that one submission to the tutor. No second AI call, no mark-value cap, no calibration metrics — those were considered and declined. |
| **AV-94** | **The official mark scheme always wins.** Tutor-authored chapter notes and subject rules are context the AI considers; they can never override a scheme. |
| **AV-95** | **Student work is permission-checked on every view.** It is served through the API. Tutor material — mark schemes, classifieds, syllabus, teaching guidance — uses direct signed links. |
| **AV-96** | **The tutor confirms a parent's email address before the first send.** |
| **AV-97** | **If Redis is unavailable, each API instance falls back to its own in-process counter and alarms.** Logins are never blocked wholesale, and never left uncounted. |

### Reversals and design (settled 19 Aug, after the engineering audit)

| # | Decision |
|---|---|
| **AV-98** | **The narrative is kept.** It is not deleted. Supersedes `AV-52`. It is the always-on-screen paragraph that updates as marks land; the weekly send is a scheduled artifact. They are different things. |
| **AV-99** | **One writer produces both.** A single generator writes the text that appears on screen *and* the text in the weekly send. One voice, one AI cost, and the two can never contradict each other about the same student. |
| **AV-100** | **Peer improvement ranking and student AI chat are still deleted** (`AV-57` stands, with the cost seen and accepted). |
| **AV-101** | The tutor home shows the marking count **and** a time estimate, **explicitly labelled as an estimate** — "47 questions marked — roughly 3 hours of marking". |
| **AV-102** | **Every screen is redesigned — existing ones as well as new.** The product should read as one thing after this plan, not as new screens bolted onto old. |
| **AV-103** | **The Avora visual identity is kept exactly as built** — parchment/espresso/terracotta, Lora and Inter, the motifs. The redesign is **layout and structure only, never style.** |
| **AV-104** | **Design comes first as its own pass**, then each phase builds its own screens against that spec. No phase waits on design; nothing is built without it. |

### Navigation and placement (settled 19 Aug)

| # | Decision |
|---|---|
| **AV-105** | **Tutor navigation is flat, ordered by how often each is used**: Overview · Review · Homework · Classes · Students · Mocks · Past papers · Readiness · Reports · Library. No grouping, no sub-menus. |
| **AV-106** | **Student navigation**: Home · Homework · Mocks · Past papers · Progress · Materials. |
| **AV-107** | **Parent navigation**: Overview · Progress · Attendance · Reports. |
| **AV-108** | **The Homework tab holds the detail** — questions, marking, management. The per-class Homework tab shows **name and metadata only** and links through to it. |
| **AV-109** | **The teaching plan, lessons and in-person attendance all live on the class's Schedule tab.** |
| **AV-110** | **Library holds every choice made during onboarding**, the uploaded material (syllabus document, teaching guidance), and the classifieds. |
| **AV-111** | **The "AI marking agreement" is the per-subject marking rules**, read and edited in Library. It describes **how the AI marks, never when a mark counts** — `AV-25` is unchanged. |
| **AV-112** | **Readiness gets its own tab**, holding both the class readiness view and the readiness setup (weights, switching factors off, custom criteria). **Reports gets its own tab.** |
| **AV-113** | **Usage lives in its own small settings area**, separate from Library. |
| **AV-114** | **The Students tab is grouped by class.** From it the tutor can invite and remove students, open a student's full record, move a student between classes, and link a parent. |
| **AV-115** | **The Mocks tab covers small tests, big tests and mocks.** The tutor can type scores in, upload work for AI marking, and **assign mocks to students like homework**. |
| **AV-116** | **An assigned mock is timed from when the student first opens it.** Late submissions are **accepted and flagged, never blocked**. |
| **AV-117** | **Past papers upload as a single paper or a booklet.** On a booklet, **the AI extracts the list of papers inside** — session, paper number, code, page range — and the tutor checks it. When assigning, the tutor picks one paper from that list. |
| **AV-118** | **A lesson is either in person or online.** In person, the tutor logs attendance. Online, attendance comes from a **Zoom or Google Meet integration**. |
| **AV-119** | **A lesson is pre-filled from the plan, and a reminder 15 minutes before prompts the tutor to revise it.** Afterwards nothing is required — it counts as taught unless the tutor says otherwise. |
| **AV-120** | **That reminder goes by email, phone notification and in-app.** |
| ~~AV-41~~ | ~~The student sees their mistake pattern in the homework tab.~~ **Superseded by AV-121.** |
| **AV-121** | **The student's mistake pattern lives on their Progress tab**, alongside readiness, predicted grade, weak topics and attendance. |
| **AV-122** | **A mobile app for notifications and quick actions only** — not a second copy of the product. For tutors, students and parents. **iOS and Android from one shared codebase.** Built as the **final phase** of this plan. |

> **Deliberate asymmetry — do not "fix" it.** AV-18: a *behind-schedule* re-plan waits for tutor
> acceptance. AV-68: a *syllabus edit* reflows automatically. Both stand as written.

> **Deliberate difference — do not harmonise.** AV-46 keeps homework completion detail out of the
> parent's day-to-day view; AV-64 puts an attendance and homework record in the parent's report.

---

## 4. Engineering decisions

Mine, not the product manager's. Flagged so they can be vetoed.

| # | Decision | Why |
|---|---|---|
| E1 | Introduce a **`Chapter` table**, not `Topic.parent_id`. | A chapter is scheduled by the plan, owns a classified, and carries its own rollup. `Topic.parent_id` stays for genuine sub-topics. |
| E2 | Add `SETTLED_STATUSES` to `models/homework.py`, export from the barrel, repoint the four modules that each declare a copy. | Four correct copies exist (`activity.py:32`, `averaging.py:34`, `api/past_papers.py:49`, `api/submissions.py:51`); three sites restate it wrongly. One definition ends the bug class. |
| E3 | **Leave `api/analytics.py:101` entirely unchanged** except for a comment explaining why it is deliberately `finalized`-only. | Per AV-80. Auto-finalized marks have `final_marks = ai_marks` by construction (`marking.py:303`), which is why the filter is there. The comment prevents the next engineer "fixing" it. |
| E4 | The recompute runner is `python -m seed.recompute_readiness`, reusing `enqueue_readiness_v2_debounced` with staggered `run_after`. | Mirrors `python -m seed.load_syllabus`. No new endpoint to secure; the existing debounce prevents duplicates. |
| E5 | The plan's schedule is **generated deterministically from AI-supplied chapter weights**, never emitted wholesale by the model. | The AI is good at "Chapter 7 is dense, give it 1.6× time"; bad at arithmetic over a calendar with holidays. Keeps it explainable (`PROD-1`). |
| E6 | Mocks reuse the polymorphic `Submission` path. | `PROD-9` / `ADR-0004` — no parallel code path. |
| E7 | Chapter readiness is **stored**, not computed on read. | Reports, weekly sends and the tutor home all need it; per-request computation puts N queries in a request path (`PERF-1`). |
| E8 | Custom criteria are **a distinct model**, not `ReadinessFactor` members. | `ReadinessFactor` is a non-native enum matched in `if`/`match` chains (`DB-5`, `DB-6`). Tutor-created values cannot be enum members. |
| E9 | Email goes through **one provider module in `services/`**, all templates in one place. | Mirrors `services/ai.py` as sole vendor entry point (`AI-1`). |
| E10 | The repository rename (AV-4) is a **manual GitHub action for the owner**. | An agent cannot rename a repo it does not own. |
| E11 | Store `time_zone` on the user, defaulted from the tutor. **Every stored timestamp stays UTC**; convert at the edges. | Storing local times is how "due Friday" becomes two different days. Columns are already `DateTime(timezone=True)`. |
| E12 | The owner's usage tool (AV-71) is a **separate deployable**, not a route in the API. | It is the one deliberate cross-account read. Keeping it outside means `PROD-4`/`SEC-7` stays true without exception inside the product. |
| E13 | The plan's automatic reflow (AV-68) runs as a **job**, not inline in the edit request. | Rescheduling a year of slots is not request-path work (`BE-13`, `PERF-1`). |
| **E14** | **Invariant: one Avora account = one organization = one tenant = (today) exactly one tutor.** Use `organization_id` as the tenant column everywhere; do not introduce a second "account" concept. | The audit flagged the terminology clash between AV-1 and the existing org-scoped model. This resolves it without a migration — solo-tutor is a *policy* on top of the tenant model, not a different model. |
| **E15** | **Invariant: a `PlanSlot` is a planned occurrence; a `Lesson` is the confirmed actual occurrence.** Slots carry provenance — `generated` · `manually_modified` · `confirmed` · `completed`. | Makes AV-77 enforceable: only `generated` future slots are eligible for automatic reflow. Without provenance there is no way to tell a tutor's edit from the generator's output. |
| **E16** | **Marking context is assembled in exactly one function**, which applies AV-76's precedence and is the only place that knows the order. | Precedence spread across call sites is precedence that drifts. One function, one test per conflict pair. |
| **E17** | **Invariant: AI-generated mistakes are replaceable on re-run; a tutor-revised mistake is never overwritten.** | Same contract `mark_submission` already honours for marks (`marking.py:272`). Extends `BE-6` to the new job. |
| **E18** | Redis (AV-83) is used **only** for rate-limit counters. **Postgres remains the source of truth for all application state.** | Prevents Redis quietly becoming a second database. If a second use appears, it gets its own decision. |
| **E19** | Worker liveness state moves **into the database** as part of the worker split. | `jobs.py:62-69` keeps `_started_at`, `_last_loop_at`, `_job_started_at`, `_restart_times` as module state read by the health endpoint. The code comment already says this must move. Split the worker without it and the health check silently lies. |
| **E20** | The pre-marking scan (AV-93) is a **pure function taking submission text and returning a boolean plus the matched reason**, called before the AI request is built. | `BE-4`/`CODE-3` — decision math is pure and unit-testable without a session or a model. It is also the only control in the marking path that does not depend on model judgement, so it must be trivially auditable. |
| **E21** | File serving splits by sensitivity (AV-95): student submissions proxy through the API after the existing ownership check; tutor material mints a short-lived signed URL. | The volumes point opposite ways — tutor PDFs are the megabytes and carry no personal data; student photos are small and are a named minor's work. Route by what is actually at risk, not by one uniform rule. |
| **E22** | Export and account deletion (10.4) require **re-authentication immediately before the action**, write an audit row, are rate limited, and deliver out of band to the account's verified address. | Both are whole-tenant primitives reachable from a single stolen session. Standard practice for a bulk-egress endpoint; no product decision needed. |
| **E23** | **Task 0.0 audits what already exists** and annotates every downstream task before any of them runs. | Revision 3 specified building timezones, a grade-boundary writer, cold-start handling and a tutor-home aggregate — **all of which already exist and shipped**. An agent reading a task in isolation has no way to know. This is the cheapest possible fix and it must run first. |
| **E24** | The single narrative writer (AV-99) keeps the **existing precomputed-and-stored shape**: a background job writes the text, surfaces read the stored row. The weekly send reads the same rows. | `services/narrative.py` already implements exactly this, for exactly the stated reason — *no primary surface waits on a model to render its primary content*. Merging the weekly send into it is far less work than building a second generator, and the sweep-not-a-chain reasoning in that file must survive (`CODE-13`). |
| **E25** | **A database snapshot is taken immediately before every destructive step**, named in the task, and the task states how to restore it. | "No users yet" makes destruction safe, not reversible. `5.3` drops tables and `2.1`/`2.2` rebuild them; reverting a commit does not bring a dropped table back. |
| **E26** | Every phase that changes the data model **updates `seed/demo.py` in the same phase**, and every task that breaks existing tests **fixes them rather than deleting the assertion**. | The verification table asks every phase to prove itself against a seeded demo account; the seed only knows the old shape. And an agent facing forty red tests will otherwise "fix" one by removing the check, which silently retires a control. |

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

**Resolved by decision:** marking-context layers (AV-75) · precedence (AV-76) · v1 retirement (AV-78) ·
reflow protection (AV-77) · type safety (AV-79) · sequencing (AV-81) · scale timing (AV-82) · Redis
(AV-83) · load testing (AV-84) · account/organization terminology (E14) · PlanSlot vs Lesson (E15).

**Rejected:** the `idempotency_key` column, and adding Redis for anything beyond rate limiting
(the audit's own §8 forbids a second application datastore; E18 holds the line).

**Additional findings the audit missed**, folded into Phase 1:

- **HEIC transcoding is CPU-bound and runs in-process** (`storage.py:_to_jpeg`), blocking the
  event loop for every iPhone photo a student uploads — already a `BE-13`/`PERF-1` violation.
- **`fetchFileUrl()` is a sanctioned bypass of the single API client** (`FE-1`); signed URLs
  change that contract and the frontend must move with it.
- **The single-origin deployment constraint comes from Google Classroom's OAuth redirect** —
  and Classroom is being hidden (AV-58), which lifts it.
- **The test suite never runs a migration** (SQLite in-memory, schema from `Base.metadata`), so
  every new database constraint is only exercised by CI's Postgres job. `RISK-3` is the failure
  that has already happened here.

### 5b. The threat review, resolved

A security review of revision 2 (19 Aug) raised ten findings. **Every one is resolved by a
decision above or by acceptance criteria inside the task that owns it.** The table below is the
map. **A finding that lives only in a review document gets missed by the agent executing the
task six weeks later — so each remediation is written into its task, and this table exists only
to prove none was dropped.**

| ID | Finding | Severity | Resolved by | Lives in |
|---|---|---|---|---|
| F1 | The auto-finalize gate is self-referential; typed answers remove its friction | Critical | `AV-91`, `AV-92`, `AV-93`, `E20` | Task 3.3 |
| F2 | Precedence in a prompt is not an access control | High | `AV-94` | Task 3.2 |
| F3 | Signed URLs move authorization from request time to mint time | High | `AV-95`, `E21` | Task 1.2 |
| F4 | Redis failure mode for the login throttle undecided | High | `AV-97` | Task 1.4 |
| F5 | A minor's record emailed automatically to an unverified address | High | `AV-96` | Task 8.5 |
| F6 | Export is a one-request full-tenant exfiltration primitive | Medium | `E22` | Task 10.4 |
| F7 | The worker becomes a high-privilege principal with no user context | Medium | Acceptance criteria | Task 1.3 |
| F8 | Token revocation is one cache away from breaking | Medium | Regression test | **Task 0.9** |
| F9 | Second-order injection if the weekly send carries free text | Medium | Acceptance criteria | Task 8.2 |
| F10 | Structured logs become a re-identifiable store of minors' data | Low | Deferred decision | Task 11.4 |

**Declined, deliberately:** a second AI call to detect injection, a mark-value cap on
auto-finalize, and calibration metrics (override rate, remark rate). All three were offered and
not taken. **Do not add them back without asking** — and note that declining calibration means
there is currently no way to detect F1 being exploited. That is a known, accepted position.

**One decision deferred on purpose:** log retention period, at task 11.4. It is a cost and
forensics trade-off that cannot be sensibly made before there is any traffic. **Task 11.4 must
raise it rather than pick a number.**

---

## 6. Dependency map

```
Phase 0   Truth and hygiene          ← 0.0 (audit what exists) runs FIRST
                    │   (serial — 0.6's rename and 1.2's object storage
                    │    both rewrite services/storage.py)
        ┌───────────┴───────────┐
        ▼                       ▼
Phase 1  Scale foundation   Phase D  The design pass
        │    (backend only)      │   (screens only — no collision)
        └───────────┬───────────┘
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
                    │
                    ▼
Phase 12 The mobile app        ← last, against a settled product
```

Phases 3 → 4 → 5 are **serial by decision** (AV-81): marking produces the evidence and mistake
rows both later phases consume, so their contracts settle first. Phase 6 runs alongside them.

---

## 7. Tasks

### Phase 0 — Truth and hygiene

| ID | Task | Size | Mode |
|---|---|---|---|
| **0.0** | **Audit what already exists** — ✅ done 19 Aug | S | ✅ |
| **0.1** | Shared `SETTLED_STATUSES` + fix the v2 gatherers | S | → |
| **0.2** | Recompute runner and full backfill | S | after 0.1 |
| **0.3** | Delete student AI chat | S | ∥ |
| **0.4** | Delete peer improvement ranking | S | ∥ |
| **0.5** | Hide Google Classroom sync and knowledge base | S | ∥ |
| **0.6** | Rename MANARA / IGCSE-OS → Avora | M | ∥ |
| **0.7** | Time zones | S | ∥ |
| **0.8** | Python type checker + generated API types | M | ∥ |
| **0.9** | Token-revocation regression test | S | ∥ |
| **0.10** | Fill in the AI price table | S | ∥ |

**0.0 — Audit what already exists** *(E23)* — ✅ **DONE, 19 Aug.** Results below.

Revision 3 specified building four things that were already built and shipped. An agent handed a
task in isolation cannot know that, and would happily build a second one. **Read your task's row
below before writing anything.**

Legend: **BUILT** — exists and works; your task is a rework or an extension, not a build ·
**PARTIAL** — the hard part exists; only the named piece is new · **ABSENT** — genuinely nothing.

| Task | State | What is actually there |
|---|---|---|
| 0.1 settled statuses | PARTIAL | Four **correct** copies already: `activity.py:32`, `averaging.py:34`, `api/past_papers.py:49`, `api/submissions.py:51`. Three sites restate it wrongly. |
| 0.2 recompute runner | ABSENT | `seed/` holds only `demo.py` and `load_syllabus.py`. |
| 0.3 student chat | BUILT → delete | `api/chat.py` 198, `models/chat.py` 44, `TutorChatPage.tsx`. Student-gated on every route, so removal is clean. |
| 0.4 peer ranking | BUILT → delete | `services/improvement.py` 349, `api/improvement.py` 34, `ImprovementPage.tsx`, `api/improvement.ts`, `lib/student.ts`, a nav entry, three test files. |
| 0.5 Classroom + KB | BUILT → hide | `api/classroom.py`, `services/google_classroom.py`, `api/knowledge.py` all live. |
| 0.6 rename | — | MANARA / IGCSE-OS naming throughout code, docs and the repo name. |
| **0.7 time zones** | **BUILT** | `services/timezones.py` with `normalize_timezone`, `PUT /organization/timezone`, `TimezoneSetting.tsx` — at **organization** level. **Only the per-user override (AV-67) is new.** |
| 0.8 type safety | ABSENT | No `mypy` or `pyright` anywhere in `pyproject.toml`. TypeScript interfaces are hand-mirrored. |
| 0.9 revocation test | ABSENT | No test references `token_version`. **The behaviour is already correct** (`api/deps.py:29`); only the test is missing. |
| **0.10 price table** | ABSENT | `MODEL_PRICING = {}` at `services/ai.py:387`, populated only through the `AI_MODEL_PRICING` env var. **This is a configuration change, not a code change.** |
| **Phase D** | PARTIAL | `experience-design.md`, `avora-visual-identity.md` and the token set in `frontend/src/index.css` all exist. **Five of the tutor's ten tabs already exist as pages** — `LibraryPage`, `MocksPage`, `PastPapersPage`, `GroupsPage`, `TodayDashboard` — and `GradeBoundariesPage`, `SyllabusUploadPage`, `PreferencesPage`, `ClassReadinessPage` exist as routes outside the nav. |
| 1.2 object storage | ABSENT | Local disk — but paths are stored **relative to `UPLOAD_DIR` specifically so the folder can move**, which is most of the design work already done. |
| **1.3 worker split** | **PARTIAL** | The DB-backed queue and the **atomic claim already work** — `jobs.py:184` uses `FOR UPDATE SKIP LOCKED`. **Do not rewrite them.** New: the process split, and moving liveness state out of `jobs.py:62-69`. |
| 1.4 Redis limiter | ABSENT | `services/rate_limit.py` is in-process; its own docstring already names Postgres or Redis as the fix and says when to do it. |
| 1.5 two-instance suite | ABSENT | — |
| 2.1 Chapter | ABSENT | `Topic.parent_id` exists but is read only for display, never for rollup. |
| 2.2 tutor-owned subjects | ABSENT | `Subject` has **no `organization_id`**; unique on `(exam_board, code)`; five seeded syllabus JSONs. |
| 2.3 syllabus extraction | BUILT → extend | `SyllabusUpload` + the `SYLLABUS` prompt already do upload → AI draft → tutor review → apply. It produces a **flat** topic list; chapters are the extension. **Reuse this pattern; do not invent a second one.** |
| **2.4 grade boundaries** | **BUILT** | `api/grade_boundaries.py` 107 lines **and** `GradeBoundariesPage.tsx`. The writer and the editor both exist. Only collapsing the two conflicting sources is new. |
| 2.5 teaching guidance | ABSENT | — |
| 2.6 marking rules | ABSENT | — |
| 3.1 Classified | BUILT → extend | `models/homework.py:22`. **Already carries an optional mark scheme.** New: `chapter_id` and `notes`. |
| 3.2 marking context | PARTIAL | `MARKING` prompt v3 exists **with the untrusted-input clause already written well**. Board, level and tutor rules are not passed. |
| 3.3 typed answers | ABSENT | Submissions are files only. |
| 3.4 AI-marked mocks | PARTIAL | `Assessment` / `AssessmentType` / `AssessmentScore` exist in `models/readiness.py` as hand-entered scores. The marking pipeline exists. **Nothing connects them.** |
| 3.5 booklets | ABSENT | `PastPaper` is a single paper. |
| 3.6 timed mocks | ABSENT | `PastPaperAttempt.timed` exists but is **self-declared**, not measured. |
| 4.1 mistake categories | PARTIAL | `MistakeCategory` is a fixed five-member enum. Making it tutor-owned is the change. |
| **4.2 AI mistake tagging** | **ABSENT — the defect** | `Mistake`, the query, and `mistake_analysis()` all exist. **Nothing anywhere creates a row.** The only constructor in the repo is `tests/test_readiness_v2.py:115`. |
| 4.3–4.5 mistakes | ABSENT | — |
| 5.1 factor changes | BUILT → change | `consistency` is live; the homework blend is `accuracy * 0.7 + completion * 0.3` in `readiness_factors.py`. |
| 5.2 chapter rollup | ABSENT | — |
| 5.3 delete v1 | BUILT → delete | v1 tables live and read by `api/analytics.py`, `services/reports.py`, `services/student_crm.py`. |
| 5.4 configurable factors | PARTIAL | `ReadinessWeights` exists. Switching factors off and custom criteria are new. |
| **5.5 cold start** | **BUILT** | Already implemented **and tested** on the parent and student screens. |
| 5.6 weak threshold | ABSENT | `MASTERY_THRESHOLD = 75.0` is hardcoded — and is a **different line** from the weak threshold. Do not conflate them. |
| 5.7 past-paper gating | ABSENT | — |
| **Phase 6 teaching plan** | ABSENT | Entirely. A per-class `ScheduleTab.tsx` exists as a shell to build into. |
| Phase 7 attendance | ABSENT | `Lesson` and `LessonTopic` exist. No mode, no register, no Zoom or Meet. |
| 8.1 email | ABSENT | **No email of any kind** — no provider, no templates, nothing. |
| 8.2 weekly send | ABSENT | — |
| **8.3 narrative** | **BUILT** | `services/narrative.py` 565, `models/narrative.py` 95, `api/narrative.py` 154, plus `ClassNarrative.tsx`, `TodayDashboard.tsx`, `ClassOverview.tsx`, `ParentDashboard.tsx`. **Keep it** (AV-98) — merge, don't rebuild. |
| 8.5 invites | BUILT → change | `services/invites.py` with `build_invite` / `check_usable`, **code-based**. Email links are the change. |
| 8.6 reports | BUILT → rework | `services/reports.py` 217 + `api/reports.py` 126. |
| 8.7 web push | ABSENT | — |
| **9.1 onboarding** | ABSENT | Entirely. Confirmed. |
| **9.2 tutor home** | **BUILT** | `services/today.py` 322 + `api/today.py` 48, with exceptions-first ordering in `_STATUS_ORDER`. **A rework, not a build.** |
| 10.1 usage rollups | PARTIAL | `ai_usage_events` already meters **every** call; `api/ai_usage.py` 110. Per-account rollups are new. |
| 10.3 owner tool | ABSENT | — |
| 10.4 delete + export | ABSENT | — |
| **11.4 observability** | PARTIAL | `WorkerStatus` already distinguishes `running` / `stale` / `stalled` / `crash_looping` — **better than most production systems**. Metrics and structured request logging are new. |
| 11.5 dead-letter | PARTIAL | The terminal `failed` state exists. **Nothing watches it** — `jobs.py:229` says so itself. |
| Phase 12 app | ABSENT | — |

**Reconciliation with `docs/experience-implementation-plan.md`: done.** Its PRs 1–29 have landed;
it now carries a header marking it delivered, naming the disagreements, and stating that its
decisions still bind except where this plan supersedes them. Its `D1`–`D6` and this document's
`AV-1`–`AV-122` can no longer be confused.

> **The headline for anyone starting work:** more exists than the plan implies. The queue, the
> atomic claim, the retry and dead-letter states, the narrative, the tutor home, cold start, the
> grade-boundary editor, timezones and the syllabus upload→review→apply pattern are all built and
> working. **The genuinely empty areas are the teaching plan, attendance, email, onboarding and
> the mobile app.**

**0.10 — Fill in the AI price table** *(engineering audit #10)*

**This is a configuration change, not a code change** — confirmed by 0.0. `MODEL_PRICING = {}` at
`services/ai.py:387` is deliberately empty and is merged with the `AI_MODEL_PRICING` environment
variable, which wins. **Set the env var; do not edit the dict.** Malformed JSON is ignored rather
than breaking every AI call, so a typo fails silently — verify the endpoint reports money
afterwards rather than assuming.

Every call currently records `cost_usd = NULL` and reports as `unpriced_call_count` — never `$0`,
which is correct behaviour (`AI-17`) and completely useless for pricing.

This plan adds a weekly paragraph per person, mistake tagging on every wrong answer, plan
drafting and reflows, and a materially larger marking prompt. **Without this task, AV-2's usage
tracking reports call counts and no money**, and there is no way to know whether a tutor costs
more to serve than they pay.

**0.1 — Shared `SETTLED_STATUSES` + fix the v2 gatherers** *(AV-29, E2, E3)*

- Define `SETTLED_STATUSES = (SubmissionStatus.finalized, SubmissionStatus.auto_finalized)` in
  `backend/app/models/homework.py`; export from `models/__init__.py`.
- Repoint the four existing copies (`services/activity.py`, `services/averaging.py`,
  `api/past_papers.py`, `api/submissions.py`). Behaviour unchanged.
- Fix the three wrong sites in `services/readiness_v2.py` — `_marked_questions_for_topic`,
  `_homework_points`, `_mistake_points_and_total` — and `services/student_crm.py:129`.
- **Leave `api/analytics.py:101` alone** (AV-80, E3); add only the comment explaining why.
- Tests (`tests/test_readiness_v2.py`): auto-finalized homework contributes to Topic Mastery ·
  counts as submitted in Homework Performance · counts toward Mistake Analysis'
  `total_questions`. Mirror `test_averaging.py::test_auto_finalized_work_counts`.

**0.2 — Recompute runner** *(AV-29, E4)* — `backend/seed/recompute_readiness.py`, run as
`python -m seed.recompute_readiness`. Walks every (student, subject) with evidence and calls
`enqueue_readiness_v2_debounced` with increasing `run_after`. Document in runbook §14.

**0.3 / 0.4 — Deletions** *(AV-57, AV-100)* — **Student AI chat** (`api/chat.py` 198 + `models/chat.py`
44 + `TutorChatPage.tsx`) is student-gated on every route, so removal is clean. **Peer improvement
ranking** (`services/improvement.py` 349 + `api/improvement.py` 34 + `ImprovementPage.tsx`,
`api/improvement.ts`, `lib/student.ts`, a nav entry and three test files).

Remove routes, services, models, frontend screens, API wrappers, tests, and a migration dropping
the tables. Check `App.tsx` for orphaned routes and `main.py` for orphaned mounts and handlers.

**The narrative is NOT deleted** (AV-98). Revision 2 had it removed; that is reversed. See 8.2/8.3.

Both deletions were confirmed with their line counts in front of the product manager, including
that the last code commit before this plan was a fix to `rank_of`. They are deliberate.

**0.5 — Hide Classroom and knowledge base** *(AV-58)* — Remove routes and frontend surfaces;
leave services, models and tables. Comment each entry point so it is not read as dead code.
**Removing the Classroom surface lifts the single-origin deployment constraint** — record that
in §08, and Phase 1 depends on it.

**0.6 — Rename to Avora** *(AV-4, E10)* — User-facing strings, `docs/`, docstrings, `README.md`,
`CLAUDE.md`, package names, demo seed. One PR. **The GitHub repo rename is manual** — flag it.

**0.7 — Time zones** *(AV-67, E11)* — **Mostly already built.** `services/timezones.py` with
`normalize_timezone`, `PUT /organization/timezone`, and `TimezoneSetting.tsx` all exist and ship
today, at organization level.

**What is actually new:** a per-user override so students and parents can set their own (AV-67),
defaulting to the organization's. Timestamps stay UTC; convert at render and at the scheduling
boundary. **Read `services/timezones.py` before writing anything** — the normalisation and
validation are done.

Lands early because Phase 6 (plan weeks), Phase 7 (lesson dates) and Phase 8 (the weekly send)
all need it. Note that the weekly send deliberately ignores the per-user value (AV-90).

**0.8 — Type safety** *(AV-79)* — Add a Python type checker (mypy or pyright) wired into CI,
enforced at service boundaries first rather than repo-wide on day one; there is **no Python type
checking at all** today, so expect a backlog. Add TypeScript API types generated from FastAPI's
OpenAPI schema, replacing the hand-mirrored interfaces in `frontend/src/api/*.ts`. This lands in
Phase 0 so everything built afterwards is checked. **Closes `RISK-6`.**

**0.9 — Token-revocation regression test** *(threat review F8)*

A test asserting that bumping `users.token_version` invalidates an already-issued access token on
the very next request. **It passes today** — `api/deps.py:29` compares the token's `tv` claim
against the database on every request. It exists to fail the day someone caches the user row
during Phase 11's performance work, which is exactly where that optimisation gets made and
exactly where nobody is thinking about authentication.

Add a comment at any user-row cache boundary stating the constraint (`CODE-12`). If revocation
silently stops working, logout stops logging out and a tutor resetting a student's password
stops locking them out — the case `SEC-1` and `ADR-0008` exist for.

---

### Phase D — The design pass *(AV-102, AV-103, AV-104)*

**Runs parallel to Phase 1 and must complete before Phase 2 builds anything with a screen.**
Phase 1 is entirely backend, so the two do not collide.

Revision 3 was roughly 80% backend. It described databases and jobs in detail and gave the
screens a clause each — for a product whose entire value is what the tutor sees. This phase
closes that, and every subsequent phase builds its own screens against what this produces.

| ID | Task | Size | Mode |
|---|---|---|---|
| **D.1** | Screen inventory and current-state capture | S | → |
| **D.2** | Redesign the existing screens | L | after D.1 |
| **D.3** | Design the new screens | L | after D.1 |
| **D.4** | States, empty states and copy | M | after D.2, D.3 |

**Scope, precisely.** **Every screen is redesigned — existing as well as new** (AV-102). The
product must read as one thing afterwards, not as new screens bolted onto old ones.

**The visual identity does not change** (AV-103). Parchment, espresso and terracotta; Lora for
display and Inter for UI; the motifs; the semantic token classes. `docs/avora-visual-identity.md`
is binding and `frontend/src/index.css` holds the tokens. **This pass changes layout, structure,
hierarchy and what appears on each screen — never palette, type or style.** Use the semantic
token classes (`bg-surface`, `text-ink-700`, `border-line`), never stock Tailwind names
(`UX-2`), and never wrap the retarget block in an `@layer` (`UX-1`).

**The navigation is settled** (AV-105–AV-122) and is the frame every screen hangs off. Design to it.

| Role | Tabs, in order |
|---|---|
| **Tutor** | Overview · Review · Homework · Classes · Students · Mocks · Past papers · Readiness · Reports · Library — **flat, ordered by frequency of use** (AV-105). Plus a small settings area for usage (AV-113). |
| **Student** | Home · Homework · Mocks · Past papers · Progress · Materials (AV-106) |
| **Parent** | Overview · Progress · Attendance · Reports (AV-107) |

**Where things live, decided:**

- **Homework** holds the detail; the per-class Homework tab shows name and metadata and links
  through (AV-108). `/tutor/homework` currently redirects to Review with a comment saying homework
  was folded into it — **that fold is reversed.**
- **The class's Schedule tab** holds the teaching plan, lessons, and in-person attendance (AV-109).
- **Library** holds every onboarding choice, the syllabus document, the teaching guidance, the
  classifieds, and the per-subject marking rules — which are what the tutor calls the **AI
  marking agreement** (AV-110, AV-111).
- **Readiness** is one tab for both the class view and the setup behind it; **Reports** is its
  own tab (AV-112).
- **Students** is grouped by class: invite, remove, open a record, move between classes, link a
  parent (AV-114).
- **The student's mistake pattern** sits on their Progress tab, not in Homework (AV-121,
  superseding AV-41).

**D.1 — Inventory** — Every screen that exists today, and every screen the decision register
implies. Five of the tutor's tabs already exist as pages — `LibraryPage`, `MocksPage`,
`PastPapersPage`, `GroupsPage`, `TodayDashboard` — and `GradeBoundariesPage`,
`SyllabusUploadPage`, `PreferencesPage`, `ClassReadinessPage` exist as routes outside the nav.
**Confirm each against 0.0 before designing it as new.**

Genuinely new, at minimum: onboarding (11 steps) · the teaching-plan schedule with editing,
acceptance and re-plan · chapter tree editing · the mistake-categories editor · the mistake
revision surface · the custom-criteria builder · the weak-threshold setting · attendance capture ·
three weekly-send surfaces · typed-answer input · the timed-mock sitting screen · booklet upload
and paper-picking · the Students tab · the parent's four tabs · the tutor usage view.

**D.2 / D.3 — Design** — Output goes into `docs/experience-design.md`, extending the document
that already governs this product rather than starting a competing one. For each screen: what it
shows, what it does when there is no data, what a tutor/student/parent can do from it, and how it
connects to the screens either side.

**D.4 — States and copy** — `docs/experience-implementation-plan.md` already demonstrates the
standard: every state a surface can be in, and the exact words it says in each. Match it.
**Absent data is shown as absent** — "not enough data yet", never `0` or an empty bar
(`PROD-2`, `UX-19`). **Self-declared data is labelled as self-declared** (`PROD-8`, `UX-20`), and
so is anything a tutor hand-scored (AV-34).

---

### Phase 1 — Scale foundation *(AV-82)*

**Runs after Phase 0, not alongside it** — 0.6's rename and 1.2's object storage both rewrite
`services/storage.py`. These are the two pieces that get materially harder to retrofit, plus the
prerequisites for a second API instance. Everything built after this is written for a
multi-instance world.

> **Deployment stays single-instance until Phase 11 (AV-85).** Phase 1 makes scaling out
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

**Security acceptance criteria — threat review F3** *(AV-95, E21)*

**Serving splits by sensitivity. This is not an optimisation to simplify away.**

- **Student submissions proxy through the API**, running the same ownership check they run today
  (`_tutor_owns()` / `_enrolled_scope`) on **every view**. Revocation stays instant. These files
  are photographs of a named minor's marked work; a signed URL is a bearer credential that can be
  forwarded, screenshotted or logged, and cannot be revoked before it expires.
- **Tutor material** — mark schemes, classifieds, syllabus documents, teaching guidance — mints a
  short-lived signed URL. These are the megabytes and they carry no personal data.
- Signed URLs are minted **per request, after** the authorization check, never cached or reused.
- **Never log a signed URL.** They land in request logs by default.
- Object keys are tenant-scoped and unguessable — assert this in a test, not by convention.

**1.3 — Worker as a separate process** *(§6)*

- Split the worker out of the API's `lifespan` into its own entry point, so API and worker
  capacity scale independently.
- **Move worker liveness state into the database** (E19) — `_started_at`, `_last_loop_at`,
  `_job_started_at`, `_restart_times` in `workers/jobs.py`. The health endpoint reads the DB.
- **The claim logic already works** — `.with_for_update(skip_locked=True)` at `jobs.py:184`.
  Do not rewrite it. Add the multi-worker race test instead.
- Deployment: API service and worker service, separately scalable.

**Security acceptance criteria — threat review F7**

The worker becomes a principal with database write, AI keys, storage write and outbound email —
a broader credential set than the API, on a process with no authenticated user behind any of its
decisions. Job payloads already carry identifiers rather than objects (`BE-9`) and handlers
re-read live state, which is the right shape; the gap is that every authorization decision inside
a handler is implicit.

- **Separate credentials per service.** The worker's storage credential is write-scoped to the
  prefixes it writes; the API's cannot write where it only reads.
- **Handlers derive tenant scope from the entity they load**, never from the payload.
- **Enqueue is the trust boundary** — validate there that the enqueuing user may act on the
  identifiers being queued.

**1.4 — Shared rate limiting on Redis** *(AV-83, E18)*

Move `FixedWindowLimiter`'s counters from process memory into Redis. **Redis is for rate-limit
counters only** — Postgres stays the source of truth for all application state (E18). Failed
logins stay throttled **per identifier, not per IP** — the API sits behind a proxy where one
shared address means a global lockout (`SEC-14`).

**Security acceptance criteria — threat review F4** *(AV-97)*

Redis availability must not become an authentication dependency in either direction.

- **On Redis failure, fall back to the existing in-process counter and raise an alarm.** Logins
  are never blocked wholesale (a self-inflicted outage an attacker could trigger by degrading
  Redis) and never left uncounted (a free credential-stuffing window). Throttling degrades from
  global to per-instance, which is exactly today's behaviour.
- The fallback path needs its own test and its own alert. A silent fallback is the same as no
  fallback.
- Namespace keys by purpose and tenant so one caller cannot consume or collide with another's
  counter.

**1.5 — Two-instance correctness suite** *(AV-84, §14)*

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

**2.1 — `Chapter`** *(AV-9, E1)* — `Chapter` in `models/syllabus.py`: `id`, `subject_id`, `code`,
`title`, `position`, `weight`. Add `chapter_id` to `Topic`. Migration uses
`batch_alter_table(..., naming_convention=NAMING)` and names the FK explicitly (`DB-17`);
declare the index in the model as well as the migration (`DB-12`). Re-export (`BE-3`). No
production data, so the migration may be destructive.

**2.2 — Tutor-owned subjects** *(AV-6, AV-7, AV-8, E14)* — Add `organization_id` (`PROD-3`, `DB-2`)
and a `level` enum (`igcse` / `o_level` / `a_level`, `native_enum=False`). Unique constraint
becomes `(organization_id, exam_board, code)`. **Every subject query filters by the
authenticated user's organization** (`PROD-4`, `SEC-7`); student-visible material stays scoped by
*(organization, subject)* (`SEC-8`) — `_enrolled_scope` in `api/past_papers.py` is the reference.
Delete `seed/syllabus/*.json`; `seed/demo.py` creates its own subject. Tests: another
organization's subject returns **`404`, not `403`** (`API-7`, `SEC-9`, `QA-12`).

**2.3 — Syllabus extraction produces chapters** *(AV-9, AV-10)* — `SyllabusUpload.draft` becomes
chapter-first: `{..., chapters: [{code, title, topics: [...]}]}`. Update `SYLLABUS` in
`services/prompts.py` and **bump its version** (`AI-6`, `AI-7`). Update the review UI to edit
two levels. Drop `grade_boundaries` from the draft — 2.4 makes them tutor-entered.

**2.4 — Grade boundaries** *(AV-11)* — **The writer already exists**: `api/grade_boundaries.py`,
107 lines, shipped as PR 26. Check whether a frontend editor exists before building one (0.0).

Make the org-scoped `grade_boundaries` table the **only** source; remove the read of
`Subject.grade_boundaries`.
`predict_grade()` maps through tutor-entered boundaries — **no model ever produces a grade**
(`PROD-6`). No boundaries means no predicted grade, never a fabricated one (`PROD-2`).

**2.5 — Teaching guidance upload** *(AV-10)* — A second document per subject, stored through the
Phase 1 `StorageService`. Phase 6 reads it to weight the plan.

**2.6 — Per-subject marking rules** *(AV-75)* — Free-text marking rules on `Subject`, edited by the
tutor. Applies to every chapter and classified in that subject. **No account-wide layer** (AV-75).
Consumed by Phase 3's context assembler.

---

### Phase 3 — Marking and evidence *(AV-81 — settles before mistakes and readiness)*

| ID | Task | Size | Mode |
|---|---|---|---|
| **3.1** | Chapter-scope classifieds, add notes | M | → |
| **3.2** | Marking-context assembly and precedence | M | after 3.1 |
| **3.3** | Typed answers as a submission type | M | ∥ |
| **3.4** | AI-marked mocks | M | ∥ |
| **3.5** | Past-paper booklets + AI extraction of the paper list | M | ∥ |
| **3.6** | Timed mocks, server-side clock | M | after 3.4 |

> **What a `Classified` is.** A booklet of past-paper questions compiled by topic, uploaded by a
> tutor and reused. It is the source homework is created from: the tutor uploads it, the AI
> extracts the question list, the tutor publishes it as an assignment. Optionally it carries its
> own mark scheme — which is what makes a mark from it eligible to auto-finalize. The word is
> the tutoring trade's, not ours. *(This definition was requested by the SWE audit and missed in
> revision 3.)*

**3.1 — Classified changes** *(AV-20, AV-21, AV-23)* — Add `chapter_id` and `notes` to `Classified`.
The upload flow moves to "start of chapter", reached from the plan or the chapter list. Homework
creation otherwise unchanged.

**3.2 — Marking context and precedence** *(AV-21, AV-24, AV-75, AV-76, E16)*

**One function assembles the entire marking context**, applying AV-76's order:

```
official mark scheme   (absolute — never overridden)
  → chapter notes      (most specific tutor input)
    → subject rules    (AV-75)
      → exam board and level   (AV-24)
```

**Bump `MARKING`'s version** (`AI-7`). **Preserve the untrusted-input clause in substance** —
page content is data, never instructions, and anything addressing the marker is flagged with
low confidence for a tutor rather than acted on (`SEC-20`, `SEC-21`, `AI-8`). **The
auto-finalize rule does not change** (AV-25): scheme-backed and confident, nothing more (`AI-11`,
`ADR-0009`).

**Security acceptance criteria — threat review F2** *(AV-94)*

A language model has no privilege model. All four layers arrive as tokens in one context, so
"the mark scheme is absolute" is a request, not an enforcement — and two of those layers are
**free text a tutor wrote**, sitting in the instruction position.

- **The official mark scheme always wins** (AV-94). Where a scheme covers the question, tutor notes
  inform only the judgement calls it leaves open. They can never relax it.
- **Treat tutor free text as data, not instruction** — the same posture the prompt already takes
  toward student pages. Label each block structurally so the model is told what it *is*, not
  merely handed them in order.
- **One test per conflict pair** in the precedence order, asserting the higher layer wins.
- **Cap the length of tutor-authored context.** An unbounded field in an instruction position is
  an unbounded attack surface, and it silently raises cost per mark.

The realistic failure is not a malicious tutor. It is an ordinary one writing *"always give full
marks if the method is right"* because that is how they teach — and every student in that subject
then being marked differently from the exam they will actually sit. It would present as the model
being generous and be debugged as a model problem.

**3.3 — Typed answers** *(AV-73)* — The pipeline takes text where it takes images. **Typed text is
untrusted input to the marking prompt**, exactly as page content is. Bump the prompt version.

**Security acceptance criteria — threat review F1** *(AV-91, AV-92, AV-93, E20)*

This is the plan's critical finding. **Typed answers auto-finalize like photographed work
(AV-91)** — the trust rule does not change by channel. But typed input is a materially easier
injection channel than handwriting: perfect fidelity, arbitrary length, and marks come back
afterwards, so a student can refine an attempt across submissions.

- **A deterministic scan runs before the marking call** (AV-93). A pure function over the submitted
  text (E20) returning a boolean and the matched reason; a hit sets `needs_review` for that one
  submission and the AI's confidence is not consulted. It is crude and bypassable — and it is
  **the only control in this path that does not depend on the model's own judgement about the
  attacker's text.** Do not replace it with a model call.
- **No feedback while a student is still working** (AV-92). Marks and feedback appear only after
  submission. Do not build an in-progress feedback surface.
- **Preserve the untrusted-input clause in substance** when bumping the prompt (`SEC-20`,
  `SEC-21`, `AI-8`).

**Known and accepted:** a second AI call to detect injection, a mark-value cap on auto-finalize,
and calibration metrics were all offered and **declined**. Declining calibration means there is
no way to detect this being exploited. That is a deliberate position, not an oversight — **do not
add these back without asking.**

**3.5 — Past-paper booklets** *(AV-117)* — Today `PastPaper` is one paper. Add a **booklet**: one
uploaded file holding many papers.

On upload, an AI job extracts the list — session label, paper number, code, page range — and the
tutor reviews and corrects it before it is applied, exactly as `SyllabusUpload` already works for
syllabuses. **Reuse that draft-then-review pattern**; do not invent a second one. New prompt
surface in `services/prompts.py` with a `version` (`AI-6`, `AI-7`); handler must be safe to
re-run on the same payload, replacing the draft rather than appending (`BE-6`).

When assigning, the tutor picks one paper from the extracted list. A single-paper upload skips
extraction entirely and behaves as today.

**3.6 — Timed mocks** *(AV-115, AV-116)* — A mock is assigned like homework and **timed from when
the student first opens it**. The clock is **server-side** — a client-side timer is a suggestion,
not a limit. Late submissions are **accepted and flagged, never blocked** (AV-116), so nobody loses
work; the flag is recorded and shown to the tutor.

This replaces a self-declared `timed` flag with a measured one. Past-paper attempts currently
carry `timed` and `time_taken_minutes` as **self-declared** data that must be labelled as such
wherever shown (`PROD-8`, `UX-20`). **A measured mock is not self-declared and must not carry
that label** — the two are different and the UI has to tell them apart.

**3.4 — AI-marked mocks** *(AV-26, E6)* — Through the existing pipeline. **No parallel code path**
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

**4.1 — Categories** *(AV-39)* — `MistakeCategory` becomes a tutor-owned, org-scoped table, seeded
at subject setup from a suggested list the tutor accepts, edits or replaces. `Mistake.category`
becomes an FK. **Nothing may branch on a category's value** — no `if category == "careless"`.

**4.2 — AI tagging** *(AV-37, AV-38, AV-69, E17)* — For each question where marks were lost, the AI
returns a category **from this tutor's list** (passed into the prompt) and a severity on the
existing 1–3 scale. Prompt lives only in `services/prompts.py` with a **bumped version**.
Untrusted-input clause preserved (`SEC-20`, `SEC-21`, `AI-8`). **Invariant (E17): AI mistakes are
replaced on re-run, never appended; a tutor-revised mistake is never overwritten** — the same
contract `mark_submission` honours for marks (`BE-6`, `BE-7`). Tests: drive with
`process_one_job()`, never `worker_loop()` (`QA-6`); monkeypatch the **calling module's**
`structured_complete` with `fake_ai` (`QA-7`); never call a real provider (`QA-8`).

**4.3 — Tutor revision** *(AV-38)* — Editable from the marked-work view. **No prompt, no queue, no
blocking step.** A revision is a tutor override of AI output, so it writes an append-only audit
row with no API to edit or delete it (`PROD-7`, `AI-12`) — `MarkOverrideAudit` is the pattern.

**4.4 / 4.5 — Rollups and student view** *(AV-40, AV-41)* — Aggregate per topic and per chapter on
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

**5.1 — Factor set changes** *(AV-30, AV-32)* — Remove `consistency` from `ReadinessFactor` handling,
`FACTOR_WEIGHT_ATTR`, the weights model and `readiness_factors.py`. Enum members are non-native
so no migration is forced — which is exactly why the `if`/`match` chains must be audited by hand
(`DB-6`). `homework_performance()` becomes accuracy only: delete the
`accuracy * 0.7 + completion_rate * 100 * 0.3` blend, but **keep `completion_rate` in `detail`**
so it can be shown as a fact. Surface completion separately on the profile and class view.
Punctuality appears **only in the weekly send** (AV-32).

**5.2 — Chapter rollup** *(AV-9, E7)* — One stored row per chapter per run, rolled from its topics'
scores weighted by evidence count, in `evaluate_subject_factors`. Chapter score is `None` when no
topic beneath it has evidence (`PROD-2`).

**5.3 — Delete v1** *(AV-78)* — Repoint `api/analytics.py`, `services/reports.py` and
`services/student_crm.py` to v2 snapshots; **stop the v1 writes; drop `topic_readiness`,
`readiness_history` and `tutor_preferences`** in the same change. Remove the per-subject v1
fallback and the `engine: "v1"` reporting from `/readiness/*`. **Closes `RISK-5`.** Update
`docs/governance/risk-register.md`, §01's Known Gaps table, and §06.

**5.4 — Configurable factors and custom criteria** *(AV-34, AV-35, E8)* — Three capabilities:
**re-weight** (extend `ReadinessWeights`) · **switch off** (a disabled factor is *omitted* from
the weighted set, never zero-weighted) · **add a custom criterion** — `CustomCriterion` (name,
description, weight, scope) plus `CustomCriterionScore` (student, criterion, score, updated_at,
updated_by), **hand-scored by the tutor**, no AI, no derivation. Configuration resolves **per
account with subject overrides** (AV-35) — one precedence rule, one place, tested both ways. Every
custom score is manual data and is **labelled as tutor-entered wherever shown** (`PROD-1`,
`PROD-8`, `UX-20`), reports and the parent view included.

**5.5 — Cold start** *(AV-36)* — **Already built and tested** on the parent and student screens
(PRs 21–27). Confirm what exists in 0.0 before writing anything.

What remains is making sure the reworked factor set and chapter rollup keep the same behaviour: a
score appears from the first marked piece, carrying evidence count and confidence (already
computed by `_confidence_from_count`), and "not enough data yet" still applies to a factor with
*no* evidence (`PROD-2`, `UX-19`).

**5.6 — Weak threshold and surfaces** *(AV-42, AV-43, AV-74)* — Tutor-set, captured at onboarding,
stored per account with the same subject-override precedence as 5.4. **`MASTERY_THRESHOLD = 75.0`
in `services/readiness_v2.py` is a different line** — it decides what counts as mastered for
Syllabus Coverage. Do not conflate them; comment the distinction. Student sees their weak topics
as information; tutor sees them in the class view and aggregated on home. **Nothing is generated,
assigned or suggested as work** (AV-42).

**5.7 — Past-paper gating** *(AV-31)* — `past_paper_performance` returns `NO_DATA` until the class's
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

**6.1 — Data model** *(AV-13–AV-16, AV-72, E15)* — Per class: `TeachingPlan` (group_id, exam_date,
lessons_per_week, lesson_minutes, past_paper_start_date, status `draft`/`accepted`, accepted_at,
accepted_by_id) · `PlanSlot` (plan_id, chapter_id, scheduled_date, sequence, **provenance:
`generated` / `manually_modified` / `confirmed` / `completed`**) · `PlanBreak` (plan_id,
start_date, end_date, label). **Invariant E15: a `PlanSlot` is a planned occurrence; a `Lesson`
is the confirmed actual one.** Teaching and past-paper phases **overlap by design** (AV-16) — the
model must not assume disjoint intervals.

**6.2 — Inputs** *(AV-15)* — Exam date, lessons per week, lesson length, past-paper start,
holidays and breaks. Collected in onboarding (Phase 9), editable afterwards from class settings.

**6.3 — Drafting** *(AV-14, E5)* — Two deliberately separated steps:

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

**6.4 — Accept and edit** *(AV-13)* — Draft until accepted. **Nothing reads a draft plan** — not
lesson suggestions, not the classified prompt, not the tutor home. Tutor edits any slot at any
time; an edit sets provenance `manually_modified` and does not require re-acceptance.

**6.5 — Plan → lesson** *(AV-17, E15)* — Creating a lesson pre-selects topics from the next
unstarted slot; the tutor can change them freely. **Lessons are never auto-created.** Confirming
a lesson sets that slot `confirmed`. `lesson_topics` remains the sole source of syllabus coverage
(`PROD-14`).

**6.6 — Behind schedule** *(AV-18)* — Compare confirmed lessons to scheduled slots; show the gap on
home and the class view; offer a re-plan that **recalculates and waits for acceptance**.

**6.7 — Chapter-start prompt** *(AV-20, AV-22)* — When the plan enters a chapter with no classified,
prompt on the tutor's home. **Non-blocking.**

**6.8 — Automatic reflow on syllabus edits** *(AV-68, AV-77, E13, E15)* — Adding, splitting,
reordering or removing a chapter **reflows automatically, with no acceptance step**. Runs as a
job. **Only `generated` future slots are eligible** — `manually_modified`, `confirmed` and
`completed` slots are never moved (AV-77). **This is intentionally different from 6.6**; comment
the branch point (`CODE-12`) so it is not read as a bug.

---

### Phase 7 — Attendance

| ID | Task | Size | Mode |
|---|---|---|---|
| **7.1** | Attendance model, lesson mode, in-person register | M | → |
| **7.2** | Attendance surfaces | S | after 7.1 |
| **7.3** | Zoom and Google Meet attendance integration | L | after 7.1 |
| **7.4** | Lesson pre-fill and the 15-minute reminder | M | after 7.1 |

**7.1 — Attendance and lesson mode** *(AV-44, AV-109, AV-118)* — `LessonAttendance` (lesson_id,
student_id, state, source, recorded_by_id, recorded_at) and a **mode on `Lesson`: in person or
online** (AV-118). In person, the tutor logs it **on the lesson, in the class's Schedule tab**
(AV-109). `source` records whether a human or an integration set it — a tutor needs to know which.

Attendance is **not** a readiness factor (AV-33). It explains gaps; it does not score them.

**7.3 — Zoom and Google Meet** *(AV-118)* — For online lessons, pull the attendance list from the
call. **Two separate integrations**, each with its own sign-in flow and its own approval from
that company.

- **Google Meet attendance reports are a paid Workspace feature.** A tutor on a free Google
  account gets nothing, silently. Say so at the point they connect it, not after.
- Both add OAuth redirect URIs, which is the constraint that pinned the deployment to one origin
  for Google Classroom (§08). Hiding Classroom (AV-58) lifts that; **this puts it back.** Plan the
  redirect URIs deliberately rather than discovering the constraint again.
- OAuth `state` is verified server-side and bound to the tutor who started the flow
  (`security.create_state_token`); the browser comparison is a second check, never the check.
- Matching a call participant to a student is fuzzy — people join as "iPad" or a nickname.
  **Unmatched participants are surfaced for the tutor, never guessed at.**

**7.4 — Lesson pre-fill and reminder** *(AV-119, AV-120)* — The plan pre-fills what the lesson covers.
**15 minutes before it starts, remind the tutor** so they can revise it — by email, phone
notification and in-app (AV-120; push comes from 8.7).

**After the lesson nothing is required** (AV-119): it counts as taught with the topics that stood,
unless the tutor says otherwise. That keeps admin near zero — and it means **a cancelled lesson
nobody flags is recorded as taught**, quietly inflating syllabus coverage, which feeds readiness.
Make cancelling one action from the reminder and from the Schedule tab.

---

### Phase 8 — Intelligence and communication

| ID | Task | Size | Mode |
|---|---|---|---|
| **8.1** | Email infrastructure | M | → |
| **8.2** | Weekly send generator (three variants) | L | ∥ |
| **8.3** | Merge the narrative into one writer with the weekly send | M | after 8.2 |
| **8.4** | Weekly send on each role's home | M | after 8.2 |
| **8.5** | Transactional email triggers | M | after 8.1 |
| **8.6** | Tutor reports | M | ∥ |
| **8.7** | Web push notifications | M | after 8.1 |

**8.1 — Email** *(AV-54, E9)* — One provider module in `services/`, all templates in one place,
unsubscribe and bounce handling. Configuration through `get_settings()`, never `os.environ`
(`BE-15`). A missing key degrades email with a clear message and never blocks startup (`INF-9`).

**8.2 — Weekly send** *(AV-49, AV-50, AV-62–AV-66)* — **Fixed facts plus one AI paragraph.** Facts are
computed deterministically; the AI writes a short steer and **must never restate a number the
facts do not contain** (`PROD-1`). Generated by a **sweep**, not a self-perpetuating chain — the
comment in `services/narrative.py` explains exactly why, and **that reasoning must be carried
into the replacement, not deleted with it** (`CODE-13`).

Three variants:
- **Tutor** — across their classes. Punctuality appears here and nowhere else (AV-32).
- **Student** — their own week.
- **Parent** — *is the parent report* (AV-63): readiness and predicted grade · attendance and
  homework record, plus the AI paragraph. **Not** the chapter/topic breakdown, **not** mistake
  patterns (AV-64). One weekly artifact for a parent, never two.

**Sends automatically to all three roles** (AV-62, AV-65); the tutor reads but does not gate it. The
AI paragraph is written **in the tutor's chosen language** (AV-66).

**The AI paragraph comes from the merged narrative writer, not a second generator** (AV-99, 8.3).
Build the fact computation here; take the prose from there. Do not build a parallel writer —
that is precisely the duplication 8.3 exists to prevent.

**Timing:** on the account's chosen day (AV-88, AV-89), fired on **the tutor's clock** — one batch,
one moment, regardless of what time zone a student or parent has set for themselves (AV-90). This
is the one place a recipient's own time zone is deliberately ignored; say so in a comment
(`CODE-12`) beside the scheduling code, which otherwise converts per viewer (E11).

**Security acceptance criteria — threat review F9**

**The fact set is numeric and enumerable values only** — scores, counts, dates, category names,
states. **Never free text derived from a student's submission**, which means no feedback text and
no mistake notes, however natural they look as inputs.

Including them would put student-controlled text inside a prompt whose output is emailed to a
parent, with the marking-path defences applying only at the first hop. This is not currently a
live path — `services/reports.py` does not consume feedback text — and this criterion exists to
keep it that way.

**8.3 — Merge the narrative and the weekly send into one writer** *(AV-98, AV-99, E24)*

**The narrative is kept.** Revision 2 deleted it; that is reversed. It is 814 backend lines plus
four screens, built three weeks ago as PRs 13–15, and it does something the weekly send does not:
it is **always on screen and updates whenever new marks land**, where the weekly send is a
scheduled artifact.

Left alone they overlap badly. The parent narrative already refreshes weekly on a sweep, and the
parent's weekly report is also weekly — so a parent would receive two AI-written texts about
their child on the same schedule, from two systems that can disagree, and you would pay for both.

**One writer produces both** (AV-99). Keep `services/narrative.py`'s existing shape (E24): a
background job writes the text, surfaces read the stored row. The weekly send reads those same
rows rather than generating its own.

- **Do not delete** `services/narrative.py`, `models/narrative.py`, `api/narrative.py`, or the
  surfaces reading them — `ClassNarrative.tsx`, `TodayDashboard.tsx`, `ClassOverview.tsx`,
  `ParentDashboard.tsx`, `api/narrative.ts`.
- **The sweep-not-a-chain reasoning in `services/narrative.py` must survive the merge**
  (`CODE-13`). It explains why the parent refresh re-derives who is due from the table every run
  rather than each job scheduling the next: the worker marks a job failed at `MAX_ATTEMPTS` with
  nothing watching it, so a chain would end a parent's updates permanently and silently after one
  transient outage. That is a hard-won comment — do not delete it with the code around it.
- `narrative_sweep_interval_hours` in `config.py` stays and governs the merged writer.
- One voice, one AI cost per student per cycle, and no way for the screen and the email to
  contradict each other about the same child.

**8.4 — Home surfaces** *(AV-51)* — Each role's home shows their latest weekly send.

**8.5 — Transactional triggers** *(AV-54, AV-61)* — Homework set · homework due · marked work ready ·
account and invite emails. **Students and parents join by invite link sent to an address the
tutor supplies** (AV-61). Invites stay bounded — 14-day expiry, parent-link codes single-use
because one exposes a named child's entire record; mint with `build_invite()`, validate with
`check_usable()` (`SEC-12`, `SEC-13`). **Anything invalidating a credential bumps
`users.token_version`** (`SEC-1`, `ADR-0008`) — a password-reset flow must, or an old refresh
token keeps minting access tokens for 30 days. Scheduling reads the recipient's time zone (0.7).

**Security acceptance criteria — threat review F5** *(AV-96)*

**The tutor confirms a parent's address before the first send.** The address is typed by hand,
and every weekly send afterwards carries a named child's readiness, predicted grade and
attendance. A typo delivers that record to a stranger, every week, until someone notices — and a
valid-but-wrong address never bounces.

- Show the address back and require explicit confirmation before anything is sent to it.
- Hard-suppress on bounce or complaint, and surface it to the tutor.
- Changing a parent's address re-triggers confirmation.
- No PII in the invite URL itself; keep `SEC-12`'s bounds — 14-day expiry, parent-link codes
  single-use, because **one exposes a named child's entire record** (`SEC-13`).

**8.6 — Tutor reports** *(AV-53, AV-112)* — Chapter and topic breakdown · mistake patterns · plan
progress and countdown · attendance. On demand **and** weekly. **This is the tutor's report**;
the parent's is a different document produced by 8.2 — neither is built by filtering the other.
Reports get their own top-level tab (AV-112).

**8.7 — Web push notifications** *(AV-120)* — Notification infrastructure does not exist today.
Build it: service worker, subscription storage per user, and the send path, wired to the same
provider module as email (E9).

Delivers the 15-minute lesson reminder (7.4) and any other trigger the tutor opts into. **Web
push does not work on iPhone unless the user has added Avora to their home screen** — that is
the constraint the mobile app in Phase 12 exists to solve. Until then, iPhone users get email and
in-app.

**Per-channel opt-out is required**, not optional: a tutor who wants the lesson reminder on their
phone but the weekly summary by email must be able to say so.

---

### Phase 9 — Onboarding and tutor home

| ID | Task | Size | Mode |
|---|---|---|---|
| **9.1** | Blocking onboarding flow | L | → |
| **9.2** | Tutor home rework | M | ∥ |

**9.1 — Onboarding** *(AV-56, AV-60, AV-66, AV-67, AV-74)* — Step-by-step, in this order:

1. Language, time zone, and weekly send day — the last pre-filled with a default (AV-66, AV-67, AV-89)
2. Subject — exam board and level (AV-6, AV-7)
3. Syllabus upload, then review the chapter/topic tree (AV-9, AV-10)
4. Teaching guidance upload (AV-10)
5. Grade boundaries (AV-11)
6. Per-subject marking rules — **offered, skippable** (AV-75, AV-87)
7. Mistake categories — accept, edit or replace the suggested list (AV-39)
8. Weak-topic threshold (AV-74)
9. Class — one subject (AV-72)
10. Exam date, lessons per week and length, past-paper start, holidays (AV-15)
11. **Accept the teaching plan** — the finish line (AV-60)

**Adding students is optional and sits outside the flow** (AV-60). Server-side state, resumable,
**not skippable** up to step 11. A frontend gate is never an authorization control (`SEC-10`).

**9.2 — Tutor home** *(AV-47, AV-48, AV-101)* — **This is a rework, not a build.** The aggregate already
exists: `services/today.py` (322 lines) and `api/today.py`, shipped as PRs 17–18, with
exceptions-first ordering in `_STATUS_ORDER`. Extend it; do not replace it.

Compact overview: work awaiting review · plan progress per class · upload prompts · weak topics
across classes. Plus **one piece of good news: the marking the AI handled for them.** Nothing
else is framed as good news — the rest lives in the class and module screens.

**The good-news figure, precisely** (AV-101): the **count is real** and traceable to the rows that
produced it — auto-finalized marks in the period. The **time is an estimate and is labelled as
one**: *"47 questions marked — roughly 3 hours of marking."* `PROD-1` requires every number to
trace to what produced it, and an unlabelled time saving does not. This is the most-viewed screen
in the product. **The word "roughly" is load-bearing — do not drop it, and never present the
estimate as a measurement.**

---

### Phase 10 — Usage and sell-readiness

| ID | Task | Size | Mode |
|---|---|---|---|
| **10.1** | Usage rollups | M | → |
| **10.2** | Tutor's own usage view | S | after 10.1 |
| **10.3** | Owner internal usage tool | M | after 10.1 |
| **10.4** | Account deletion and data export | L | ∥ |

**10.1 / 10.2** *(AV-2)* — Roll up per account: AI spend (`ai_usage_events` already meters every
call), students and classes, storage used, activity. **Never invent a price** —
`AI_MODEL_PRICING` is empty by default, and a model with no entry records `cost_usd = NULL` and
reports as `unpriced_call_count`, never `$0` (`AI-17`).

**10.3 — Owner tool** *(AV-3, AV-71, E12)* — **A separate internal tool, not a route in the API.**
Keeping it outside the FastAPI app is the point: `PROD-4`/`SEC-7` stays true without exception
inside the product. **Do not build it by relaxing an existing scoping helper.** Record the
boundary in an ADR.

**10.4 — Deletion and export** *(AV-70)* — Deletion covers every table plus object storage, in
FK-safe order, **verified by a test asserting nothing survives** — not by inspection. Export
produces a readable archive of students, marks, reports and readiness history.

**Security acceptance criteria — threat review F6** *(E22)*

Export returns the entire tenant in one call, which makes it an exfiltration primitive reachable
from a single stolen session — and refresh tokens live 30 days.

- **Re-authenticate immediately before the action**, independent of session age. Applies to
  deletion too, which is the destructive twin of the same primitive.
- **Deliver out of band** — a link to the account's verified address — rather than in the
  response body, so the account holder learns it happened.
- Write an audit row, notify the account, and rate limit hard.
- Deletion must clear **object storage**, not only database rows, and should reach the log
  aggregator (see 11.4).

---

### Phase 11 — Scale hardening *(AV-82 — "the rest")*

| ID | Task | Size | Mode |
|---|---|---|---|
| **11.1** | Statelessness audit and remediation | M | ∥ |
| **11.2** | Concurrency audit | L | → |
| **11.3** | Database constraints for enforceable invariants | M | after 11.2 |
| **11.4** | Structured logging and metrics | M | ∥ |
| **11.5** | Dead-letter visibility and alerting | S | ∥ |
| **11.6** | Load test at 1,000 students | L | last |

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
an alert. The Redis fallback path from 1.4 alarms here too (AV-97).

**Security acceptance criteria — threat review F10**

Organization, user, student and submission IDs across a distributed system are a re-identifiable
personal-data store once aggregated, even with content correctly excluded.

- Access-control the aggregator as production data, because it is.
- Include it in the Phase 10 deletion path — an account that exercises deletion should not remain
  fully reconstructable from logs.
- **Retention period is a deliberately deferred decision.** It is a cost, forensics and privacy
  trade-off that cannot be made sensibly before there is traffic. **Raise it; do not pick a
  number.**

**11.6 — Load test at 1,000 students** *(AV-84, AV-86)* — **The last task in the plan**, run against
the finished product so the numbers reflect what you will actually operate. One realistic run.

**Sized `L`, not `M`.** Most of the work is not the run — it is generating 1,000 students with a
year of realistic classes, homework, marks, evidence and readiness. Testing an empty database
teaches you nothing. Expect the fixture generator to be the bulk of this task, and build it on
top of `seed/demo.py` rather than beside it.
Measure p50/p95/p99 latency, error rate, database utilisation, queue latency, worker throughput.
**Identify the first bottleneck and fix that** — do not pre-optimise everything. The 5,000 and
10,000 tiers are deferred until real traffic justifies them.

> **11.2 is the gate on scaling out (AV-85).** Until the concurrency audit is complete, the
> deployment stays on one instance regardless of what Phase 1 made possible.

---

### Phase 12 — The mobile app *(AV-122)*

**The last phase, after everything else is finished.** It is built against a settled product, not
a moving one.

| ID | Task | Size | Mode |
|---|---|---|---|
| **12.1** | App shell, auth and push registration | L | → |
| **12.2** | Tutor quick actions | M | after 12.1 |
| **12.3** | Student quick actions | M | after 12.1 |
| **12.4** | Parent view | S | after 12.1 |
| **12.5** | Store submission and release process | M | last |

**Scope is deliberately narrow** (AV-122): **notifications and quick actions only — not a second
copy of the product.** Anything not on the list below opens the web app in a browser. Hold this
line: the moment the app grows a screen the web app also has, every future change has to be made
twice, forever, and this phase stops being a phase.

- **Tutor**: receive notifications · the 15-minute lesson reminder with one-tap revise or cancel ·
  glance at the review queue · confirm a lesson and take the register.
- **Student**: homework and mock reminders · photograph and submit work — the phone is already
  where that happens · see what is due.
- **Parent**: the weekly send, delivered to their phone rather than their inbox.

**iOS and Android from one shared codebase** (AV-122). Reuse the existing API — the app is another
client of the same endpoints, and `api/client.ts`'s contract (bearer token, one transparent
refresh on `401`) is the model to follow. **The refresh token still never goes anywhere
script-readable** (`SEC-2`); on a phone that means the platform keychain, not local storage.

**12.5 — Store submission.** Two review processes, two release cycles that do not match your web
deploys, and a rejection is a schedule risk you do not control. Budget for it. **The web app must
never depend on an app release** — anything the app can do, the web can do too.

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
| 0 | Every task is annotated with what already exists (0.0); auto-finalized homework moves Topic Mastery and counts as submitted; the recompute runner regenerates every snapshot; the type checker and generated API types run in CI; the AI price table returns money, not `unpriced_call_count` |
| D | Every screen in the product — new and existing — has a spec covering what it shows, its empty state and its copy, in `docs/experience-design.md`. Palette and type unchanged |
| 1 | Two APIs and two workers run together: upload via #1 and read via #2, one shared rate limit, one marking operation per submission, one email per send, safe worker restart |
| 2 | A tutor creates a subject from their own syllabus upload and sees chapters containing topics; another tutor gets `404` |
| 3 | Marking receives mark scheme, chapter notes, subject rules, board and level in that precedence; a typed answer marks as safely as a photographed one; a mock becomes evidence |
| 4 | Marking produces mistakes in the tutor's own categories; a tutor revision writes an audit row and survives a re-run |
| 5 | No consistency factor; homework score is accuracy-only; chapters carry scores; **no v1 table exists and every surface agrees** |
| 6 | Onboarding inputs produce a draft plan; accepting it makes lesson suggestions live; skipped lessons flag behind-schedule; a syllabus edit reflows generated slots and leaves hand-edited ones untouched |
| 7 | Attendance recorded at lesson confirmation appears for tutor, student, parent and in reports |
| 8 | Three different weekly artifacts generate and send, on home and by email, in the tutor's language — **all from one writer**, with the on-screen paragraph and the emailed text unable to disagree |
| 9 | A brand-new tutor completes onboarding in one pass, with no students, and lands on a home page with a plan, prompts and the marking figure |
| 10 | Usage rolls up per account; the owner tool reads across accounts and **no API route does**; an account deletes completely and exports readably |
| 11 | Concurrency hotspots hold under racing workers; failed jobs raise an alert; the load test names the first bottleneck |
| 12 | The app receives a lesson reminder and a student submits a photograph from it; every other route opens the web app; the web product works fully with the app uninstalled |

**Whole-plan acceptance:** a new tutor signs up, completes onboarding, accepts a teaching plan,
teaches a lesson from it, uploads a chapter classified, sets homework, has it auto-marked with
mistakes tagged, sees readiness and weak topics move, receives a weekly send by email, and
generates a report — on a two-instance deployment, without an engineer touching anything.

---

## 9. Out of scope

- **WhatsApp integration** (AV-55) — future scope.
- **Payment and plan limits** (AV-2) — usage tracking only.
- **Multi-tutor accounts** (AV-1) — solo tutor; the tenant model supports more later (E14).
- **Generated or auto-assigned practice** (AV-42) — weak topics are shown, never acted on.
- **The GitHub repository rename** (E10) — manual, for the owner.
- **A translated UI** (AV-66) — only AI-written prose follows the tutor's language.
- **Monthly intelligence** — weekly only (AV-49).
- **Multi-subject classes** (AV-72).
- **Load testing at 5,000 and 10,000 students** (AV-84) — deferred until traffic justifies it.
- **Redis for anything but rate limiting** (E18).

## 10. Known risks carried

| Risk | State after this plan |
|---|---|
| `RISK-1` — API pinned to one instance | **Capability delivered in Phase 1; risk closed at 11.2.** Phase 1 removes the three named causes — the uploads disk, the in-process worker, the in-process rate limiter — but the deployment deliberately stays single-instance until the concurrency audit completes (AV-85). Until then the risk is *unrealised*, not gone. |
| `RISK-5` — two readiness engines disagree | **Closed.** AV-78 deletes v1 outright rather than keeping it written. |
| `RISK-6` — frontend/backend contract drift | **Closed.** Task 0.8 generates TypeScript types from the backend's own schema. |
| No Python type checker | **Closed.** Task 0.8 introduces one at service boundaries. |
| `RISK-3` — a migration correct on SQLite, wrong on Postgres | **Unchanged and more exposed.** This plan adds many migrations and, in 11.3, many constraints. The suite still never runs a migration; CI's Postgres job remains the only check. |
| **Prompt injection reaching an auto-finalized mark** (threat review F1) | **Mitigated, not closed, by decision.** AV-93's deterministic scan is the only control that does not depend on model judgement. A second AI check, a mark-value cap and calibration metrics were offered and declined — so there is **no detection layer**. Accepted position; revisit if remark volume or tutor overrides ever suggest it is being exploited. |
| **No AI evaluation harness** | **Open and growing.** This plan bumps five prompt versions — `SYLLABUS`, `MARKING` twice, mistake tagging, plan weighting, weekly paragraph — with nothing measuring whether output got better or worse. §09 already records the absence of calibration on the trust rule as a known gap; this plan widens the surface without addressing it. |
| **Children's-data regulatory posture** | **Not addressed anywhere.** The data subjects are minors. Task 10.4 (deletion and export) and AV-96 (confirmed recipient) are the start of that work, not the end. Lawful basis, retention and consent have no owner in this plan. |
