# 5.3 — v1 consumer map (2026-09-23, from ecc:code-explorer; verify line numbers before editing)

## Load-bearing traps
- `services/readiness_factors.py:21` imports `_decay`, `_age_days` from `services/readiness.py` (v1). v2 factor math depends on them → must move before 5.3b deletes the file.
- `services/readiness_summary.py` is NOT v1-only. Shared, engine-agnostic: `CONFIDENT`, `MIN_WEAK_CONFIDENCE` (:38-39), `DIRECTION_NOISE_BAND` (:46), `MONTH_WINDOW_DAYS` (:51), `trend_direction` (:54), `ScorePoint`, `scores_of` (:87), `window_start` (:92), `period_delta` (:108), `month_delta` (:150), `_aware` (:155), `v2_score_points` (:187). v1-only: `WEAK_THRESHOLD` (:32), `v1_score_points` (:170), `build_summary` (:207).
  Importers: `readiness_summary_v2.py:44-50` (build_summary, month_delta, scores_of, trend_direction, v2_score_points); `groups.py:25` (CONFIDENT); `today.py:41` (CONFIDENT, trend_direction).
- `build_summary_v2` (`readiness_summary_v2.py:222-256`) falls back to v1 `build_summary` for subjects with **no snapshot row at all** (L228-251, sets `engine="v1"`). Removing the fallback without a "no snapshot yet" branch makes those subjects vanish (PROD-2). A zero-evidence subject already gets a `status=ready, score=None` snapshot from `compute_readiness_v2` (`readiness_v2_ai.py:288-300`).

## Readers (5.3a repoints these)
- `services/student_crm.py:29,99` — calls v1 `build_summary` directly. Repoint: `build_summary_v2` (same return type).
- `services/reports.py` `build_report_facts` (:50-144) — `TopicReadiness` :65-67 (strongest/weakest topics), inline weak literal `r.score <= 60` :93, `ReadinessHistory` :106-119 (own earliest-vs-latest trend, >1/<-1 threshold at :118). Output is a text block for the report prompt. v2: latest ready snapshot + `_subject_from_snapshot` topics; trend via `v2_score_points` + `trend_direction`/`month_delta`.
- `api/analytics.py` `group_analytics` (:31-133) → `GroupAnalyticsPage.tsx`. Per-student N+1 loop over `TopicReadiness` (:49-74, PERF-1). Fields: `weak_students` (score asc, top 10), `weak_topics` (avg over confident students, asc, top 10), `agreement` (AI-vs-tutor marks — not readiness, untouched). `WEAK_THRESHOLD` :28 declared, never used.
- `services/groups.py` — `summaries()` (:96-190): `covered` (:153-172) = students with a CONFIDENT `TopicReadiness` → `GroupSummary.students_with_evidence`. `weighted_learner_scores()`/`class_health()` (:193-277): raw SQL over `TopicReadiness`/`Topic`/`GroupMember` (:218-239) → Home strip `ClassStripRow.score/predicted_grade/status` and Class page.
- `services/today.py` `build_class_overview` (:179-299): `TopicReadiness` :222-234 (class weak topics), `ReadinessHistory` :239-249 (per-learner direction). Docstring :187-193 names RISK-5. `build_today` (:137-176) → `class_health`. Schemas `schemas/today.py:20-25` (`ClassStripRow`), `:52-95` (`ClassOverview`, `ClassLearnerRow`: student_id, student_name, score, predicted_grade, status, direction).
- `api/readiness.py` — `topic_evidence` (:95-132) reads `TopicReadiness` for the drill-down header score/confidence → v2: that topic's `topic_mastery` `FactorEvaluation` from the latest ready snapshot's run. `student_trend` (:135-172) has its own inline v2-then-v1 fallback (`ReadinessHistory` :158-168).
- Frontend consumers of class data: `frontend/src/api/today.ts:49-56` (`ClassLearnerRow`), `tutor/ClassOverview.tsx`, `tutor/ClassReadinessPage.tsx`, `tutor/GroupAnalyticsPage.tsx`.

## Writers (5.3b removes the v1 half; v2 is already enqueued at each)
`api/assessments.py:125-128, 243-248, 351-354`; `api/lessons.py:198-203`; `services/marking.py:607-612`; `api/preferences.py:58-59` (v1 only; file deleted). Handler `workers/handlers.py:32,66` (`recompute_readiness`). `seed/demo.py:553` calls `recompute_student` directly and never runs v2 — demo needs v2 (5.3a).

## Seed estimates (decision 14)
`POST /students/{id}/seed-readiness` (`api/assessments.py:260-354`) writes `Evidence(source_type=EvidenceSource.tutor_estimate)`, ref `tutor_estimate:{student}:{topic}`. v1 honours it via `SEEDED_SOURCES` in `services/readiness.py` (decaying, overtaken by marked evidence; tests `tests/test_seeded_evidence.py:1-99`). v2 `topic_mastery` works from marked questions only; `readiness_v2.py:~250` reads `Evidence.topic_id` only for coverage. UI: `tutor/StudentDetailPage.tsx:66-215`.

## WEAK_THRESHOLD copies
`readiness_summary.py:32` (used :251), `api/analytics.py:28` (unused), `reports.py:93` literal. v2 weak topics are AI-picked (`readiness_v2_ai.py:236,369-387`) until 5.6.

## Tests
- v1-only, delete in 5.3b: `test_readiness_engine.py` (move decay/confidence asserts with `_decay`/`_age_days`), `test_seeded_evidence.py:1-99` (replace with v2 prior tests in 5.3a), `test_new_capabilities.py:139-196`, `test_authorization.py:153` entry, `test_direction.py:242-259`.
- Port in 5.3a (fixtures write TopicReadiness/ReadinessHistory): `test_class_overview.py` (`_learner` :55-85), `test_groups.py` (`_give_topic_readiness` :257-271, class_health tests), `test_today_endpoint.py:86`, `test_coverage.py` (:67-78 helper, :86-190), `test_direction.py:71-193` (use `write_snapshots` :199-218), `test_readiness_api.py:77-115` (relies on v1 sync compute).
- Literal `"recompute_readiness"` used generically: `test_jobs.py:24-48`, `test_health.py:109-117` (swap in 5.3b); `test_mocks.py:436-440` asserts the v1 job (swap to `compute_readiness_v2` in 5.3b).
- Pattern: many tests call `process_one_job()` then assert a score; v2 needs `fake_ai` (QA-7) or direct snapshot fixtures.

## Migrations
Head `0054`. v1 tables: `0004_readiness.py:46-75` (`topic_readiness`, `readiness_history`), `0009_tutor_preferences.py` (`tutor_preferences`; check `TimestampMixin` for `updated_at` drift). `evidence`, `assessments`, `assessment_scores`, `tutor_observations` stay.
