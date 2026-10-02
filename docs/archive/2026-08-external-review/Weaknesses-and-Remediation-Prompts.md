# Avora — Weaknesses and Remediation Prompts

**A complete defect register with a ready-to-use prompt for every issue**
Compiled 6 August 2026 · 38 issues

---

## What this is

Every weakness found in the Avora codebase (repository: `muslim216/IGCSE-OS-product-repositiry-`, branch `claude/igcse-os-planning-q8be0t`), each with a copy-pasteable prompt written to be handed to either an experienced software engineer or an AI coding agent.

Findings came from three sources, and each issue says which:

| Tag | Meaning |
|---|---|
| **VERIFIED** | I read the code and confirmed the defect and its mechanism directly. Treat as fact. |
| **REVIEWED** | Found by a specialist review agent (security, database, Python, React, performance, silent-failure). Strong evidence, file:line given, but not independently re-confirmed by me. |
| **DOCUMENTED** | Avora's own engineering documentation already records it. Confirmed present; the team knows. |

**Nothing here is speculative.** Every issue points at specific code.

## How to use the prompts

Each prompt is self-contained — it carries its own context, so it works in a fresh session with no prior conversation.

**For a human engineer:** read the issue body first, then the prompt is your ticket description and acceptance criteria.

**For an AI coding agent:** paste the prompt as-is. Each one names the exact files, states the acceptance criteria, and — importantly — states the constraints that stop the agent "fixing" things it shouldn't. Work one issue per branch.

**A warning about the AI-agent route.** Issues marked **P0** change how student grades are calculated. Do not let an agent merge those unattended. The prompts require a regression test precisely so a human has something concrete to review.

## Severity key

| | Meaning |
|---|---|
| **P0** | Live defect producing wrong data or losing student work right now |
| **P1** | Security, tenancy, or permanent data-loss exposure |
| **P2** | Operational blindness — real failures nobody is told about |
| **P3** | Performance and scale ceilings |
| **P4** | Correctness risk that hasn't fired yet |
| **P5** | Quality, tooling, accessibility, compliance |

---

## Triage table

