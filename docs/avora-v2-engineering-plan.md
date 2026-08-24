# Avora v2 — Engineering Fix Plan

> **What this is.** The team-facing execution plan closing what audit v2
> (`avora-production-readiness-audit-v2.md`) found. It expands the eleven P1 findings plus the
> priority slice of P2s into task cards detailed enough for an engineer who has never seen the
> repo to pick one up and finish it without asking what "done" means.
>
> **Companion docs:** findings + evidence live in the audit; task summaries live in
> `avora-v2-remediation-plan.md`. This document is the how.
>
> **Written:** 24 August 2026. Baseline: default `e622e76`.

---

## 1. Working agreement (read before anything)

- **Repo:** `muslim216/IGCSE-OS-product-repositiry-`, default branch is literally named
  `claude/igcse-os-planning-q8be0t` (GitHub rename pending — nothing hardcodes "main").
- **One branch per task**, named for it (`fix/…`, `feat/…`, `ops/…`). **Never merge** — PRs are
  opened into the default branch and the owner merges. Nothing pushes to the default branch
  except documentation-only changes.
- Every task ships with its own **negative-case test** (wrong role, other org's row, oversized
  input, failure path). A fix without its regression test is not done.
- Local gates before every PR: `ruff check . && ruff format --check .`,
  `mypy app/services app/schemas`, full `pytest`, frontend `npm test`, `npm run build`
  (that build is the only TS type check), `eslint --max-warnings 0`, `prettier --check`.
  CI runs the same plus Alembic up→down→up on Postgres 16.
- **Constitution wins.** `docs/` volumes define the rules (`PROD-*`, `SEC-*`, `AI-*`, `DB-*`);
  cite rule IDs in PRs rather than re-deriving arguments.
- Backend setup: `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`,
  `docker compose up -d db`, `alembic upgrade head`. Frontend: `npm install`.
- **SQLite caveat that shapes several tasks:** the suite runs on SQLite, which does not enforce
  foreign keys by default. Any fix whose bug class lives below SQLAlchemy (FK enforcement,
  cascades, constraints) must be verified against Postgres (CI's migrations job or a local
  docker Postgres), not just the unit suite.

## 2. Sequencing overview

| Stage | Contents | Why this order |
|---|---|---|
| Sprint 0 | T0.1–T0.3 | Prerequisites: unmerged Phase-0a branches carry a P1 (readiness blindness) and a latent migration fork |
| Sprint 1 | C1–C6 | Six independent small code fixes; each lands alone, any order |
| Sprint 2 | W1–W4 | Need owner decisions (§6) or external setup |
| Sprint 3 | P2 batch | Grouped follow-ups, started only after Sprint 1 closes |

---

## 3. Sprint 0 — prerequisites

### T0.1 — Merge Phase-0a (five branches) ⚠️ includes a migration-fork trap

**Owner action, but engineering must prepare it.**

Branches, in merge order: `fix/av-29-settled-statuses` (`edacdec`) →
`feat/av-29-recompute-runner` (`56e40c9`, stacks on 0.1) → `chore/av-57-remove-student-chat`
(`3fa76e7`) → `chore/av-57-remove-peer-ranking` (`e347f46`) → `chore/av-58-hide-classroom-kb`
(`20b2852`). None exist on origin yet — push each first.

**The trap:** default now contains `0025_user_time_zone` with `down_revision = "0023"`. The
0.3 branch adds `0024_drop_chat`, which *also* chains from `0023`. Merging 0.3 unrebased
creates **two Alembic heads** and `alembic upgrade head` fails in every environment.

**Fix before opening the 0.3 PR:** rebase the branch and reparent the migration — change
`0024_drop_chat.py`'s `down_revision` from `"0023"` to `"0025"` (and rename the file to
`0026_drop_chat.py` to preserve ordering conventions, updating its `revision = "0026"`).
Then verify locally: `alembic upgrade head && alembic downgrade base && alembic upgrade head`.

