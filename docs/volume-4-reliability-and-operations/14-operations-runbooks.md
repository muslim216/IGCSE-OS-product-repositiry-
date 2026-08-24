# 14. Operations Runbooks

> **Volume 4 — Reliability & Operations** · Engineering Constitution v1.2 · Status: Active
> **Owner:** Founder (see `governance/ownership.md`)
>
> What to do when something is broken. Each runbook: symptoms → diagnosis → action →
> verification.

## Contents

- [Purpose](#purpose)
- [Scope](#scope)
- [Sources](#sources)
- [Principles](#principles)
- [Current Reality](#current-reality)
- [Runbooks](#runbooks)
  - [R1 — Deploy a change](#r1--deploy-a-change)
  - [R2 — Verify what is actually running](#r2--verify-what-is-actually-running)
  - [R3 — Roll back](#r3--roll-back)
  - [R4 — A migration failed and the service will not start](#r4--a-migration-failed-and-the-service-will-not-start)
  - [R5 — Background work has stopped](#r5--background-work-has-stopped)
  - [R6 — A job is poisoned](#r6--a-job-is-poisoned)
  - [R7 — An AI provider is down or over quota](#r7--an-ai-provider-is-down-or-over-quota)
  - [R8 — Marking is failing or wrong](#r8--marking-is-failing-or-wrong)
  - [R9 — Readiness looks wrong or stale](#r9--readiness-looks-wrong-or-stale)
  - [R10 — Google Classroom sync is failing](#r10--google-classroom-sync-is-failing)
  - [R11 — The uploads disk is full or files are missing](#r11--the-uploads-disk-is-full-or-files-are-missing)
  - [R12 — Rotate a secret](#r12--rotate-a-secret)
  - [R13 — Restore the database](#r13--restore-the-database)
  - [R14 — Support tasks](#r14--support-tasks)
  - [R15 — Incident response](#r15--incident-response)
- [Standards](#standards)
- [Known Gaps](#known-gaps)
- [Review Triggers](#review-triggers)

---

## Purpose

Nothing in this system alerts. Every runbook below therefore begins with a symptom a human
noticed — usually a tutor reporting that something has stopped — rather than with a page. That
is the honest starting point, and §11 records it as the gap it is.

These procedures exist so that the response to a failure is a checklist rather than a
reconstruction, and so that the knowledge required to operate Avora is not held in one
person's memory.

## Scope

**In scope:** deploying, verifying, and rolling back; migration failures; the job system;
provider outages; marking and readiness problems; Classroom; disk and file problems; secret
rotation; database restore; user support; incident response.

**Out of scope:** why the system is shaped this way (§08, §11); the standards a fix must meet
(§12, §13).

### Non-goals

- **No automated remediation.** Every procedure here is a human one.
- **No runbook for a failure mode that has never been reasoned about.** A speculative runbook
  is worse than none, because it will be followed.

## Sources

Written from: `render.yaml`; `backend/Dockerfile`; `backend/app/config.py`;
`backend/app/workers/jobs.py`; `backend/app/models/homework.py`;
`backend/app/services/ai.py`; `backend/app/services/google_classroom.py`;
`backend/app/services/storage.py`; `backend/app/security.py`; `backend/app/api/auth.py`;
`README.md`.

---

## Principles

**P1 — Establish what is running before changing it.** A surprising number of "bugs" are a
deploy that did not land. R2 comes before almost everything.

**P2 — Stop the bleeding, then diagnose.** Roll back or flip a kill switch first; understand
afterwards. The exception is anything that would destroy evidence.

**P3 — Prefer configuration to code in an incident.** Re-routing a surface is an environment
variable. A code fix is a pull request, a build, and a migration run.

**P4 — Write down what you did.** Every incident ends with a note. The next person is you, six
months later.

**P5 — Never rotate `JWT_SECRET` or `GOOGLE_TOKEN_ENCRYPTION_KEY` casually.** Each has a blast
radius that surprises people. See R12.

---

## Current Reality

Everything in this section is the operating context the runbooks assume. Read it once; the
procedures below all depend on it.

**Access needed:** the Render dashboard (service, database, logs, shell), the Vercel dashboard,
GitHub, and the Google Cloud console for Classroom.

**Three facts that shape almost every response:**

1. **`main` deploys on merge.** There is no gate after the merge button.
2. **Migrations run at container start**, chained `alembic upgrade head && uvicorn`. A failing
   migration means the service **never starts** — the previous revision keeps serving.
3. **The job worker lives inside the API process**, supervised by `_supervised_worker()`,
   which restarts the loop after 5 seconds if it raises or returns. If the *process* dies the
   background work dies with it; if only the loop dies it comes back and logs why.

**Two health endpoints, and only one of them tells you anything.**

- **`GET /api/v1/health`** returns a static `{"status": "ok"}` without touching the database
  or the worker. This is what Render polls, deliberately (§11). Treat a healthy response as
  "the process is accepting connections", not as "the system works".
- **`GET /api/v1/health/ready`** is the one to open during an incident. It is public — no
  token needed — and returns:

  ```json
  {
    "status": "ok",
    "database": {"ok": true},
    "worker": {"state": "running", "seconds_since_loop": 0.4, "job_running_seconds": null},
    "queue": {"pending": 0, "running": 0, "failed": 0, "done": 812,
              "oldest_pending_age_seconds": null}
  }
  ```

  It answers with **503** when the database is unreachable or the worker is unhealthy. Read
  `worker.state` carefully: `running` is fine, `not_started` means the lifespan never ran,
  `stalled` means a single job has been in flight past `JOB_STALL_SECONDS` (900), and `stale`
  means the loop itself stopped. **A `queue` of `null` means the database was unreachable** —
  it is not a queue of zeroes, and the distinction is the difference between "nothing to do"
  and "I cannot see".

---

## Runbooks

### R1 — Deploy a change

**Trigger:** a pull request is ready.

**Action**

1. Confirm both suites pass locally: `cd backend && .venv/bin/python -m pytest`, and
   `cd frontend && npm test`. Run `npm run build` if the frontend changed — it is the only
   type check.
2. If the change includes a migration, verify `upgrade` → `downgrade` → `upgrade`, and against
   Postgres if it alters a populated table (`QA-11`).
3. Merge into `main` once approved.
4. Watch the Render deploy through to "Live". Watch the Vercel deploy if the frontend changed.
5. **Do not treat the change as shipped until R2 confirms it.**

**Verification:** R2.

---

### R2 — Verify what is actually running

**Symptoms:** an endpoint that should exist returns 404; a fix appears not to have worked; a
migration revision "does not exist".

**Diagnosis**

1. Render dashboard → the service → **Events**. Is the most recent deploy "Live" or "Failed"?
   A failed deploy leaves the **previous** revision serving while `main` has moved on.
2. Render → **Logs**. Startup logs show the Alembic run. A migration error there is R4.
3. Confirm the connected branch is the repository's default branch on **both** Render and
   Vercel. A service left on a stale branch serves it silently, and the symptoms look exactly
   like application bugs.
4. Check the deployed commit against `main`'s head.

**Action:** if the deploy failed, read the reason. Migration failure → R4. Build failure → fix
forward or R3.

**A third reason now exists: a failed health check.** `render.yaml` sets
`healthCheckPath: /api/v1/health`, so a revision whose process never answers that path is
marked failed rather than going live. This is the intended behaviour — it is what stops a
wedged uvicorn from being reported as a successful deploy — but it is new, so the first time
you see it, check that the process is actually starting before assuming the check itself is
wrong. Migrations run before uvicorn, so a health check that never passes usually means the
process died after Alembic succeeded.

**Verification:** the deployed commit matches `main`, the deploy is "Live", and the behaviour
you expected is present.

---

### R3 — Roll back

**Symptoms:** a change has shipped and is causing harm.

**Diagnosis:** decide which kind of rollback applies — this is the whole decision.

| The bad change was… | Roll back by… |
|---|---|
| Code only | Render → Events → **Redeploy** the last good revision. Fastest path. |
| Frontend only | Vercel → Deployments → **Promote to Production** on the last good build. |
| Code plus a **backwards-compatible** migration | Redeploy the previous revision. Leave the migration applied. |
| Code plus a **breaking** migration | **Do not redeploy blindly.** The old code will not run against the new schema. Fix forward, or apply the `downgrade` first — see below. |
| Configuration | Change the value in the dashboard and restart. |

**Action for a breaking migration:**

1. Put the change beyond further harm — if it is a specific feature, consider a kill switch
   (`READINESS_V2_SHADOW_ENABLED` is the only one that exists).
2. Take a database backup **before** downgrading. A `downgrade` that drops a column destroys
   its data.
3. Run the downgrade from a Render shell: `alembic downgrade -1`.
4. Redeploy the previous revision.

**Verification:** R2, plus the specific behaviour that prompted the rollback.

**Note:** `INF-4` requires a change touching migrations, environment, or the start command to
state its rollback in the pull request. During an incident is not the moment to work it out.

---

### R4 — A migration failed and the service will not start

**Symptoms:** the deploy shows "Failed"; the API is unreachable or serving the previous
revision; Render logs show an Alembic traceback.

**This is the highest-severity ordinary failure**, because `alembic upgrade head && uvicorn`
means a failed migration is a service that never starts.

**Diagnosis**

1. Render → Logs → the failing deploy. Read the Alembic error.
2. Determine **how far it got**. Alembic applies migrations one at a time and commits each, so
   a failure mid-chain leaves the database at an intermediate revision. From a Render shell:
   `alembic current`.
3. The most common causes here, in order: a non-nullable column added to a populated table
   without a default (this is what broke 0012); a constraint violated by existing data; a
   SQLite-only construct that Postgres rejects; a `batch_alter_table` missing its naming
   convention (`DB-17`).

**Action**

1. **Do not retry the deploy** hoping it works. It will fail identically.
2. If the partially applied state is safe, fix the migration and ship a new one. Prefer a new
   migration over editing the failed one if any environment has applied it.
3. If the partially applied state is unsafe, `alembic downgrade <last good revision>` from a
   shell, then redeploy the previous revision.
4. Test the corrected migration against a Postgres copy with representative data before
   retrying.

**Verification:** `alembic current` matches head; the service starts; R2 confirms the revision.

---

### R5 — Background work has stopped

**Symptoms:** homework stays "processing" forever; readiness never updates; reports never
finish; nothing appears from Classroom. **The API responds normally and `/api/v1/health`
returns `ok`** — liveness cannot see this. `/api/v1/health/ready` can.

This is the system's signature silent failure. The worker shares the API process.

**Diagnosis**

**Start with `GET /api/v1/health/ready`** — it answers most of this runbook in one request,
without a database console:

| `worker.state` | Meaning |
|---|---|
| `running` | The loop is turning. If work is still stuck, the problem is a handler, not the worker — go to R6. |
| `stalled` | One job has been in flight for over 15 minutes. A handler is hung; restart, then R6. |
| `stale` | The loop stopped and nothing is in flight. The supervisor should have restarted it — check the logs for `job worker died` and how often it repeats. |
| `not_started` | `lifespan` never ran. The process is misconfigured or came up wrong; restart. |

`queue.oldest_pending_age_seconds` tells you how long this has been going on, and
`queue.failed` tells you whether jobs are dying rather than queueing.

Then query the `jobs` table for detail:

```sql
SELECT status, COUNT(*) FROM jobs GROUP BY status;

-- how long has the oldest pending job been waiting?
SELECT id, type, created_at, run_after, attempts
FROM jobs WHERE status = 'pending' ORDER BY id LIMIT 20;

-- anything failed recently?
SELECT id, type, attempts, error, created_at
FROM jobs WHERE status = 'failed' ORDER BY id DESC LIMIT 20;
```

Interpret:

| Pattern | Meaning |
|---|---|
| Many `pending`, none `running`, oldest is old | **The worker is not running.** Restart the service. |
| One job `running` for a long time | A handler is stuck — a hung provider call, or an unbounded loop. Restart, then R6. |
| Many `failed` with the same error | A dependency is down (R7) or a handler has a bug. |
| `pending` jobs with a future `run_after` | Normal. Debounced readiness synthesis waits up to `READINESS_V2_COALESCE_SECONDS` (default 600). |

Also check Render logs for `job worker started`, `job worker stopped`,
`job worker iteration crashed`, and — the one that matters most — **`job worker died;
restarting`**. A single occurrence is the supervisor doing its job. The same line repeating
every five seconds means the loop cannot survive startup, and the queue will not drain until
whatever it names is fixed.

Note the asymmetry in what you will actually see: the app configures no logging, so `log.info`
lines from the `jobs` logger are invisible, while `log.error` and `log.exception` reach stderr
through Python's last-resort handler. The supervisor's failures show up; the routine
lifecycle messages do not.

**Action**

1. Restart the Render service. This restarts the worker, and pending jobs are picked up
   because they are rows — nothing was lost.
2. A job left `running` when the process died stays `running` and **will not be re-claimed**.
   Reset it:
   ```sql
   UPDATE jobs SET status = 'pending' WHERE status = 'running' AND id = <id>;
   ```
   Only do this once you are certain no worker is processing it, and only for handlers you
   have confirmed are idempotent — which all of them are required to be (`BE-6`).
3. If the worker died from a specific job, that job is R6.

**Verification:** `pending` count falls; the affected submissions complete; the tutor's stuck
item resolves.

---

### R6 — A job is poisoned

**Symptoms:** one job fails twice and is now `failed`. Nothing announces it. A single
submission, report, or extraction never completes.

**Diagnosis**

```sql
SELECT id, type, payload, attempts, error FROM jobs WHERE status = 'failed' ORDER BY id DESC;
```

Read `error`. Also read the domain error column the handler should have written —
`assignments.extraction_error`, `submissions.ai_error`, `reports.error`,
`syllabus_uploads.error`, `readiness_snapshots.error` — which is what the tutor sees.

**Action**

- **Transient cause** (provider blip, rate limit): re-enqueue by setting the row back to
  pending. Note that retries have **no backoff**, so both attempts were spent within seconds —
  a rate limit will have consumed both.
  ```sql
  UPDATE jobs SET status = 'pending', attempts = 0, error = NULL WHERE id = <id>;
  ```
- **Bad input** (an unreadable PDF, an unsupported attachment): the job will never succeed.
  Leave it failed, clear the domain error if it is misleading, and tell the tutor what to
  re-upload.
- **Handler bug:** fix forward. Every handler is idempotent, so re-running after the fix is
  safe.

**Verification:** the job reaches `done`, or the tutor has an accurate error message and a
clear next step.

---

### R7 — An AI provider is down or over quota

**Symptoms:** one group of features fails while others work. The split is diagnostic:

| Failing | Provider |
|---|---|
| Marking, question extraction, syllabus extraction | **Gemini** |
| Chat, reports, readiness synthesis, class briefs | **Anthropic** |

**Diagnosis**

1. Check the provider's status page.
2. Look at `jobs.error` and the domain error columns for the provider's message.
3. Confirm the key is still set and valid in Render's environment.

**Action — re-route the surface. This is a configuration change, no code, no deploy of new
code:**

```
AI_MARKING_PROVIDER=anthropic
AI_EXTRACTION_PROVIDER=anthropic
AI_SYLLABUS_PROVIDER=anthropic
```

or the reverse for an Anthropic outage — **except `chat`**. Chat is the only streaming surface
and `stream_complete()` is Anthropic-only; setting `AI_CHAT_PROVIDER=gemini` makes chat raise.
Leave chat down rather than mis-route it.

Restart the service after changing the variables. Re-enqueue the jobs that failed (R6).

**Verification:** a new submission marks successfully; `GET /ai-usage/analytics?group_by=provider`
shows calls arriving at the new provider.

**Afterwards:** re-route back once the provider recovers, and record the model change in usage
history — every record stores the provider and model that produced it, so the switch is
auditable.

---

### R8 — Marking is failing or wrong

**Symptoms:** submissions fail to mark; or marks are arriving and are wrong.

**Diagnosis — these are different problems.**

**Failing:** check `submissions.ai_error` and the `jobs` table. Usually R7 or R5.

**Wrong:** this is more serious, because a scheme-backed confident mark auto-finalizes and
counts immediately.

1. Identify the scope. Every mark records what produced it:
   ```sql
   SELECT ai_model, ai_prompt_version, COUNT(*)
   FROM question_marks
   WHERE created_at > now() - interval '7 days'
   GROUP BY 1, 2;
   ```
2. Did a prompt version or a model change recently? That is the first hypothesis, and there is
   no evaluation harness that would have caught it (`RISK-10`).
3. Check whether the affected questions were scheme-backed. Without a mark scheme, marks are
   `unsure` and should never have auto-finalized.

**Action**

1. If a prompt or model change is implicated, revert it — a prompt revert is a code change, so
   a model re-route (R7) is the faster mitigation.
2. Identify the affected marks by `ai_model` and `ai_prompt_version` and give the tutor the
   list to review. **Do not bulk-edit marks.** Every change to an already-set mark writes a
   `MarkOverrideAudit` row, and the tutor holds final authority (`PROD-7`).
3. If students have already seen wrong marks, they can contest them — but only **one remark
   request per question, ever**, so do not spend that on something the tutor is already fixing.

**Verification:** new submissions mark correctly; the affected set has been reviewed by the
tutor.

---

### R9 — Readiness looks wrong or stale

**Symptoms:** a score has not moved after work was marked; a score looks implausible; the same
student shows different readiness in different places.

**Diagnosis**

**Different numbers in different places is expected today and is not a bug you can fix
locally.** `/readiness/*` serves v2 snapshots, while `analytics.py`, `reports.py`, and
`student_crm.py` still read v1 tables directly (`RISK-5`).

For staleness:

1. Is a run pending? `is_updating` is derived from the `jobs` table.
   ```sql
   SELECT id, status, run_after FROM jobs
   WHERE type = 'compute_readiness_v2' AND status IN ('pending','running')
   ORDER BY id DESC;
   ```
   A pending job with a future `run_after` is the debounce working as designed — up to
   `READINESS_V2_COALESCE_SECONDS` (default 600).
2. Did the last run fail?
   ```sql
   SELECT id, student_id, subject_id, status, error, created_at
   FROM readiness_snapshots ORDER BY id DESC LIMIT 20;
   ```
   `status='failed'` means Layer 2 failed but the deterministic factor rows were kept.
3. Is the response saying `engine: "v1"`? Then no ready snapshot exists for that
   (student, subject) and the fallback is serving.
4. For an implausible score, decompose it — this is what the audit trail is for:
   ```sql
   SELECT factor, score, confidence, evidence_count
   FROM factor_evaluations WHERE evaluation_run_id = '<the snapshot's run id>';
   ```

**Action**

- Failed run: re-enqueue (R6). It is append-only, so a re-run is a new audited evaluation.
- Provider problem: R7.
- **Emergency:** set `READINESS_V2_SHADOW_ENABLED=false` and restart. Despite the name this is
  a **kill switch**: v2 runs stop being enqueued and the whole product falls back to v1. Use it
  only if v2 is producing actively harmful numbers, and record that you did — it is easy to
  forget the product is now on a different engine.

**Verification:** a new snapshot with `status='ready'` appears, and the score decomposes
sensibly against its factor rows.

---

### R10 — Google Classroom sync is failing

**Symptoms:** "not configured"; sync returns an auth error; courseWork is not importing; some
students' submissions are missing.

**Diagnosis**

| Symptom | Cause |
|---|---|
| "Not configured" everywhere | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` unset |
| Connect flow fails at Google | `GOOGLE_REDIRECT_URI` does not match the Google OAuth client **verbatim** — origin *and* path |
| Sync returns an auth error | The stored refresh token is invalid, revoked, or undecryptable |
| Some students missing | **Expected.** Roster emails that do not match an Avora account are skipped, not guessed |
| Some attachments missing | **Expected.** Only PDF/JPEG/PNG/WebP are imported; native Google Docs are skipped |

**Action**

- Redirect URI mismatch: the value in `render.yaml` must be registered verbatim as an
  authorized redirect URI on the Google Cloud OAuth client. A bare origin will not match.
- Invalid token: the tutor disconnects and reconnects in Settings.
- **Undecryptable** token: this means `GOOGLE_TOKEN_ENCRYPTION_KEY` changed — see R12. Every
  linked tutor must reconnect.
- Missing students: match the roster email to an Avora account, or have the student's account
  created with that address.

**Verification:** `POST /classroom/sync` completes; courseWork appears as draft assignments;
`classroom_work_links` rows exist so re-sync stays idempotent.

---

### R11 — The uploads disk is full or files are missing

**Symptoms:** uploads fail; downloads 404 while the database row exists; the service behaves
oddly under write load.

**This is the sharpest data-loss exposure in the system** (`RISK-8`). The database stores only
relative paths, with no integrity link to the files.

**Diagnosis**

1. Render → the service → **Disks**. The disk is 10 GB, mounted at `/data`, with
   `UPLOAD_DIR=/data/uploads`. Nothing monitors its usage.
2. From a Render shell: `df -h /data` and `du -sh /data/uploads`.
3. If files are missing rather than the disk being full, check whether a deploy ran without the
   disk mounted — that orphans every row.

**Action**

**Disk full:**
1. Confirm `UPLOAD_DIR` is `/data/uploads`, not a path inside the container. A wrong value fills
   the container's own filesystem and loses files on the next deploy.
2. Increase the disk size in Render.
3. Look for orphaned files — written by a request that later failed without calling
   `delete_file()`. There is **no reconciliation tool**; comparing directory contents against
   the union of path columns is a manual query.

**Files missing:**
1. Establish whether the disk was ever unmounted. If so, the files are gone — the rows are not
   recoverable from the database alone.
2. Tell the affected tutors precisely which work must be re-uploaded. Do not delete the rows;
   they carry marks and evidence that are still valid.

**Verification:** uploads succeed; `df -h /data` shows headroom; downloads resolve.

---

### R12 — Rotate a secret

**Read this whole section before rotating anything.** Two of these have blast radii that
surprise people.

| Secret | Blast radius | Procedure |
|---|---|---|
| **`JWT_SECRET`** | **Every session ends immediately** — all access and refresh tokens become invalid. Also invalidates every stored Google refresh token **if `GOOGLE_TOKEN_ENCRYPTION_KEY` is unset**, because the key is then derived from it | Set a new value; restart. Warn users first. Set a dedicated `GOOGLE_TOKEN_ENCRYPTION_KEY` beforehand to decouple the two |
| **`GOOGLE_TOKEN_ENCRYPTION_KEY`** | **Every stored Google refresh token becomes undecryptable.** Every linked tutor must reconnect Classroom | Set a new value; restart; tell every linked tutor to reconnect |
| `ANTHROPIC_API_KEY` | Chat, reports, readiness, class briefs fail until the new key is live | Issue a new key at the provider; update in Render; restart; revoke the old |
| `GEMINI_API_KEY` | **The homework pipeline fails** until the new key is live | As above. Consider R7's re-route as a bridge |
| `GOOGLE_CLIENT_SECRET` | New OAuth connections fail; existing refresh tokens keep working | Rotate in Google Cloud; update in Render; restart |
| Database credentials | Total outage until updated | Rotate in Render; the service picks up `DATABASE_URL` from the database binding |

**Universal steps**

1. Establish the blast radius from the table **before** changing anything.
2. Change the value in the Render dashboard.
3. Restart the service — configuration is read once at startup via an `lru_cache`d
   `get_settings()`.
4. Verify the affected surface works.
5. Revoke the old credential at the provider.
6. If the rotation was prompted by a leak: rotate first, investigate second, and write the
   incident note (R15). A key committed to git is in the history permanently — rotation is the
   only remedy.

**Verification:** the affected surface works with the new value, and the old credential is
confirmed revoked.

---

### R13 — Restore the database

**Symptoms:** data loss, corruption, or a migration that destroyed a column.

> **This procedure has never been executed.** `REL-19` requires it to be run against a
> non-production target at least once. Until then it is a plan, not a verified capability.

**Action**

1. **Stop writes.** Suspend the Render service. A restore that races the application produces a
   worse state than the one you started with.
2. Render → the database → **Backups**. Identify the target point in time. Confirm what the
   plan actually retains — this has not been verified either.
3. Restore into a **new** database instance, not over the live one, so the current state
   remains available for comparison.
4. Compare. Establish precisely what was lost between the restore point and the incident.
5. Repoint `DATABASE_URL` to the restored instance and restart.
6. **Reconcile against the uploads disk.** The disk is not restored with the database, so
   after a restore the two are at different points in time: rows may reference files written
   after the restore point, or files may exist with no row. There is no tool for this.
7. Re-enqueue any background work that was in flight.

**Verification:** the application starts; spot-check recent submissions, marks, and readiness
snapshots; confirm file downloads resolve.

---

### R14 — Support tasks

**A student cannot sign in.**
Most likely the throttle: 10 failed attempts per identifier per 15 minutes. It clears on its
own after the window and resets on a successful sign-in. It is an in-process counter, so a
service restart also clears it — a heavy-handed but effective fix.

**Reset a student's password.**
`POST /groups/{id}/students/{id}/reset-password`, tutor-initiated. **This bumps
`token_version`**, ending every existing session for that account immediately — which is the
point: a reset is how a tutor evicts whoever else has been using a shared account.

**An invite has expired.**
All invites expire after 14 days. Parent-link codes are **single-use** and cannot be reused
once redeemed. Issue a new one.

**A parent is linked to the wrong child.**
Remove the `ParentLink` row and issue a fresh single-use invite. Do not edit the row to point
at a different student.

**A student disputes a mark.**
They contest it in the app, which routes it to the tutor's review queue with the AI's original
reasoning attached. **One request per question, ever** — a database constraint, not a policy —
so do not spend it casually. It is never resolved by AI.

**A tutor wants readiness recomputed now.**
It is debounced by design. Adding evidence enqueues a run scheduled
`READINESS_V2_COALESCE_SECONDS` out. Waiting is correct; if genuinely urgent, the pending job's
`run_after` can be set to the past.

---

### R15 — Incident response

**Severity**

| Level | Meaning | Examples |
|---|---|---|
| **SEV1** | Data loss, a security breach, or a total outage | Disk loss, credential leak, database down, service will not start |
| **SEV2** | A core workflow is broken for everyone | Marking down, worker dead, migration failed |
| **SEV3** | A feature is degraded, or one user is affected | One provider down, a poisoned job, Classroom sync failing |

**Response**

1. **Assess.** Which severity, and how many people are affected right now?
2. **Communicate early.** For SEV1 or SEV2, tell affected tutors what is broken and what you
   are doing before you have a fix. They are teaching; they need to plan around it.
3. **Stop the bleeding** (P2) — roll back (R3), flip a switch, or re-route a surface (R7).
4. **Preserve evidence.** Do not clear `jobs.error` or domain error columns before reading
   them. Do not restart when a stuck process is the only evidence, unless the restart is the
   mitigation.
5. **Diagnose**, then fix forward through the normal pull-request flow.
6. **Confirm recovery** with the specific check from the relevant runbook.
7. **Write it up** — within a day, while the detail is still accurate.

**The write-up**, kept short and blameless: what happened; when it started and when it was
resolved; how it was detected — and **note honestly if a user detected it**, which today is
usually the case; the root cause; what made it worse or slower to fix; what changes.

Then update this constitution: add or re-rank the risk in `governance/risk-register.md`, add a
`Known Gap` where one is revealed, and add a runbook here if the failure mode was not covered.

---

## Standards

**`OPS-1` — MUST · Critical · Active**
Confirm what is actually running (R2) before diagnosing an application bug.
*Rationale:* a failed or lagging deploy presents exactly like a code defect, and a service on a
stale branch presents like missing endpoints.

**`OPS-2` — MUST · Critical · Active**
Never retry a failed migration deploy unchanged. Establish the applied revision first with
`alembic current`.
*Rationale:* it will fail identically, and a partially applied chain leaves the database at an
intermediate revision that the next attempt may make worse.

**`OPS-3` — MUST · Critical · Active**
Take a database backup before running any `downgrade` that drops a column or a table.
*Rationale:* a downgrade destroys data, and this is the one irreversible step in R3.

**`OPS-4` — MUST · Critical · Active**
Establish a secret's blast radius from R12's table before rotating it.
*Rationale:* `JWT_SECRET` ends every session; `GOOGLE_TOKEN_ENCRYPTION_KEY` forces every linked
tutor to reconnect. Both surprise people.

**`OPS-5` — MUST · Important · Active**
Prefer a configuration change to a code change during an incident.
*Rationale:* P3 — re-routing a surface is a restart; a code fix is a build plus a migration run
plus a deploy.

**`OPS-6` — MUST NOT · Critical · Active**
Never bulk-edit marks, evidence, or readiness rows to correct an AI error. Route corrections
through the tutor.
*Rationale:* `PROD-7` — the tutor holds final authority and every override is audited. A direct
write bypasses the audit trail that makes the record defensible.

**`OPS-7` — MUST · Important · Active**
Preserve error state — `jobs.error` and domain error columns — until it has been read.
*Rationale:* it is frequently the only evidence, because there is no logging or error tracking
(§11).

**`OPS-8` — MUST · Important · Active**
Only reset a `running` job to `pending` once certain no worker is processing it.
*Rationale:* handlers are idempotent (`BE-6`), so a duplicate run is safe, but two workers on
one job wastes an AI call and can interleave writes.

**`OPS-9` — MUST · Important · Active**
Record every use of `READINESS_V2_SHADOW_ENABLED=false`, and treat it as an open incident until
reverted.
*Rationale:* it silently moves the entire product to a different readiness engine, and the
name does not suggest that.

**`OPS-10` — MUST · Important · Active**
Every SEV1 and SEV2 incident gets a written note within a day, and the constitution is updated
with what it revealed.
*Rationale:* P4, and `governance/change-process.md` — an incident that changes nothing will
recur.

**`OPS-11` — MUST · Important · Active**
A new failure mode encountered in production gets a runbook here.
*Rationale:* this document is only as useful as its coverage, and the moment the knowledge is
freshest is immediately after using it.

**`OPS-12` — SHOULD · Important · Active**
Check `/data` usage before any change expected to increase upload volume.
*Rationale:* `INF-14` — 10 GB, unmonitored, holding every piece of student work ever submitted.

---

## Known Gaps

| Gap | Why it matters | Severity |
|---|---|---|
| **Nothing alerts.** Every runbook still starts from a human noticing. | `/api/v1/health/ready` now answers the "is it broken" question in one request, so *diagnosis* is fast. *Detection* is unchanged: it is however long until a tutor complains. An external monitor polling that endpoint and alerting on 503 would close this, and it is the single highest-value operational change available. §11. | `blocking` |
| **The database restore procedure has never been executed.** | R13 is a plan, not a verified capability. `REL-19`. | `blocking` |
| **No reconciliation tool for rows against files.** | R11 and R13 both require it and neither can offer one. `RISK-8`. | `blocking` |
| **Backup retention is unverified.** Nothing records what Render's plan actually retains or for how long. | R13 step 2 cannot be planned without it. | `blocking` |
| **`READINESS_V2_SHADOW_ENABLED` is the only kill switch** in the product. | R9's emergency step is all-or-nothing: there is no way to disable a single AI surface without re-routing it to a provider that may not support it. | `before scale` |
| **No staging environment.** | Every runbook's "test it first" step has nowhere to run. §08. | `blocking` |
| **Job retries have no backoff**, so R6's transient-cause path has usually already burned both attempts. | The retry budget is spent before the condition it would recover from has cleared. §04, `REL-9`. | `before scale` |
| **No documented on-call or escalation.** | Nothing defines who executes these procedures out of hours. `governance/ownership.md`. | `before scale` |
| **The manual end-to-end verification script referenced by the archived handoff is outside the repository** and unrecoverable. | The runbooks above are now the only written operational procedures. | `nice to have` |

---

## Review Triggers

Update this document when:

- An incident occurs that is not covered by a runbook here (`OPS-11`).
- A runbook is executed and found to be wrong or incomplete — fix it immediately afterwards.
- A kill switch, feature flag, or alerting is added.
- The deploy, rollback, or migration process changes.
- A new external dependency is added — it needs an outage runbook.
- A secret is added — it needs a row in R12.
- Either health endpoint changes what it reports, which changes the diagnosis step of R2 and R5.
- Alerting is introduced, which changes the opening assumption of every runbook here.
- A staging environment appears.
