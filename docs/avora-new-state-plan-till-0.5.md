# Avora New State Plan — handoff through task 0.5

> **What this is.** A handoff written at the point tasks `0.0`–`0.5` of
> `docs/avora-new-state-august-16.md` are complete and committed. It records what was built,
> what was decided and by whom, what was verified and how, and what the next person needs to
> know that the commits alone do not tell them.
>
> **Status at handoff:** six branches, all off the default branch, **none merged**. Nothing has
> deployed. The merge button is the owner's.
>
> **Written:** 22 August 2026.

---

## 1. The one-paragraph version

Phase 0 of the Avora plan is the clearing phase: fix a readiness defect that silently discarded
most marks, then remove or hide what the new product shape does not include. All six pieces are
built, tested and committed to six separate branches — one PR each, as the owner asked. The
backend suite went from 498 to 500 passing and the frontend stayed at 161, with no assertion
deleted anywhere in the process. Nothing is merged, so production is exactly where it was.

---

## 2. Branch inventory

Every branch is cut from the default branch (`claude/igcse-os-planning-q8be0t`, still awaiting
the GitHub rename) and none has been merged.

| Task | Branch | Head | Files | Suite at commit |
|---|---|---|---|---|
| `0.0` | *(none — see below)* | — | — | — |
| `0.1` | `fix/av-29-settled-statuses` | `edacdec` | 10 | backend 499 |
| `0.2` | `feat/av-29-recompute-runner` | `56e40c9` | 13 | backend 503 |
| `0.3` | `chore/av-57-remove-student-chat` | `3fa76e7` | 41 | backend 492 · frontend 161 |
| — | `docs/fix-stale-semantic-counts` | `f14fe2e` | 1 | docs only |
| `0.4` | `chore/av-57-remove-peer-ranking` | `e347f46` | 12 | backend 478 · frontend 153 |
| `0.5` | `chore/av-58-hide-classroom-kb` | `20b2852` | 33 | backend 500 · frontend 161 |

**Task `0.0` has no branch by design.** It was the audit — "read your task's row before
writing anything" — and it produced findings, not code. It is marked `✅ DONE, 19 Aug` in
`docs/avora-new-state-august-16.md` §7, where its results live as a BUILT / PARTIAL / ABSENT
table covering every later task. It is complete; there is simply nothing to merge. Its finding
for `0.1` (four correct copies of the settled-status tuple already existed, three other sites
restated it wrongly) is what shaped `0.1` into a consolidation rather than a new feature.

**The counts differ by branch because each is measured against its own branch, not a shared
base.** They are not comparable to each other and are not meant to be. `0.2` is the only branch
stacked on another (`0.1`); every other branch is independent, which is why `0.3`'s and `0.4`'s
totals look lower — each deletes a feature and its tests without the others' additions present.

**Merge order matters in one place only.** `0.3` (delete student chat) and `0.5` (hide the
knowledge base) both touch documentation that lists where `build_tutor_context()` is injected.
`0.5`'s docs say five call sites and name `api/chat.py` as one that "goes when task `0.3`
lands". If `0.3` merges first, that sentence needs updating to four. Nothing breaks either way;
it is a prose correction, not a conflict.

---

## 3. What each task actually did

### 0.1 — `SETTLED_STATUSES` and the readiness v2 gatherers *(AV-29, E2, E3)*

**The defect.** Readiness v2's three evidence gatherers filtered submissions on
`status == finalized`. But the marking pipeline's *own default successful outcome* is
`auto_finalized` — a mark that is scheme-backed and confident enough to need no tutor. Every one
of those was invisible to readiness. The engine was scoring students on the subset of their work
that happened to need human review.

**The fix.** One tuple, `SETTLED_STATUSES`, defined once in `models/homework.py`, replacing
seven scattered restatements — four that were correct and three that said `finalized` alone and
so could not see the pipeline's default outcome. The three v2 gatherers
(`_marked_questions_for_topic`, `_homework_points`, `_mistake_points_and_total`) now filter on
it.

**What was deliberately *not* changed:** `api/analytics.py`. Its AI-agreement rate compares
`final_marks` to `ai_marks`, and an auto-finalized mark has them equal by construction —
including those rows would inflate agreement toward 100% by counting the AI agreeing with
itself. The file carries a comment saying so, so the next person to notice the inconsistency
finds the reason rather than "fixing" it. *(AV-80, E3.)*

### 0.2 — Recompute runner *(AV-29, E4)*

`backend/seed/recompute_readiness.py`. Walks every distinct `(student, subject)` pair that has
evidence and enqueues a v2 recompute, staggered 30 seconds apart so a full recompute cannot
saturate the single-instance worker. Refuses to run when `READINESS_V2_SHADOW_ENABLED` is off,
because a recompute into a disabled engine is silent waste.

### 0.3 — Delete student AI chat *(AV-57)*

