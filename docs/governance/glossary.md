# Glossary

> **Governance layer.** Domain and system terminology, defined once.
>
> **Status:** Active · Part of Engineering Constitution v1.2
>
> **Binding:** `GOV-6` — terminology defined here is used with this meaning throughout the
> constitution. A document needing a different meaning defines a different term.

Several of these words have a loose everyday meaning and a precise Avora meaning, and the
two are not the same. *Assessment* is a table, not "any evaluation". *Snapshot* is a
readiness row, not a database backup. *Classified* is a document, not a security level.
Where a term maps to a table or a symbol, that is given, because the definition and the code
must not drift apart.

---

## Product and domain

**Assessment** — A tutor-entered examination event: a quiz, topic test, or mock. Table
`assessments`, with per-topic scores in `assessment_scores`, typed by `AssessmentType`.
*Not* a general word for evaluation, and *not* the Assessment Performance readiness factor,
which is computed from these rows.

**Classified** — A topic-organized compilation of past-paper questions, with structures that
vary by tutor. The main practice source for most of the academic year. Table `classifieds`.
**Distinct from a past paper** — see *Past paper*. Nothing to do with confidentiality.

**Classroom** — Google Classroom, an optional import source. Never "a class in Avora";
that is a *Group*.

**CRM** — Student CRM: the student's complete, continuously-updating academic record.
Aggregated by `services/student_crm.py`, which serves both the UI and AI grounding. Backing
tables: `student_profiles`, `student_subjects`, `tutor_notes`, `parent_communications`.

**Evidence** — A single scored observation about one student on one topic, from one source,
at one time. Table `evidence`. **Only finalized outcomes become evidence** — nothing
provisional. Written exclusively by `services/evidence.py`. The atomic input to readiness.

**Evidence source** — What produced a piece of evidence: `past_paper`, `mock`, `homework`,
`quiz`, `observation`, or `tutor_estimate` (`EvidenceSource`). Each carries a weight in
`readiness.SOURCE_WEIGHTS`. `tutor_estimate` is the only one that is not a mark on a piece
of work: it is self-declared, labelled as such wherever shown (`PROD-8`), and loses weight
as marked evidence arrives.

**Factor** — One of the six dimensions Readiness v2 scores independently: Topic Mastery,
Past Paper Performance, Homework Performance, Assessment Performance, Syllabus Coverage,
Mistake Analysis (`ReadinessFactor`; `consistency` is a retired member, kept only so
pre-5.1 rows load). Each produces a `factor_evaluations` row
per run.

**Evaluation run** — One complete Readiness v2 computation for one (student, subject),
identified by `evaluation_run_id` — a UUID string shared by that run's `factor_evaluations`
rows and its `readiness_snapshots` row. The unit of traceability: it is what lets a score
name its exact inputs.

**Group** — A teaching class. Table `groups`, membership in `group_members`. One-to-one
tutoring is a group of one. Lessons are group-level events.

**Homework** — Work assigned to students, optionally derived from a classified booklet.
Entity: `Assignment`. The *homework pipeline* is the sequence booklet → extraction →
publication → submission → marking → review → evidence.

**Lesson** — A dated teaching event: date, notes, topics covered, per-student observations.
Table `lessons`. **Not** the recurring timetable entry, which is a *Schedule slot* — the two
were both once called `Lesson`, and the rename is a common source of confusion in older code
and documents.

**Mastery** — Solid performance across difficulty tiers on a topic, not mere familiarity.
Topic Mastery buckets question-level marks by `QuestionDifficulty` and requires performance
across tiers. Distinct from a raw topic score.

**Mistake** — A tagged error on a mark: one **mistake category** (a word the tutor owns, not
a fixed enum — see *Mistake vocabulary* below), with severity 1–3 and an optional `note`.
Table `mistakes`. Written either by the tagging job or by a tutor, told apart by **mistake
source**. Recurring mistakes reduce readiness.

**Observation** — A tutor's recorded judgement about a student, optionally topic-scoped,
usually captured on a lesson. Becomes evidence with source `observation` — the
lowest-weighted source, because it is subjective.

