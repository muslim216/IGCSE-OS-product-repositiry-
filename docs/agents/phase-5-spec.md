# Phase 5 — Readiness: specification

Written 2026-09-23. Local only; `docs/**` is never committed (standing owner
instruction). Source of truth for the Phase 5 PRs, plus 6.1 and 6.2, which the
owner pulled into this phase — **and on 2026-09-25 moved back out, with 5.7
(decision 17)**. Every **settled** decision below was put to the
owner and answered — do not reopen one without asking. **Open** decisions block
the task named against them; ask before that task branches.

Plan doc: `docs/avora-new-state-august-16.md` L1274+ (Phase 5), L1336+ (6.1, 6.2),
audit rows L712–718. Where this spec and the plan doc differ, this spec wins and
the plan doc gets corrected in the PR that causes the difference (`GOV-1`,
`CODE-21`).

---

## Settled decisions

| # | Decision | Answer |
|---|---|---|
| 1 | 5.7 needs 6.1, which is Phase 6 | **Build 6.1 inside Phase 5** |
| 2 | With 6.1 alone no class has a past-paper start date | **Pull 6.2 in too.** Gate strictly per AV-31 |
| 3 | 5.6 "captured at onboarding" — onboarding is Phase 9 | **Tutor settings now**, default 60. Phase 9 writes the same row later |
| 4 | 5.3 drops `tutor_preferences` | **Delete `/me/preferences` outright.** v2 never read it. *Correction 2026-09-23:* the "Preferences" tab (`tutor/PreferencesPage.tsx`) is the **v2** weights screen and **stays** — it is what 5.4 extends. Only the unused v1 wrapper (`getPreferences`/`updatePreferences`/`Preferences` in `api/readiness.ts`) goes |
| 5 | Punctuality once `consistency` is gone | **Invisible until 8.2** (weekly send). Derivable from `submitted_at`/`due_at`; nothing stored is lost |
| 6 | Custom criterion vs the readiness score | **Shown beside readiness, never in it.** No `weight` field. Deviates from the plan's `CustomCriterion(… weight …)` |
| 7 | 5.2 surfaces | **Store and expose via API only.** No UI change in Phase 5 |
| 8 | Subject override semantics (5.4, 5.6) | **Whole-row override.** A subject row replaces the account row entirely; no per-field inheritance |
| 9 | Student in several classes of one subject (5.7) | Past-paper phase has started if it has started in **any** of them |
| 10 | O1 — who decides a weak topic | **The threshold.** AI stops picking `weak_topics`; prompt version bumped |
| 11 | O3 — plan inputs vs draft status | **Inputs read regardless of status.** "Nothing reads a draft" governs slots only |
| 12 | O2 — `recommended_revision` vs AV-42 | **Recorded, decided later.** Unchanged through Phase 5 |
| 13 | 5.3 — class score once v1 is gone | **Mean of learners' latest v2 subject scores**, grade via the same boundaries; unscored learners omitted and counted ("N of M with evidence"). Class weak topics = mean of learners' `topic_mastery` rows from their latest run |
| 14 | 5.3 — tutor seed estimates (`tutor_estimate`) | **Fold into v2 Topic Mastery** as a labelled, decaying prior that marked work overtakes (`PROD-8`). The seed form keeps working |
| 15 | 5.3 — Group Analytics page | **Repoint to the shared v2 class aggregation** (one function for Class page, Home strip, Group Analytics). Agreement panel untouched |
| 17 | Phase 5 pace (2026-09-25, reverses 1 and 2) | **5.7, 6.1 and 6.2 move back to Phase 6.** 5.7 still needs 6.1/6.2, so it lands there after them; decision 9 and the 6.1/6.2/5.7 sections below travel with it. Also: 5.4 ships as 2–3 PRs; Simple tasks (5.3b, 5.2) run inline, not via subagents |
| 18 | 5.4c — who sees custom-criteria scores (2026-09-28) | **Students see their own**, as well as the tutor profile, reports and the parent view. Labelled tutor-entered everywhere |
| 19 | 5.4c — custom criteria in AI reports (2026-09-28) | **Option A: a plain table in the report, labelled tutor-entered. The AI never reads them** (same boundary as decision 6) |
| 16 | 5.3 size | **Two PRs.** 5.3a: every reader on v2, v1 still writes (rollback-safe). 5.3b: delete v1 code, tables, fallback, `/me/preferences` |

## Former open decisions — now settled as 10–12 above (kept for the reasoning)