Chat, its conversations and messages tables, the frontend surface and three orphaned modules.
Migration `0024_drop_chat.py`, verified up → down → up on SQLite.

Three things were preserved on the owner's explicit instruction rather than deleted with the
feature:

- **`services/student_crm.py` and `schemas/crm.py` comments** were *rewritten*, not removed —
  they were the only surviving record of why the CRM aggregation is one whole record, a reason
  that outlived `student_context.py` (`CODE-13`).
- **`AiFeature.chat`** stays in the enum with a comment explaining it is frozen but *populated*:
  historical `ai_usage_events` rows still carry it, and task `10.1`'s per-account rollups must
  count it as real spend that has stopped, not as a dead value to skip.
- **`FE-1` was narrowed rather than dropped** across six documents, with `ADR-0006` getting a
  superseding note rather than an edit.

### 0.4 — Delete peer improvement ranking *(AV-57, AV-100)*

The most valuable part of this task was not the deletion. `services/improvement.py` carried a
**de-anonymisation analysis** — four concrete attack vectors (screenshot collusion, exact-delta
fingerprinting, join/leave landmarks, achievement-event correlation) and three accepted residual
risks — that existed nowhere else. It was recovered from git and preserved into `UX-32` in §02
before the file went.

`UX-32` is left **Active**. Its permission now has no subject, which is not the same as
pre-approval for some future ranking feature; the rule text says so explicitly.

### 0.5 — Hide Classroom and the knowledge base *(AV-58)*

Routers dropped from the mount loop; services, models, tables and migrations untouched. Both
modules stay *imported* behind a `noqa` — hidden code that is never imported rots silently, and
the failure would surface at exactly the wrong moment.

**The two are not symmetrical, and this is the single most important thing in this handoff.**
The knowledge base never had a UI, so re-mounting its router really is the whole of bringing it
back. **Classroom's tutor surface was deleted, not hidden** — `api/classroom.ts`,
`ClassroomSettingsPage.tsx`, `ClassroomCallbackPage.tsx` and the `/settings/classroom/callback`
route are gone. Re-mounting `classroom.router` restores the API and leaves nothing to drive it.
That is stated at four entry points (`api/classroom.py`, `services/google_classroom.py`, §01,
runbook R10) because a re-activation planned on the wrong assumption would be discovered late.

`build_tutor_context()` still runs on all five call sites, reading rows that already exist.
Nothing can create new ones, so a fresh deployment compiles an empty block. Intended, not a bug
— and `services/knowledge.py` says so, because the obvious future "simplification" is to delete
the injection on the evidence that the table is empty.

`/tutor/settings` survives as a timezone-only page (`SettingsPage.tsx`). *The owner chose this*
— "Timezone-only page, same route" — over folding it away, because where settings live is Phase
D's decision, not this task's.

---

## 4. Decisions the owner made, recorded so they are not re-litigated

These were asked rather than assumed, and the answers bind subsequent work.

| Question | Answer |
|---|---|
| The three chat orphans — delete or keep? | Delete all three, with the three preservation obligations in §3 above. |
| PR granularity | **One PR per task.** |
| What replaces `/tutor/settings`? | Timezone-only page, same route. |
| Does hiding the KB routes while `build_tutor_context` still runs match intent? | "Correct — that's what AV-58 means." |
| The rate-limit risk surfaced during the doc sweep | Do not escalate it; leave it for Phase 10. Both Known Gaps were rewritten to be factual at unchanged `before scale` severity, naming Phase 10 as owner. |
| Pre-existing stale doc counts | Fix in a separate PR — hence `docs/fix-stale-semantic-counts`. |
| Model pricing | Opus 5 at $5/$25, Sonnet 5 at $3/$15 per million tokens. |

Standing instructions in force: **no architecture or product guesses** — anything that
meaningfully affects the app is the owner's call; **never merge**, only ask for a PR; use ECC
agents generously, **except `agentic-os`, which is never to be acted on**.

---

## 5. What was verified, and what was not

**Verified.** Backend 500 passed and frontend 161 passed on `0.5`, with `ruff check`,
`ruff format --check`, `eslint`, `prettier --check` and `npm run build` (`tsc -b` — the only
type check anywhere) all clean. Migration `0024` round-trips up → down → up on SQLite.

**Not verified, and why.** *The migration has not been exercised against Postgres.* The owner
declined a local Postgres install, so `DB-16`'s up → down → up is confirmed only on SQLite here.
CI's `migrations` job runs it against real Postgres 16 on every PR, which is the real check — but
it has not run yet, because nothing has been opened as a PR. **A migration that is correct on
SQLite and wrong on Postgres is a failure that has actually happened in this repo (`RISK-3`).**
Watch that job on `0.3`.

**Also unverified by anything:** every Python type annotation in `backend/`. There is no Python
type checker in CI. That is task `0.8`'s job.

---

## 6. Traps and corrections found along the way

Recorded because each cost time and would cost it again.