**Organization** — The tenant boundary. Auto-created per tutor at signup; students and
parents inherit their creating tutor's organization. Table `organizations`. Every top-level
aggregate carries `organization_id`.

**Parent link** — The single-use association between a parent account and a student. Table
`parent_links`, established by a single-use invite because it exposes a named child's entire
record.

**Past paper** — A complete examination paper, sat as a whole. Table `past_papers`, with
`past_paper_questions` and the roll-up `past_paper_attempts`. **Distinct from a classified**:
a past paper feeds the Past Paper Performance factor *and* Topic Mastery; a classified feeds
Topic Mastery and Homework Performance.

**Predicted grade** — A grade computed deterministically from a readiness score and the
subject's ordered grade boundaries, by `predict_grade()` in `services/grades.py`. **Never
produced by a model.**

**Readiness** — How prepared a student is for their examination in a subject, expressed as a
percentage with a confidence level. The product's central metric. Ambiguous on its own:
qualify it as *readiness score*, *topic readiness*, or *subject readiness* where the
distinction matters.

**Readiness v1 / v2** — Two engines that both exist today. **v1**: `services/readiness.py`,
deterministic, writing `topic_readiness` and `readiness_history`. **v2**: a deterministic
Layer 1 (`readiness_factors.py`, `readiness_v2.py`) producing `factor_evaluations`, plus an
AI Layer 2 (`readiness_v2_ai.py`) producing `readiness_snapshots`. The `/readiness/*`
endpoints serve v2 and fall back per-subject to v1. See §01.

**Remark request** — A student's contest of a finalized mark. Table `remark_requests`, one
per question ever, enforced by a unique constraint. Never resolved by AI.

**Schedule slot** — A recurring timetable entry on a group: weekday plus time. Table
`schedule_slots`. Formerly called `Lesson`. A `Lesson` may be created from a slot or ad hoc.

**Snapshot** — A `readiness_snapshots` row: the outcome of one evaluation run for one
(student, subject) — score, predicted grade, weak topics, rationale, revision plan, and
`status` (`ready` or `failed`). **A snapshot row exists only once a run finishes**, which is
why "is updating" is derived from the `jobs` table and not from a snapshot column. Nothing
to do with database backups.

**Submission** — A student's submitted work. Table `submissions`. **Polymorphic**: exactly
one of `assignment_id` or `past_paper_id` is set. Never read `assignment_id`
unconditionally.

**Subject** — A curriculum subject for one exam board, with its own topic tree. "CIE Maths"
and "Edexcel Maths" are separate subjects. Table `subjects`; exam board is a property of the
subject, not of the student. Subjects are **global**, shared across organizations — which is
why scoping by subject alone leaks data across tenants.

**Syllabus** — The topic tree for a subject. Table `topics`. Five are built in; more can be
added by AI extraction from an uploaded document (`syllabus_uploads`).

**Topic** — A node in a subject's syllabus tree, and the unit at which mastery and evidence
are recorded.

## Teaching plan

**Teaching plan** — What a tutor intends to teach one class, and when: a `teaching_plans` row
with `plan_slots` and `plan_breaks`. Belongs to a class (*Group*), whose single subject supplies
its chapters. Tutor-only. See §01, §06.

**Plan slot** — One *planned* lesson occurrence: a chapter on a date, in an order. Table
`plan_slots`. **Never a Lesson** — a *Lesson* is the confirmed, actual one (`E15`); a slot that
gets taught keeps its own row and gains a `lesson_id`. `lesson_id IS NULL` means not taught.

**Provenance** — Who last decided a plan slot, `PlanSlotProvenance`: `generated` (the system
laid it, and may move it), `manually_modified` (the tutor moved or changed it, or freed it from a
deleted lesson; the system leaves it alone), `confirmed` (a lesson claimed it), `completed`
(taught). Only `generated` slots are ever moved by a machine (AV-77).