| # | Issue | Sev | Source | Effort |
|---|---|---|---|---|
| [1](#av-1) | Auto-finalized homework scored as never submitted → **hard zero** | P0 | VERIFIED | S |
| [2](#av-2) | Marking failure strands a correctly-marked submission forever | P0 | VERIFIED | M |
| [3](#av-3) | Resubmission race: stale job clobbers marks; orphaned files leak disk | P0 | REVIEWED | M |
| [4](#av-4) | Past-paper marking failures are invisible to every tutor list | P0 | REVIEWED | S |
| [5](#av-5) | Failed marking shown to student as "being marked" forever | P0 | REVIEWED | S |
| [6](#av-6) | Classroom import can create a permanently orphaned submission | P0 | REVIEWED | S |
| [7](#av-7) | Two readiness engines serve different numbers for one student | P1 | DOCUMENTED | L |
| [8](#av-8) | `admin` role is a global cross-organisation superuser | P1 | REVIEWED | M |
| [9](#av-9) | Tutors can read colleagues' reports for subjects they don't teach | P1 | REVIEWED | S |
| [10](#av-10) | `JWT_SECRET` has an insecure default and no startup guard | P1 | VERIFIED | S |
| [11](#av-11) | Google token encryption key derives from `JWT_SECRET` | P1 | VERIFIED | S |
| [12](#av-12) | Org scoping is convention, not mechanism (`CurrentOrg` dead) | P1 | DOCUMENTED | M |
| [13](#av-13) | Uploads disk has no backup, restore, or reconciliation | P1 | DOCUMENTED | M |
| [14](#av-14) | Database restore procedure has never been executed | P1 | DOCUMENTED | S |
| [15](#av-15) | No `ondelete=` on any of 109 foreign keys | P1 | VERIFIED | M |
| [16](#av-16) | Polymorphic "exactly one parent" invariant has no DB constraint | P4 | REVIEWED | S |
| [17](#av-17) | Nothing alerts on anything | P2 | DOCUMENTED | S |
| [18](#av-18) | Failed jobs are terminal with no dead-letter queue | P2 | DOCUMENTED | M |
| [19](#av-19) | No request IDs, no error tracking, almost no logging | P2 | DOCUMENTED | M |
| [20](#av-20) | `sync_classroom` has no per-item error isolation | P2 | REVIEWED | S |
| [21](#av-21) | Classroom silently drops unmatched students and attachments | P2 | REVIEWED | S |
| [22](#av-22) | Blocking CPU + disk I/O on the shared event loop | P3 | VERIFIED | M |
| [23](#av-23) | 109 foreign keys, zero indexed | P3 | VERIFIED | M |
| [24](#av-24) | N+1 query cluster across 7 confirmed sites | P3 | REVIEWED | M |
| [25](#av-25) | 29 list endpoints, zero pagination | P3 | VERIFIED | L |
| [26](#av-26) | Job worker is strictly serial | P3 | REVIEWED | S |
| [27](#av-27) | Single-instance ceiling — three constraints break together | P3 | DOCUMENTED | L |
| [28](#av-28) | `factor_evaluations` grows unbounded with no retention | P3 | DOCUMENTED | M |
| [29](#av-29) | Test schema diverges from production (4 missing indexes) | P4 | REVIEWED | S |
| [30](#av-30) | No prompt or model regression harness | P4 | DOCUMENTED | L |
| [31](#av-31) | No AI spend cap; pricing table empty | P4 | DOCUMENTED | M |
| [32](#av-32) | Auto-finalize threshold has never been calibrated | P4 | DOCUMENTED | S |
| [33](#av-33) | Token refresh has no coalescing — refresh storm logs users out | P4 | REVIEWED | S |
| [34](#av-34) | Streaming chat has no cancellation — cross-conversation leak | P4 | REVIEWED | S |
| [35](#av-35) | Effect re-seeding silently discards concurrent tutor edits | P4 | REVIEWED | M |
| [36](#av-36) | Frontend/backend contract drift, unenforced | P4 | DOCUMENTED | M |
| [37](#av-37) | Accessibility: focus trap, focus ring, skip link, live region | P5 | MIXED | M |
| [38](#av-38) | Supply chain: no lockfile, root container, no scanning | P5 | VERIFIED | M |

Effort: **S** = under a day · **M** = a few days · **L** = a week or more

---

# P0 — Live defects

<a id="av-1"></a>
## AV-1 — Auto-finalized homework is scored as never submitted

**P0 · VERIFIED · Effort S · This is the most serious issue in the codebase.**

**What's wrong.** `backend/app/services/readiness_v2.py:164` filters homework with `submission.status != SubmissionStatus.finalized`. That only matches manual tutor sign-off. It excludes `SubmissionStatus.auto_finalized` — which, by design, is what *most* homework ends up in, since the entire point of the marking pipeline is that confident scheme-backed marks finalize with no tutor step.

The codebase's own convention proves this is a mistake: `backend/app/api/submissions.py:50` defines `SETTLED_STATUSES = (auto_finalized, finalized)` and uses it correctly in four places. This path doesn't.

**Why it matters.** Tracing into `backend/app/services/readiness_factors.py:127` (`homework_performance`):

- Auto-finalized submissions become `HomeworkPoint(pct=None)` — counted in the denominator, excluded from the numerator. Scored **as if never submitted**.
- If a student's homework is *entirely* auto-finalized — the normal case — `submitted` is empty and the function returns **`score = 0.0`** with `accuracy: None`.

A student who submitted everything and got everything right scores **zero** on Homework Performance. Not "no data" — a hard zero presented as a real measurement, feeding the readiness score and predicted grade shown to students and parents.

It also directly violates the project's own `PROD-2` rule ("no surface may render a missing measurement as 0"), which is otherwise enforced carefully throughout.

`_consistency_points`, reading the same rows, does *not* filter by status and is unaffected. The bug is isolated to that one comparison.

```text
CONTEXT
Repo: Avora (FastAPI + React IGCSE tutoring platform). Python 3.11, async SQLAlchemy 2.0.
A submission reaches one of two settled states: `finalized` (a tutor signed it off) or
`auto_finalized` (the AI was confident and had an official mark scheme, so no tutor was
needed). `backend/app/api/submissions.py:50` defines the canonical pair:
    SETTLED_STATUSES = (SubmissionStatus.auto_finalized, SubmissionStatus.finalized)

BUG
`backend/app/services/readiness_v2.py:164`, inside `_homework_points`, reads:
    if submission is None or submission.status != SubmissionStatus.finalized:
        points.append(HomeworkPoint(pct=None, on_time=None))
        continue
This treats every `auto_finalized` submission as not submitted. In
`backend/app/services/readiness_factors.py:127` (`homework_performance`), points with
`pct=None` are excluded from `submitted` but still counted in `len(points)`, so
completion_rate is understated. When ALL of a student's homework is auto_finalized —
the common case — `submitted` is empty and the function returns score = 0.0 with
accuracy None. A student with perfect, fully-marked homework scores zero.

TASK
1. Fix the status check to treat both settled statuses as submitted. Import
   SETTLED_STATUSES rather than duplicating the tuple; if importing from
   `app/api/submissions.py` into a service would violate the project's
   `api -> services -> models` layering rule (BE-1, see docs/volume-2-application-
   engineering/04-backend-engineering.md), move the constant down to
   `app/models/homework.py` next to the SubmissionStatus enum and re-import it in
   both places. State which option you chose and why.
2. Audit every other status comparison in the readiness and evidence paths for the
   same mistake. Grep for `SubmissionStatus.finalized` across backend/app and check
   each hit: does it mean "a tutor signed this off specifically" (correct as-is) or
   "this submission is settled" (must include auto_finalized)? List your verdict per
   site in the PR description.
3. Add a regression test in `backend/tests/test_readiness_v2.py` proving a student
   whose submissions are ALL `auto_finalized` with full marks gets a
   homework_performance score near 100, not 0. The test must fail before your fix.

ACCEPTANCE
- The new test fails on the current code and passes after the change.
- `cd backend && python -m pytest` is green.
- No existing readiness test is weakened or deleted to make this pass.
- PR description lists every `SubmissionStatus.finalized` site audited in step 2.

CONSTRAINTS
- Do not change `readiness_factors.py`'s scoring maths. The maths is correct; only the
  data reaching it is wrong.
- Do not "fix" `homework_performance` returning 0.0 when `submitted` is empty by making
  it return NO_DATA without discussion — that path is legitimate for a student who
  genuinely submitted nothing, and changing it is a separate product decision.
- Historical readiness snapshots computed under the bug are wrong. Do not attempt a
  backfill in this PR; note in the description that a recompute of affected students
  is required and let a human schedule it.
```

<a id="av-2"></a>
## AV-2 — A marking failure strands a correctly-marked submission forever

**P0 · VERIFIED · Effort M**

**What's wrong.** In `backend/app/services/marking.py`:

1. `_settle_submission` sets `status = auto_finalized`, sets `finalized_at`, flushes, then calls `record_marks_as_evidence`.
2. If `record_marks_as_evidence` raises — a transient DB error, lock timeout, statement timeout — the exception unwinds to `mark_submission`'s `except`, which sets `status = ai_failed` and calls `session.commit()` on the **same session**, committing the already-flushed final marks alongside the wrong status.
3. On retry, `mark_submission` proceeds (status isn't `finalized`), but the idempotency guard in `_run_marking` (line ~215) sees every question already has `final_marks` set and **returns early — never reaching `_settle_submission` again**.
4. `mark_submission` then sets `ai_error = None` and returns normally. The job is marked `done`. Nothing will ever retry it.

**Why it matters.** End state: marks are correct and committed, `status` is permanently `ai_failed`, `ai_error` is `None` (a self-contradiction — failed with no reason), **no `Evidence` rows exist**, and **no readiness recompute was ever enqueued**. The student's work is marked but invisible to the readiness engine forever.

The student sees "being marked" indefinitely (see AV-5). The only recovery is a tutor manually opening the submission and clicking Finalize — undocumented and easy to miss. It triggers precisely on the auto-finalize happy path, where every question was confidently marked.

```text
CONTEXT
Repo: Avora. `backend/app/services/marking.py` contains the AI marking job handler.
Job delivery is at-least-once with MAX_ATTEMPTS = 2 (backend/app/workers/jobs.py).

BUG (trace it yourself before changing anything)
- `_settle_submission` sets status=auto_finalized, flushes, then calls
  `record_marks_as_evidence(session, submission, subject_id)`.
- `mark_submission`'s except block sets status=ai_failed, ai_error=str(exc), and
  commits the SAME session — persisting the already-flushed final_marks with the
  failed status.
- On retry, the guard in `_run_marking` ("if questions and all(... final_marks is not
  None ...)": return) fires and returns early, so `_settle_submission` never runs
  again. `mark_submission` then sets ai_error=None and returns cleanly, so the job is
  marked done and never retried.
- Result: correct marks committed, status stuck at ai_failed, ai_error None, NO
  Evidence rows, NO readiness recompute enqueued. Permanent and silent.

TASK
1. Make the recovery path work. The idempotency guard should skip the expensive AI
   call and the marking loop — it must NOT skip settlement. Restructure so that a
   re-run of an already-marked submission still reaches `_settle_submission` and
   therefore still writes evidence and enqueues the recompute.
2. `record_marks_as_evidence` and `build_homework_evidence` are already idempotent by
   `source_ref` (they delete prior rows for that source_ref first). Confirm this by
   reading `backend/app/services/evidence.py` and state it in the PR — the fix depends
   on it being safe to re-run settlement.
3. Stop the contradictory state: the except block must not stamp `ai_failed` over a
   submission whose marks are all final. Decide the correct behaviour (re-raise so the
   job retries with status untouched, or set a distinct recoverable state) and justify it.
4. Write a regression test in `backend/tests/test_auto_marking.py` that:
   - monkeypatches `record_marks_as_evidence` to raise on first call only,
   - runs the job twice via `process_one_job` (the existing tests' pattern),
   - asserts the submission ends `auto_finalized`, with Evidence rows present and a
     readiness recompute job enqueued.
   It must fail before the fix.

ACCEPTANCE
- New test fails on current code, passes after.
- `cd backend && python -m pytest` green — especially
  `test_re_marking_never_overwrites_a_tutor_finalized_mark`, which must still pass.
- No submission can end in a state where final_marks are set but status is ai_failed.

CONSTRAINTS
- The guarantee that a re-run NEVER overwrites a tutor-finalized mark (rule BE-7) is
  load-bearing and must survive. If your restructure touches that path, prove it with
  the existing test.
- Do not increase MAX_ATTEMPTS as a workaround — it does not fix the early return.
- Do not add a data migration to repair existing stranded rows in this PR. Report how
  to find them instead: submissions with status ai_failed, ai_error IS NULL, and all
  question_marks.final_marks NOT NULL.
```

<a id="av-3"></a>
## AV-3 — Resubmission race clobbers marks; old files leak disk

**P0 · REVIEWED · Effort M**

**What's wrong.** Two defects in one code path. On resubmission, `backend/app/api/submissions.py:120-133` (and the same pattern at `past_papers.py:313-314`) reuses the existing `Submission` row, deletes the old `SubmissionFile` **database rows** only, resets status, and enqueues a fresh `mark_submission` job.

1. **`storage.delete_file()` is never called**, so the physical files stay on the 10 GB disk forever with nothing pointing at them — invisible and unreclaimable.
2. **There is no version/generation column on `Submission`**, and `mark_submission` only checks `status == finalized` before proceeding. An in-flight job for the *previous* submission holds eagerly-loaded `submission.files` pointing at the now-deleted-from-DB files, and will happily finish and write marks.

**Why it matters.** A student uploads the wrong page, sees "being marked", and immediately resubmits the correct one. Two marking jobs now race for the same submission. Depending on timing, the marks recorded against a student's permanent record can be those of the **superseded** page. Silent, non-deterministic, and it produces a wrong mark that counts.

The disk leak compounds AV-13: the disk with no backup is also filling with files nothing references.

```text
CONTEXT
Repo: Avora. Students resubmit homework by uploading again to the same assignment.
`backend/app/api/submissions.py:120-133` handles this: it reuses the existing
Submission row, deletes old SubmissionFile DB rows, resets status to `submitted`,
and enqueues a new `mark_submission` job for the same submission_id.
`backend/app/api/past_papers.py:313-314` repeats the pattern.

TWO BUGS
(a) Orphaned files. `await db.delete(f)` removes the DB row but
    `storage.delete_file(f.path)` is never called, so the file stays on the Render
    persistent disk forever with no row referencing it. Unbounded, invisible leak on
    a 10 GB volume that has no backup and no monitoring.
(b) Stale-job race. `Submission` has no version/generation column
    (backend/app/models/homework.py). `mark_submission` (backend/app/services/
    marking.py) only guards on `status == finalized`. If a student resubmits while the
    previous marking job is mid-flight, the old job holds eagerly-loaded
    `submission.files` for the superseded upload, completes, and writes marks against
    the wrong content — possibly after the new job already wrote the right ones.

TASK
1. Add a monotonic integer `version` (or `generation`) column to `Submission` via a new
   Alembic migration in backend/alembic/versions/. Default 1, NOT NULL. Follow the
   safe-migration pattern for a populated table: add nullable, backfill, then set NOT
   NULL in a separate step — see AV-15/AV-20 rationale and migration 0012 for the
   pattern that previously took production down.
2. Bump `version` on every resubmission, include it in the `mark_submission` job
   payload, and have the handler re-read the submission and return early (a no-op, not
   an error) when the payload's version is older than the row's current version.
3. Call `storage.delete_file()` for each replaced file on resubmission, in both
   submissions.py and past_papers.py. Deleting the row and the file must not diverge —
   if the DB transaction rolls back after you unlink, you have destroyed a live file.
   Sequence it so the file is removed only after the row deletion commits.
4. Add tests in backend/tests/test_homework.py:
   - resubmission bumps version and a stale-version job is a no-op that does not alter
     marks or status,
   - resubmission removes the previous file from disk (assert via storage.absolute_path).

ACCEPTANCE
- Both tests fail before the change and pass after.
- `cd backend && python -m pytest` green.
- CI's migration job (up -> down -> up on Postgres 16) passes with the new migration.
- The new migration is reversible.

CONSTRAINTS
- Job handlers must stay idempotent (rule BE-6). A stale job is a silent no-op, never
  an exception — raising would burn a retry and log a false failure.
- Do not delete files for submissions in a settled state (auto_finalized/finalized);
  those are the marked record.
- Write a one-off reconciliation script under backend/seed/ or scripts/ that lists
  files on disk with no matching DB row, but do NOT have it delete anything. Deletion
  against the only copy of student work is a human decision.
```

<a id="av-4"></a>
## AV-4 — Past-paper marking failures appear in no tutor list

**P0 · REVIEWED · Effort S**

**What's wrong.** Two gaps combine:

- `backend/app/api/assignments.py:262-280` (`assignments_needing_attention`) uses an **inner join** to `Assignment`. Past-paper submissions have `assignment_id IS NULL`, so they are excluded entirely.
- `backend/app/api/submissions.py:400-422` (`review_queue`) filters only on `status == needs_review`, never `ai_failed`.

**Why it matters.** When AI marking fails terminally on a past paper, the submission appears in **no tutor-facing list at all** — not the review queue, not "needs attention". The only way to find it is to already know its URL. Combined with AV-5, a student's past-paper attempt can simply never be marked, and neither student nor tutor is ever told.

Past papers carry evidence weight 1.8 — the heaviest signal in the readiness engine. Silently losing them skews readiness most.

```text
CONTEXT
Repo: Avora. Submissions are polymorphic: each has EITHER assignment_id (homework) OR
past_paper_id (a full past paper), never both. Per ADR-0004 both flow through one
marking pipeline. Past papers carry the highest evidence weight (1.8) in the readiness
engine, so losing one distorts a student's score more than losing any other source.

BUG
(a) `backend/app/api/assignments.py:262-280` (`assignments_needing_attention`) inner-joins
    Assignment: `.join(Assignment, Assignment.id == Submission.assignment_id)`. Past-paper
    submissions (assignment_id IS NULL) are silently excluded from the tutor's attention feed.
(b) `backend/app/api/submissions.py:400-422` (`review_queue`) filters only
    `Submission.status == needs_review`, so `ai_failed` submissions never surface either.
Net: a past paper whose marking failed terminally is in NO tutor-facing list.

TASK
1. Make the attention feed cover past papers. `review_queue` in submissions.py already
   outer-joins both Assignment and PastPaper — copy that shape rather than inventing a
   second one. Response must clearly identify which parent a row came from.
2. Include terminally-failed submissions in tutor-facing surfaces. Decide whether
   `ai_failed` belongs in review_queue, in the attention feed, or both, and justify it.
   It must be visually distinct from "waiting for tutor judgement" — these need a retry
   or an escalation, not a marking decision.
3. Give the tutor a way to act. A failed submission with no re-run control is only
   marginally better than an invisible one. Add a re-enqueue endpoint (tutor-gated,
   idempotent) or state explicitly why it belongs in AV-18 instead.
4. Tests in backend/tests/test_past_papers.py and test_homework.py: a past-paper
   submission in `ai_failed` appears in the tutor surface(s) you chose; a homework
   submission in `ai_failed` does too.

ACCEPTANCE
- Tests fail before, pass after.
- `cd backend && python -m pytest` green.
- No cross-tenant leak: a tutor sees only their own organisation's failures. Add an
  explicit test for this — the review_queue scoping is the model to copy.

CONSTRAINTS
- Do NOT add a past-paper-specific code path (rule PROD-9). Both go through one query.
- Preserve the existing role gates (`user: TutorUser` in the signature, never a check
  in the body — rule BE-17). `backend/tests/test_authorization.py` will fail if you
  drop one.
- Keep pagination in mind (AV-25): do not add a new unbounded list endpoint.
```

<a id="av-5"></a>
## AV-5 — Failed marking is shown to the student as "being marked", forever

**P0 · REVIEWED · Effort S**

**What's wrong.** `backend/app/api/submissions.py:199-209` maps `SubmissionStatus.ai_failed → "being_marked"` in the student-facing view. `frontend/src/student/HomeworkPage.tsx` renders that as the same badge used for genuinely in-progress work.

**Why it matters.** When marking fails terminally (2 attempts, then dead), the submission sits at `ai_failed` permanently. The student sees "Being marked" indefinitely and has no reason to tell anyone — it looks like the system is working. Combined with AV-4 (the tutor can't see it either) and AV-17 (nothing alerts), a piece of student work vanishes with every party believing it's in hand.

This is the exact failure the product's own honesty principle exists to prevent.

```text
CONTEXT
Repo: Avora. When the AI marking job exhausts its retries a submission is left at
SubmissionStatus.ai_failed permanently (backend/app/workers/jobs.py, MAX_ATTEMPTS = 2).

BUG
`backend/app/api/submissions.py:199-209` maps the student-facing `public_status` for
ai_failed to "being_marked" — the same value used for genuinely in-flight marking.
`frontend/src/student/HomeworkPage.tsx` (STATUS_BADGE) renders it identically. The
student sees "Being marked" forever and never learns their work was not marked.

TASK
1. Give ai_failed an honest, distinct student-facing status. Wording should not alarm or
   blame the student and must not expose internal error detail — something like
   "Delayed — your tutor has been notified" is the right register. Confirm the tutor
   genuinely IS notified (see AV-4); if not, choose wording that is true today.
2. Add the matching badge in frontend/src/student/HomeworkPage.tsx.
3. Harden the badge lookup. STATUS_BADGE[...] is indexed directly with no fallback, so
   any future backend status not present in the map throws inside .map() and blanks the
   entire homework list. Add a generic fallback.
4. Tests: backend test asserting public_status for ai_failed is the new value;
   frontend test (vitest + React Testing Library) asserting an unknown status renders
   the fallback instead of throwing.

ACCEPTANCE
- `cd backend && python -m pytest` and `cd frontend && npm test` both green.
- No student-facing surface reports a terminally failed submission as in progress.

CONSTRAINTS
- Do not surface raw `ai_error` text to students — it can contain provider messages and
  internal detail. Tutors may see it; students may not.
- Keep the existing public_status mapping shape; this is one entry, not a redesign.
```

<a id="av-6"></a>
## AV-6 — Classroom import can create a permanently orphaned submission

**P0 · REVIEWED · Effort S**

**What's wrong.** In `backend/app/services/google_classroom.py:353-387`, every attachment can be silently skipped (missing Drive file, disallowed MIME, or `storage.save_bytes` raising `ValueError`) — each a bare `continue` with no logging. But the `Submission` row is created **unconditionally** at line 354-358, while the marking job is only enqueued `if files:` at line 365.

**Why it matters.** A submission with zero usable attachments is created at `status=submitted`, no marking job ever runs, so it never reaches `ai_failed` or `needs_review`. It therefore appears in neither the review queue nor the attention feed. It just sits there forever. The student turned work in via Classroom; Avora recorded a submission and did nothing with it, silently.

```text
CONTEXT
Repo: Avora. `backend/app/services/google_classroom.py` imports turned-in Google
Classroom submissions. Only PDF and image attachments are importable; other Drive types
are deliberately skipped.

BUG
Lines ~353-387: attachments are skipped with bare `continue` on three paths (drive_file
is None, disallowed MIME, storage.save_bytes raising ValueError) with NO logging. The
Submission row is created unconditionally (~354-358), but the marking job is enqueued
only `if files:` (~365). A submission with zero usable attachments therefore exists at
status=submitted, is never marked, never reaches ai_failed or needs_review, and appears
in no tutor list. It rots silently.

TASK
1. Stop creating a submission that cannot be processed. Either do not create the row
   when no attachment survives filtering, or create it in a distinct state that DOES
   surface in the tutor's attention feed (see AV-4). Choose one and justify it — note
   that not creating it means the next sync retries the item, which may be what you want.
2. Add logging. This module currently has no logging import and no logger at all. Add
   one and log every skip with enough context to diagnose: course id, coursework id,
   student id, attachment name, and the reason.
3. Make the reason reachable by the tutor, not just the log — a tutor whose student's
   work silently never arrived has no way to find out why today. Surface it near the
   course link in frontend/src/tutor/ClassroomSettingsPage.tsx, or persist a skip
   record. State your choice.
4. Test in backend/tests/test_classroom.py using the existing mocked-API pattern: a
   coursework submission whose only attachment is an unsupported type does NOT leave an
   unprocessable submission invisible to tutors.

ACCEPTANCE
- Test fails before, passes after.
- `cd backend && python -m pytest` green.
- No code path can leave a Classroom-imported submission with zero files and no route
  to a human.

CONSTRAINTS
- Keep the deliberate policy of skipping non-PDF/image attachments and unmatched
  students rather than guessing (see AV-21 for the unmatched-student half). This issue
  is about making skips VISIBLE, not about importing more types.
- `sync_classroom` must stay idempotent — re-running must not duplicate submissions.
  ClassroomWorkLink is the existing mechanism; preserve it.
```

---

# P1 — Security, tenancy, and data loss

<a id="av-7"></a>
## AV-7 — Two readiness engines serve different numbers for the same student

**P1 · DOCUMENTED · Effort L**

**What's wrong.** `/readiness/*` serves v2 snapshots, but `backend/app/api/analytics.py`, `backend/app/services/reports.py` and `backend/app/services/student_crm.py` still read the v1 tables (`topic_readiness`, `readiness_history`, `tutor_preferences`) directly.

**Why it matters.** A tutor sees one readiness number on the readiness page and a different one for the same student in a report or on the CRM record. Both are "correctly" computed — they came from different engines — which makes the discrepancy hard to diagnose and corrosive to trust in the metric the whole product is sold on. Their register rates this the highest-likelihood unresolved risk and notes it has **already materialised**.

Note this interacts with **AV-1**: the v2 engine is currently producing wrong homework scores, so completing the cutover *before* fixing AV-1 would propagate the bug everywhere. **Fix AV-1 first.**

```text
CONTEXT
Repo: Avora. Two readiness engines coexist. v1: backend/app/services/readiness.py,
writing topic_readiness / readiness_history, configured by tutor_preferences. v2:
readiness_factors.py (pure maths) + readiness_v2.py (DB gathering) + readiness_v2_ai.py
(AI synthesis), writing factor_evaluations and readiness_snapshots.
`backend/app/services/readiness_summary_v2.py` serves /readiness/* from v2 with a
per-subject fallback to v1 (response says engine: "v1" when it falls back).
Still on v1 and NOT repointed: app/api/analytics.py, app/services/reports.py,
app/services/student_crm.py. So two screens show one student different numbers.

PREREQUISITE — read this first
Issue AV-1 in this register is a live bug in the v2 homework factor
(readiness_v2.py:164 excludes auto_finalized submissions, producing a hard zero).
Do NOT start this cutover until AV-1 is fixed and merged, or you will propagate a
known-wrong score to every remaining surface. Verify AV-1 is fixed before proceeding.

TASK
1. Repoint the three modules to read v2 through `services/readiness_summary_v2.py` —
   the same aggregation /readiness/* uses. Do not write a fourth query path
   (rule PROD-13: no third engine, no second source of truth for one metric).
2. Preserve the per-subject v1 fallback while any student lacks a ready v2 snapshot, so
   no screen goes blank mid-migration.
3. Handle shape differences honestly. Where v1 exposed something v2 does not (or vice
   versa), do not invent a value — follow rule PROD-2 and render absent data as absent.
   List every such difference in the PR.
4. Only once all readers are repointed and verified, plan the removal of
   topic_readiness / readiness_history / tutor_preferences. Do NOT drop tables in this
   PR — propose it as a follow-up with a separate migration.
5. Rename READINESS_V2_SHADOW_ENABLED. It is a kill switch, not a shadow flag, and the
   name invites someone to disable it believing it merely stops a duplicate
   computation. Keep the old env var working as a deprecated alias for one release.
6. Tests: extend backend/tests/test_readiness_cutover.py so analytics, reports and CRM
   return the SAME numbers as /readiness/* for the same student and subject.

ACCEPTANCE
- A single student and subject yields identical readiness figures across
  /readiness/*, analytics, reports and the CRM record.
- `cd backend && python -m pytest` green.
- No table is dropped in this PR.

CONSTRAINTS
- Ship incrementally: one reader per PR (analytics, then reports, then CRM) is safer
  than all three at once, and each is independently verifiable.
- Reports are read by parents. A wrong number here is worse than a missing one.
- Keep the fallback until data proves it is unused — measure how often it fires before
  removing it.
```

<a id="av-8"></a>
## AV-8 — The `admin` role is a global cross-organisation superuser

**P1 · REVIEWED · Effort M**

**What's wrong.** Every ownership check in the codebase follows the shape:

```python
if X.tutor_id != user.id and user.role != UserRole.admin:
    raise HTTPException(403)
```

The admin branch **never compares `organization_id`**. The pattern repeats across ~14 routers: `groups.py:42`, `lessons.py:38,49`, `analytics.py:34`, `assignments.py:44,170,192,238`, `knowledge.py:25`, `syllabus_uploads.py:18,62`, `classifieds.py:71,107`, `resources.py:20-21,128`, `students.py:45,79`, `readiness.py:48`, `past_papers.py:83`, `submissions.py:60,299`.

**Why it matters.** An `admin` account in one organisation can read and write **every other organisation's** groups, submissions, past-paper mark schemes, syllabus uploads, knowledge base entries and CRM notes. `User.organization_id` is non-nullable for admins too, so the role *looks* org-scoped and isn't.

Not currently exploitable — there's no self-service path to become admin, only seeding or direct DB access. But the moment "admin" is used for per-organisation staff, which is the obvious step when tutoring centres are onboarded, this becomes total cross-tenant access to minors' academic records.

```text
CONTEXT
Repo: Avora, multi-tenant. Every tutor gets an Organization at signup; students and
parents inherit it. Roles: student, tutor, parent, admin (backend/app/models/users.py).
`User.organization_id` is nullable=False for EVERY role including admin.

BUG
Ownership checks throughout backend/app/api/ read:
    if X.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(403)
The admin branch never compares organization_id, so admin is a GLOBAL superuser across
all organisations, not an org-scoped role. Confirmed at: groups.py:42, lessons.py:38,49,
analytics.py:34, assignments.py:44,170,192,238, knowledge.py:25, syllabus_uploads.py:18,62,
classifieds.py:71,107, resources.py:20-21,128, students.py:45,79, readiness.py:48,
past_papers.py:83, submissions.py:60,299.

DECIDE FIRST, THEN IMPLEMENT
This is a product decision before it is a code change. Exactly one of:
(a) `admin` is org-scoped staff -> every admin check must ALSO require
    resource.organization_id == user.organization_id.
(b) `admin` is platform staff (Avora employees) -> introduce a separate role
    (e.g. platform_admin) for genuine cross-org access, make `admin` org-scoped per (a),
    and ensure no org-scoped account can ever hold the platform role.
Recommend (b) if there is any intent to onboard tutoring centres, since (a) leaves no
way for the vendor to support customers. State your choice and reasoning before coding.

TASK
1. Implement the chosen model across ALL sites listed above. Do not fix a subset.
2. Put the check somewhere it cannot be forgotten. The project already learned this
   lesson for role gates (RISK-7: eleven duplicated `_require_tutor` helpers were
   converged onto a dependency in the handler signature, because a check in the body
   fails OPEN when omitted). Apply the same reasoning here — a shared helper or
   dependency, not another copy-paste of the condition at 20 sites.
3. Add regression tests in backend/tests/test_authorization.py mirroring the existing
   `test_students_cannot_see_another_organizations_past_papers`: an admin in org B must
   NOT reach org A's groups, submissions, mark schemes, CRM notes or knowledge entries.
   Confirm each test fails before your fix.

ACCEPTANCE
- New cross-org admin tests fail before, pass after.
- `cd backend && python -m pytest` green.
- No ownership helper compares role without also constraining tenancy (unless the
  platform role from option (b) is deliberately exempt, in which case say so at the site).

CONSTRAINTS
- Do not regress the closed half of RISK-7: role gates stay in handler signatures
  (`user: TutorUser` / `StudentUser`), never as calls in the handler body (rule BE-17).
- `backend/seed/demo.py` may create an admin — keep it working.
- If you choose (b), the new role needs a migration; follow the safe pattern in AV-15.
```

<a id="av-9"></a>
## AV-9 — Tutors can read colleagues' reports for subjects they don't teach

**P1 · REVIEWED · Effort S**

**What's wrong.** `backend/app/api/reports.py:38-42` (`_check_can_view_student`), used by `get_report` (98-105) and `list_reports` (81-94), authorises a viewing tutor if `visible_subject_ids` returns **any** non-empty set for that student. It never checks that `report.subject_id` is a subject the *viewing* tutor actually teaches.

**Why it matters.** Tutor A teaches Student X in Maths only. Tutor B, same organisation, teaches Student X in Physics and generates a `tutor`-audience report — which can carry candid assessments. Tutor A can fetch and read it. Within-organisation, but still a disclosure of confidential professional notes to someone with no relationship to that subject.

```text
CONTEXT
Repo: Avora. Reports are generated per student per subject, with three audiences
(student / tutor / parent). The `tutor` audience can contain candid professional
assessment not intended for other staff.

BUG
`backend/app/api/reports.py:38-42` (`_check_can_view_student`) authorises the caller if
`visible_subject_ids(...)` returns any non-empty set for that student — proving SOME
teaching relationship exists, not the specific one the report concerns. Used by
get_report (98-105) and list_reports (81-94). Tutor A (teaches Student X in Maths only)
can therefore read Tutor B's Physics tutor-audience report on the same student.

TASK
1. Intersect `report.subject_id` with the caller's `visible_subject_ids(...)` before
   returning content, in both get_report and list_reports (list must filter, not 403).
2. Decide and document the rule for reports with `subject_id IS NULL` ("all subjects").
   Suggested: visible only to a tutor who teaches the student in at least one subject,
   or restrict to org admins. State your choice at the code site.
3. Consider whether audience should narrow visibility further — should a `parent`-audience
   report be readable by any teaching tutor? Probably yes. Say so explicitly rather than
   leaving it implicit.
4. Tests in backend/tests/test_reports.py: a tutor who teaches a student only in subject
   A gets 403/absence for a subject-B report on that student; the owning tutor still gets it.

ACCEPTANCE
- Tests fail before, pass after.
- `cd backend && python -m pytest` green.
- list_reports omits unauthorised reports rather than erroring the whole request.

CONSTRAINTS
- Do not break parent access: parents see reports for linked children via ParentLink,
  a separate path. Verify it still works.
- Report generation is already restricted to tutor/admin. Do not widen it.
```

<a id="av-10"></a>
## AV-10 — `JWT_SECRET` has an insecure default and no startup guard

**P1 · VERIFIED · Effort S**

**What's wrong.** `backend/app/config.py:24`: `jwt_secret: str = "change-me-in-production"`. Nothing refuses to boot, or even warns, if that default survives into a deployment.

**Why it matters.** If `JWT_SECRET` is ever unset — a routine first-deploy mistake, or any deployment not using the Render blueprint — every access token, refresh token and OAuth state token is signed with a publicly known constant. Anyone can mint a token for any `user_id` and impersonate any user in any organisation. It also unlocks AV-11.

Currently mitigated only by `render.yaml` setting `generateValue: true`. That is one deployment path being correct, not a control.

```text
CONTEXT
Repo: Avora. `backend/app/config.py:24` sets
    jwt_secret: str = "change-me-in-production"
It signs access tokens, refresh tokens and OAuth state (backend/app/security.py).
render.yaml sets it via generateValue: true, so the deployed service is currently safe —
but nothing in the application enforces that.

RISK
Any deployment not using the Render blueprint (self-host, a second environment, local
Docker exposed beyond localhost) inherits a publicly known signing key. An attacker can
forge a token for any user_id and token_version and fully impersonate any user in any
organisation. This also compromises stored Google refresh tokens — see AV-11.

TASK
1. Fail fast at startup when jwt_secret is the known default, outside dev/test. Prefer
   removing the default entirely so pydantic-settings requires the env var; if a default
   must remain for the test suite, gate it on an explicit environment flag and refuse to
   start otherwise. The error must name the variable to set.
2. Apply the same reasoning to any other credential-shaped setting with a usable
   default. Audit config.py and report what you found.
3. Ensure the test suite and docker-compose still work — set the value explicitly in
   backend/tests/conftest.py and docker-compose.yml rather than relying on a default.
4. Test asserting the app refuses to start with the default secret when not in
   dev/test mode.

ACCEPTANCE
- App refuses to boot with the default secret outside dev/test, with a message naming
  JWT_SECRET.
- `cd backend && python -m pytest` green.
- `docker compose up` still works for local development.

CONSTRAINTS
- Follow the existing degradation philosophy (rule AI-20): a missing credential raises
  with a message naming the variable. A missing SIGNING key is different from a missing
  AI key — it must prevent startup, not degrade a surface.
- Do not log the secret, or any prefix of it, in the error.
```

<a id="av-11"></a>
## AV-11 — Google token encryption key derives from `JWT_SECRET`

**P1 · VERIFIED · Effort S**

**What's wrong.** `backend/app/services/google_classroom.py:86`:

```python
material = (settings.google_token_encryption_key or settings.jwt_secret).encode()
```

When `GOOGLE_TOKEN_ENCRYPTION_KEY` is unset, the key encrypting stored Google OAuth refresh tokens at rest is derived from the same secret that signs every auth token.

**Why it matters.** Two consequences, and the second is an operational trap nobody has written down:

1. **Blast radius.** Compromising `JWT_SECRET` doesn't just let an attacker forge sessions — it decrypts every tutor's stored Google refresh token, granting read access to their Classroom and Drive. One secret, two unrelated systems.
2. **Rotation breaks decryption silently.** Rotating `JWT_SECRET` — the correct response to a suspected leak, and the thing you'd do *first* — makes every stored Google refresh token undecryptable. Every tutor's Classroom integration breaks at once, during an incident, with no obvious connection to the rotation.

```text
CONTEXT
Repo: Avora. `backend/app/services/google_classroom.py:86` derives the key that
encrypts stored Google OAuth refresh tokens at rest:
    material = (settings.google_token_encryption_key or settings.jwt_secret).encode()
GOOGLE_TOKEN_ENCRYPTION_KEY is optional; render.yaml generates one, but the fallback
means any deployment without it reuses the JWT signing secret.

TWO PROBLEMS
1. Blast radius: compromising JWT_SECRET forges sessions AND decrypts every tutor's
   Google refresh token (Classroom + Drive read access). One secret, two systems.
2. Rotation trap (undocumented): rotating JWT_SECRET — the correct first response to a
   suspected leak — silently makes every stored Google refresh token undecryptable.
   Every tutor's Classroom integration breaks simultaneously, mid-incident, with no
   obvious causal link. Nothing in the runbooks warns about this.

TASK
1. Remove the fallback. Require GOOGLE_TOKEN_ENCRYPTION_KEY whenever Google Classroom
   is configured (i.e. when GOOGLE_CLIENT_ID/SECRET are set). Keep the existing graceful
   degradation when Classroom is not configured at all — the app must still run.
2. Handle existing encrypted tokens. Decrypting with the old derived key and re-encrypting
   with the new one needs a deliberate migration path. Simplest defensible option: on
   decryption failure, treat the tutor's Google link as disconnected and prompt them to
   reconnect, rather than crashing. Implement that and say so in the PR.
3. Document the rotation dependency in docs/volume-4-reliability-and-operations/
   14-operations-runbooks.md: rotating JWT_SECRET invalidates all sessions (intended)
   and, before this fix, also broke Google tokens (unintended).
4. Tests: Classroom configured without an encryption key fails loudly at startup or
   configuration time, not at first use; a token that cannot be decrypted degrades to
   "reconnect required" rather than raising.

ACCEPTANCE
- No code path derives the token encryption key from jwt_secret.
- App still starts and runs fully with Classroom unconfigured.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- Do not log key material or token plaintext.
- Coordinate with AV-10; both touch config validation. Sequence them or do them together.
- Deploy note: after this ships, GOOGLE_TOKEN_ENCRYPTION_KEY must be set in Render
  before the release, or Classroom breaks. Call this out in the PR.
```

<a id="av-12"></a>
## AV-12 — Org scoping is a convention, not a mechanism

**P1 · DOCUMENTED · Effort M**

**What's wrong.** `get_current_org_id()` and `CurrentOrg` exist in `backend/app/api/deps.py` and are **called nowhere**. Every query applies organisation scoping by hand against `user.organization_id`.

**Why it matters.** Tenant isolation depends on every developer remembering one line in every query, forever, with nothing detecting an omission. A missing filter fails **open** and silently. The security review confirmed every current query is correct — this is about the mechanism, not a live leak.

The team already solved exactly this problem one layer up: eleven duplicated role-check helpers were converged onto a dependency in the handler signature, with a test that fails if anyone reintroduces the old pattern. They did the hard version for roles and stopped short for tenancy.

```text
CONTEXT
Repo: Avora, multi-tenant. `backend/app/api/deps.py` defines `get_current_org_id()` and
`CurrentOrg`. Both are dead code — grep confirms zero call sites. Organisation scoping is
applied ad hoc in each query against `user.organization_id`.

WHY THIS MATTERS
Rule PROD-4 ("any query returning tenant data filters by organization") is enforced by
memory. A query that omits the filter fails OPEN with nothing to detect it. Integer PKs
are enumerable (a deliberate, documented trade-off), so an unscoped query is a
cross-tenant leak, not merely a bug. A security review confirmed all CURRENT queries
scope correctly — this is about making the next one safe, not fixing a live leak.

PRECEDENT TO FOLLOW
RISK-7's role half was closed exactly this way: eleven byte-identical `_require_tutor`
helpers called in handler bodies were replaced with `TutorUser`/`StudentUser`
dependencies in handler signatures, plus `backend/tests/test_authorization.py`, which
fails if a route loses its gate or a router grows its own copy. Do the tenancy half the
same way.

TASK
1. Adopt CurrentOrg (or delete it and build what actually fits — decide and justify).
   The goal is that org scoping is structurally present rather than remembered.
2. Add an enforcement test in the spirit of test_authorization.py. Options, in order of
   preference: a test that introspects queries over tenant-scoped tables for an
   organization predicate; or a test that a known-unscoped query is rejected; or at
   minimum a maintained list of tenant-scoped models with a test that every router
   touching one uses the shared scoping helper. Perfect static detection is hard —
   something that fails on the obvious regression beats nothing.
3. Migrate routers incrementally. Do not convert all 23 in one PR — start with the
   highest-risk (students.py, submissions.py, past_papers.py, reports.py) and land the
   rest in follow-ups.
4. Update docs/volume-1-product-and-ux/01-product-architecture.md and
   volume-3-platform-engineering/07-security-architecture.md, which currently state
   CurrentOrg is dead code.

ACCEPTANCE
- `cd backend && python -m pytest` green.
- The enforcement test demonstrably fails when scoping is removed from a converted
  router — prove this, don't assume it.
- Behaviour is unchanged; this is a refactor toward structural enforcement.

CONSTRAINTS
- Subjects and topics are deliberately GLOBAL (shared across organisations). Do not
  scope them. Past-paper visibility is correctly scoped by (organization, subject)
  derived from enrolment — see `_enrolled_scope` in app/api/past_papers.py — and must
  keep working; there is a test for it.
- Related but distinct: AV-8 (admin bypasses tenancy). Sequence AV-8 first; it is a live
  hole, this is hardening.
```

<a id="av-13"></a>
## AV-13 — Uploads disk has no backup, restore, or reconciliation

**P1 · DOCUMENTED · Effort M · Highest business consequence in this register.**

**What's wrong.** Booklets, mark schemes and student submissions are files on a 10 GB Render disk. The database stores only relative paths. There is no backup, no restore procedure, no row-to-file reconciliation, and no disk-usage monitoring.

**Why it matters.** A disk loss destroys every piece of student work ever submitted, with the database still confidently referencing it. A deploy without the disk mounted orphans every row. The disk can fill silently — and AV-3 is actively leaking orphaned files into it.

For a product whose promise is a complete academic record, this is not an incident. It's the end of the customer relationship.

```text
CONTEXT
Repo: Avora. `backend/app/services/storage.py` writes uploads to a local disk; DB rows
store paths relative to UPLOAD_DIR. render.yaml mounts a 10 GB persistent disk at /data.
No backup, no restore procedure, no reconciliation between rows and files, no disk
monitoring. The module docstring states it was written so the folder can move to object
storage later without touching rows.

TASK — ship in this order, each independently valuable
1. IMMEDIATE (hours): a scheduled copy of the uploads directory to off-host storage.
   Even a nightly sync to an S3 bucket run from a cron job is a step change from zero.
   Do this first, before the refactor, so exposure drops today.
2. Reconciliation tool (backend/scripts/ or seed/): report DB rows whose file is missing,
   and files with no DB row (AV-3 is actively creating the latter). REPORT ONLY — it must
   not delete. Deleting against the only copy of student work is a human decision.
3. Object storage migration: implement an S3-backed storage backend behind the existing
   storage.py interface. Keep the local backend for development. Paths are already
   relative, so DB rows should not need to change — confirm this and say so.
   Do the blocking-I/O fix (AV-22) in the same pass or immediately after: S3 client calls
   are async-friendly and make that problem largely disappear.
4. Disk-usage alerting until the migration lands (see AV-17).
5. Write and then ACTUALLY EXECUTE a restore drill. Document the result in
   docs/volume-4-reliability-and-operations/14-operations-runbooks.md. An untested
   backup is a hypothesis.

ACCEPTANCE
- Uploads exist in at least two places.
- Reconciliation runs and reports honestly against the live dataset.
- A restore has been performed at least once and the outcome written down.
- `cd backend && python -m pytest` green throughout.

CONSTRAINTS
- Never delete a file automatically in any of this work.
- Preserve the existing upload validation exactly as-is: magic-byte checking, the 20 MB
  cap enforced before AND after HEIC transcoding, server-generated random filenames.
  A security review specifically confirmed this layer is sound — do not weaken it while
  swapping the backend.
- Moving off local disk removes one of the three constraints pinning the app to a single
  instance (AV-27). Note the interaction; do not attempt the other two here.
```

<a id="av-14"></a>
## AV-14 — The database restore procedure has never been executed

**P1 · DOCUMENTED · Effort S**

**What's wrong.** A restore procedure exists on paper in the operations runbooks. It has never been run. Backup retention is also unverified — nothing records what the Render plan actually retains, or for how long.

**Why it matters.** An untested backup is a hypothesis. The first execution should not be during an outage, against production, under pressure, by someone reading the steps for the first time.

```text
CONTEXT
Repo: Avora. docs/volume-4-reliability-and-operations/14-operations-runbooks.md contains
a database restore procedure (R13). It has never been executed. The doc's own Known Gaps
section records this, and also that backup retention is unverified — nobody has recorded
what Render's plan actually retains or for how long.

TASK
1. Establish the facts: what does the current Render Postgres plan back up, how often,
   with what retention, and what is the recovery point objective? Write the answers into
   the runbook. This is a dashboard/documentation task, not a code one.
2. Execute a real restore into a scratch database. Time it. Record: wall-clock duration,
   every step that was wrong or missing in the written procedure, and the data loss
   window observed.
3. Correct the runbook against what actually happened.
4. Do the same for uploads once AV-13 lands. A database restored without its files is a
   catalogue pointing at nothing.
5. Record a restore-drill cadence (quarterly is reasonable at this stage) and note who
   owns it, in docs/governance/ownership.md.

ACCEPTANCE
- A restore has been performed and its real duration recorded.
- The runbook matches observed reality, not the original assumption.
- Retention and RPO are written down as facts, with the source.

CONSTRAINTS
- Never restore over production to test a procedure.
- The restored scratch database contains real minors' data. Delete it immediately after
  the drill and record that you did.
- This is a prerequisite for any customer due-diligence conversation (AV-13 and the
  compliance gap). Treat it as commercial work, not housekeeping.
```

<a id="av-15"></a>
## AV-15 — No `ondelete=` on any of 109 foreign keys

**P1 · VERIFIED · Effort M**

**What's wrong.** I confirmed: 109 `ForeignKey(` declarations across `backend/app/models/*.py`, **zero** with `ondelete=`. Cascades exist only at the ORM level, on 10 relationships. Postgres therefore defaults to `NO ACTION` everywhere.

**Why it matters.** Any delete performed outside the ORM's relationship graph — raw SQL, a maintenance script, a future admin console, a bulk `session.execute(delete(...))` — either fails with a foreign-key violation or orphans rows, depending on the path. Deleting a `User` who has `Evidence`, `Mistake`, `FactorEvaluation`, `ReadinessSnapshot` or `MarkOverrideAudit` rows simply fails, because nothing tells the ORM to cascade those.

This also blocks the deletion path that GDPR-style erasure requests require.

```text
CONTEXT
Repo: Avora. Verified counts: 109 `ForeignKey(` declarations across
backend/app/models/*.py, ZERO with `ondelete=`. `cascade="all, delete-orphan"` appears on
only 10 ORM relationships. Postgres defaults to NO ACTION for the rest.

WHY THIS MATTERS
Any delete outside the ORM relationship graph (raw SQL, maintenance script, admin
console, bulk session.execute(delete(...))) either raises a FK violation or orphans rows.
Deleting a User with Evidence / Mistake / FactorEvaluation / ReadinessSnapshot /
MarkOverrideAudit rows fails outright. This also blocks the data-erasure path the product
needs before it can answer a deletion request.

TASK
1. Produce a table of all 109 FKs with a decision per relationship: CASCADE, SET NULL, or
   RESTRICT. Do this as a reviewable artifact BEFORE writing any migration — this is a
   design exercise and the wrong choice destroys data.
2. Apply these defaults unless there is a specific reason otherwise:
   - Child rows that are meaningless without their parent (SubmissionFile -> Submission,
     QuestionMark -> Submission, LessonTopic -> Lesson): CASCADE.
   - Append-only audit tables (mark_override_audit, factor_evaluations,
     readiness_history) referencing an acting user: SET NULL or RESTRICT, NEVER CASCADE.
     Deleting a user must not silently erase audit history — that is the whole point of
     an append-only table.
   - Organization references: RESTRICT. Deleting an organisation should be deliberate
     and loud.
3. Write the Alembic migration(s) to add the constraints. Split across several
   migrations by domain rather than one 109-constraint change.
4. Add ondelete= to the model definitions too, so models and migrations agree
   (see AV-29 — this exact drift already exists for indexes).
5. Tests asserting cascade behaviour for a representative sample, particularly that
   deleting a user does NOT delete audit rows.

ACCEPTANCE
- The decision table is in the PR description and reviewed before merge.
- CI's migration job (up -> down -> up on Postgres 16) passes.
- `cd backend && python -m pytest` green.
- No audit table cascades from a user delete.

CONSTRAINTS
- Adding FK constraints to populated tables takes locks. Use ADD CONSTRAINT ... NOT VALID
  followed by VALIDATE CONSTRAINT in a separate step, so the exclusive-lock window is
  seconds rather than proportional to table size. Migration 0012 took production down by
  ignoring exactly this — read backend/alembic/versions/0012_organizations.py first and
  do not repeat its pattern.
- Deletion is deletion in this codebase — there are no soft deletes, deliberately. Do not
  introduce one here.
```

<a id="av-16"></a>
## AV-16 — Polymorphic "exactly one parent" invariant has no database constraint

**P4 · REVIEWED · Effort S**

**What's wrong.** A `Submission` must have exactly one of `assignment_id` / `past_paper_id`; a `QuestionMark` exactly one of `question_id` / `past_paper_question_id`. Both are `nullable=True` with **no `CheckConstraint`** — there are no CHECK constraints anywhere in the models.

**Why it matters.** A row with both set, or neither, is representable. `review_queue` outer-joins both and picks whichever is non-null, so a both-set row silently shows the wrong parent, and a neither-set row disappears from every listing that joins through one side. The existing unique constraints don't help — Postgres treats NULLs as distinct.

```text
CONTEXT
Repo: Avora. Per ADR-0004, submissions are polymorphic: exactly one of assignment_id
(homework) or past_paper_id (past paper) must be set. Same shape for QuestionMark:
exactly one of question_id / past_paper_question_id. Both pairs are nullable=True with no
CheckConstraint — there are no CHECK constraints anywhere in backend/app/models/.

WHY THIS MATTERS
A row with both FKs set, or neither, is representable. `review_queue`
(backend/app/api/submissions.py:400+) outer-joins both parents and picks whichever is
non-null — a both-set row silently shows the wrong parent; a neither-set row vanishes from
every listing that joins through one side. The existing UniqueConstraints on
(assignment_id, student_id) and (past_paper_id, student_id) do not prevent either case,
because Postgres treats NULLs as distinct.

TASK
1. Add CHECK constraints in the models and a matching Alembic migration:
     CheckConstraint("(assignment_id IS NOT NULL) <> (past_paper_id IS NOT NULL)",
                     name="ck_submissions_exactly_one_parent")
   and the QuestionMark equivalent.
2. Before adding them, query for existing violating rows and report the count. If any
   exist, stop and escalate — do not delete or "repair" them without a human decision.
3. Add the constraint with NOT VALID first, then VALIDATE CONSTRAINT in a separate step,
   to keep the lock window short (see AV-15).
4. Tests asserting the database rejects both-set and neither-set rows.

ACCEPTANCE
- Violating rows cannot be inserted.
- CI's migration job passes.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- The test suite runs on SQLite (backend/tests/conftest.py builds from
  Base.metadata.create_all). SQLite supports CHECK constraints, but verify the syntax
  works on BOTH SQLite and Postgres — `<>` on booleans is the sort of thing that differs.
  If it doesn't port, use the equivalent
  ((a IS NOT NULL AND b IS NULL) OR (a IS NULL AND b IS NOT NULL)) form.
- Enums here are VARCHAR (native_enum=False) by deliberate decision. Do not convert
  anything to a native enum while you are in these models.
```

---

# P2 — Operational blindness

<a id="av-17"></a>
## AV-17 — Nothing alerts on anything

**P2 · DOCUMENTED · Effort S · Best effort-to-value ratio in this document.**

**What's wrong.** `GET /api/v1/health/ready` accurately reports database reachability, worker liveness, and queue depth including pending/running/failed counts. Nobody polls it. There is no alerting, no error tracking, no metrics, no uptime monitor.

**Why it matters.** Detection time equals "however long until a tutor complains." Every runbook in the operations documentation begins with a human noticing. The diagnosis capability is genuinely good; the detection capability is zero.

This is the cheapest fix in this entire register — an external uptime monitor is minutes of configuration — and it changes AV-4, AV-5, AV-6 and AV-18 from silent to visible.

```text
CONTEXT
Repo: Avora. `GET /api/v1/health/ready` (backend/app/main.py) already reports database
reachability, background-worker state, and queue pending/running/failed counts, returning
503 when the database is unreachable or the worker has stopped turning. `GET
/api/v1/health` is a deliberately shallow liveness probe used by Render's healthCheckPath
(a DB round trip there would turn a blip into a restart loop — do not change it).

THE GAP
Nothing polls /health/ready. No alerting, no error tracking, no metrics. Detection time
is "until a tutor complains." This is the residual of RISK-4 and it is mostly
configuration, not code.

TASK
1. Point an external uptime monitor (Better Stack, Healthchecks.io, UptimeRobot — any)
   at /api/v1/health/ready with alerts to a channel a human actually reads. Minutes of
   work; do it first.
2. Add error tracking. Sentry's FastAPI and React integrations are the obvious choice.
   Ensure PII scrubbing is configured before enabling — this application handles minors'
   data, so student names, emails and handwriting file paths must not leave the system in
   an error payload. Verify scrubbing works before pointing it at production.
3. Alert on the signals that already exist but are unwatched:
   - failed job count above zero (see AV-18),
   - oldest-pending-job age above a threshold,
   - uploads disk usage above 70% (AV-13),
   - AI spend per day above a threshold (AV-31).
4. Add a build/revision identifier to the health response. "Is the fix deployed?"
   currently requires reading the Render dashboard. Inject it at build time in the
   Dockerfile.
5. Record what alerts exist, what each means, and who responds, in
   docs/volume-4-reliability-and-operations/11-reliability-sre.md and
   docs/governance/ownership.md.

ACCEPTANCE
- A deliberately stopped worker produces an alert to a human within minutes. Test this
  by actually breaking it in a non-production environment.
- Errors from both frontend and backend reach the tracker with PII scrubbed — verify by
  inspecting a real captured event.
- /api/v1/health reports the running revision.

CONSTRAINTS
- Do NOT change what Render's healthCheckPath points at. The shallow/deep split is
  deliberate and the reasoning is in render.yaml's comments.
- Scrub PII before enabling error tracking, not after. Verify with a real event.
- Free tiers are sufficient at current volume. Cost is not a reason to defer this.
```

<a id="av-18"></a>
## AV-18 — Failed jobs are terminal with no dead-letter queue

**P2 · DOCUMENTED · Effort M**

**What's wrong.** After 2 attempts a job is marked `failed`, logged at error level, and forgotten. There is no dead-letter queue, no re-enqueue path, and no metric. Recovery requires someone writing SQL. The retry policy is a single attempt at a fixed 60 seconds — no exponential backoff, no jitter, no per-error-class handling.

**Why it matters.** A provider outage lasting more than a minute exhausts the retry budget for every job in flight. A burst of failures retries in lockstep. And when they finally fail, marking has stopped for those submissions with nobody told — this is the mechanism underneath AV-2, AV-4 and AV-5.

```text
CONTEXT
Repo: Avora. `backend/app/workers/jobs.py`: MAX_ATTEMPTS = 2, RETRY_BACKOFF_SECONDS = 60
fixed, POLL_SECONDS = 2.0. A job that fails twice is marked JobStatus.failed, logged at
error, and forgotten — no dead-letter queue, no re-enqueue path, no metric. Recovery is a
manual SQL statement. The `run_after` column is the existing scheduling primitive and
already supports delayed re-claim.

TASK
1. Improve the retry policy: exponential backoff with jitter, and a larger attempt budget
   for transient error classes (network, provider 5xx, provider rate limit) than for
   deterministic ones (malformed payload, missing row — retrying those is pure waste).
   Build on `run_after`; do not add a scheduler.
2. Add a re-enqueue path for terminally failed jobs: a tutor- or admin-gated endpoint, or
   at minimum a documented, safe script. All 8 handlers are idempotent by design (their
   mechanisms are tabulated in docs/volume-2-application-engineering/
   04-backend-engineering.md) — verify that claim for each handler before relying on it,
   and say so in the PR.
3. Expose failed jobs operationally: extend the /health/ready payload or add an ops
   endpoint listing failed jobs with type, age and error. Wire an alert (AV-17).
4. Distinguish "failed and retryable" from "failed and needs a human" in the Job row, so
   an automated re-enqueue cannot loop forever on a deterministic failure.
5. Tests in backend/tests/test_jobs.py: backoff grows across attempts; a re-enqueued job
   runs and succeeds; a deterministic failure is not retried indefinitely.

ACCEPTANCE
- Tests fail before, pass after.
- `cd backend && python -m pytest` green.
- A failed job is discoverable and recoverable without writing SQL.

CONSTRAINTS
- Handlers must remain idempotent (rule BE-6) — re-enqueue depends on it entirely.
- Do not introduce Redis, Celery, or any external queue. "Background work is rows in the
  Postgres jobs table" is a deliberate architectural decision (ADR-0002) with a stated
  revisit trigger that has not fired. Build on run_after.
- The job claim uses FOR UPDATE SKIP LOCKED and is already safe for concurrent workers.
  Do not break that — AV-26 depends on it.
```

<a id="av-19"></a>
## AV-19 — No request IDs, no error tracking, almost no logging

**P2 · DOCUMENTED · Effort M**

**What's wrong.** No logging configuration and only two loggers in the entire backend. No request IDs anywhere. No metrics. `backend/app/services/google_classroom.py` — a module making live third-party API calls with multiple silent-skip paths — has **no logging import at all**.

**Why it matters.** A user-reported error cannot be tied to a log line. An incident could not be reconstructed. Unhandled exceptions go to stdout on one container and are lost on restart.

```text
CONTEXT
Repo: Avora. No logging configuration exists; only two loggers in the whole backend. No
request/correlation IDs. No metrics. backend/app/services/google_classroom.py has no
logging import at all despite making live third-party calls with several bare `continue`
skip paths (see AV-6, AV-21).

TASK
1. Add central logging configuration in backend/app/main.py: structured JSON output,
   level from an env var, one consistent format. Render captures stdout, so this is
   about content and shape, not transport.
2. Add request-ID middleware: generate or accept X-Request-ID, attach it to every log
   line for that request, and return it in the response headers so a user-reported error
   can be traced to a log line. Propagate it into job payloads so background work
   triggered by a request stays correlated.
3. Add logging where failures are currently silent — google_classroom.py first (it has
   none), then every bare `except ... : continue` or `pass` across backend/app/services/.
   Grep for them and report the list.
4. Surface the request ID in the frontend's error display (frontend/src/api/client.ts and
   error UI) so a user can quote it in a support message.
5. Never log: passwords, tokens, JWT contents, API keys, student names, email addresses,
   or file contents. Add a redaction helper and use it.

ACCEPTANCE
- Every request logs with a correlation ID, and that ID is returned to the client.
- A background job's logs can be traced back to the request that enqueued it.
- No PII in any log line — verify by inspecting real output from a local run.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- Do not log request bodies. This application handles minors' academic data and
  handwriting file references.
- Keep it dependency-light: Python's stdlib logging plus a formatter is sufficient. Do
  not add a heavyweight observability framework — "no unnecessary complexity" is an
  explicit project non-goal.
- Pairs naturally with AV-17. Sequence them together.
```

<a id="av-20"></a>
## AV-20 — `sync_classroom` has no per-item error isolation

**P2 · REVIEWED · Effort S**

**What's wrong.** `backend/app/services/google_classroom.py:268-286` loops over every course link, every piece of coursework, and every turned-in submission, making live Google API calls per item — **with no try/except anywhere**. Any single failure propagates out and fails the whole job for every other item.

**Why it matters.** One Drive file that 404s, one course the token lost access to, one transient Google 5xx, and the entire tutor's sync fails. With 2 attempts and no scheduled re-trigger (sync is on-demand only), the job goes to `failed` and nothing retries until the tutor manually clicks sync. A single flaky roster entry can silently stop importing homework for an entire class.

```text
CONTEXT
Repo: Avora. `backend/app/services/google_classroom.py:268-286` (`sync_classroom`) loops
over every ClassroomCourseLink for an account and, per link, every coursework item and
every turned-in submission, making live Google API calls per item (get_student_profile,
download_drive_file). There is no try/except around any of it. `_sync_course` (288-318)
and `_sync_submissions` (321-366) are the same. MAX_ATTEMPTS is 2 and this job type is
only enqueued on demand — there is no scheduler — so a job that fails twice stops until
the tutor manually clicks sync again.

TASK
1. Wrap each course, each coursework item and each submission iteration in its own
   try/except. Log and continue on a single item's failure; only genuinely account-level
   failures (token refresh failure, revoked authorisation) should abort the whole job.
2. Accumulate per-item failures and surface them: return a summary the tutor can see in
   frontend/src/tutor/ClassroomSettingsPage.tsx — "synced 24 items, 2 failed" with
   reasons — rather than an all-or-nothing outcome.
3. Only update `link.last_synced_at` to reflect what actually succeeded. Today it is set
   as though the sync fully succeeded even when items were skipped (see AV-21).
4. Distinguish retryable failures (5xx, rate limit) from permanent ones (404, permission
   denied) so a retry is worth attempting.
5. Tests in backend/tests/test_classroom.py, using the existing mocked-API pattern: one
   failing item does not prevent the other items in the same sync from importing.

ACCEPTANCE
- Test fails before, passes after.
- `cd backend && python -m pytest` green.
- A single bad item cannot stop a whole class's import.

CONSTRAINTS
- sync_classroom must stay idempotent — ClassroomWorkLink makes re-polling safe. Preserve it.
- Keep the deliberate policy of skipping (never guessing) unmatched students and
  unsupported attachment types. This is about isolation and visibility, not about
  importing more.
- Overlaps AV-6 and AV-21, all in this file. Consider doing all three in one PR.
```

<a id="av-21"></a>
## AV-21 — Classroom silently drops unmatched students and attachments

**P2 · REVIEWED · Effort S**

**What's wrong.** `google_classroom.py:335-343` skips a submission when the Classroom roster email matches no Avora account — `continue`, no log, no record. Lines 381-386 skip an attachment that fails validation the same way. `link.last_synced_at` is still updated as though everything succeeded.

**Why it matters.** Real turned-in student work is dropped with zero trace. There is no signal anywhere that anything was skipped. A tutor whose student's work never arrived has no way to discover why — and the most likely cause (the student's Classroom email differs from their Avora account email) is trivially fixable *if anyone knew*.

The skip-rather-than-guess policy is correct. The silence is not.

```text
CONTEXT
Repo: Avora. In backend/app/services/google_classroom.py:
- 335-343: a turned-in submission is skipped when the Classroom roster email matches no
  Avora student account — bare `continue`, no logging, no record.
- 381-386: an attachment failing validation (oversize, MIME mismatch) is skipped the same
  way.
`link.last_synced_at` is updated as though the sync fully succeeded.

The skip-rather-than-guess policy is CORRECT — attaching one student's work to another's
record would be far worse. The problem is that it is invisible.

TASK
1. Log every skip with full context: course id, coursework id, roster email (see PII note
   below), student id where known, attachment name, and the reason.
2. Persist skips so a tutor can act on them. The most common cause — a student whose
   Classroom email differs from their Avora account email — is trivially fixable IF
   anyone knows. Add a lightweight record (new table or a JSON summary on
   ClassroomCourseLink; choose and justify) and surface it in
   frontend/src/tutor/ClassroomSettingsPage.tsx.
3. Consider offering a resolution action: let the tutor map an unmatched roster email to
   an existing student. Design it so the tutor makes the decision explicitly — never
   fuzzy-match automatically.
4. Only mark the sync fully successful when nothing was skipped; otherwise report partial
   success with a count.
5. Tests in backend/tests/test_classroom.py: an unmatched roster email produces a visible,
   queryable skip record rather than silence.

ACCEPTANCE
- Test fails before, passes after.
- `cd backend && python -m pytest` green.
- A tutor can see what was skipped and why, without reading logs.

CONSTRAINTS
- Roster emails are personal data belonging to minors. Store them only if the tutor needs
  them to resolve the mismatch, and cover them by the retention policy (compliance gap).
  Do not log them at info level — use debug, or log a hash plus the student's display name.
- Never auto-match on anything but an exact email. Guessing is the failure mode this
  policy exists to prevent.
- Overlaps AV-6 and AV-20 in the same file — consider one combined PR.
```

---

# P3 — Performance and scale

<a id="av-22"></a>
## AV-22 — Blocking CPU and disk I/O on the shared event loop

**P3 · VERIFIED · Effort M · Two independent reviewers rated this critical.**

**What's wrong.** `backend/app/services/storage.py` performs synchronous, CPU-bound and blocking-I/O work directly on the asyncio event loop:

- `_to_jpeg` (line 35-45) — PIL HEIC→JPEG decode and re-encode, pure CPU
- `_write` (line ~148) — synchronous `Path.write_bytes`
- `read_file` (line ~162) — synchronous `Path.read_bytes`

Called from async request handlers (`submissions.py:134`, `past_papers.py:144-145,325`, `classifieds.py:35,46`, `resources.py:81`, `syllabus_uploads.py:43`, `assignments.py:40,54`) **and** from job handlers (`marking.py:134,139,169,174,234` — up to 5 files per submission; `extraction.py:94,98,198,201`; `syllabus_extraction.py:62`; `google_classroom.py:382`).

**Why it matters.** The background worker runs **inside the API process, on the same event loop** (`main.py` lifespan). So a single student uploading an iPhone photo blocks *everything* — every other student's page load, every tutor's dashboard, and the job worker's own polling — for 150ms to over a second per photo.

This is worst at homework deadlines, the app's single most concentrated traffic pattern, when many students upload at once. It directly violates the project's own rule BE-13.

```text
CONTEXT
Repo: Avora. FastAPI, fully async. CRITICAL ARCHITECTURAL FACT: the background job worker
runs INSIDE the API process on the SAME asyncio event loop (backend/app/main.py lifespan,
_supervised_worker). Rule BE-13 states: never make a blocking call in a request handler,
service, or job handler, because it stalls request serving for every user.

BUG — the rule is violated in the hottest path in the product
backend/app/services/storage.py runs synchronous work directly on the loop:
  - _to_jpeg (~line 35-45): PIL HEIC->JPEG decode + re-encode. Pure CPU, 150ms-1s+ for a
    typical 3-12MP iPhone photo.
  - _write (~line 148): synchronous Path.write_bytes
  - read_file (~line 162): synchronous Path.read_bytes

Call sites — request handlers (via save_upload):
  app/api/submissions.py:134, past_papers.py:144-145,325, classifieds.py:35,46,
  resources.py:81, syllabus_uploads.py:43, app/services/assignments.py:40,54
Call sites — job handlers (worse; blocks the worker that must keep turning):
  app/services/marking.py:134,139,169,174,234 (up to 5 files per submission),
  extraction.py:94,98,198,201, syllabus_extraction.py:62, google_classroom.py:382

IMPACT
One student uploading a photo freezes the entire API and the job worker for the duration.
Worst at homework deadlines — the most concentrated traffic this app sees.

TASK
1. Move all three functions off the event loop with asyncio.to_thread (Python 3.11).
   `read_file` and `save_bytes` currently have sync signatures called from async code, so
   their callers need `await` too — update every call site listed above.
2. Also wrap `file_block`'s base64 encoding in backend/app/services/ai.py:147 — it
   base64-encodes up to 20MB per file, 2-7 times per marking/extraction job. Smaller than
   the transcode but the same category and the same fix.
3. Consider bounding concurrent transcodes with a semaphore. The API instance is a Render
   `starter` plan; several simultaneous large-image decodes could exhaust memory. Pick a
   small limit (2-4), make it configurable, and say why you chose the number.
4. Verify with a test or a measurement that the loop is no longer blocked — e.g. assert a
   concurrent lightweight request completes while a large HEIC upload is in flight.

ACCEPTANCE
- No synchronous file or image operation remains on the event loop in storage.py or ai.py.
- `cd backend && python -m pytest` green.
- Demonstrated: a health check responds promptly during a large upload.

CONSTRAINTS
- Preserve the upload validation semantics EXACTLY: magic-byte checking, the 20 MB cap
  enforced both before and after HEIC transcoding (the ordering is deliberate and
  commented — read it), and server-generated random filenames. A security review
  confirmed this layer is sound.
- HEIC transcoding must stay. iPhones shoot HEIC by default and it is most of what
  students upload; the marking pipeline cannot accept it.
- Do NOT move the worker to a separate process in this PR. That is AV-27 and it has two
  other prerequisites.
- If AV-13's S3 migration is happening, coordinate — S3 calls are async-natively and much
  of this disappears.
```

<a id="av-23"></a>
## AV-23 — 109 foreign keys, zero indexed

**P3 · VERIFIED · Effort M**

**What's wrong.** I confirmed directly: 109 `ForeignKey(` declarations across the models, **zero** `index=True`, and exactly **one** `Index(` declaration in the entire model layer (on `jobs`). Postgres does not auto-index foreign keys.

The worst single case: `GroupMember.student_id`. It has only a composite `UniqueConstraint("group_id", "student_id")`, whose backing btree serves `group_id`-led lookups — not `student_id`-led ones. There are **27 call sites** filtering `GroupMember.student_id ==`, and they drive the access-control check ("may this viewer see this student") on nearly every authenticated request.

**Why it matters.** Every FK filter and every join is a sequential scan. This is what converts each N+1 in AV-24 from "N fast lookups" into "N table scans." It compounds monotonically: `evidence`, `factor_evaluations` and `ai_usage_events` grow every day and are never pruned.

```text
CONTEXT
Repo: Avora, Postgres + async SQLAlchemy 2.0, 52 tables.
VERIFIED COUNTS: 109 `ForeignKey(` declarations in backend/app/models/*.py; 0 with
index=True; exactly 1 `Index(` declaration in the model layer (on `jobs`, homework.py:312).
Postgres does NOT auto-index foreign keys — only primary keys and unique constraints.

WORST CASE — do this one first
`GroupMember.student_id` (backend/app/models/groups.py) has only a composite
UniqueConstraint("group_id", "student_id"), whose btree serves group_id-led lookups, not
student_id-led. There are 27 call sites filtering `GroupMember.student_id ==` — including
app/api/me.py:23,40, readiness.py:43,68, submissions.py:101,229,278, assessments.py:37,207,268,
students.py:64,84, groups.py:91,137,187, lessons.py:162, past_papers.py:70, classifieds.py:80,
resources.py:26, auth.py:200, services/reports.py:118,144, readiness_v2.py:150,241,
readiness_v2_ai.py:301, student_crm.py:69,111, readiness.py:162. This column drives the
"may this viewer see this student" check on nearly every authenticated request.

TASK
1. Add Index("ix_group_members_student_id", "student_id") to GroupMember. Ship this alone
   first — it is the highest-value single line in this issue.
2. Index the remaining FKs that are actually queried. Do not blanket-index all 109 —
   every index costs write throughput. Derive the list from real query patterns; at
   minimum: submissions.student_id, submissions.assignment_id, submissions.past_paper_id,
   question_marks.submission_id, topic_readiness.student_id, topic_readiness.topic_id,
   ai_usage_events.organization_id, ai_usage_events.tutor_id, group_members.group_id,
   mistake.student_id, and every organization_id column (12 of them, all filtered for
   tenant scoping).
3. Add composite indexes where queries filter on multiple columns, ordered by selectivity.
4. Add `Index("ix_jobs_type_status", "type", "status")` — the debounce check in
   readiness_v2_ai.py filters on (type, status) and the existing (status, run_after) index
   does not serve it. See AV-24.
5. Declare every index in BOTH the model and the migration (see AV-29 — this drift
   already exists).
6. In the migration, use CREATE INDEX CONCURRENTLY for production safety. Note that
   CONCURRENTLY cannot run inside a transaction — use Alembic's autocommit_block().

ACCEPTANCE
- CI's migration job (up -> down -> up on Postgres 16) passes.
- `cd backend && python -m pytest` green.
- The PR states, per index, which query it serves. An index nobody can name a query for
  should not be added.

CONSTRAINTS
- Do not index columns that are never filtered. Write cost is real, especially on
  append-only tables written by every job run.
- The test suite runs on SQLite and will not exercise Postgres query plans. Validate
  plans with EXPLAIN against a Postgres instance with representative data — CI cannot
  do this for you.
- Coordinate with AV-15 (ondelete) — both touch the same models and can share migrations.
```

<a id="av-24"></a>
## AV-24 — N+1 query cluster across seven confirmed sites

**P3 · REVIEWED · Effort M**

**What's wrong.** Seven confirmed sites, all loops issuing per-iteration queries:

| Site | Shape |
|---|---|
| `app/api/analytics.py:49-74` | Per student: `db.get(User)` + a `TopicReadiness` select. 30 students → 60+ queries where 2 would do |
| `app/services/readiness_v2.py:317-333` | Per topic: one query each. 40-80 topics per subject |
| `app/services/readiness_summary.py:26-38` | Per subject: 3 queries. 8 subjects → 24 instead of 3 |
| `app/services/reports.py:51-133` | Per subject: up to 6 queries, inside a background job |
| `app/services/student_crm.py:85-96, 118-145` | Per enrolment and per homework row |
| `app/api/submissions.py:400-433` | Per queue row: 2 more queries. 50 submissions → 100+ extra |
| `app/services/readiness_v2_ai.py:70-77` | **Worst.** Unbounded `SELECT` over pending jobs with no `LIMIT`, deduped in Python, on *every* call |

**Why it matters.** The last one fans out catastrophically. Both `readiness_weights.py:72` and `preferences.py:58` loop over every student a tutor teaches calling `enqueue_readiness_v2_debounced`, which runs that unbounded scan each time. A tutor saving weight sliders once for a 30-student group can trigger thousands of queries, all serialized through the single worker on the shared event loop.

```text
CONTEXT
Repo: Avora, async SQLAlchemy 2.0. Seven confirmed N+1 sites. Note these compound with
AV-23 (109 FKs, zero indexed), so each "N queries" is currently "N sequential scans", and
with AV-22/AV-26 (single worker, shared event loop), so background fan-out stalls request
serving.

SITES, worst first
1. app/services/readiness_v2_ai.py:70-77 — `enqueue_readiness_v2_debounced` runs an
   UNBOUNDED `SELECT Job.payload WHERE type='compute_readiness_v2' AND status='pending'`
   with no LIMIT, filtered and deduped in PYTHON, on every single call. Callers loop over
   students: app/api/readiness_weights.py:64-73 and app/api/preferences.py:51-59. A tutor
   saving weight sliders for a 30-student group runs that full scan 30+ times.
2. app/services/readiness_v2.py:317-333 — one query per topic (40-80 per subject), fanned
   out per student by the callers above.
3. app/api/analytics.py:49-74 — per student: db.get(User) + a TopicReadiness select.
   30 students = 60+ queries. Tutor-facing page, opened repeatedly during live sessions.
4. app/api/submissions.py:400-433 (review_queue) — 2 extra queries per row (unsure count,
   _open_remarks). 50 submissions = 100+ extra queries per page load.
5. app/services/reports.py:51-133 — up to 6 queries per subject, inside a background job.
6. app/services/readiness_summary.py:26-38 — 3 queries per subject.
7. app/services/student_crm.py:85-96 and 118-145 — per enrolment and per homework row.

TASK
1. Fix site 1 first — highest multiplier. Filter in SQL rather than Python: Postgres JSON
   `payload->>'student_id'` comparison, or use `select(exists().where(...))` since dedup
   only needs existence, not rows. Add the (type, status) index from AV-23. Consider a
   batched "enqueue debounced for these N students" call so the per-student loop
   disappears entirely.
2. Fix sites 2-7 with the standard pattern: one query using `WHERE id IN (...)`, build a
   dict in memory, then iterate. `_topic_coverage` at readiness_v2.py:225-263 already does
   this correctly with two bulk queries — copy that shape rather than inventing another.
3. Add a test that asserts query COUNT for the worst offenders, so a regression is caught.
   SQLAlchemy event listeners can count executions; wire one into a pytest fixture.

ACCEPTANCE
- Query count for a 30-student group analytics load drops from 60+ to a small constant.
- `enqueue_readiness_v2_debounced` no longer scans the full pending-jobs table per call.
- Query-count regression tests exist for at least sites 1, 2 and 3.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- Behaviour must not change — same results, fewer queries. Readiness figures before and
  after must be identical for the same input.
- Do not add eager loading globally as a shortcut; it moves the cost rather than removing
  it and can make unrelated queries much heavier.
- Do these AFTER or WITH AV-23. Fixing N+1 without indexes leaves the remaining queries
  scanning; adding indexes without fixing N+1 leaves the round-trip count.
- Site 1's callers (readiness_weights.py, preferences.py) are user-facing saves. Verify
  the tutor's save still feels instant.
```

<a id="av-25"></a>
## AV-25 — 29 list endpoints, zero pagination

**P3 · VERIFIED · Effort L**

**What's wrong.** I confirmed exactly: **29 list-returning GET endpoints, 29 of them with no `limit`, `offset`, `page` or cursor parameter.** Nothing in the codebase caps a result set.

**Why it matters.** Several back tables that only ever grow — `evidence`, `factor_evaluations`, `ai_usage_events`, `mark_override_audit`, `chat_messages`, `reports`, `submissions`. `GET /ai-usage/analytics` aggregates the entire usage table per organisation with no date bound and no index on `organization_id`.

Nothing breaks today on a fresh database. It breaks with no code change at all — just calendar time. This is a guaranteed future incident with a known date-shaped trigger.

```text
CONTEXT
Repo: Avora. VERIFIED: 29 list-returning GET endpoints across backend/app/api/, and 29 of
them accept no limit/offset/page/cursor parameter. Nothing caps any result set.

Endpoints backed by monotonically growing tables are the urgent subset: evidence,
factor_evaluations, ai_usage_events, mark_override_audit, chat_messages, reports,
submissions. `GET /ai-usage/analytics` (app/api/ai_usage.py:22-33,78-92) aggregates the
whole ai_usage_events table per organisation with no date bound and no index on
organization_id (AV-23).

This will not break today. It will break with no code change — only time.

TASK
1. Add pagination to all 29. Prefer cursor-based (`WHERE id > :last_id ORDER BY id LIMIT
   :n`) over OFFSET for append-only tables, where OFFSET degrades linearly.
2. Order by urgency: review_queue, reports, chat conversations/messages, ai_usage
   analytics, and anything reading evidence / factor_evaluations / mark_override_audit
   first. Purely bounded lists (subjects, a group's schedule slots) can come later.
3. Choose a default and a maximum page size (50 default / 200 max is reasonable) and
   apply them consistently. Document the choice in
   docs/volume-2-application-engineering/05-api-standards.md, which already has a rule
   (API-12) binding new endpoints only.
4. Add a date bound to the AI usage analytics queries — default to trailing 90 days with
   an explicit all-time opt-in.
5. Update the matching TypeScript clients in frontend/src/api/*.ts and the pages that
   consume them. Infinite scroll or an explicit "load more" — pick one and be consistent.
6. Tests: an endpoint returns at most the page size; the cursor walks the full set
   without gaps or duplicates.

ACCEPTANCE
- No endpoint can return an unbounded result set.
- Frontend handles paginated responses without regression.
- `cd backend && python -m pytest` and `cd frontend && npm test` green.

CONSTRAINTS
- This is a breaking API change for every affected endpoint. The frontend is the only
  consumer, so ship both sides together in one PR per endpoint group — rule FE-4 requires
  it and nothing enforces it automatically (AV-36).
- Do not paginate an endpoint whose consumer needs the complete set to compute something
  correct. Check each caller before changing it.
- Ship in several PRs grouped by domain. One PR touching 29 endpoints plus their clients
  is unreviewable.
```

<a id="av-26"></a>
## AV-26 — The job worker is strictly serial

**P3 · REVIEWED · Effort S**

**What's wrong.** `backend/app/workers/jobs.py` processes exactly one job at a time — claim, run to completion including the AI network call, then poll again after 2 seconds. There is no concurrency.

**Why it matters.** Marking, extraction, readiness synthesis, report generation and Classroom sync all queue behind each other. AI vision-marking calls take seconds to tens of seconds. Ten submissions near a deadline means the last student waits minutes. Queue wait is the user-visible latency for every AI surface in the product.

The good news: the claim query already uses `FOR UPDATE SKIP LOCKED`, so it was **built** for concurrent workers. It's simply never invoked with more than one.

```text
CONTEXT
Repo: Avora. backend/app/workers/jobs.py: `worker_loop` claims one job, runs it to
completion (including the AI network call), then polls again after POLL_SECONDS = 2.0.
No concurrency anywhere. All AI work — marking, extraction, readiness synthesis, reports,
Classroom sync — serializes through this one loop.

The claim query already uses `with_for_update(skip_locked=True)`, so it was designed for
concurrent claimers. It is simply never run with more than one.

TASK
1. Run N concurrent worker tasks, N from an env var (default 3-4). The existing
   SKIP LOCKED claim makes this safe with no query change — verify that claim, then
   confirm it in the PR.
2. Keep the supervision behaviour: `_supervised_worker` restarts a loop that raises OR
   returns cleanly, and re-raises CancelledError so shutdown works. Each of the N tasks
   needs the same treatment.
3. Update `/health/ready` to report per-worker state, not a single boolean.
4. Bound concurrency against the AI providers — N concurrent markings means N concurrent
   provider calls. Check provider rate limits and consider a semaphore around AI calls
   specifically, separate from worker count.
5. Tests in backend/tests/test_jobs.py: two workers claim different jobs and never the
   same one; a job that fails in one worker does not affect another.

ACCEPTANCE
- N jobs run concurrently; no job is claimed twice.
- `cd backend && python -m pytest` green.
- Health endpoint reports each worker.

CONSTRAINTS
- DO THIS AFTER AV-22. While blocking calls remain on the event loop, more concurrent
  workers make contention worse, not better — they all share one loop. AV-22 is the
  prerequisite and this is close to worthless without it.
- Handlers must be idempotent (rule BE-6) and must never overwrite a tutor-finalized
  value (BE-7). More concurrency means more chances to expose a violation — re-verify.
- This does NOT lift the single-instance constraint (AV-27); it is concurrency within one
  process. Do not confuse the two.
```

<a id="av-27"></a>
## AV-27 — Single-instance ceiling: three constraints break together

**P3 · DOCUMENTED · Effort L**

**What's wrong.** Three independent things pin the API to exactly one instance, and all three break the moment you add a second:

1. `render.yaml` mounts a persistent disk for uploads; a Render service with a disk runs one instance. `services/storage.py` writes to local disk.
2. The job worker runs **inside the API process**.
3. `services/rate_limit.py` is a process-global dict — with two instances the login throttle becomes per-instance and its effective limit doubles.

**Why it matters.** Every deploy is downtime. Any instance loss is a full outage. And this ceiling is hit exactly when things are going well — the work takes weeks, and it becomes urgent the day a tutoring centre signs.

The documented unwind order is: storage to S3 → worker to its own service → rate limiter to Postgres or Redis.

```text
CONTEXT
Repo: Avora. Three independent constraints pin the API to exactly one instance:
1. render.yaml mounts a 10 GB persistent disk for uploads; a Render service with a disk
   runs a single instance. backend/app/services/storage.py writes to local disk.
2. The background job worker runs inside the API process (backend/app/main.py lifespan).
3. backend/app/services/rate_limit.py is a process-global dict, so with two instances the
   login throttle becomes per-instance and the effective limit multiplies by instance count.
Consequences today: every deploy is downtime; any instance loss is a full outage.

The documented unwind order (docs/volume-3-platform-engineering/08-infrastructure-and-
deployment.md) is: storage to object storage, then worker to its own service, then rate
limiter to a shared store. Follow it — the order matters.

TASK — one PR per step, in this order
1. Object storage. Largely covered by AV-13; this is the same work. Once uploads are in
   S3 the disk can be unmounted, which is what actually releases the single-instance pin.
2. Extract the worker into its own Render service running the same image with a different
   entrypoint. The job table's FOR UPDATE SKIP LOCKED claim already makes multiple workers
   safe. Keep worker health reporting working (AV-17, AV-26).
3. Move rate limiting to a shared store. Postgres is the default choice here — "no Redis,
   no external queue, no message broker" is an explicit project non-goal whose stated
   revisit trigger is exactly this moment. If you propose Redis, write the ADR that
   reverses the non-goal, per docs/governance/non-goals.md: name the trigger, the cost,
   who pays it, and what becomes permanently harder.
4. Only after all three: raise instance count and confirm zero-downtime deploys.

ACCEPTANCE
- Each step ships independently and leaves the system working.
- After step 3, two instances run correctly: no lost uploads, no duplicated job execution,
  a login throttle that holds across instances.
- `cd backend && python -m pytest` green at every step.

CONSTRAINTS
- Do not attempt all three at once. Each is independently valuable and independently
  risky.
- There is no staging environment (a documented gap). Either create one first or plan a
  careful production rollout with a tested rollback — do not discover this in production.
- Steps 1 and 2 are worth doing on their own merits even if you never add an instance:
  step 1 closes the data-loss risk, step 2 stops slow jobs stalling request serving.
```

<a id="av-28"></a>
## AV-28 — `factor_evaluations` grows unbounded with no retention

**P3 · DOCUMENTED · Effort M**

**What's wrong.** `factor_evaluations` is append-only: roughly 6 subject-level rows plus one row per topic per run. For a 30-topic subject that's ~36 rows per run, and runs are triggered by marking, assessments, lessons and weight changes — per student, per subject. No retention policy is implemented. Its only index is `(evaluation_run_id, student_id, subject_id)`, which is useless for a time-based delete.

**Why it matters.** The fastest-growing table in the schema, on the most frequent background job, sitting on a `basic-256mb` database plan. A future `DELETE ... WHERE created_at < ?` would be a full-table scan and a mass-delete lock with heavy bloat.

```text
CONTEXT
Repo: Avora. `factor_evaluations` (backend/app/models/readiness_v2.py:202-226) is
append-only by deliberate design — one row per factor per run is what makes every readiness
number traceable (rule PROD-1). Each compute_readiness_v2 run writes ~6 subject-level rows
plus one per topic (~36 rows for a 30-topic subject). Runs are triggered from marking
(services/marking.py:357), assessments (api/assessments.py:129,249), lessons
(api/lessons.py:203) and weight changes (api/readiness_weights.py:73) — per student, per
subject. No retention policy is implemented. The only index is
(evaluation_run_id, student_id, subject_id), which cannot serve a time-based delete.
The Postgres plan is basic-256mb.

TASK
1. Define the retention policy as a product decision first, not a technical one. The
   append-only design exists for explainability — deleting history removes the ability to
   answer "why was this number what it was in March". Options: keep N most recent runs per
   (student, subject); keep everything for N months then thin to one run per week; keep
   the full current academic year. Get this decided and written into
   docs/volume-2-application-engineering/06-database-design.md (rule DB-20 is currently
   Draft) BEFORE implementing.
2. Implement it as a new job handler following the existing pattern in
   backend/app/workers/ — registered in main.py, idempotent, safe to re-run.
3. Prefer partitioning over row deletes. Monthly RANGE partitions on created_at make
   retention a DROP PARTITION — instant, no bloat, no long lock — rather than a mass
   DELETE. Apply the same to readiness_snapshots, which has the same shape.
4. If you keep row deletes instead, add a created_at-led index and delete in batches with
   commits between, never one large statement.
5. Do the same analysis for ai_usage_events and evidence, which also only grow. Report
   the projected growth rate of each per active student per month.

ACCEPTANCE
- A retention policy is written down and agreed before code lands.
- Pruning runs, is idempotent, and cannot delete rows still needed by a current snapshot.
- CI's migration job passes.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- NEVER delete rows a readiness snapshot still references. A snapshot whose factor rows
  are gone is exactly the unexplainable number rule PROD-1 exists to prevent.
- Do not touch `evidence` retention without a separate decision — it is the raw academic
  record and the most valuable data the company holds.
- Partitioning an existing populated table is a significant migration. Plan the cutover
  and test the rollback.
```

<a id="av-29"></a>
## AV-29 — Test schema diverges from production

**P4 · REVIEWED · Effort S**

**What's wrong.** Four of five production indexes exist **only in migrations**, not in the model definitions: `ix_evidence_student_topic`, `ix_factor_evaluations_run_student_subject`, `ix_readiness_snapshots_student_subject`, `ix_mark_override_audit_question_mark_id`. `tests/conftest.py` builds the test schema from `Base.metadata.create_all`, which only sees what the models declare.

**Why it matters.** No test ever exercises an indexed query plan. Worse, the models are now a source of truth that disagrees with the migrations — the next `alembic revision --autogenerate` will propose **dropping** these indexes. The fifth index (`ix_jobs_status_run_after`) is correctly declared in both places, proving the team knows the pattern.

```text
CONTEXT
Repo: Avora. backend/tests/conftest.py builds the test schema via
`Base.metadata.create_all` on SQLite, so it only sees indexes declared in
backend/app/models/. Four production indexes exist ONLY in migrations:
  - ix_evidence_student_topic            (alembic/versions/0004_readiness.py:44)
  - ix_factor_evaluations_run_student_subject (0016_readiness_v2_schema.py:169-173)
  - ix_readiness_snapshots_student_subject    (0016_readiness_v2_schema.py:194-198)
  - ix_mark_override_audit_question_mark_id   (0019_auto_marking_review_queue.py:51-55)
The fifth (ix_jobs_status_run_after) IS correctly declared in both the model
(app/models/homework.py:312) and migration 0018 — proving the intended pattern.

WHY THIS MATTERS
No test exercises a production query plan, and the models now disagree with the
migrations: `alembic revision --autogenerate` would propose DROPPING these four indexes.

TASK
1. Add matching Index(...) declarations to __table_args__ on Evidence, FactorEvaluation,
   ReadinessSnapshot and MarkOverrideAudit, exactly matching the migrations (same names,
   same columns, same order).
2. Verify the models and migration history now agree — run autogenerate against a
   Postgres shadow database and confirm it proposes an empty diff.
3. Add a CI guard so this drift cannot recur: an `alembic check` (or autogenerate-and-
   assert-empty) step against Postgres in .github/workflows/ci.yml. This closes the whole
   class of problem, not just these four.
4. Do this WITH AV-23, which adds many more indexes — the same rule applies to all of
   them and one migration is better than two.

ACCEPTANCE
- Models and migrations agree; autogenerate produces an empty diff.
- CI fails if a future model change is not reflected in a migration.
- CI's migration job passes.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- Do not add a migration that recreates existing indexes — they are already in the
  database. This is a model-layer declaration change only, to make metadata match
  reality. Confirm no migration is needed and say so.
- Do not switch the test suite to run migrations instead of create_all. That is a
  deliberate, documented decision (fast in-memory SQLite); migration correctness is
  answered by the separate CI job.
```

---

# P4 — AI safety, cost, and frontend correctness

<a id="av-30"></a>
## AV-30 — No prompt or model regression harness

**P4 · DOCUMENTED · Effort L**

**What's wrong.** Tests use a `fake_ai` fixture and never exercise a real model. Nothing measures whether a prompt change makes marking better or worse. There is also no model-upgrade playbook — and `GEMINI_MODEL`'s default is explicitly a placeholder.

**Why it matters.** A scheme-backed confident mark auto-finalizes and counts on a student's permanent record with no human in the loop. So a prompt regression — or a provider silently updating a model behind a floating alias — changes marks that count, and the only detection mechanism is students complaining.

```text
CONTEXT
Repo: Avora. Prompts live in backend/app/services/prompts.py, versioned, with the version
stamped on every record they produce — genuinely good traceability. Marking is on v3,
bumped when marks began counting without tutor review. But tests use the `fake_ai` fixture
and never call a real model, and nothing measures whether a prompt change improves or
degrades marking. A scheme-backed, confident mark auto-finalizes onto a student's permanent
record with no human in the loop (ADR-0009).

TASK
1. Build a golden set: 30-50 real marked questions with known-correct outcomes, spanning
   easy/medium/hard, with and without an official mark scheme, and including edge cases —
   blank answers, partially worked solutions, a page containing text that addresses the
   marker (the prompt-injection case rule AI-9 exists for).
2. Write an evaluation harness (backend/evals/ or similar) that runs the real marking
   prompt against the golden set and reports: exact-mark agreement rate, mean absolute
   error in marks, confidence calibration (how often is `high` confidence actually
   correct), and the auto-finalize rate.
3. Establish the current baseline and commit it. Without a baseline the harness cannot
   tell you anything.
4. Make it a gate: any change to a prompt or a model id must run the harness and compare
   against baseline. Run it manually or on-demand in CI, NOT on every PR — it costs real
   money and calls a live provider.
5. Write the model-upgrade playbook in docs/volume-3-platform-engineering/09-ai-platform.md:
   how a model change is validated before it reaches marking.
6. Fix the placeholder: GEMINI_MODEL's default is explicitly not a real model id. Either
   set a real default or make the app fail loudly at startup when the marking surface is
   routed to a placeholder.

ACCEPTANCE
- The harness runs against a real provider and produces the metrics above.
- A committed baseline exists.
- The process for prompt and model changes is documented.
- Deliberately degrading the marking prompt produces a visibly worse score — prove the
  harness detects a regression, don't assume it.

CONSTRAINTS
- The golden set contains real student work. Anonymise it and store it deliberately —
  do not commit identifiable minors' handwriting to the repository. Consider a private
  bucket referenced by the harness.
- Do not run this on every PR. It costs money per run and calls a live provider.
- Do not weaken the two safety instructions in the prompts to improve a score: the
  marking prompt's data-not-instructions rule and the chat prompt's anti-cheating rules
  are security controls (rules AI-8, AI-9). If a score improves by removing one, the
  score is wrong, not the rule.
```

<a id="av-31"></a>
## AV-31 — No AI spend cap; pricing table empty

**P4 · DOCUMENTED · Effort M**

**What's wrong.** Every AI call is metered into `ai_usage_events` — the hard part, and it's built. But there is **no enforcement**: no per-tutor allowance, no cap, no circuit breaker. And `AI_MODEL_PRICING` is `{}` in every environment, so spend is reported as `unpriced_call_count` rather than money.

**Why it matters.** Two distinct problems. Commercially, **nobody can currently answer what a customer costs to serve**, which blocks pricing a subscription whose entire model is "platform plus an AI allowance." Operationally, one tutor bulk-uploading a year of past papers spends whatever it spends.

The system is being deliberately honest — it refuses to record an unknown price as `$0` (rule AI-17). That's correct behaviour making a real gap visible.

```text
CONTEXT
Repo: Avora. Every AI call is metered at a single choke point (backend/app/services/ai.py
-> record_usage) into ai_usage_events with provider, model, prompt version, token counts
and cost_usd. Metering has no holes — that is the hard part and it is done. What is
missing is enforcement, and prices.

AI_MODEL_PRICING is `{}` by default and empty in every environment, so estimate_cost_usd
returns None, cost_usd is NULL, and GET /ai-usage/analytics reports unpriced_call_count.
That is deliberately correct (rule AI-17 forbids recording a fabricated price), but it
means cost is currently unmeasured. The business model is a tutor subscription including
an AI allowance, with student top-ups beyond it — so this blocks pricing.

TASK
1. Populate AI_MODEL_PRICING with real per-million-token prices for every model actually
   in use. Verify against current provider pricing pages; do not guess. Document where
   the numbers came from and when, since they change.
2. Backfill cost_usd for historical ai_usage_events where the model and token counts are
   known, so there is a usable cost history rather than a hard cutover.
3. Report cost per organisation, per tutor and per student over a period. Answer
   concretely: what does an average tutor cost per month?
4. Implement per-organisation budgets: a configurable monthly allowance, with a warning
   threshold and a hard cap. Decide what happens at the cap — degrade AI surfaces with a
   clear message, or block? Recommend degrading with a clear message rather than a
   silent failure, and say why.
5. Add a circuit breaker for anomalous spend: if an organisation's hourly spend exceeds
   N times its trailing average, stop and alert (AV-17). This catches the runaway case
   the allowance alone will not.
6. Surface remaining allowance to tutors in the frontend, so the cap is never a surprise.

ACCEPTANCE
- GET /ai-usage/analytics reports real money, not unpriced_call_count.
- A per-organisation cap is enforceable and tested.
- Exceeding the cap produces a clear user-facing message, never a silent failure or an
  unhandled error.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- Never fabricate a price. Rule AI-17: a model with no pricing entry records NULL and is
  reported as unpriced. Keep that behaviour for any model you cannot price.
- Keep enforcement at the single choke point in services/ai.py. A cap that call sites opt
  into is a cap with holes, exactly as metering would be.
- Do not break graceful degradation (rule AI-20): the app must still run when a provider
  key is missing.
- Two existing cost optimisations must survive: prompt caching of shared mark schemes
  (cache=True) and debounced readiness synthesis. Both are documented in §10.
```

<a id="av-32"></a>
## AV-32 — The auto-finalize threshold has never been calibrated

**P4 · DOCUMENTED · Effort S**

**What's wrong.** Marks auto-finalize when scheme-backed and of high/medium confidence. Whether that threshold is set correctly is measurable from data already in the database — tutor override rate on auto-finalized marks, and student remark-request rate. **Neither is computed.**

**Why it matters.** The single most consequential product decision — when a machine's judgement counts on a child's record without a human — is running on assumption. ADR-0009 explicitly names this as work to do "before adjusting the threshold," and it hasn't been done.

```text
CONTEXT
Repo: Avora. Per ADR-0009, a mark auto-finalizes — counting immediately, becoming
evidence, with no tutor action — if and only if it is both scheme-backed
(has_mark_scheme) and of high/medium confidence. The ADR's own "Revisit when" section
says the threshold should be reconsidered when the remark-request rate or the tutor
override rate on auto-finalized marks indicates miscalibration, and notes that both are
measurable from existing rows and NEITHER is currently measured.

The data is already there: MarkOverrideAudit rows (append-only, every tutor mark change),
RemarkRequest rows (one per question, ever, DB-enforced), and QuestionMark with
ai_model / ai_prompt_version / confidence stamped on each.

TASK
1. Compute and expose these metrics, sliced by confidence level, by has_mark_scheme, by
   subject, by prompt version and by model:
   - tutor override rate on auto-finalized marks (how often a human disagreed),
   - mean signed error when overridden (is the AI systematically generous or harsh?),
   - student remark-request rate on auto-finalized vs tutor-finalized marks,
   - remark upheld rate (how often the student was right).
2. Add an admin/ops endpoint or a scheduled report. This is an internal calibration tool,
   not a tutor-facing feature — do not build a dashboard nobody asked for.
3. Interpret the baseline and write it down. A high override rate on `medium` confidence
   would argue for tightening to `high` only; a near-zero rate on both might justify
   widening. Do not change the threshold in this PR — produce the evidence.
4. Slice by prompt version and model, so this doubles as the detector for AV-30's
   regression problem.

ACCEPTANCE
- The metrics compute correctly against seeded test data.
- A baseline is documented in docs/adr/0009-trust-first-auto-finalized-marking.md or a
  linked analysis.
- `cd backend && python -m pytest` green.

CONSTRAINTS
- Do NOT change the auto-finalize rule in this PR. Rule AI-12 makes widening it an
  architectural change requiring an ADR, not a threshold tweak. This issue produces the
  evidence such an ADR would need.
- Respect tenancy: an organisation must only see its own calibration data unless the
  caller is genuine platform staff (see AV-8).
- These queries touch append-only tables that only grow — mind AV-23 and AV-25.
```

<a id="av-33"></a>
## AV-33 — Token refresh has no coalescing

**P4 · REVIEWED · Effort S**

**What's wrong.** `frontend/src/api/client.ts:210-213` and, independently, `frontend/src/api/chat.ts:54-58` each call `refreshTokens()` on their own 401, with no shared in-flight promise.

**Why it matters.** Any screen firing several parallel queries — `TodayDashboard` fires lessons, groups, attention, plus one query per group — will issue N simultaneous `POST /auth/refresh` calls the moment the access token expires. If the backend rotates the refresh cookie on use, all but the first get a stale cookie and 401. **The user is logged out despite a perfectly valid session.**

This compounds with AV-34: TanStack Query's default `retry: 3` multiplies the number of concurrent refresh attempts.

```text
CONTEXT
Repo: Avora frontend. React 18 + TanStack Query. The access token lives in localStorage;
the refresh token is an httpOnly cookie scoped to /api/v1/auth, sent same-origin via
Vercel's /api/* rewrite to the Render backend.

BUG
frontend/src/api/client.ts:210-213 calls refreshTokens() on a 401 with no shared in-flight
promise. frontend/src/api/chat.ts:54-58 hand-rolls its OWN separate refresh for the
streaming path. Nothing coalesces them.

Scenario: TodayDashboard fires lessons + groups + attention, plus one useQueries per group.
When the access token expires, all of them 401 at once and each independently POSTs
/auth/refresh. If the backend rotates the refresh cookie on use, only the first succeeds
and the rest get a stale cookie and 401 — logging the user out mid-session. The one-shot
retry flag cannot distinguish "genuinely expired" from "lost the refresh race".
Compounded by AV-34: TanStack Query's default retry is 3, multiplying the storm.

TASK
1. Add a module-level in-flight promise in client.ts:
     let refreshPromise: Promise<StoredTokens | null> | null = null;
   Every caller awaits the same promise; clear it when it settles. One refresh per
   expiry, no matter how many requests 401 simultaneously.
2. Make chat.ts import and reuse that same mechanism instead of its own. Two independent
   refresh paths is the root of this bug.
3. Confirm the backend's actual refresh semantics before finalising: does
   POST /api/v1/auth/refresh rotate the refresh cookie, and does it invalidate the old one
   immediately? Read backend/app/api/auth.py and state the answer — it determines how
   severe the race is and whether a queued retry can succeed.
4. Requests that 401'd while a refresh was in flight should retry once with the NEW token
   rather than failing.
5. Test with a mocked fetch: N concurrent 401s produce exactly ONE refresh call and all N
   requests then succeed.

ACCEPTANCE
- Test fails before, passes after.
- `cd frontend && npm test` green, `npm run build` clean.
- No path calls refresh outside the shared mechanism.

CONSTRAINTS
- Do not move the refresh token into localStorage. The httpOnly cookie is a deliberate
  security decision (a page script cannot read it) and the same-origin rewrite exists to
  make it work.
- Preserve the existing behaviour where a genuine auth failure logs the user out cleanly —
  do not create a retry loop that hides a real expiry.
- Coordinate with AV-34: fix the QueryClient retry default at the same time, or this
  remains partly masked.
```

<a id="av-34"></a>
## AV-34 — Streaming chat has no cancellation

**P4 · REVIEWED · Effort S**

**What's wrong.** `frontend/src/student/TutorChatPage.tsx:31-97` and `frontend/src/api/chat.ts:35-95`: `streamMessage` has no `AbortController` or signal, and the `onChunk` closure calls `setStreaming` with no guard tied to which conversation was active when the stream began.

**Why it matters.** A student sends a message, then switches conversation while the stream is still running. Tokens from conversation A **visibly render into conversation B's transcript**. On completion, cache invalidation fires against the wrong context. Nothing aborts the fetch, so the connection and the server-side work continue after the user has moved on — burning AI spend nobody is watching (AV-31).

Also in this file: the streaming transcript has no `aria-live`, so screen-reader users get no feedback at all while the AI replies (see AV-37).

```text
CONTEXT
Repo: Avora frontend. frontend/src/student/TutorChatPage.tsx (31-97) and
frontend/src/api/chat.ts (35-95) implement the student's streaming AI mentor chat. Chat is
the only streaming surface in the product (Anthropic only).

BUG
`streamMessage` accepts no AbortController/signal. The `onChunk` closure calls
setStreaming/setMessages directly with no guard on which conversation was active when the
stream started.

Scenario: student sends a message, then clicks a different conversation (setActiveId) or
navigates away while the SSE stream is running. Tokens from conversation A render into
conversation B's transcript; on completion, queryClient.invalidateQueries and setMessages
fire against the wrong context. Nothing aborts the fetch, so the connection and the
server-side generation continue after the user has left — wasted AI spend (see AV-31).

TASK
1. Create an AbortController per send, pass its signal into the fetch in chat.ts, and
   abort on unmount and on conversation change.
2. Capture the conversation id in the closure and no-op the chunk and completion handlers
   if the active conversation has since changed. Use a ref so the check reads current
   state, not the value captured at send time.
3. Handle AbortError distinctly — it is an expected cancellation, not an error to surface
   to the student.
4. Decide what happens to a half-streamed message when the student navigates away: keep
   the partial text, or discard it? Whichever you choose, be consistent between local
   state and what the server persisted, so returning to the conversation is not confusing.
5. Add `role="log" aria-live="polite" aria-relevant="additions"` to the transcript
   container — screen-reader users currently get zero feedback while the reply streams.
   Throttle live-region updates to sentence or paragraph boundaries rather than every
   token, or it will over-announce.
6. Test: switching conversation mid-stream leaves the other transcript untouched.

ACCEPTANCE
- Test fails before, passes after.
- `cd frontend && npm test` green, `npm run build` clean.
- No state update from an abandoned stream reaches the wrong conversation.

CONSTRAINTS
- Do not break the streaming UX — tokens must still appear incrementally.
- The daily message cap and anti-cheating guardrails are backend concerns; do not touch
  them from here.
- Aborting the client fetch may not stop server-side generation. Check whether the backend
  detects client disconnect and note it in the PR — if it does not, that is a separate
  cost issue worth raising.
```

<a id="av-35"></a>
## AV-35 — Effect re-seeding silently discards concurrent tutor edits

**P4 · REVIEWED · Effort M**

**What's wrong.** `frontend/src/tutor/SubmissionReviewPage.tsx:49-61` and `frontend/src/tutor/PreferencesPage.tsx:103-105` both hold form state that is **fully overwritten** from a `useEffect` whenever the query data's object reference changes — including after their own successful mutation triggers `invalidateQueries`.

**Why it matters.** A tutor saves a draft mark on question 1, then edits question 2 while the refetch is in flight. When it resolves, the effect replaces the entire drafts object with server data that doesn't know about the question-2 edit. **The edit is silently discarded** — no error, no indication.

On the submission review page, that's a lost mark on a student's record. This is a genuine lost-update bug, not a cosmetic staleness issue.

```text
CONTEXT
Repo: Avora frontend. React 18 + TanStack Query.
- frontend/src/tutor/SubmissionReviewPage.tsx:49-61 holds per-question mark drafts in
  local state, re-seeded from a useEffect keyed on the query's data object.
- frontend/src/tutor/PreferencesPage.tsx:103-105 does the same for readiness weight
  sliders.
Both effects fully overwrite local state whenever the query data reference changes —
including after their OWN successful mutation triggers invalidateQueries/setQueryData.

BUG — lost update
SubmissionReviewPage: tutor clicks "Save draft" on question 1, then edits question 2 while
the refetch is in flight. When it resolves, the effect replaces the whole drafts object
with server data that predates the question-2 edit. The edit vanishes with no error.
PreferencesPage: adjust a second slider during the save round-trip and onSuccess's
setQueryData triggers the same reset.

On the submission review page this is a lost MARK on a student's permanent record.

TASK
1. Stop unconditionally re-seeding from server data after the component's own mutation.
   Options, in preference order:
   (a) optimistic updates via onMutate, so local state is the source of truth during the
       round-trip and the server response confirms rather than replaces;
   (b) track per-field dirty state and re-seed only untouched fields;
   (c) seed once on first load and thereafter only on an explicit user-initiated refresh.
   Choose one, apply it to both pages, and justify it.
2. Make save state visible: a tutor should be able to tell what is saved, what is
   in flight, and what failed. Silent discard is the worst possible outcome and it is
   what happens today.
3. Audit for the same pattern elsewhere — grep for useEffect blocks that setState from
   query data and report every hit with a verdict.
4. Tests: edit field B while a save of field A is in flight; assert B survives after the
   refetch resolves. One test per page.

ACCEPTANCE
- Tests fail before, pass after.
- `cd frontend && npm test` green, `npm run build` clean.
- No user edit can be discarded without the user being told.

CONSTRAINTS
- Do not introduce a form library as part of this fix. It is a large dependency decision
  and "no unnecessary complexity" is an explicit project non-goal — raise it separately if
  you think it is warranted.
- Marks are the highest-stakes data in the product. Prefer failing loudly over resolving a
  conflict silently in either direction.
- Deliberate polling on these pages (refetchInterval) must keep working — the fix must not
  turn a background refresh into a lost edit either.
```

<a id="av-36"></a>
## AV-36 — Frontend/backend contract drift, unenforced

**P4 · DOCUMENTED · Effort M**

**What's wrong.** `frontend/src/api/*.ts` hand-mirrors backend Pydantic response shapes as TypeScript interfaces. There is no OpenAPI codegen and no contract test — although FastAPI generates a correct schema at `/docs` for free.

Worse, status fields are typed as loose `string` rather than literal unions: `homework.ts` lines 33, 48, 118, 139, 159. Business logic then does raw string comparisons — `AssignmentDetailPage.tsx:110` checks `a.status === "review"`, `SubmissionReviewPage.tsx:63-64` checks `"finalized"`/`"auto_finalized"` — and label lookups fall back silently with `?? a.status`.

**Why it matters.** Rename a backend enum value and *nothing* catches it. Not the type checker, not the tests. `editable` becomes permanently false, the Publish button silently disappears, and the only symptom is an unlabelled status pill showing the raw new string. The team rates the likelihood of this as high.

Note the direct relevance to **AV-1**: that bug is precisely a status-comparison mismatch, one layer down.

```text
CONTEXT
Repo: Avora. frontend/src/api/*.ts hand-mirrors backend Pydantic response models as
TypeScript interfaces. No OpenAPI codegen, no contract test — though FastAPI already
generates a correct schema at /docs for free. Rule FE-4 requires both sides to change in
one PR; that is a convention with nothing enforcing it.

Made worse by loose typing: status fields are `string`, not literal unions —
frontend/src/api/homework.ts:33,48,118,139,159 and syllabusUpload.ts. Business logic does
raw string comparison (AssignmentDetailPage.tsx:110 `a.status === "review" ||
a.status === "extraction_failed"`; :51 `"published"`/`"closed"`; SubmissionReviewPage.tsx:63-64
`"finalized"`, `"auto_finalized"`), and label maps fall back silently (`STATUS_LABEL[a.status] ?? a.status`).

Rename a backend enum value and NOTHING catches it: not tsc, not the tests. `editable`
goes permanently false, the Publish UI silently disappears, and the only symptom is a raw
unlabelled status string in a pill. (Note: issue AV-1 in this register is exactly this
class of bug on the backend — a status comparison that missed a value.)

TASK
1. Generate TypeScript types from the backend's OpenAPI schema. `openapi-typescript` is
   the lightest option. Add a script that fetches /openapi.json from a locally running
   backend and writes the types.
2. Add a CI check that regenerates types and fails if the committed types differ from
   what the current backend produces. This is the actual enforcement — the generator
   alone changes nothing.
3. Convert status fields to literal unions (generated types give this automatically) so a
   renamed value is a compile error at every comparison site.
4. Migrate the hand-written interfaces to the generated ones incrementally, one API module
   per PR. Do not do all of them at once.
5. Where a label map is indexed by a status, make exhaustiveness a compile-time
   requirement (a Record keyed on the union type) so adding a status forces adding a label.

ACCEPTANCE
- Types are generated from the real backend schema.
- CI fails when backend and frontend types diverge — prove it by renaming a field
  locally and watching CI fail.
- `cd frontend && npm run build` (tsc -b + vite build) clean.
- Renaming a backend enum value produces a frontend compile error.

CONSTRAINTS
- Do not hand-edit generated files.
- Ship incrementally. A single PR replacing every interface is unreviewable and will
  stall.
- Keep the runtime error parsing in client.ts working — it parses FastAPI's 422 body
  shape, which is separate from response types and is its own documented gap.
```

---

# P5 — Quality, accessibility, and supply chain

<a id="av-37"></a>
## AV-37 — Accessibility: focus trap, focus ring, skip link, live region

**P5 · MIXED · Effort M**

**What's wrong.** Several confirmed WCAG failures:

- **`Modal` has no focus trap and no focus restore** (`components/ui.tsx:118-166`). Keyboard users tab out of the dialog into the page behind it; on close, focus drops to `<body>` rather than returning to the trigger.
- **No focus-visible styling anywhere.** A repo-wide grep for `focus-visible` returns zero matches, while `focus:outline-none` appears 10 times — often with only a border-colour change to compensate, which is low contrast on the dark theme. WCAG 2.4.7 failure.
- **No skip link.** Every page renders 7-9 nav items before `<main>`.
- **No `aria-live` on the streaming chat transcript** (covered in AV-34).
- **`eslint-plugin-jsx-a11y` is not installed at all.**
- **`--color-line` (contrast 1.21) is the default input border** — form fields have no perceptible boundary for low-vision users.

**A correction to Avora's own documentation.** `docs/volume-1-product-and-ux/02-ux-and-accessibility-standards.md` lists `role="assistant"` in `TutorChatPage.tsx` as a blocking invalid-ARIA bug. **It isn't one.** `role` there is a plain component prop (`MessageBubble({ role, content })`) used only for a style branch — it is never spread onto a DOM node. The doc's Known Gaps entry is wrong and should be removed. The real issue in that file is the delete-conversation button (`✕` with only a `title`) having no accessible name — which the doc doesn't mention.

```text
CONTEXT
Repo: Avora frontend. React 18 + Tailwind CSS v4, dark theme. Target users include
students on phones and parents. docs/volume-1-product-and-ux/02-ux-and-accessibility-
standards.md sets WCAG AA as the standard; it is currently enforced by review alone.

CONFIRMED ISSUES
1. Modal (src/components/ui.tsx:118-166) has no focus trap and no focus restore. The
   useEffect at 131-139 moves focus in and handles Escape, but nothing intercepts
   Tab/Shift+Tab, and nothing stores/restores document.activeElement. Keyboard users tab
   into the page behind the open dialog; on close, focus drops to <body>.
2. No focus-visible styling anywhere — repo-wide grep for "focus-visible" returns zero
   matches, while `focus:outline-none` appears 10 times (ui.tsx, LoginPage, TutorSignupPage,
   TutorChatPage, DashboardHeader, EvidenceToAction, CreateLessonModal), often compensated
   only by a border-colour change that is low-contrast on the dark theme. WCAG 2.4.7 fail.
3. No skip link. AppShell renders 7-9 nav items before <main> on every page.
4. No aria-live on the streaming chat transcript (also covered by AV-34).
5. eslint-plugin-jsx-a11y is NOT installed.
6. `--color-line` (contrast 1.21 on surface) is the default input border — form fields
   have no perceptible boundary for low-vision users.
7. Icon-only buttons lack accessible names: TutorChatPage.tsx:120-126 and
   AssignmentDetailPage.tsx:309 use `✕` with only a `title` attribute.
8. No prefers-reduced-motion handling anywhere.

DOCUMENTATION CORRECTION — verify and fix
The same doc lists `role="assistant"` in TutorChatPage.tsx as a blocking invalid-ARIA
bug. It is NOT a bug: `role` there is a plain component prop on MessageBubble({ role,
content }) used only for a style branch, never spread onto a DOM node. Verify this
yourself, then remove that entry from the doc's Known Gaps and replace it with item 7.

TASK
1. Install and configure eslint-plugin-jsx-a11y. CI already runs
   `eslint . --max-warnings 0`, so rules will gate immediately. Fix what it finds.
2. Add a focus trap and focus restore to Modal. Cycle Tab within the panel's focusable
   descendants and restore document.activeElement on close.
3. Add a global focus-visible style in src/index.css:
     :focus-visible { outline: 2px solid var(--color-brand-600); outline-offset: 2px; }
   rather than relying on each component to hand-roll focus rings correctly.
4. Add a visually-hidden-until-focused skip link as the first focusable element in
   AppShell, targeting the <main> that wraps <Outlet/>.
5. Fix the input border token so form fields meet the 3:1 non-text contrast requirement.
6. Add aria-labels to icon-only buttons (item 7).
7. Add a prefers-reduced-motion block in index.css.
8. Correct the documentation as described above.

ACCEPTANCE
- eslint with jsx-a11y passes at --max-warnings 0.
- Manual keyboard pass: open a modal, tab through it (focus stays inside), close it
  (focus returns to the trigger), and reach main content via the skip link.
- `cd frontend && npm test` green, `npm run build` clean.
- The incorrect Known Gaps entry is removed and replaced.

CONSTRAINTS
- src/test/contrast.test.ts already checks design tokens — keep it passing. Note its
  known limitation: it verifies each token clears the ratio its ROLE needs, but nothing
  checks a token is used in the role it was measured for.
- Do not restyle the product. These are targeted accessibility fixes, not a redesign.
- Two class vocabularies coexist (semantic tokens and remapped stock Tailwind names).
  Do not attempt that convergence here — it is separate, larger work.
```

<a id="av-38"></a>
## AV-38 — Supply chain: no lockfile, root container, no scanning

**P5 · VERIFIED · Effort M**

**What's wrong.** I confirmed directly from `backend/Dockerfile`:

- `pip install --no-cache-dir .` against `>=` ranges with **no lockfile** — two builds of the same commit can produce different dependency trees
- **No `USER` directive** — the container runs as root
- **No `.dockerignore`** — the build context carries whatever is in the directory
- No `HEALTHCHECK`

And nothing scans dependencies. The first `npm audit` anyone ran reported **8 advisories: 1 critical (`vitest`), 1 high (`vite`)**, both needing a semver-major upgrade. Both are dev-only and neither ships to a user — but the count grew unobserved for two major versions.

CI runs ruff, eslint, prettier, pytest, vitest, `tsc -b` and a migration up/down/up — genuinely solid. It has **no dependency audit, no secret scan, no SAST, and no Python type checker**.

```text
CONTEXT
Repo: Avora. VERIFIED from backend/Dockerfile: `pip install --no-cache-dir .` against
`>=` ranges with no lockfile; no USER directive (runs as root); no .dockerignore; no
HEALTHCHECK. Nothing scans dependencies anywhere.

The first `npm audit` anyone ran reported 8 advisories: 1 critical (vitest <=3.2.5, repo
has ^2.0.5) and 1 high (vite <=6.4.2, repo has ^5.4.0), both needing a semver-major.
Both are devDependencies and Vercel serves a static build, so neither ships to a user —
the exposure is a developer running the dev server and CI running untrusted PR code. But
the count grew unobserved for two majors, which is the actual finding.

CI (.github/workflows/ci.yml) already runs ruff check + format, eslint --max-warnings 0,
prettier --check, pytest, vitest, `npm run build` (tsc -b), and an Alembic
up -> down -> up against Postgres 16. That is a solid baseline. It has NO dependency
audit, NO secret scan, NO SAST, and NO Python type checker.

TASK — five independent pieces, ship separately
1. Add scanning to CI first — cheapest, and it has a demonstrated hit rate.
   `pip-audit` for Python and `npm audit --audit-level=high` for the frontend, in the
   existing lint job. Decide whether it blocks or warns initially; blocking is right once
   the current findings are cleared.
2. Add a secret scan (gitleaks or trufflehog). I found no committed secrets, so this is
   preventive — add it while the repo is clean.
3. Pin dependencies. Generate a lockfile (pip-tools or uv) and install from it in the
   Dockerfile so two builds of one commit are identical. The frontend already has
   package-lock.json — verify the Dockerfile-equivalent path uses `npm ci`, not
   `npm install`.
4. Harden the container: add a non-root USER, add a .dockerignore (at minimum .git,
   .venv, tests, __pycache__, *.md), and add a HEALTHCHECK.
5. Upgrade vite and vitest on their OWN branch. A double semver-major across 49 frontend
   tests and the Tailwind v4 plugin is a real upgrade with its own regression surface —
   do not bundle it with anything else.
6. Separately, add a Python type checker (mypy or pyright). ~22k lines of annotations are
   currently unverified while the frontend has tsc -b in CI. Expect to need
   --ignore-missing-imports and a per-module opt-in ratchet rather than one sweep; do not
   attempt to make 22k lines type-clean in one PR.

ACCEPTANCE
- CI fails on a new high/critical advisory.
- Builds are reproducible from a lockfile.
- The container runs as a non-root user and still works end to end.
- Existing CI jobs stay green.

CONSTRAINTS
- Do not bundle the vite/vitest major upgrade with the CI or Dockerfile changes. Separate
  branches — this is exactly the pattern the project's own split-commit practice exists for.
- Non-root will affect the uploads mount at /data. Verify permissions on Render before
  merging, or the app cannot write uploads.
- Do not add the type checker as a blocking gate on day one. Ratchet it per module.
```

---

## Suggested sequencing

**Week 1 — stop active harm**
AV-1 (wrong scores now), AV-17 (an uptime monitor is an afternoon and makes six other issues visible), a backup of the uploads disk from AV-13 step 1.

**Weeks 2-4 — stop losing student work**
AV-2, AV-3, AV-4, AV-5, AV-6 — the silent-loss cluster. AV-22 (blocking I/O) because it's a same-day fix with the widest felt impact. AV-10 and AV-11 (config hardening, hours of work).

**Month 2 — protect the value proposition and the data**
AV-7 (only after AV-1 is merged), AV-13 in full, AV-8, AV-23 + AV-24 together, AV-31 so pricing becomes possible.

**Month 3 — before selling beyond individual tutors**
AV-12, AV-14, AV-15, AV-25, the compliance work, AV-30, AV-38.

## Two notes on using this register

**AV-1 gates AV-7.** Completing the readiness cutover while the v2 homework factor is broken would propagate a known-wrong score to every remaining surface. Fix AV-1 first — the prompt for AV-7 says so explicitly.

**AV-22 gates AV-26.** Adding concurrent workers while blocking calls remain on the shared event loop makes contention worse, not better.

## On the quality of what's here

It's worth stating plainly, because a register of 38 defects reads worse than the codebase deserves.

Several things came back genuinely clean under focused review: upload validation (magic-byte checking independent of the client-declared type, caps enforced before *and* after transcoding, server-generated filenames), the auth and session layer (bcrypt, dummy-hash on miss to defeat timing attacks, instant token revocation, signed OAuth state), prompt-injection defences backed by server-side mark clamping, and the absence of any XSS vector in the markdown renderer. The security reviewer could not find a single endpoint returning tenant data with no scoping at all.

Roughly two-thirds of what's above the team had already found and written down themselves. That's rare, and it means these are known problems rather than lurking ones.

The genuinely new findings cluster in one place: **paths where a failure is silent.** AV-1, AV-2, AV-4, AV-5 and AV-6 are all variations on the same theme — something goes wrong, the data ends up incorrect or the work disappears, and nobody is told. That's the pattern worth fixing at the cultural level, not just the code level.