- **Subagent output is not evidence.** A documentation agent inserted a confident, entirely
  false claim that Reports is grounded by `student_crm.py`; `reports.py` never imports it. A
  later sweep produced three more: a wrong `503` count in §05, a wrong knowledge-base injection
  list, and an over-broad "nothing reads `GOOGLE_REDIRECT_URI`". All four were caught by reading
  the code. **Verify every factual claim a subagent makes before it lands in a document.**
- **The same sweep also caught a false claim of mine** — that re-mounting the Classroom router
  was the whole of re-activating it. It was not, because the frontend was deleted. The review
  was worth running; it is the trust that is unwarranted, not the tool.
- **Naive element counting over-counts.** Two `<main>` occurrences in `LandingPage.tsx` sit
  inside a JSX comment. The doc's original figure was right and the "correction" was wrong.
  Strip comments and cross-check against closing tags.
- **Don't reason about tuple order.** The four repointed `SETTLED_STATUSES` sites were checked
  individually; all are membership tests, so order is irrelevant. That was confirmed, not
  assumed.
- **`docs/avora-new-state-august-16.md` is untracked and was lost once.** It has never been
  committed. It vanished mid-session and was unrecoverable from git; work continued only because
  the owner restored it. **Recommend committing it.** It was deliberately left out of the `0.5`
  PR as scope creep, so this is a decision waiting on the owner.

---

## 7. What is next

**Immediately:** open PRs for the six branches. CI has never run on any of them — in particular
the Alembic job on `0.3`.

**Task `0.6` — rename MANARA → Avora *(AV-4, E10)*.** The large one: user-facing strings,
`docs/`, docstrings, `README.md`, `CLAUDE.md`, package names, demo seed. One PR. **The GitHub
repository rename is manual and is the owner's** — and note that `CLAUDE.md` still carries a
placeholder note about the default branch's real name, to be deleted when that lands.

**Task `0.7` — time zones *(AV-67, E11)*.** Mostly built already: `services/timezones.py`,
`PUT /organization/timezone` and `TimezoneSetting.tsx` all ship today at organization level.
What is new is a per-user override defaulting to the organization's. **Read
`services/timezones.py` first** — normalisation and validation are done. Note the weekly send
deliberately ignores the per-user value (`AV-90`).

**Task `0.8` — type safety *(AV-79)*.** A Python type checker in CI, enforced at service
boundaries first; plus TypeScript API types generated from the OpenAPI schema, replacing the
hand-mirrored interfaces in `frontend/src/api/*.ts`. Closes `RISK-6`.

**Task `0.9`** — token-revocation regression test (threat review F8).

**Task `0.10` — AI price table.** The owner has supplied the rates. The remaining check is that
the `AI_MODEL_PRICING` keys match the model IDs `config.py` actually sends, since `AI-17`
forbids inventing a price and an unmatched key reports `unpriced_call_count` rather than
failing loudly.

### A note on Gemini

The plan was revised while this work was in flight and **`AV-124` retires Gemini from every
surface**, superseding `AV-123`. This does **not** invalidate anything on the six branches. The
plan assigns the retirement to **task `3.2`**, deliberately as one PR — "a half-migrated
`config.py` is worse than the Gemini routing it replaces, because nothing signals which surfaces
already moved." Until `3.2` lands, `config.py` still routes marking, extraction and syllabus to
Gemini, and `test_ai_provider.py::test_default_routing_splits_providers_by_surface` is asserting
the correct current state.

`AV-29`, `AV-57`, `AV-58`, `AV-80` and `AV-100` were each re-checked against the revised plan
and all still mean what the commits claim.

---

## 8. Known documentation drift not caused by this work

Found while verifying, deliberately left alone — the owner's instruction is that stale counts go
in their own PR. Listed so the next person does not re-derive them:

- `docs/README.md` — "23 routers, 24 services, 21 migrations, 8 background job handlers". Actual:
  27 routers (25 mounted), 31 services, **10** job handlers.
- `04-backend-engineering.md` — "All 8 handlers are registered at the top of `main.py`", then
  lists 8. There are 10; `narrative` and `sweep_parent_narratives` are missing from that list and
  from the idempotency table below it.
- `03-frontend-engineering.md` — "13 modules in `frontend/src/api/`" (actual 16); "tutor/ 17
  pages" (20); "student/ 10 pages" (12); "test/ 7 spec files" (20 — and §12 already says 20, so
  the two documents disagree); "`/student` and nine siblings" (12); "`TUTOR_NAV` (9 entries)"
  (4).
- `05-api-standards.md` lines 51 and 197 — "all 23 routers" in the Sources block and in the
  `_require_tutor` history. Pre-existing count drift; `AV-58` does not falsify either sentence.
- `docs/manara-architecture.md` — target-state spec, divergence expected per `CLAUDE.md`. But
  note one item is now actively misleading: it lists Classroom's "Settings UI (frontend)" as
  "the remaining piece", and that UI was built and has since been deleted.