**O1 — who decides a weak topic (blocks 5.6).** Today v2's weak topics are
**picked by the AI**: `prompts.py:227` asks the synthesis model for
`weak_topics` "with genuinely low scores", stored on `ReadinessSnapshot.weak_topics`
and read by `readiness_summary_v2.py:134`. A tutor-set threshold (AV-74) cannot
coexist with a model's judgement of "low".
*Recommendation:* weak = deterministic — a topic whose `topic_mastery` score is
at or below the resolved threshold with confidence ≥ `low` (the v1 rule at
`readiness_summary.py:251`, now tutor-set). Remove `weak_topics` from the
synthesis output; bump the `READINESS` prompt version (`AI-7`). Old snapshots keep
their stored column; readers stop using it.

**O2 — `recommended_revision` vs AV-42 (raise only; not Phase 5 scope unless the
owner says so).** `prompts.py:230` asks for "2-3 concrete, actionable next steps
for the student", shown via `readiness_summary_v2.py:190`. AV-42 says "no
generated practice, no 'do this now'". This is a live product contradiction,
recorded here so it is not suppressed. No change without an answer.

**O3 — the plan's inputs vs "nothing reads a draft plan" (blocks 6.1).** 6.1 puts
`exam_date`, `past_paper_start_date` etc. on `TeachingPlan`, whose `status` is
`draft`/`accepted`; 6.4 says nothing reads a draft. With no drafting or accept
flow until 6.3/6.4, every plan is a draft forever, so 5.7 could never read its
start date.
*Recommendation:* the inputs are tutor-entered facts about the class, not AI
output — they are read regardless of `status`; "nothing reads a draft" governs
**slots** only. Comment that branch point (`CODE-12`). Alternative: move the
inputs onto `groups` and keep `TeachingPlan` for slots only.

---

## PR order

One PR per task, branched off the latest default branch, merged only after the
review bots are read and fixed (memory `merge-after-fixing-review-bots`).
Migrations continue from `0053_mistake_revision_audit.py`.