**Draft / accepted / stale** — A plan's `status` is `draft` or `accepted`; a class has at most one
of each. Nothing reads a draft; accepting is what makes a plan live. **Stale** is not a status:
it is `draft_result.status` after the inputs or breaks changed since the last drafting run, and a
stale draft cannot be accepted.

**Draft result** — `teaching_plans.draft_result`: what the last drafting run did and why (weights,
reasons, AI used or degraded, failure). NULL means never drafted.

**Reflow** — The automatic re-laying of a plan's future `generated` slots when a subject's
chapters change (6.8, AV-68, E13). No acceptance step, no AI call. Job `reflow_plan`. *Not* a
re-plan.

**Re-plan** — A tutor's one-click request, for a class that is behind, to draft a fresh plan from
today beside the live one (6.6, AV-18). Waits for the tutor to accept it. *Not* a reflow.

**Not recorded** — The honest word for a planned lesson dated before today with no lesson against
it. It may have been taught and never logged, so Avora never says "missed" (`PROD-2`).

---

## Marking and trust

**Auto-finalized** — A mark accepted with no tutor action, or a submission in which every
mark was. Requires the mark to be both scheme-backed (`has_mark_scheme`) **and** confident
(`high` or `medium`). Submission status `auto_finalized`.

**Confidence (marking)** — The model's stated certainty about a mark: `high`, `medium`,
`low`, or `unsure` (`MarkConfidence`). **The safety mechanism**: it is what decides whether a
mark counts without a human. Distinct from *confidence (readiness)*.

**Confidence (readiness)** — How much recent, decay-weighted evidence backs a score:
`none`, `low`, `medium`, `high` (`ReadinessConfidence`). Distinct from *confidence
(marking)*.

**Finalized** — A mark or submission signed off by a tutor. Distinct from *auto-finalized*,
which had no tutor in the loop. Only finalized and auto-finalized marks become evidence.

**Needs review** — A mark, or a submission containing one, that requires a tutor: no
official mark scheme, low confidence, a question the model skipped, or an open remark
request. Surfaced by `GET /submissions/review-queue`.

**Override** — A tutor changing a mark that had already been set. Writes an append-only
`mark_override_audit` row: old, new, who, when. There is no API to edit or delete those
rows.

**Review queue** — The tutor's work list of marks needing a decision. Lives at
`GET /submissions/review-queue`, not in the assignment list.

## AI platform

**Surface** — A named AI use case that resolves independently to a provider and model:
`marking`, `extraction`, `syllabus`, `reports`, `readiness`, `class_brief`, `narrative`.
Configured by `AI_<SURFACE>_PROVIDER` / `AI_<SURFACE>_MODEL`. **Call sites name a surface,
never a model.** The single most important vocabulary term in §09. (`chat` was a surface here
until task 0.3 deleted the student AI chat surface entirely, AV-57 — streaming, which existed
only for it, went too.)

**Prompt version** — The version stamped on a prompt in `services/prompts.py`, recorded on
every record the prompt produced (`ai_prompt_version`) and every usage event. Bumped
whenever prompt text changes meaningfully.

**Unpriced call** — An AI call whose model has no entry in `AI_MODEL_PRICING`. Records
`cost_usd = NULL` and is reported as `unpriced_call_count`. **Never folded in as `$0`.**