Expect textual conflicts vs current default in `CLAUDE.md`, `backend/tests/conftest.py`,
`frontend/src/test/Nav.test.tsx`, and `tests/test_authorization.py` (default moved under these
branches during PR #41). Resolve keeping both intents; the chat/ranking deletions win on their
own surfaces.

### T0.2 — Delete local Finder duplicates

Untracked junk breaking local pytest: `backend/tests/test_ai_pricing 2.py` (fails the suite
with stale expectations), `backend/alembic/versions/0025_user_time_zone 2.py` (makes local
`alembic upgrade` raise DuplicateRevision), plus `docs/* 2.md` and `frontend/openapi 2.json`.
Delete all `" 2"` copies.

### T0.3 — Green baseline

Confirm CI green on the default branch after T0.1 merges (especially the Alembic job). Record
suite counts as the pre-fix baseline: backend 530+, frontend 181.

---

## 4. Sprint 1 — six independent code fixes

Each card: Problem → Evidence → Fix spec → Tests → Acceptance. All six are small (S), mutually
independent, and can be parallelized across engineers.

---

### C1 — Startup reaper for orphaned jobs *(P1-2)*

**Problem.** A job is committed `status='running'` before its handler runs. If the process
dies mid-handler (every deploy landing while marking runs qualifies), the row stays `running`
forever: the claim query selects `pending` only, retries never engage, and the student's
submission shows "being marked" indefinitely with nothing watching.

**Evidence.** `backend/app/workers/jobs.py:176-193` (commit running → separate-session
execution), claim at `:179`; runbook R5 prescribes manual SQL as the recovery
(`14-operations-runbooks.md:312-318`).

**Fix spec.**
1. In `app/main.py` lifespan, immediately before the worker task starts, open a session and
   run `UPDATE jobs SET status='pending' WHERE status='running'` (SQLAlchemy
   `update(Job).where(Job.status == JobStatus.running).values(status=JobStatus.pending)`).
2. Comment above it citing: safe because handlers are idempotent (BE-6); correct because the
   single-instance deployment means no live worker can legitimately hold a `running` row at
   startup (RISK-1); replaces manual runbook step R5.2.
3. Leave in-job retry/backoff untouched.

**Tests** (`tests/test_jobs.py`):
- `test_startup_requeue_resumes_orphaned_running_job`: seed a `running` job with a counting
  side-effect handler; run the reaper helper; assert status `pending`; run
  `process_one_job()`; assert handler executed exactly once and job ends `done`.
- `test_startup_reaper_leaves_pending_and_failed_alone`: seed pending/failed/done rows;
  assert only `running` transitions.

**Acceptance.** Kill-switch simulation covered by the first test; `worker_status` unaffected;
runbook R5.2 updated to "automatic since <date>; manual SQL remains the fallback."

---

### C2 — Enforce upload size before reading bytes *(P1-10)*

**Problem.** The `UploadFile` path reads the entire body into RAM, then checks the size — a
20 MB limit enforced after an unbounded allocation. Authenticated users can memory-pressure
the single instance.

**Evidence.** `backend/app/services/storage.py:108-109` (`data = await file.read()` precedes
the limit check). The `save_bytes` path at `:134` already checks first — mirror it.

**Fix spec.**
1. Replace the single read with a chunked loop (e.g. 1 MiB chunks into a `bytearray`),
   aborting with the existing size error the moment cumulative length exceeds
   `MAX_UPLOAD_BYTES` (+1 sentinel).
2. Keep all downstream behavior identical: magic-byte validation, alias normalization, HEIC
   transcode operate on the same buffer as today.
3. Do not touch `save_bytes`.

**Tests** (`tests/test_storage.py`):
- `test_oversized_upload_rejected_before_full_read`: monkeypatch a file object whose `read`
  yields more than the limit in chunks; assert rejection and that total bytes materialized
  stayed ≤ limit + chunk.
- `test_upload_at_exact_limit_succeeds` and existing happy-path/HEIC tests stay green.

**Acceptance.** No endpoint path reads unbounded bytes before validation.

---

### C3 — Block resubmission that would orphan audit rows *(P1-5)*

**Problem.** Resubmitting homework deletes the submission's `QuestionMark` rows. If a tutor
ever adjusted a draft mark, `MarkOverrideAudit.question_mark_id` references those rows; the
FK (no `ondelete`) makes the DELETE fail on Postgres → 500, transaction rollback, submission
permanently stuck in `needs_review`. SQLite doesn't enforce FKs, so tests never saw it.

**Evidence.** `backend/app/api/submissions.py:142-151` (delete loop);
`models/homework.py:261` (audit FK, no ondelete); audit rows written pre-finalize at
`submissions.py:673`.

**Fix spec (endpoint guard, chosen over cascade deliberately).**
1. In `submit_work`, before deleting marks, check for audit rows:
   `select(MarkOverrideAudit.id).join(QuestionMark, …).where(QuestionMark.submission_id == submission.id)` —
   if any exist, raise `HTTPException(409, "A tutor has already reviewed marks on this "
   "submission — ask them to reset it before uploading again")`.
2. Do NOT delete audit history and do NOT add `ondelete=CASCADE` in this task (audit is an
   append-only record; a reset flow is a separate product decision).
3. Note the constraint in the resubmit UX copy follow-up (P2 list).

**Tests** (`tests/test_homework.py`):
- `test_resubmission_with_tutor_audit_returns_409`: finalize-free flow where tutor edited a
  draft (creating an audit row), then resubmit → 409, marks intact, submission unchanged.
- `test_resubmission_without_audit_still_works`: existing happy path stays green.

**Acceptance.** Reproduce-then-prevent demonstrated against Postgres in CI (the migrations job
runs with real FK enforcement; add the scenario to an integration test there if the SQLite
suite cannot express it).

---

### C4 — Explicit provider timeouts and retry caps *(P1-6)*

**Problem.** Both SDK clients are constructed with library defaults (Anthropic ≈600 s timeout,
internal retries). The worker is strictly serial and serves every organization, so one hung
provider call stalls all marking/extraction/readiness platform-wide for many minutes; a
provider brownout is effectively a pipeline outage behind green health checks.

**Evidence.** `backend/app/services/ai.py:142-148` (Anthropic), `:151-167` (Gemini); zero
`timeout=` hits across services; serial claim at `workers/jobs.py:179`.

**Fix spec.**
1. Introduce a per-surface timeout map next to `resolve_surface`:
   `chat: 60s · reports/readiness/narrative/class_brief: 120s · marking/extraction/syllabus:
   300s`.
2. Construct clients with `timeout=<mapped>` and `max_retries=1` (both providers support the
   kwarg; Gemini via its request options).
3. Cache clients per (provider, timeout-bucket) instead of constructing per call (also closes
   audit F17 connection-churn).
4. Optional, if review finds it low-risk: wrap `process_one_job` handler invocation in
   `asyncio.timeout(JOB_STALL_SECONDS)` so even a wedged call eventually fails into the
   normal retry path.

**Tests.** Unit: client factory returns configured timeout/retries per surface. Manual note in
PR: simulated slow response no longer blocks beyond the mapped budget.

**Acceptance.** `grep -rn "AsyncAnthropic(" app/services` shows exactly one construction site
with explicit kwargs; same for Gemini.

---

### C5 — Stop window-refetch from destroying unsaved work *(P1-4)*

**Problem.** `main.tsx` creates the QueryClient with stock defaults (`staleTime: 0`,
`refetchOnWindowFocus: true`). Several screens seed editable local state from query data in a
`useEffect` with no dirty-guard, so returning focus to the tab silently overwrites a tutor's/
student's in-progress edits. One screen (PreferencesPage) additionally renders defaults before
load resolves and saves silently on failure.

**Evidence.** `frontend/src/main.tsx:16`;
`tutor/SubmissionReviewPage.tsx:75-87` (drafts seed, no guard);
`tutor/GradeBoundariesPage.tsx:45-47` (boundary draft);
`student/TutorChatPage.tsx:31-33` (messages replaced wholesale; also `onSend` calls
`createConversation()` outside its try/catch — unhandled rejection, busy-flag never set);
`tutor/PreferencesPage.tsx:100-114` (mount race + no `onError`). Contrast the correct pattern
already in the codebase: `tutor/AssignmentDetailPage.tsx:59-72` (`!dirty` guard).

**Fix spec.**
1. `main.tsx`: `new QueryClient({ defaultOptions: { queries: { staleTime: 30_000,
   refetchOnWindowFocus: false } } })`. Add a comment explaining why (unsaved-draft
   protection; data freshness is handled per-query where it matters).
2. Port the AssignmentDetailPage `dirty` pattern to SubmissionReviewPage and
   GradeBoundariesPage seeds.
3. TutorChatPage: merge incoming server messages with local optimistic ones by id rather than
   replacing; move `createConversation()` inside the try/catch and surface its failure.
4. PreferencesPage: gate the whole render on `prefs.isLoading` (skeleton exists in ui.tsx);
   add `onError` to the save mutation (toast or inline).
5. Audit remaining `useEffect(() => setState(query.data))` occurrences
   (`grep -nE "setDraft|setForm|setMessages" frontend/src`) and either guard or justify each
   in a comment.

**Tests** (`src/test/*.test.tsx`, vitest + testing-library):
- `refocus does not clobber dirty draft` (SubmissionReviewPage): edit textarea, fire window
  focus, assert edit persists.
- Same shape for GradeBoundariesPage.
- `preferences page waits for load before showing sliders` and `save failure shows error`.
- Chat: `conversation creation failure shows an error and clears busy`.

**Acceptance.** Zero remaining ungated data→state seed effects; QueryClient defaults documented.

---

### C6 — Meter syllabus extraction *(P1-9)*

**Problem.** Syllabus extraction spends real multimodal tokens and writes **no**
`ai_usage_events` row — the only surface structurally invisible in cost analytics. Contradicts
ai.py's module contract.

**Evidence.** `backend/app/services/syllabus_extraction.py` imports only
`file_block, require_parsed, structured_complete`; zero `record_usage` references.

**Fix spec.** Mirror `extraction.py:126-133`: import `record_usage` + `AiFeature.syllabus`
(already exists in the enum), call after `require_parsed`, attributing
`organization_id`/`tutor_id` from the `SyllabusUpload` row.

**Test.** With the `fake_ai` fixture patched onto this module (QA-7: patch the *calling*
module, not `services.ai`), assert one `ai_usage_events` row exists with feature=syllabus and
non-zero tokens.

**Acceptance.** `/ai-usage/analytics` shows syllabus volume; grep confirms no AI-calling
service lacks `record_usage` (this was the last one).

---

## 5. Sprint 2 — decisions then builds

### W1 — Unify admin tenancy scoping *(P1-7 · needs Decision D1)*

**Problem.** `today.py:36-41` states and implements the rule — *"an admin is a tutor with
wider reach inside their own organization, not across organizations"* (org mismatch checked
*before* role). Everywhere else uses bare role checks: an admin satisfies `_tutor_owns` for
**any** submission in any organization → cross-tenant reads AND writes (marks, finalize —
which mint readiness evidence). ~12 sites listed in the audit
(`assignments.py:44,170,192`, `groups.py:43`, `lessons.py:38,49`, `resources.py:21,128`,
`knowledge.py:25`, `syllabus_uploads.py:19,63`, `analytics.py:34`, `classifieds.py:71,107`,
`past_papers.py:83`, `students.py:45,79`, `readiness.py:48`, worst: `submissions.py:80-81`).