| # | Task | Branch | Blocked by |
|---|---|---|---|
| 1 | 5.1 factor set | `feat/phase-5-1-drop-consistency` | — |
| 2a | 5.3a readers on v2 | `feat/phase-5-3a-readers-on-v2` | 1 |
| 2b | 5.3b delete v1 | `feat/phase-5-3b-delete-v1` | 2a |
| 3 | 5.2 chapter rollup | `feat/phase-5-2-chapter-rollup` | 1 |
| 4a–c | 5.4 configurable factors + custom criteria — 4a config (#95, merged), 4b criteria backend (#96, merged), 4c UI (#97, merged) | `feat/phase-5-4a-…`, `-4b-custom-criteria`, `-4c-…` | 2 |
| 5 | 5.6 weak threshold (O1 settled: decision 10) — **#98, merged** | `feat/phase-5-6-weak-threshold` | 4 |
| 6 | 5.5 cold start — check **failed** (zero-evidence student got an invented score); fixed in **#99, merged** (owner: "not enough data", 2026-09-30) | `fix/phase-5-5-cold-start` | 1–4 |
| 7 | Phase-end sweep — `ecc:code-reviewer` over #90–#99, then three review rounds: admin org scope (13 routers), half-life wired, backfill by enrolment, honest empty states, shared-student scoping — **#100, merged 2026-10-02** | `fix/phase-5-sweep` | 1–6 |
| — | ~~6.1, 6.2, 5.7~~ | moved to Phase 6 (decision 17) | — |

---

## 5.1 — Drop consistency; homework is accuracy only *(AV-30, AV-32)*

- Delete `consistency()`, `ConsistencyPoint` (`readiness_factors.py:280+`),
  `_consistency_points` and its call (`readiness_v2.py:199`, `:447`), the
  `FACTOR_WEIGHT_ATTR` entry (`readiness_v2_ai.py:138`), `weight_consistency`
  from `ReadinessWeights`, both schemas (`schemas/readiness.py:210,221`) and
  `api/readiness_weights.py:26`, and the frontend weights control.
- `ReadinessFactor.consistency` — **remove the member.** It is non-native
  (`DB-5`) so no migration is forced, which is why every `if`/`match` over the
  enum is audited by hand (`DB-6`). Old `factor_evaluations` rows hold the string
  `"consistency"`; every reader of historical rows must tolerate a value that no
  longer parses — check before removing, or keep the member marked retired if any
  reader would raise. Record which in the PR.
- Migration: drop `readiness_weights.weight_consistency` (`batch_alter_table`,
  `DB-17`), working `downgrade()` (`DB-16`).
- `homework_performance()`: score = accuracy only. Delete the
  `accuracy * 0.7 + completion_rate * 100 * 0.3` blend (`readiness_factors.py:157`).
  **Keep `completion_rate` in `detail`.** The no-marks branch (`:136–143`) that
  scores completion alone must stop producing a score — no accuracy evidence is
  no-data (`PROD-2`).
- Surface completion as a fact on the student profile and class view (from
  `detail`), labelled as completion, never as a score.
- `READINESS` prompt says "seven deterministic factor sub-scores" — fix the count,
  bump `version` (`AI-7`).
- Tests: homework score equals accuracy; completion present in `detail`;
  no-marks-but-submitted is no-data; consistency absent from a run.
- Backfill: after deploy, `python -m seed.recompute_readiness` (runbook R9) — the
  factor's maths changed.

## 5.3 — Delete v1 *(AV-78)*

> **Status 2026-09-26:** 5.3a merged (#91); 5.3b built on `feat/phase-5-3b-delete-v1` —
> migration `0055`, `engine` field removed from `SubjectReadiness` (not just its `"v1"` value),
> `PROD-10` deprecated (its `SOURCE_WEIGHTS` table died with v1; replacement is an owner call).

- Repoint to v2 snapshots: `api/analytics.py`, `services/reports.py`,
  `services/student_crm.py` (via `readiness_summary.build_summary`),
  `services/today.py` / `api/today.py`, `services/groups.py`.
- Stop every v1 write; delete `services/readiness.py`,
  `services/readiness_summary.py` and v1 models `TopicReadiness`,
  `ReadinessHistory`, `TutorPreferences` (remove from `models/__init__.py`, `BE-3`).
- Delete `api/preferences.py`, its route mount (`main.py:29,316`), its schema,
  and the unused v1 frontend wrapper in `api/readiness.ts:175-204`. **Keep**
  `tutor/PreferencesPage.tsx` and its route — it is the v2 weights screen
  (decision 4, corrected).
- Remove the per-subject v1 fallback and `engine: "v1"` from `/readiness/*`.
- **Carried from 5.1:** homework completion ("N of M handed in") on the class
  view (`ClassLearnerRow`, `services/today.py`). 5.1 shipped it on the profile
  only, because the class view still read v1 tables until this task.
- Migration drops `topic_readiness`, `readiness_history`, `tutor_preferences`;
  `downgrade()` recreates them empty (data is not restored — say so in the
  docstring).
- Weak topics: until 5.6, carry today's `60.0` as the single constant in one
  place (the two copies at `api/analytics.py:28` and `readiness_summary.py:32`
  collapse to one). 5.6 replaces it.
- Regenerate `openapi.json` + `schema.d.ts` (`FE-4`).
- **Closes `RISK-5`.** Update `risk-register.md`, §01 Known Gaps, §06, and
  `CLAUDE.md`'s Readiness bullet (local).

## 5.2 — Chapter rollup *(AV-9, E7)*

- In `evaluate_subject_factors`, after topic mastery: one `FactorEvaluation` row
  per chapter per run — **new nullable `chapter_id` column** beside `topic_id`,
  factor `topic_mastery`. Score = topic scores weighted by evidence count; `None`
  with confidence `no_data` when no topic beneath has evidence (`PROD-2`).
  Append-only like every other row.
- Pure function for the maths (`BE-4`): `(score, evidence_count)` pairs in,
  `(score | None, evidence_count)` out.
- Migration adds `chapter_id` (FK named explicitly, `DB-17`); index declared in
  the model and the migration if a reader filters on it (`DB-12`).
- Expose on the v2 readiness response as `chapters: [{chapter_id, name, score,
  confidence, evidence_count}]`. No UI (decision 7). Regenerate types.
- Tests: weighted mean; chapter with no evidence is `None` not `0`; a chapter
  mixing evidenced and bare topics uses only the evidenced ones.

## 5.4 — Configurable factors and custom criteria *(AV-34, AV-35, E8)*

**Config shape (decision 8).** `readiness_weights` gains nullable `subject_id`;
the unique becomes `(organization_id, subject_id)` — and because Postgres treats
NULLs as distinct, the account row's uniqueness needs a partial unique index
`WHERE subject_id IS NULL` (verify on Postgres in CI; SQLite behaves differently,
`RISK-3`). Per factor an `enabled_<factor>` boolean beside `weight_<factor>`.

**One resolver, one place:** `resolve_readiness_config(session, org_id,
subject_id)` in `services/` — subject row if it exists, else account row, else
built-in defaults. Tested both ways plus the default case. Every reader of
weights (the engine, the AI synthesis, the settings API) goes through it.

**Switch off:** a disabled factor is **omitted** from the weighted set passed to
synthesis — never sent with weight 0. Still computed and stored (evidence is not
thrown away), flagged disabled in the response.

**Custom criteria (decision 6):**
- `CustomCriterion` — organization_id, subject_id (nullable = all subjects),
  name, description, archived_at. No weight. Scope rule: a criterion with a
  subject applies to that subject only; without one, to every subject.
- `CustomCriterionScore` — organization_id, student_id, criterion_id, score
  (0–100), updated_at, updated_by_id. Unique `(student_id, criterion_id)`.
- Hand-scored by the tutor. No AI, no derivation. Unscored = absent, never 0
  (`PROD-2`).
- **Never enters the readiness score or the synthesis prompt.**
- Shown beside readiness on the tutor profile, reports and the parent view,
  **labelled tutor-entered everywhere** (`PROD-1`, `PROD-8`, `UX-20`).
- Every score edit writes an append-only audit row (`PROD-7` spirit — tutor data,
  traceable). Confirm with the owner only if this proves heavy; default is to
  build it.
- Tutor-gated in the signature (`BE-17`); org-scoped from the user (`SEC-7`);
  `404` not `403` (`API-7`). Negative tests: other org's criterion, student role,
  parent role (`QA-12`).

**UI:** extend the existing factor-weights screen with enabled toggles and a
subject selector ("All subjects" = account row; picking a subject creates its
override, copied from the account row, with a "remove override" action). Custom
criteria managed in tutor settings; scored on the student profile.

## 5.6 — Weak threshold and surfaces *(AV-42, AV-43, AV-74)* — blocked by O1

- `weak_threshold` column on `readiness_weights` — same row, same resolver,
  same whole-row precedence as 5.4. Default 60 (today's value).
- **`MASTERY_THRESHOLD = 75.0` (`readiness_v2.py:62`) is a different line** — it
  decides mastered-for-coverage. Do not conflate; comment the distinction at
  both.
- Weak-topic rule per O1's answer.
- Surfaces: student sees their weak topics as information; tutor sees them in
  the class view (`api/analytics.py`) and aggregated on home (`services/today.py`).
  **Nothing generated, assigned or suggested** (AV-42).
- Settings UI: threshold input on the weights screen, per account/subject.

## 6.1 — Plan data model *(AV-13–16, AV-72, E15)* — blocked by O3

Per the plan doc: `TeachingPlan` (group_id, exam_date, lessons_per_week,
lesson_minutes, past_paper_start_date, status, accepted_at, accepted_by_id) ·
`PlanSlot` (plan_id, chapter_id, scheduled_date, sequence, provenance) ·
`PlanBreak` (plan_id, start_date, end_date, label). E15 invariant: a slot is
planned, a `Lesson` is actual. Teaching and past-paper phases **overlap by
design** — no disjoint-interval assumption. `organization_id` on every top-level
aggregate (`PROD-3`, `DB-2`). Models only plus the migration; no drafting (6.3),
no accept flow (6.4).

## 6.2 — Plan inputs on the class *(AV-15)*

Exam date, lessons per week, lesson length, past-paper start, breaks — editable
from class settings (onboarding capture is Phase 9). Tutor-gated, org-scoped,
404 on another tutor's class. Dates validated (break end ≥ start). Absent fields
show as unset, never defaulted into a fabricated date.

## 5.7 — Past-paper gating *(AV-31)*

`past_paper_performance` returns `NO_DATA` unless the past-paper phase has
started — `past_paper_start_date` set and ≤ today — in **any** class the student
is enrolled in for that subject (decision 9). No date = not started = omitted
(decision 2). The gate is data passed into the pure factor function, not a
session call inside it (`BE-4`). Tests: no plan; date in future; date past;
two classes, one started. Backfill via `recompute_readiness` after deploy — the
gate changes existing scores.

## 5.5 — Cold start *(AV-36)*

Already built and tested (PRs 21–27). After 5.1–5.4: confirm a score still
appears from the first marked piece with evidence count and confidence
(`_confidence_from_count`), and "not enough data yet" still applies to a factor
with no evidence (`PROD-2`, `UX-19`). Run the existing parent/student cold-start
tests; a PR only if one fails.

---

## Per-task gate (every PR)

`pytest`, `ruff check`, `ruff format --check`, `mypy`, `npm test`,
`npm run lint`, `npm run build`; types regenerated when a response schema moves.
Two reviewers — the language reviewer matching the diff and
`ecc:silent-failure-hunter`, prompts naming `file:line` and rule IDs. Read the
diff yourself after. Discrimination check on every fix. One `ecc:code-reviewer`
sweep over the integrated phase at the end — pointed at contracts one task
changed that another relies on (5.1's factor set ↔ 5.4's config ↔ 5.7's gate).
Docs owed per task are updated locally, never committed.
