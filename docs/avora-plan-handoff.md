# Avora New State plan — programme handoff

**Audience: agents, not humans.** Dense and declarative on purpose. Every assertion is either
(a) verified in-session and marked `VERIFIED`, (b) sourced to a file path, commit, PR or rule ID,
or (c) marked `UNVERIFIED`. **Do not upgrade an `UNVERIFIED` claim without testing it.**

This is the **programme-level** handoff — where the whole plan stands. Two phase-local records hold
the detail this document does not repeat, and both are still accurate:

- [`docs/av-82-phase-1-handoff.md`](av-82-phase-1-handoff.md) — the scale work: invariants,
  test-infrastructure constraints for concurrency, review-bot behaviour.
- [`docs/av-9-phase-2-handoff.md`](av-9-phase-2-handoff.md) — subjects, chapters and syllabus: what
  is stored but not yet consumed, the tenancy and grade-boundary invariants, and what Phases 3, 6
  and 9 must pick up.
- [`docs/av-81-phase-3-handoff.md`](av-81-phase-3-handoff.md) — marking and evidence: the
  assembler, the **reversed** `AV-76` precedence, and what 3.4/3.5/3.6 must not break.

| Field | Value |
|---|---|
| Programme | Avora New State (revision 5) |
| Spec of record | [`docs/avora-new-state-august-16.md`](avora-new-state-august-16.md) — §7 holds the tasks |
| Handoff written | 2026-08-30 |
| State as of | **Phase 2 complete** — 2.1–2.6 merged (PRs #57–#62) |
| Phases complete | **0, D, 1, 2** — 4 of 14 |
| Phases remaining | **3, 4, 5, 6, 7, 8, 9, 10, 11, 12** — 10 of 14 |
| Tasks complete | **25 of 80 enumerated** (Phase 2 done) |
| Next task | **Phase 3 — marking and evidence (`AV-81`), now unblocked** |
| Migration head | `0033_subject_marking_rules` on the default branch |
| Deployed instances | **1** — and that is deliberate (§3) |

> **Task count, precisely.** The plan's own §2 says "roughly 76 tasks across 14 phases". Counting
> the task tables in §7 gives **80**. The header is an estimate written before revision 5 added
> tasks; the tables are the authority. Do not treat "76" as a checklist length.

---

## 1. Programme status

| Phase | Name | Tasks | Status | Landed |
|---|---|---|---|---|
| **0** | Truth and hygiene | 0.0 – 0.10 (11) | ✅ **DONE** | 19–25 Aug · PRs #41, #51 and predecessors |
| **D** | The design pass | D.1 – D.4 (4) | ✅ **DONE** | 24 Aug · PR #43 — docs only |
| **1** | Scale foundation (`AV-82`) | 1.1 – 1.5 (5) | ✅ **DONE** | 27–30 Aug · PRs #52–#56 |
| **2** | Subjects, chapters, syllabus | 2.1 – 2.6 (6) | ✅ **DONE** | 4–8 Sep · PRs #57–#62 |
| **3** | Marking and evidence (`AV-81`) | 3.1 – 3.6 (6) | ⬜ not started | — |
| **4** | Mistakes | 4.1 – 4.5 (5) | ⬜ not started | — |
| **5** | Readiness | 5.1 – 5.7 (7) | ⬜ not started | — |
| **6** | Teaching plan | 6.1 – 6.8 (8) | ⬜ not started (parallel to 3–5) | — |
| **7** | Attendance | 7.1 – 7.4 (4) | ⬜ not started | — |
| **8** | Intelligence and communication | 8.1 – 8.7 (7) | ⬜ not started | — |
| **9** | Onboarding and tutor home | 9.1 – 9.2 (2) | ⬜ not started | — |
| **10** | Usage and sell-readiness | 10.1 – 10.4 (4) | ⬜ not started | — |
| **11** | Scale hardening (`AV-82` "the rest") | 11.1 – 11.6 (6) | ⬜ not started | — |
| **12** | The mobile app (`AV-122`) | 12.1 – 12.5 (5) | ⬜ not started — last | — |

**Phase 1, task by task** — all merged:

| ID | Task | PR | Merged | Principal artefacts |
|---|---|---|---|---|
| 1.1 | Architecture-impact report | #52 | 27 Aug | `docs/av-82-architecture-impact-report.md` |
| 1.2 | Object storage | #53 | 28 Aug | `app/services/storage.py`, `app/api/file_responses.py` |
| 1.3 | Worker as a separate process | #54 | 28 Aug | `app/workers/*`, `app/models/workers.py`, migration `0027` |
| 1.4 | Shared rate limiting on Redis | #55 | 29 Aug | `app/services/rate_limit.py`, `tests/test_rate_limit.py`, CI `redis:7-alpine` |
| 1.5 | Two-instance correctness suite | #56 | 30 Aug | `tests/test_two_instance.py`, `reclaim_orphaned_jobs()`, migration `0028` |

**Local checkout note:** this working copy is on the default branch at `56840c0`, 2.6's merge
commit. Branch from here for Phase 3 — a merged branch is finished and is never reopened or
stacked on (`CLAUDE.md`).

**What Phase 2 leaves for Phase 3 to pick up**, none of it a gap:

- `subjects.marking_rules` is written and read by its own editor and **nothing else**. Phase 3's
  context assembler (`E16`) is the single function that consumes it, under `AV-76`'s precedence:
  mark scheme → chapter notes → subject rules → board and level.
  `test_nothing_marks_with_them_yet` fails if that wiring lands without moving the marking
  prompt's version.
- `subjects.guidance_*` holds the teaching-guidance document, stored and served but never parsed.
  Phase 6 reads it to weight the plan (`AV-14`).
- Every topic now hangs off a `Chapter`, and `Topic.chapter_id` is still nullable only because
  rows predating 2.3 exist; nothing new creates a chapterless topic.

---

## 2. What is next, and what unblocks it

**Phase 2 is complete** (PRs #57–#62), which unblocks **Phase 3 — marking and evidence
(`AV-81`)** and, alongside it, Phase 6's teaching plan. Phase 3 is the next serial link in the
critical chain.

| ID | Task | Size | Mode | Blocked on |
|---|---|---|---|---|
| ~~2.1~~ | `Chapter` model, migration, topic reparenting | M | ✅ merged (#57) | — |
| ~~2.2~~ | Tutor-owned subjects, level field, delete seeds | M | ✅ merged (#58) | — |
| ~~2.3~~ | Syllabus extraction produces chapters | M | ✅ merged (#59) | — |
| ~~2.4~~ | Grade boundaries: one tutor-entered source | S | ✅ merged (#60) | — |
| ~~2.5~~ | Teaching guidance upload | S | ✅ merged (#61) | — |
| ~~2.6~~ | Per-subject marking rules | S | ✅ merged (#62) | — |

Three things about Phase 2 that an agent reading only its task text will get wrong:

- **2.1 and 2.2 are destructive** and are named in the plan's `E25` obligation. Snapshot the
  database first. "No production users" makes destruction *safe*, not *reversible* — reverting the
  commit does not restore a dropped table.
- **2.2 deletes `seed/syllabus/*.json`** and makes `seed/demo.py` create its own subject. The seed
  must be updated **in the same phase** (`E26`), because every later phase verifies against it.
- **2.3 flipped `ai_syllabus_provider` to `anthropic`** with the model left blank, inheriting
  `anthropic_model` (`AV-124`), and bumped `SYLLABUS` to **v2**. Done in #59. It also raised the
  `anthropic` floor to `>=0.125`: the old `>=0.40` predates `client.messages.parse`, which
  `structured_complete` calls, so a fresh resolve broke **every** Anthropic structured surface.
- **2.4 dropped `subjects.grade_boundaries`** (migration `0031`, copying it into the org-scoped
  table first). Half of `RISK-5` is closed: there is one boundary source. The other half — v1 and
  v2 answering different surfaces — is untouched. **A subject whose organization has set no
  boundaries now has no predicted grade anywhere**, by design (`PROD-2`); `make_subject` in
  `tests/factories.py` writes them so most fixtures keep working.

Read task 0.0's audit table (§7 of the plan) before writing anything in any phase; it marks each
task **BUILT** / **PARTIAL** / **ABSENT**, and revision 3 specified building four things that
already existed. 2.4 was such a case — the writer and the editor both existed and only the
source-collapsing was new. **2.5 and 2.6 are both marked ABSENT**, so they are genuinely new
build.

**Phase 2 gates Phases 3 and 6**, which are the widest part of the programme. The critical chain is
0 → 1 → 2 → 3 → 4 → 5 → 8 → 9 → 10 → 11 → 12, with D and 6 alongside. Anyone estimating a date
estimates that chain, not the task total (`AV-5` — **no completion date is claimed**).

---

## 3. Deployment posture — the distinction that matters most

**Capability was built. Deployment was deliberately not changed.**

`AV-85` is explicit: build multi-instance capability in Phase 1, keep running **one** instance until
the Phase 11 concurrency audit (11.2). The two-instance suite covers **known** cases, not every
read-modify-write in the codebase.

`RISK-1` — the API pinned to one instance by three things at once:

| Link | Capability | Deployed setting | Closed by |
|---|---|---|---|
| Uploads on a persistent local disk | `StorageBackend` + S3 backend | `STORAGE_BACKEND=local` | 1.2 |
| In-process worker | `python -m app.workers`, DB heartbeats | `RUN_WORKER_IN_API=true` | 1.3 |
| In-process rate limiter | `RateLimiter` on Redis, alarming fallback | `REDIS_URL` unset | 1.4 |

**DO NOT**, in Phase 2 or any phase before 11.2: deploy a second instance, add a worker service to
`render.yaml`, set `RUN_WORKER_IN_API=false`, or set `REDIS_URL` on the deployed service. Scaling
out is a **correctness** change, not a configuration change.

`render.yaml` declares `REDIS_URL` as `sync: false` — dashboard-managed, so **the file does not
prove the deployed value**. Confirm with `rate_limit.limiters[].configured` on `/health/ready`
before relying on it.

---

## 4. Debts carried out of the completed phases

These are obligations the plan states, that the completed phases did not discharge. They are not
owned by any remaining task, so they will not be picked up by working through §7 in order.

### 4.1 Two ADRs are owed and unwritten — `VERIFIED`

§2 of the plan lists the ADRs the programme owes "at minimum". Two belong to Phase 1, which is now
complete, and neither was written. `docs/adr/` ends at `0009` `VERIFIED`.

| Owed for | Decision to record | Status |
|---|---|---|
| Task 1.2 | Object storage and the signed-URL policy | **MISSING** |
| Task 1.4 | Redis | **MISSING** |

The Redis one matters more than it looks. **`ADR-0002` explicitly rejected Redis** — it is the
alternatives section of the Postgres-backed job queue decision ("Celery + Redis… same Redis
dependency") `VERIFIED`. Task 1.4 then introduced Redis anyway, for a deliberately bounded purpose
(`E18`: rate-limit counters only, Postgres stays the source of truth). Read cold, the repository now
contains an ADR rejecting a dependency the code has taken on. **That apparent contradiction is
exactly what an ADR exists to resolve**, and until one is written the reasoning survives only in
`CLAUDE.md`'s bullet and §07's `SEC-29`/`SEC-30`.

The remaining owed ADRs belong to tasks not yet started, and should be written **with** them:
deleting readiness v1 (5.3) · ~~the `Chapter` model (2.1 — **written, `ADR-0010`**)~~ · the teaching plan's
AI-advises/scheduler-decides split (6.3) · the separate owner tool (10.3) · marking-context
precedence (3.2).

### 4.2 Unowned operational items

- **11 failed jobs and one pending job ~9.7h old** on production, observed 2026-08-28 via
  `/api/v1/health/ready`. `UNVERIFIED` since, and predating Phase 1. Nothing watches the terminal
  `failed` state — `jobs.py` says so itself. **Task 11.5 is the fix**, which is nine phases away.
- `get_current_org_id` / `CurrentOrg` in `app/api/deps.py` remain **unused**. Organization scoping is
  applied per query against `user.organization_id`, which is what `SEC-7` requires. **Do not cite the
  dependency as the mechanism.**

---

## 5. Risks — what the plan claims versus what is true today

**The plan's §10 table describes the state *after* the programme completes.** Read today it is
misleading on two rows. This table is the current state.

| Risk | Plan §10 says | **True on 2026-08-30** |
|---|---|---|
| `RISK-1` — one instance | Closed at 11.2 | **Unrealised, not gone.** Capability delivered; deployment unchanged (§3). |
| `RISK-5` — two readiness engines disagree | "Closed" | **OPEN.** `AV-78` deletes v1 — that is **task 5.3, not started**. `analytics.py`, `reports.py` and `student_crm.py` still read v1 tables directly while `/readiness/*` serves v2. Numbers can disagree today. |
| `RISK-6` — frontend/backend contract drift | Closed | **Closed** — task 0.8 generates TS types from the backend schema, with two CI checks. |
| No Python type checker | Closed | **Closed** — task 0.8. Scope is `app.services` + `app.schemas`; `app/api`, `app/security.py`, `app/main.py` are genuinely unchecked. |
| `RISK-3` — migration right on SQLite, wrong on Postgres | Unchanged, more exposed | **Unchanged, more exposed.** The suite still never runs a migration; CI's Postgres job is the only check. Phase 2 opens with two migrations and 11.3 adds many constraints. |
| Prompt injection → auto-finalized mark (F1) | Mitigated by decision | **Mitigated, not closed.** `AV-93`'s deterministic scan is the only control not dependent on model judgement. A second AI check, a mark cap and calibration metrics were **offered and declined** — there is no detection layer. |
| No AI evaluation harness | Open and growing | **Open and growing.** The programme bumps five prompt versions with nothing measuring whether output improved. **Phase 2 fires the first of them** (2.3's `SYLLABUS`). |
| Children's-data regulatory posture | Not addressed | **Not addressed.** The data subjects are minors. Task 10.4 and `AV-96` are the start of that work, not the end. **No owner in this plan.** |

---

## 6. Obligations that bind every remaining task

From §2 of the plan. An earlier revision left these implicit, which meant nobody owned them.

- **Snapshot the database before any destructive step** (`E25`) — 2.1, 2.2 and 5.3 at minimum. The
  task states how to restore it.
- **Update `seed/demo.py` in the same phase that changes the data model** (`E26`). Every phase
  verifies against a seeded demo account and the seed only knows the old shape.
- **Fix the tests you break — never delete the assertion** (`E26`). Deleting routes breaks
  `test_authorization.py`; dropping `consistency` breaks the readiness tests. Removing a check to
  get green **silently retires a control**.
- **Update the constitution document your change describes, in the same PR** (`GOV-1`, `CODE-21`).
  The programme touches §01, §04, §05, §06, §07, §08, §09, §11, §12 and §14. Budget roughly **a
  third again on top of the code**.
- **Write an ADR for a structural decision** — see §4.1 for the five still owed.
- **A PR breaking an Active rule fixes the code, supersedes the rule, or records a Known Gap**
  (`GOV-3`). Never none of these.

---

## 7. Process constraints

- **Nothing under `backend/`, `frontend/` or `alembic/versions/` reaches the default branch without
  a PR** — a one-character edit included (`CODE-16`, `CODE-17`). **A code comment is not a
  documentation change.** Documentation-only prose may go direct.
- **The merge button belongs to the tutor/owner** unless they say otherwise **for that specific
  change**. Authorization for one PR does not carry to the next.
- **Do not switch branches, reset, rebase or rewrite history** without asking the operator.
- Branch per task off the default branch: `feat/…`, `fix/…`, `chore/…`, `docs/…`. Delete on merge.
  A merged branch is finished — never reopen or stack on it.
- Run `pytest`, `npm test`, `ruff check`, `ruff format --check`, `eslint --max-warnings 0` and
  `npm run build` locally before opening a PR. **CI is a backstop, not a substitute.**
- **`gh` needs the `env -u GITHUB_TOKEN` prefix in this environment** — an invalid `GITHUB_TOKEN`
  env var overrides the valid keyring token.
- **A green check from a review bot does not mean it found nothing.** Read the inline comments
  explicitly. CodeRabbit reports "Review skipped: manual review required for this OSS repository"
  and still posts findings when invoked.

---

## 8. Where the detail lives

| You need | Read |
|---|---|
| The task you are about to build | `docs/avora-new-state-august-16.md` §7 — one task, self-contained |
| Whether it already exists | Task 0.0's audit table, same document — **BUILT / PARTIAL / ABSENT** per task |
| What a decision `AV-n` / `E-n` means | The decision index just before §7; §3 and §4 are the authority |
| The rules a task cites (`SEC-3`, `BE-6`, `DB-17`) | `CLAUDE.md`, then the `docs/` volume it names |
| Phase 1's invariants and test constraints | `docs/av-82-phase-1-handoff.md` — **do not regress these** |
| Phase 2's invariants, and what it stored for later phases | `docs/av-9-phase-2-handoff.md` — **read before Phase 3 or 6** |
| Phase 3's invariants, the AV-76 reversal, and the three unbuilt tasks | `docs/av-81-phase-3-handoff.md` — **read before Phase 4 or 5** |
| Every single-process assumption in the repo | `docs/av-82-architecture-impact-report.md` (task 1.1's output) |
| What each role sees | `docs/experience-design.md` (Phase D's output) |
| States, empty states and copy | `docs/experience-implementation-plan.md` |
