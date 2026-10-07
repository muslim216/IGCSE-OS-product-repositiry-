# Off-plan work after Phase 9 (6–7 October 2026)

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

## Decided by the owner

- "no they cant reupload": lock the upload once any mark is final (#145).
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

- **No way to let a student redo a locked mock or past paper.** Once one question has a final
  mark the attempt is closed for good, and no tutor action reopens it. For homework the tutor
  can set it again. Offered to the owner as a "Let them redo this" action; not answered.
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

## Still owed

By the owner:

- Confirm the Render deploys of migrations 0069 and 0070 (and 0067, 0068 from Phase 9).
- The earlier owner-only jobs are unchanged: the failed production jobs, the readiness
  recompute on Render, registering the Zoom, Google and Meta apps, moving the repo off iCloud.

By the agent:

- Constitution updates for this batch: `05-api-standards.md` (the `/me/dismissals` routes, the
  soft `DELETE /groups/{id}`), `06-database-design.md` (`dismissed_prompts`, the two `groups`
  columns), `07-security-architecture.md` (`live_classes_taught_by`, the final-mark lock).
- The docs already owed for Phases 7 to 9.
- The remaining backlog decisions: `recommended_revision` against AV-42, shared students
  across organizations, Topic Mastery switched off, the enrolment source of truth, and the two
  unconfirmed Phase 7 calls.
