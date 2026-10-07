# Off-plan work after Phase 9 (6–8 October 2026)

Work done between Phase 9 and Phase 10 that is not a task in the plan: the backlog of
things owed from earlier phases, and three requests the owner made on 6 October. This
document records what shipped, what was decided, and what is still owed.

## What shipped

| PR | What | Migration |
|---|---|---|
| #144 | Independent review of #131–#133 (Phase 8 messaging) and its fixes. Detail in `phase-8-status.md`. | none |
| #145 | A student cannot replace work that has a final mark. | none |
| #146 | Mocks and past papers grouped by subject, with a subject picker for tutors. | none |
| #147 | "Not now" on what Overview asks of the tutor, with "Show hidden". | 0069 `dismissed_prompts` |
| #148 | A flaky test (`MistakeCategories.test.tsx`) that raced its own first save. | none |
| #149 | Delete a class (soft delete). | 0070 `groups.deleted_at`, `groups.deleted_by_id` |
| #150 | A tutor can let a student redo a locked attempt. | 0071 `attempt_redos` |

Also on this branch: two corrections to runbook R6 and the `/health/ready` sample
(`14-operations-runbooks.md`).

## Rules these changes introduced

**An attempt with a final mark is settled (#145).** `open_attempt` used to lock on the
submission's status alone. A remark request moves a finalized submission back to
`needs_review`, and a half-decided auto-marked submission waits there too; in that state a
re-upload was accepted and deleted every mark, mistake and tutor mistake revision. An attempt
is now settled when its status is settled **or any of its marks has `final_marks`**. This
applies to homework, past papers and mocks. A student can no longer re-upload partly marked
work.

**A dismissal is a display choice (#147).** `dismissed_prompts` stores an opaque key per
tutor. The key is never resolved to a row and grants no access. `services/onboarding.py` and
`in_flow` are unchanged: the server still says a tutor without an accepted plan is in the flow,
and the page may now show the ordinary Overview because the tutor put the guide aside. The
"Needs you" list has no "Not now", deliberately: hiding unmarked work would let it never be
marked.

**Deleting a class is soft, and ends the relationship it gave (#149).**

- A deleted class does not exist for anything forward-looking: tutor lists and
  class-management routes (`404`), the student's view of the class, its lessons, files and any
  homework or mock not yet handed in, its invite codes, and every sweep and job.
- History is kept: every `Submission`, `QuestionMark`, `Evidence` row and readiness snapshot,
  the subject enrolment, and attendance already recorded.
- Deleting a class ends the tutor's access to students taught only in that class, read and
  write, exactly as removing the student would. `live_classes_taught_by()` in
  `services/groups.py` is the one definition of "a class this tutor teaches that still exists";
  every "does this tutor teach this student" check uses it.
- The one exception is `_tutor_owns` and the review queue, so work already handed in can still
  be marked and finalized. There is no time limit on that.
- Homework in a deleted class that was not yet due at deletion, or had no due date, never
  counts as missed. Homework already overdue at deletion counts as before. Readiness does not
  change when a class is deleted, and a test computes it before and after to show that.
- There is no restore. The data staying in place is the safety net.

**A redo moves the old attempt out of the live tables (#150).** Detail in `05-api-standards.md`,
`06-database-design.md` and `07-security-architecture.md`.

- Only a tutor can do it, from the marked-work page ("Let them redo this"), after a
  confirmation. The student can then hand the work in again.
- The old attempt is written whole to one append-only `attempt_redos` row and its live rows
  are deleted, so nothing that reads marks, mistakes or evidence needs to know about redos.
  Only the new attempt counts toward readiness. The student's page lists "Attempts set aside".
- It is refused when the tutor does not teach the student (for a past paper, in that paper's
  subject), when the attempt has no final mark, while marking or tagging is queued or running,
  and when the student could not hand the work in again.
- `services/hand_in_gate.py` now holds the "may this student hand this in" rules for both the
  student's upload and the tutor's redo, and `attempt_is_locked` the one definition of locked.

## Decided by the owner

- "no they cant reupload": lock the upload once any mark is final (#145).
- "yes" to the redo button (2026-10-07), and "ok" to its design: the old attempt stays on
  record and stops counting, and only the new attempt counts.
- **Keep the AI's "what to revise next" steps in readiness** ("keep that", 2026-10-08).
  `recommended_revision` stays as it is. `AV-42` in the plan still says "no 'do this now'"; it
  now describes the weak-topic lists only. Recorded as a Known Gap in
  `01-product-architecture.md`; the plan document is not edited.
- **The Render upgrade waits** (2026-10-08): "we do this after we've settled all features and
  finished building completely." See "Production runs on a free instance" below.
- "go" on the three requests as proposed: per-subject grouping, "Not now" on setup guide
  steps, checklist lines, chapter prompts and lesson reminders but not on "Needs you", and a
  soft class delete that keeps marks and history.

## Decided on the owner's behalf, and told to them

- Dismissing the setup guide is allowed, which relaxes the Phase 9 rule that every tutor
  without an accepted teaching plan sees it.
- Deleting a class ends the tutor's access to its students.
- Recorded attendance for a deleted class stays visible.
- In #144: a weekly send is skipped when it would repeat more than half of a week already
  sent, and a stored parent send is matched to children by id.

## Known gaps

- **A redo removes override-audit rows, against `PROD-7`.** They are carried into the
  `attempt_redos` record first. Put to the owner twice and not answered; recorded as a Known
  Gap in `01-product-architecture.md` and `06-database-design.md`, the rule unchanged.
- **From #150, not built:** the student is not told their tutor reopened the work; the stored
  record and the old page files have no retention or erasure rule; the Google Classroom sync
  (hidden) could import a redone attempt again; until the student hands in again the weekly
  send and due reminders read the work as not handed in, and the "marked" notification fires a
  second time; the redo's lock and deadlock handling is tested with injected errors on SQLite,
  never with two writers on Postgres; `_viewable_student` keeps its own copy of the
  shared-class rule; the review page's in-flight check reads every pending job's payload.
- **A race in `open_attempt`.** A re-upload that reads the marks an instant before a mark is
  finalized can still delete it. The read takes no lock. It predates #145.
- **A notification queued before a class is deleted still sends.**
- **A tutor can finish marking work from a deleted class indefinitely.**
- **Access checks in #149 without a test of their own:** parent views after deletion, the
  undelivered list and weekly-send content for a former student, the tutor's assessment list
  routes, student files and recordings, and a student with one live and one deleted class in
  the same subject. A second security review read each of these and found them correct.
- **"N hidden" is a count of what the page would otherwise show now.** Stored keys for things
  that no longer exist are not counted and are only cleared by "Show hidden".
- **`backend/app/api/dismissals.py` keeps `response_model=` beside the return annotation**,
  which SonarCloud flags. It is the convention in the neighbouring routers.
- From #144, still open: a per-reader failure in the weekly build is never retried; a tutor can
  edit the contact of a parent shared with another tutor.
- **No screen in this batch has been viewed in a browser or on a phone.**

## Production runs on a free instance (found 2026-10-08)

The owner confirmed the Render API service is on the **free** instance type, not the `starter`
plan with a 10 GB disk that `render.yaml` describes. Found while reading the failed jobs.

- **Uploads are not kept.** There is no persistent disk, so every stored file is lost when the
  service redeploys, restarts or sleeps. The rows that point at them remain. Three failed jobs
  (ids 130, 289, 290) are `ObjectNotFoundError` for exactly this reason.
- **The in-process worker stops while the service sleeps**, so reminders, weekly sends and the
  sweeps run only while something keeps it awake.
- **The Render shell is unavailable** on this instance type. The database was read through its
  External Database URL instead.
- Marks, evidence and readiness are in Postgres and are unaffected.

The owner's decision is to upgrade after the build is finished. It has to happen before the
first real tutor or student uploads anything; until then a missing file in testing is expected.

**The 18 failed jobs, read on 2026-10-08:** 15 are "AI is not configured" (6 for the Gemini
key, the last on 2026-08-15; 9 for the Anthropic key, the last four on 2026-10-03 to
2026-10-06: `extract_syllabus` and three `tag_mistakes`), and 3 are the missing files above.
Whether `ANTHROPIC_API_KEY` is set in Render today is unchecked. The 5 pending jobs were the
recurring sweeps, each with a future `run_after`, which is normal.

## Still owed

By the owner:

- Render deploys: 0069 and 0070 confirmed by the owner ("render works"); 0071 confirmed by the
  agent against the live API on 2026-10-08 (the redo routes are served and the spec matches).
- Check that `ANTHROPIC_API_KEY` has a value in Render, and change the database password,
  which was pasted into a chat on 2026-10-08.
- Upgrade the Render instance and add the disk, when the build is finished.
- The earlier owner-only jobs are unchanged: the failed production jobs, the readiness
  recompute on Render, registering the Zoom, Google and Meta apps, moving the repo off iCloud.

By the agent:

- Constitution updates for this batch: `05-api-standards.md` (the `/me/dismissals` routes, the
  soft `DELETE /groups/{id}`), `06-database-design.md` (`dismissed_prompts`, the two `groups`
  columns), `07-security-architecture.md` (`live_classes_taught_by`, the final-mark lock).
- The docs already owed for Phases 7 to 9.
- The remaining backlog decisions: shared students
  across organizations, Topic Mastery switched off, the enrolment source of truth, and the two
  unconfirmed Phase 7 calls.
