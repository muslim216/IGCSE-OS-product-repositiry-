# Phase 7 (Attendance) — agent handoff

**Audience: agents, not humans.** Dense and declarative on purpose. Assertions are either
`VERIFIED` (checked in-session against the code at the commit below) or sourced to a file path
or rule ID. Anything unverified is marked `UNVERIFIED`. Do not upgrade an `UNVERIFIED` claim
without testing it.

| Field | Value |
|---|---|
| Phase | 7 — Attendance |
| Spec of record | `docs/avora-new-state-august-16.md` §"Phase 7 — Attendance" (~line 1388) |
| Decisions it implements | AV-44, AV-109, AV-118, AV-119, AV-120 (table ~line 270–365); AV-33 (attendance is not a readiness factor) |
| State as of | `8c67313` on the default branch (`claude/igcse-os-planning-q8be0t`) |
| Handoff written | 2026-10-04 |
| Migration head | `0062_plan_slot_lesson` — Phase 7's first migration is `0063` |
| Previous phase | Phase 6 (teaching plan) CLOSED — PRs #104–#113; full backend suite on main 1372 passed / 15 skipped |
| Tasks done | none |

---

## 1. Tasks and order

| ID | Task | Size | Depends on | Status |
|---|---|---|---|---|
| 7.1 | `LessonAttendance` model, lesson mode (in person / online), in-person register | M | — | MERGED (#114, migration 0063) |
| 7.2 | Attendance surfaces (tutor, student, parent, reports — AV-44) | S | 7.1 | PR #116 |
| 7.3 | Zoom and Google Meet attendance integration | L | 7.1 | PR #117 (migration 0064) |
| 7.4 | Lesson pre-fill from the plan + 15-minute reminder; "counts as taught unless said otherwise" | M | 7.1 | PR #118 |
| AV-31 | Daily past-paper readiness recompute | — | — | MERGED (#115) |

**Waves** (owner rule from Phase 6: parallel subagents unless a task builds on another):
`7.1` alone → then `7.2 ∥ 7.3 ∥ 7.4` in separate worktrees, one PR each → phase sweep.
7.2 and 7.4 both touch `frontend/src/tutor/tabs/ScheduleTab.tsx`; give each agent disjoint
file ownership or sequence them, and say which in the launch prompt.

Phase 7 runs `∥` Phase 8 per the plan (line ~534), but **7.4 depends on 8.1 and 8.7** — see §4.

---

## 2. What exists today — `VERIFIED` at `8c67313`

**Lesson** (`backend/app/models/lessons.py`)
- Columns: `organization_id`, `group_id`, `date` (a `Date`, **no time of day**), `duration_min`,
  `notes`, `schedule_slot_id` (nullable FK to the recurring template).
- No mode, no attendance, no cancelled state. `LessonTopic` (unique `lesson_id, topic_id`) is the
  root of syllabus coverage (`PROD-14`). `LessonObservation` is per-student notes.
- A `Lesson` row is created **only when the tutor records one** (E15: a `PlanSlot` is the
  planned occurrence, a `Lesson` the actual one).

**ScheduleSlot** (`backend/app/models/groups.py:88`) — weekly template: `weekday`, `start_time`
(`Time`), `duration_min`, `title`. **This is the only place a lesson start time exists.**

**PlanSlot** (`backend/app/models/teaching_plan.py`) — `scheduled_date` (Date), `chapter_id`,
`sequence`, `provenance` (`generated | manually_modified | confirmed | completed`),
`lesson_id` (unique, `ON DELETE SET NULL`, migration 0062). `services/plan_lessons.py` claims a
slot for a lesson with an atomic conditional UPDATE; `/plan/next-lesson` suggests the next one.

**Lessons API** (`backend/app/api/lessons.py`) — routes take `user: CurrentUser`, not
`TutorUser`; every one goes through `_owned_group` / `_owned_lesson`, which call
`assert_tutor()` and 404 on another org's or another tutor's group (admins: same org only).
Behaviour is tutor-only; the signature is not. New attendance routes go in the signature
(`BE-17`, `SEC-11`): `user: TutorUser`.

**Frontend** — `frontend/src/tutor/tabs/ScheduleTab.tsx` (route `schedule` under the class,
`App.tsx:136`) already hosts `TeachingPlanView.tsx` and `RecordLessonForm.tsx`. AV-109: plan,
lessons **and** in-person attendance all live on this tab. `today/BehindClasses.tsx` and
`today/CreateLessonModal.tsx` also create/read lessons.

**Time zones** — `Organization.timezone` and `User.time_zone` exist; `services/timezones.py`
does normalisation. Timestamps stay UTC; convert at render and at the scheduling boundary.
**Read `services/timezones.py` before writing the reminder.**

**Google OAuth precedent** — `backend/app/api/classroom.py` (unmounted since AV-58) is the
reference flow: `security.create_state_token` / `verify_state_token`, server-side `state` bound
to the tutor. Its docstring already warns that 7.3 reintroduces the single-origin constraint.

**Absent** — `grep -i attendance backend/app` returns nothing. No email provider, no push, no
notification table (8.1 / 8.7 build them).

---

## 3. Task briefs

### 7.1 — Attendance model, lesson mode, in-person register

- New `LessonAttendance`: `lesson_id`, `student_id`, `state`, `source`, `recorded_by_id`,
  `recorded_at`; plus `organization_id` (`PROD-3`, `DB-2`). Unique `(lesson_id, student_id)`.
- `state` and `source` are `Enum(X, native_enum=False, length=N)` (`DB-5`). `source` says
  whether a human or an integration set it — the tutor must be able to tell (spec, 7.1).
  `recorded_by_id` is null for an integration write.
- `Lesson.mode`: `in_person | online`, migration on an existing table → `batch_alter_table(...,
  naming_convention=NAMING)` (`DB-17`), with a server default so existing rows backfill.
- Indexes declared in the model **and** the migration (`DB-12`). Re-export from
  `models/__init__.py` (`BE-3`) or the test schema silently has no table.
- Register: tutor marks each enrolled student on the lesson, on the Schedule tab. Only students
  enrolled in the lesson's group may be marked — validate against enrolment, 404 otherwise
  (`API-7`). Negative-case tests: other org's lesson, student not in the group, student role
  (`QA-12`).
- **Not a readiness factor (AV-33).** Do not add it to `EvidenceSource` or any factor. It
  explains gaps; it does not score them.
- Absent attendance renders as "not taken", never as absent or 0% (`PROD-2`, `UX-19`).
- Migration verified up → down → up (`DB-16`); CI's Postgres job is the real check (`RISK-3`).

### 7.2 — Attendance surfaces

AV-44: visible to tutor, parent, student, and in reports. Student and parent read **their own**
row only — scope by the authenticated user, never a path id (`SEC-7`); parent through the
existing parent-link check. Reports (8.6) consume it later — expose a service function, not a
second query. Regenerate OpenAPI types in the same PR (`FE-4`).

### 7.3 — Zoom and Google Meet

- **Two integrations**, each with its own OAuth app, consent screen and vendor approval. Zoom
  marketplace review and Google's verification for the Meet/Reports scopes are **owner jobs
  with lead time** — they cannot be done by an agent. Start them before the code.
- **Meet attendance reports require a paid Google Workspace edition.** A free-account tutor gets
  nothing, silently — say so at connect time, not after.
- OAuth redirect URIs pin the deployment to one origin again (§08, `classroom.py` docstring).
  Decide the URIs up front.
- `state` verified server-side, bound to the tutor (`security.create_state_token`). Browser
  check is second, never the check.
- Tokens are secrets at rest — follow §07 for storage; never log them.
- Participant → student matching is fuzzy. **Unmatched participants are surfaced to the tutor,
  never guessed** (spec). Integration writes set `source` to the integration and never overwrite
  a tutor-set row.
- The pull is a job handler (`BE-2`), safe to re-run (`BE-6`), payload carries ids (`BE-9`),
  no blocking HTTP client (`BE-13`).

### 7.4 — Pre-fill and the 15-minute reminder

- The plan pre-fills what the lesson covers (AV-119) — 6.5's `/plan/next-lesson` already does
  this for a lesson the tutor starts; 7.4 makes it the default.
- **Reminder 15 minutes before start** by email, push and in-app (AV-120).
- **After the lesson nothing is required** — it counts as taught with the topics that stood.
  Consequence the spec calls out: **a cancelled lesson nobody flags is recorded as taught**, and
  that inflates syllabus coverage (`PROD-14`), which feeds readiness. Cancelling must be one
  action from the reminder and from the Schedule tab.
- This resolves Phase 6's open question 2 ("behind" counts unrecorded lessons) — once taught is
  the default, `services/plan_progress.py`'s "behind" logic must be revisited in this task.

---

## 4. Questions for the owner — ANSWERED 2026-10-04

1. **7.4 needs email and push, which Phase 8 builds (8.1, 8.7).** ANSWERED — Reminders in-app
   first; email/push come in Phase 8 (8.1/8.7).
2. **Lessons have no start time.** ANSWERED — Each planned lesson stores its own start time
   (`plan_slots.start_time`, default from the weekly timetable, editable per lesson); lessons
   have `start_time` too.
3. **"Counts as taught" — what is the record?** ANSWERED — Auto-taught only for classes with
   an ACCEPTED plan; a sweep job writes real `Lesson` (origin=plan) + `LessonTopic` rows
   (`PROD-14` kept). Topics = a contiguous share of the chapter across its lessons (5 topics/3
   lessons → 1–2, 3–4, 5); the next-lesson pre-fill uses the same split.
4. **Attendance states.** ANSWERED — present | absent only.
5. **7.3 vendor approvals** — ANSWERED — Zoom/Google built against fakes; owner registers the
   apps later (setup guide handed over separately).
6. Carried from Phase 6: a daily readiness recompute when a plan's `past_paper_start_date`
   arrives. ANSWERED — Built (PR #115).
7. **Cancelling a planned lesson.** Cancelling a planned lesson shifts the plan automatically
   (no re-plan acceptance); with no room before the exam the cancel stands and the class shows
   as behind.

---

## 5. Process — unchanged from Phase 6

- Subagents on Sonnet 5.5, orchestrator on Opus 5.5. One PR per task, branch off latest default.
- Two reviewers per task (language reviewer + `silent-failure-hunter` or second language),
  then the orchestrator reads the diff. One `code-reviewer` sweep at phase end.
- Push, read the bots: cubic posts in two waves; trigger CodeRabbit with `@coderabbitai review`;
  Kody does nothing. Fix findings, merge when CI is green on the head SHA (owner delegated
  merging). Prefix `gh` with `env -u GITHUB_TOKEN`.
- Stage by path; never `git add -A`. Docs never go into the app branch — they go on a docs
  branch, pushed.
- Discrimination checks: break the fix, watch the test fail, restore.
- Implementers run targeted tests only; the full suite (~8–10 min) runs once per PR.
- Tests never call a real AI provider or a real Zoom/Google endpoint (`QA-8`).
- Phase 6 deploys (migrations 0060–0062) confirmed live on Render/Vercel 2026-10-04.

---

## 6. After Phase 7 — the coherence pass

Owner, 2026-10-04: a cross-role "make it one system" pass is scoped for **after** Phase 7 —
`docs/coherence-pass-after-phase-7.md`. It moves the Schedule tab, class header, navigation and
parent screen. Build 7.1/7.2 to the current layout; do not pre-empt that pass.