**Build.**
1. New `backend/app/services/tenancy.py`: `def org_scoped(user, *, organization_id, tutor_id)
   -> bool` implementing today.py's three-clause logic; today.py refactored to call it.
2. Replace every bare `(tutor_id != user.id and role != admin)` / early-return-admin site with
   the helper. Mechanical but wide — do it in one PR so the rule cannot half-exist (the audit's
   own warning about half-migrations applies).
3. Extend `tests/test_authorization.py`: cross-org admin cases for submissions read/write,
   assignment access, resource download — all must 404.
4. Update §07 security architecture text to state the decided semantics.

### W2 — Throttle AI-spending endpoints *(P1-8 · needs Decision D2)*

Reuse `services/rate_limit.FixedWindowLimiter` (login_limiter's machinery):
- Key per student on `POST /submissions/{id}/resubmit`-adjacent `submit_work` AI triggers and
  `log_attempt` (which deletes settled marks and re-enqueues a full vision-marking job on every
  call). Suggested cap: 10/day/student (D2).
- Additionally refuse re-log while a mark job for the submission is `pending`/`running`
  (idempotency courtesy, saves duplicate queue pressure).
- Registration: limiter on `/auth/register/tutor|student|parent` keyed per IP-hash
  (unauthenticated bcrypt + org-creation burn).
- 429 responses carry a human message consistent with the login limiter's copy style.

### W3 — Protect the uploads disk *(P1-1 · needs Decision D3 + owner execution)*

Deliverable is mechanism + rehearsal, not prose:
1. Choose: Render disk snapshots vs nightly `rclone`/AWS-sync job from the API container
   (`/data/uploads` → bucket, incremental, versioned) — D3.
2. Implement the sync as a scheduled job (compose with the narrative sweep pattern), plus
   `scripts/reconcile_uploads.py`: compare `submission_files.path`/`classified.file_path`
   rows against bucket objects; report orphans both directions.
3. Rehearse restore once into a scratch directory; document actual RPO/RTO achieved in §11;
   retire the "there is no tool for this" sentence.

### W4 — Observability floor *(P1-3 · needs Decision D4/D5)*

1. `logging.dictConfig` at startup: JSON formatter, `LOG_LEVEL` env (default INFO),
   uvicorn.access included. Today even "job worker started" is invisible (runbook admits it).
2. Request-ID middleware: uuid4 per request, echo as `X-Request-ID`, inject into log records;
   worker logs inherit the job id as correlation key.
3. External uptime monitor polling `/api/v1/health/ready` every 60 s with alerting (D5) —
   config, not code, but it belongs in this ticket's acceptance.
4. Optional Sentry: add `SENTRY_DSN` setting + init guarded on presence (no-op when unset) —
   zero dependency when DSN absent (D4).

---

## 6. Decision register (owner answers unlock Sprint 2)

| # | Decision | Recommendation |
|---|---|---|
| D1 | Admin semantics | Org-scoped tutor (matches `today.py`/`narrative.py` and SEC-7's stated intent) |
| D2 | Student AI-trigger caps | 10 marking-bearing submissions/day/student; tutors uncapped but logged |
| D3 | Backup destination | Versioned object store (S3-compatible); nightly incremental + reconcile |
| D4 | Error tracking | Yes — Sentry or equivalent; DSN via env |
| D5 | Uptime monitoring | Any external poller on `/health/ready`, 60 s interval, alert channel |

---

## 7. Sprint 3 — P2 batch (start after Sprint 1 closes)

Grouped so related schema/type changes travel together:

1. **DB integrity PR:** declare in models the four missing index sets (readiness_snapshots,
   factor_evaluations, evidence, mark_override_audit — DB-12) + new composite
   `ix_ai_usage_org_created` on `ai_usage_events` (single migration, `batch_alter_table` +
   `NAMING`, working downgrade); add exactly-one-of CHECK constraints on
   submissions/question_marks mirroring narratives'; partial unique index on
   `evidence.source_ref`.
2. **Query batching PR:** review_queue unsure-counts + open-remarks as grouped subqueries;
   group-assignment stats as one aggregate; analytics per-student lookups joined; drop the
   unconditional 5 s poll on AssignmentDetailPage (gate it).
3. **Contract honesty PR:** `api/readiness.py:121` score → nullable + regenerate OpenAPI +
   `schema.d.ts` (FE-4 pair) + frontend null-handling ("not enough data yet").
4. **Form layer PR:** `Field` component in ui.tsx binding label/input/`aria-invalid`/error
   text from `ApiError.fields`; migrate CreateLessonModal + AssignmentCreatePage; onBlur
   validation on public forms.
5. **A11y structural PR:** AppShell h1 (visually-hidden ok), demote skipped headings, Modal
   focus trap + restore + unique aria-labelledby, name the ✕ buttons, un-hover-gate chat
   delete.
6. **Blank-screen trio PR:** loading/error branches for student Homework/Exams + MocksPage
   ported from the TodayDashboard skeleton/EmptyState pattern.
7. **Config & supply-chain PR:** JWT-default fail-fast; `.env.example` gains NARRATIVE_*
   family + UPLOAD_DIR + JWT_ALGORITHM/expiries; pip-audit + npm audit + CodeQL + coverage
   report (no gate yet) added to CI; lockfile via uv/pip-tools (separate PR, coordinate with
   Dockerfile).
8. **Transport PR:** HSTS + Permissions-Policy in vercel.json.
9. **Auth hardening PR:** single-flight refresh mutex in `client.ts`; (rotation/reuse
   detection explicitly deferred).
10. **AI hygiene PR (ride along with task 3.2/AV-124):** pricing pasted into Render dashboard
    in the same change; metering conditional-skips removed (record always, attribute with
    nullable tutor); abandoned-stream usage capture in `finally`; chat history window cap;
    SYLLABUS prompt injection clause (bump v1→v2); prompt/request-shape version stamp so
    bd97a88-class changes are traceable going forward.

---

## 8. Definition of Done (every PR)

- [ ] Negative-case test included and named for the failure it prevents
- [ ] Full local gates green (§1); CI green including Alembic round-trip
- [ ] OpenAPI + `schema.d.ts` regenerated together if any response schema changed
- [ ] Constitution documents updated in-PR where behaviour touches them (GOV-1)
- [ ] ECC reviewer gate passed for the task's named lenses; findings fixed or answered inline
- [ ] Task card's Acceptance bullets demonstrably true
- [ ] PR description links the audit finding ID (P1-n) and cites constitution rule IDs

---

## 9. Explicitly out of scope for this plan

Code splitting/bundle work · deeper a11y polish beyond items listed · token-palette sweep ·
refresh-token rotation · staging environment build · Phase D design pass · AV-124 execution
itself (task 3.2 owns it; this plan only rides its PR for pricing/metering). Each is tracked in
the audit's P2/P3 lists or the Avora plan phases.