**Grounding** — Injecting authoritative context into a prompt: the tutor's Knowledge Base via
`build_tutor_context()`, evidence-derived facts queried directly for reports/class
brief/narrative, or readiness synthesis's deterministic factor sub-scores, which the model is
not permitted to contradict. (`build_student_context()`, which grounded the deleted student
chat surface in the student's own record, was removed with it in task 0.3, AV-57.) A grounded
surface answers from Avora's data rather than from the model's priors.

**Knowledge Base** — Tutor-specific knowledge — teaching methods, solving approaches,
marking preferences, instructions — stored in `knowledge_entries` and injected into most AI
surfaces (assignment extraction, marking, report generation, readiness synthesis — not
past-paper extraction, Syllabus Extractor, Class Brief, or narrative) so the AI behaves like
*that* tutor. (Its API is currently hidden, 0.5/AV-58 — the service and injection keep
running for the surfaces that call it directly.)

## Platform and process

**Job** — A unit of background work persisted as a row in `jobs`, claimed by the in-process
worker, with a registered handler keyed by type string. Not a cron entry and not a message.

**Handler** — The async function registered for a job type in `backend/app/workers/handlers.py`. **Must
be safe to re-run on the same payload.**

**Kill switch** — `READINESS_V2_SHADOW_ENABLED`. Despite the name, it does not enable a
shadow mode: it is a switch that, when off, stops v2 runs and silently carries the app on
v1. The name is a known defect.

**Constitution** — This documentation set: `docs/governance/` plus the 14 numbered
documents. Tier 1 in the authority hierarchy.

**ADR** — Architecture Decision Record. Explains *why* a structural decision was made and
what it cost. Immutable once accepted; changed by superseding.

**Rule** — A numbered, citable standard with a verb, a class, a status, and a rationale.
Format in `governance/documentation-authority.md`.

---

## Mistake vocabulary

**Mistake category** — a word a tutor uses for what went wrong on a marked answer, owned by
their organization and scoped to one subject (`mistake_categories`). Not an enum, and nothing
in the code may branch on its value: the contents are tutor data, so a rename is a valid edit
that must fail nothing. The five published starting words are *offered* by the editor, not
written — an organization that has never saved has no categories at all ([ADR-0010](../adr/0010-tutor-owned-mistake-categories.md)).

**Archived category** — a mistake category the tutor dropped from their list. Hidden from new
tagging and from the editor; still attached to every mistake already tagged with it, and still
counted in readiness. Archiving is not deletion, and a query that filters archived categories
out of readiness silently understates a student.

**Analysed submission** — a submission the mistake-tagging job has examined, marked by
`submissions.mistakes_analysed_at`. Distinct from a *marked* submission: work can be fully
marked and never examined for mistakes. The Mistake Analysis factor's denominator counts
analysed questions, not marked ones, so that "nobody has looked yet" reads as no data rather
than as a clean record (`PROD-2`).

**Mistake source** — who wrote a mistake row: `ai` (the tagging job) or `tutor`
(`mistakes.source`). It exists so re-running the job is safe: a run deletes and rewrites only
its own `ai` rows and never touches a tutor's, which `PROD-7` requires — the tutor's judgement
outranks anything the AI produced. Readers that only ask "what went wrong" ignore the column;
anything that *writes* or *deletes* must not.

**Mistake topic** — the link between a mistake and each syllabus topic its question tests
(`mistake_topics`, unique on `(mistake_id, topic_id)`). A link table rather than a column
because one question can test two topics, and a single `topic_id` silently picked one of them.
The rows are deleted with their mistake: there is no ON DELETE CASCADE, and the test suite runs
SQLite with foreign keys off, so a wrong delete order orphans them on Postgres alone
(`RISK-3`).

**Bare question** — an extracted question with no syllabus topic linked, because none of the
codes the extractor returned matched a real topic. Its mistakes still count for the student
but reach no chapter, and the tutor is shown the count so it can be fixed.

## Terms to avoid

| Avoid | Use instead | Why |
|---|---|---|
| "class" for a teaching group | **Group** | `class` collides with the code keyword and with Classroom |
| "test" for a mock or topic test | **Assessment** | `test` means an automated test everywhere else in this repo |
| "score" unqualified | **readiness score**, **mark**, or **percentage** | Three different things |
| "shadow mode" | **kill switch** | It has not been a shadow since the cutover |
| "the AI" as an actor | the named **surface** | "The AI failed" is not diagnosable; "the marking surface failed" is |
| "sync" for readiness recomputation | **recompute** or **evaluation run** | `sync` means Google Classroom import |

## Review triggers

- A new domain entity, table, or enum is introduced.
- An existing term's meaning changes in code.
- Two documents are found using a term differently.
- A term on the "avoid" list appears in a merged document.
