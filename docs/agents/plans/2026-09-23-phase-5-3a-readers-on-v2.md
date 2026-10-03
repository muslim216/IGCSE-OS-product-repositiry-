# Phase 5.3a — Every reader on Readiness v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every surface that reads readiness reads Readiness Engine v2: the class page, the home strip, the class cards, Group Analytics, the Student CRM, reports and the topic drill-down. v1 keeps **writing**, so reverting this PR is safe, and nothing v1 is deleted. 5.3b deletes it.

**Architecture:** Five tasks, each leaving the whole suite green. (1) Move the engine-agnostic helpers out of the two v1 modules, and keep one weak-topic constant. (2) Per-student readers: the no-snapshot branch in `build_summary_v2`, the CRM, the topic drill-down and reports. (3) One set-based class aggregation, `services/class_readiness.py`, used by the home, the class page, the class cards and Group Analytics, plus homework completion on `ClassLearnerRow`. (4) Tutor seed estimates become a labelled, decaying prior inside v2 Topic Mastery. (5) `seed/demo.py` writes v2 snapshots without an AI call.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async, React 18 + TanStack Query. **No migration.**

**Spec:** `docs/agents/phase-5-spec.md`: settled decisions 13–16, section "5.3" and "Per-task gate". Consumer map: `docs/agents/plans/5-3-v1-map.md`. Every line number below was re-checked against `d03e535`.

---

## Global Constraints

- **Branch** `feat/phase-5-3a-readers-on-v2` off the latest `claude/igcse-os-planning-q8be0t`. One PR; each task is one commit.
- **`docs/**` and `CLAUDE.md` are never committed.** Stage by path only, using the explicit list in each task's commit step.
- **No migration in 5.3a.** Every index the new queries need already exists in both the model and the migration: `ix_readiness_snapshots_student_subject (student_id, subject_id, created_at)` at `models/readiness_v2.py:481-488` and `ix_factor_evaluations_run_student_subject` at `:435-442` (`DB-12`). If you find yourself writing one, stop and ask.
- **Never render a missing measurement as 0** (`PROD-2`, `UX-19`). An unscored learner is omitted and counted. A factor without evidence is omitted.
- **Self-declared data is labelled** wherever shown (`PROD-8`, `UX-20`). This applies to the tutor's estimate in Task 4.
- **Prompts live in `services/prompts.py`, and `version` is bumped on any meaningful change** (`AI-6`, `AI-7`). Task 4 bumps `"readiness"` from `v2` to `v3`.
- **Layering** `api/ → services/ → models/` (`BE-1`). Business logic lives in `services/` (`BE-2`). Decision maths stays pure (`BE-4`). Nothing issues a query per learner (`BE-13`, `PERF-1`).
- **Tenant scoping** is inherited from caller-scoped `group_ids` and the authenticated user, never from a parameter (`SEC-7`). Snapshots are keyed by `(student, subject)`, and subjects have been org-owned since 2.2 (`SEC-8`). Return `404`, not `403` (`API-7`).
- **Response-schema change → regenerate types in the same PR** (`FE-4`). From `backend/`, run `python -c "import json;from app.main import app;print(json.dumps(app.openapi(),indent=2))" > ../frontend/openapi.json`. Then, from `frontend/`, run `npm run generate:api`.
- **Semantic token classes** only in new frontend markup (`UX-2`).
- **Comments explain why. Never delete an existing comment** without confirming its reasoning is gone (`CODE-12`, `CODE-13`). A moved helper keeps its comment. A comment that names v1 behaviour this PR removes is **rewritten**, not left stale.
- **Tests:** drive jobs with `process_one_job()` (`QA-6`). Monkeypatch the *calling* module's `structured_complete` (`QA-7`), which here is `app.services.readiness_v2_ai.structured_complete`. Never call a real provider (`QA-8`).
- **Local gate before push.** In `backend/`: `.venv/bin/python -m pytest > /tmp/p.txt 2>&1; echo $?`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/python -m mypy app/services app/schemas`. In `frontend/`: `npm test`, `npm run lint`, `npm run build`, `npx prettier --check src/`. **Never pipe pytest to `tail`.**

### Verified facts — do not re-derive

- **`readiness_factors.py:21` imports `_age_days`, `_decay` from `services/readiness.py`.** The pure v2 maths depends on the v1 module. `_decay` defaults to `HALF_LIFE_DAYS` (`readiness.py:36`), so all three move together.
- **`CONFIDENT` in `readiness_summary.py:38` is built on the v1 enum `ReadinessConfidence`,** which 5.3b deletes with `models/readiness.py`. The shared replacement is therefore **`frozenset({FactorConfidence.medium, FactorConfidence.high})`**, not a move of the same object. `MIN_WEAK_CONFIDENCE` (`:39`) is v1-only, because `build_summary` at `:251` uses it, and it stays in `readiness_summary.py` on the v1 enum until 5.3b.
- **Importers of the shared helpers.** `readiness_summary_v2.py:44-50` imports `build_summary, month_delta, scores_of, trend_direction, v2_score_points`. `groups.py:25` imports `CONFIDENT`. `today.py:41` imports `CONFIDENT, trend_direction`. `tests/test_direction.py:23` imports `DIRECTION_NOISE_BAND, trend_direction`. `period_delta` and `window_start` have no caller outside the module.
- **WEAK_THRESHOLD has three copies:** `readiness_summary.py:32` (used at `:251`), `api/analytics.py:28` (declared, never used) and `reports.py:93` (literal `r.score <= 60`).
- **With no AI key, `compute_readiness_v2` writes a `failed` snapshot** (`readiness_v2_ai.py:320-336`): `structured_complete` raises and the handler catches the error. The one exception is a run where every factor is `None`, which writes a `ready`, `score=None` snapshot with no AI call (`:288-300`). `build_summary_v2` reads only `ready` snapshots (`readiness_summary_v2.py:59-71`), so a demo seeded without a key would show nothing.
- **`build_summary_v2` never drops a subject today.** v1 `build_summary` returns a `SubjectReadiness` for every subject, with `score=None` when it has no rows, and the fallback at `readiness_summary_v2.py:242-251` appends it. A subject vanishes only if the fallback is deleted without a replacement. That is the trap 5.3b would hit, and the no-snapshot branch below closes it now.
- **Tests that assert `engine == "v1"` with no v1 data:** `test_readiness_cutover.py:117-125` (failed synthesis) and `:128-135` (v2 never ran). Under Task 2's branch these subjects come back as the v2 no-snapshot shape. Both tests change in Task 2 and are **not in the map**.
- **v1-only tests that must stay green in 5.3a** (5.3b deletes them), which is why the fallback survives this PR: `test_new_capabilities.py:147-196` (v1 preferences change the `/readiness/me` score), `test_direction.py:242-259` (`build_summary` direct), `test_seeded_evidence.py` (v1 `compute_topic`), `test_readiness_engine.py`, and `test_readiness_api.py:77-123` (mock → v1 job → `/readiness/me`; the v2 job is debounced 600 s, so only the fallback answers).
- **`api/groups.py:241` `class_brief` calls the `group_analytics` *router* directly.** This is a pre-existing `BE-2` smell. Task 3 moves the aggregation into a service and leaves `class_brief` calling the router, which returns the same shape, so this PR does not widen it.
- **`TopicEvidence.score` is `float` and returns a fabricated `0.0` / `"none"`** when there is no row (`api/readiness.py:120-121`). That is a `PROD-2` violation, and Task 2 removes it. The frontend reads it at `tutor/StudentDetailPage.tsx:130`.
- **The frontend `ClassLearnerRow` (`frontend/src/api/today.ts:49-56`) and `TopicEvidence` (`api/readiness.ts:82-89`) are hand-written interfaces.** Converting them to generated aliases would widen `ReadinessStatus` and the direction unions, so this PR adds fields to the existing interfaces. The regenerated `schema.d.ts` still proves the backend shape (`FE-4`, `RISK-6`).
- **Comments that go stale and must be rewritten here:** the `seed_readiness` docstring "Known gap (RISK-5)" (`api/assessments.py:280-289`), which Task 4 closes; the `build_class_overview` docstring (`today.py:187-193`); the module docstrings of `readiness_summary_v2.py:1-20` and `api/today.py:1-12` (Group Analytics no longer loops per learner); and `narrative.py:527`, which names `class_health()`. That function keeps its name, so the last one only needs a check.
- **v2 Topic Mastery reads marked questions only** (`readiness_v2.py:84-113`). `Evidence` is read only for coverage's `practiced` flag (`:237-245`), which today counts a `tutor_estimate` row as practised. **Owner decision (2026-09-23): coverage counts marked work only** — Task 4 excludes `tutor_estimate` from `practiced_ids`.

---

### Task 1: Shared helpers leave the v1 modules; one weak threshold

**Implementer:** `ecc:tdd-guide`

**Files:**
- Create: `backend/app/services/readiness_shared.py`
- Modify: `backend/app/services/readiness_factors.py:17-21` (take over `HALF_LIFE_DAYS`, `_decay`, `_age_days`)
- Modify: `backend/app/services/readiness.py:36,79-80,103-106` (re-import them from `readiness_factors`)
- Modify: `backend/app/services/readiness_summary.py:1-205` (keep `MIN_WEAK_CONFIDENCE`, `v1_score_points`, `build_summary`; re-import everything else)
- Modify: `backend/app/services/readiness_summary_v2.py:44-50` (import from the new homes)
- Modify: `backend/app/api/analytics.py:28` (delete the unused copy)
- Test: `backend/tests/test_readiness_factors.py` (decay tests); `backend/tests/test_direction.py:23` (import path)

**Interfaces:**
- Produces `services/readiness_shared.py`, which has no dependency on v1: `CONFIDENT: frozenset[FactorConfidence]`, `WEAK_THRESHOLD = 60.0`, `DIRECTION_NOISE_BAND`, `MONTH_WINDOW_DAYS`, `trend_direction`, `ScorePoint`, `scores_of`, `window_start`, `period_delta`, `month_delta`, `_aware`, `v2_score_series(db, student_ids, subject_id) -> dict[int, list[ScorePoint]]`, and `v2_score_points(db, student_id, subject_id)`.
- Produces `readiness_factors.HALF_LIFE_DAYS`, `_decay` and `_age_days`, with the bodies unchanged.
- Choice: one new module, not one per concern. These helpers already live together, and 5.3b only needs them out of files it deletes; a split would be churn with no reader.
- Choice: `v2_score_points` becomes a one-subject call into the new set-based `v2_score_series`. Task 3's class page needs the batch form, and two copies of the same filter are the drift `CODE-12` comments in this file warn about.
- Choice: `_decay`/`_age_days` go into `readiness_factors.py` itself rather than the shared module. They are pure decision maths (`BE-4`), and `readiness_factors` is the pure module that uses them.

- [ ] **Step 1: Tests first.** Add to `test_readiness_factors.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services.readiness_factors import HALF_LIFE_DAYS, _age_days, _decay


def test_decay_halves_at_the_half_life():
    assert _decay(0) == 1.0
    assert _decay(HALF_LIFE_DAYS) == pytest.approx(0.5)


def test_age_treats_a_naive_timestamp_as_utc_and_never_goes_negative():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert _age_days(datetime(2026, 5, 31), now) == pytest.approx(1.0)
    assert _age_days(now + timedelta(days=2), now) == 0.0


def test_the_v2_factor_module_does_not_import_v1():
    # 5.3b deletes services/readiness.py; the v2 maths must not go with it.
    import app.services.readiness_factors as mod

    assert "app.services.readiness" not in {
        getattr(v, "__module__", None) for v in vars(mod).values()
    }
```

Also add a test that `readiness_shared.CONFIDENT == {FactorConfidence.medium, FactorConfidence.high}`, and change `test_direction.py:23` to import from `app.services.readiness_shared`.

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_readiness_factors.py tests/test_direction.py -q` and confirm it FAILs with an import error.
- [ ] **Step 3: Implement.** Move the three definitions into `readiness_factors.py`, keeping the docstring text. Rewrite the module docstring at `:1-15`, because "reusing its decay/confidence helpers" becomes "owning the decay helper v1 also imports". Replace the definitions in `readiness.py` with `from app.services.readiness_factors import HALF_LIFE_DAYS, _age_days, _decay  # noqa: F401 - v1 re-import until 5.3b`. That import direction is safe because `readiness_factors` no longer imports `readiness`.

  Create `readiness_shared.py`. Move `DIRECTION_NOISE_BAND` … `_aware` verbatim, with **every** comment. Carry the `CONFIDENT` comment from `readiness_summary.py:34-37` onto the new constant, plus one line: "Built on FactorConfidence: the v2 row's confidence; the v1 enum dies in 5.3b". Carry the `WEAK_THRESHOLD` comment, plus "The one copy until 5.6 makes it tutor-set (decision 10)". Then add:

```python
async def v2_score_series(
    db: AsyncSession, student_ids: Sequence[int], subject_id: int
) -> dict[int, list[ScorePoint]]:
    """Ordered (oldest-first) scored v2 snapshots for many students of one
    subject, in one query. A snapshot with no score is excluded: a no-evidence
    run is not a point on anyone's trend line."""
    if not student_ids:
        return {}
    series: dict[int, list[ScorePoint]] = defaultdict(list)
    for student_id, at, score in (
        await db.execute(
            select(ReadinessSnapshot.student_id, ReadinessSnapshot.created_at, ReadinessSnapshot.score)
            .where(
                ReadinessSnapshot.student_id.in_(list(student_ids)),
                ReadinessSnapshot.subject_id == subject_id,
                ReadinessSnapshot.status == AiSynthesisStatus.ready,
                ReadinessSnapshot.score.is_not(None),
            )
            .order_by(ReadinessSnapshot.created_at, ReadinessSnapshot.id)
        )
    ).all():
        series[student_id].append((at, score))
    return dict(series)


async def v2_score_points(db: AsyncSession, student_id: int, subject_id: int) -> list[ScorePoint]:
    """One student's series — the same query as v2_score_series, so the profile
    arrow and the class page arrow cannot drift apart."""
    return (await v2_score_series(db, [student_id], subject_id)).get(student_id, [])
```

  In `readiness_summary.py`, delete the moved bodies and replace them with `from app.services.readiness_shared import (DIRECTION_NOISE_BAND, MONTH_WINDOW_DAYS, WEAK_THRESHOLD, ScorePoint, _aware, month_delta, period_delta, scores_of, trend_direction, v2_score_points, window_start)  # noqa: F401 - re-exported until 5.3b`. Keep `MIN_WEAK_CONFIDENCE = frozenset({ReadinessConfidence.medium, ReadinessConfidence.high})` as a v1-local definition, and keep v1 `CONFIDENT = MIN_WEAK_CONFIDENCE` so `groups.py`/`today.py` stay unchanged until Task 3. **The "Each engine reads its own history" comment appears twice (`:62-67` and `:162-167`). Keep one copy, in `readiness_summary.py` beside `v1_score_points`.** Point `readiness_summary_v2.py:44-50` at `readiness_shared` for everything except `build_summary`. Delete `api/analytics.py:28`.
- [ ] **Step 4: Run** the full backend suite and confirm it PASSes. The behaviour is unchanged.
- [ ] **Step 5: Discrimination check.** Temporarily restore `from app.services.readiness import _age_days, _decay` in `readiness_factors.py` and confirm `test_the_v2_factor_module_does_not_import_v1` fails. Then restore the moved code.
- [ ] **Step 6: Commit** with `git add backend/app/services/readiness_shared.py backend/app/services/readiness_factors.py backend/app/services/readiness.py backend/app/services/readiness_summary.py backend/app/services/readiness_summary_v2.py backend/app/api/analytics.py backend/tests/test_readiness_factors.py backend/tests/test_direction.py` and the message "Shared readiness helpers leave the v1 modules (5.3a)".

---

### Task 2: Per-student readers — no-snapshot branch, CRM, drill-down, reports

**Implementer:** `ecc:tdd-guide`

**Files:**
- Modify: `backend/app/services/readiness_summary_v2.py:56-71` (make `latest_ready_snapshot` public), `:222-256` (branch)
- Modify: `backend/app/services/student_crm.py:29,99`
- Modify: `backend/app/api/readiness.py:95-132` (`topic_evidence`)
- Modify: `backend/app/schemas/readiness.py:84-90` (`TopicEvidence.score: float | None`)
- Modify: `backend/app/services/reports.py:50-144`
- Modify: `frontend/src/api/readiness.ts:82-89`, `frontend/src/tutor/StudentDetailPage.tsx:129-132`
- Create helper: `write_v2_snapshot` in `backend/tests/factories.py`
- Test: `backend/tests/test_readiness_cutover.py:117-135` (rewrite), new tests in the same file; new `backend/tests/test_report_facts.py`
- Regenerate: `frontend/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Produces: `build_summary_v2` returns one `SubjectReadiness` per requested subject, always. A subject with no `ready` snapshot gets the **no-snapshot shape**: `score=None`, `predicted_grade=None`, `status=None`, `direction=None`, `month_delta=None`, `topics=[]`, `weak_topics=[]`, `topics_with_evidence=0`, `topic_count=<real count>`, homework counts `None`, `engine="v2"`, `computed_at=None`, and `is_updating` from the job queue. The averaging fields stay real, because marked work exists independently of the engine (`PROD-1`).
- Choice: **the v1 fallback stays in 5.3a, behind this branch.** v1 is consulted only when v1 has a score for that subject. Decision 16 assigns fallback deletion to 5.3b. Rollback-safety comes from v1 still *writing*, but the fallback is what keeps the v1-only tests listed in "Verified facts" meaningful until 5.3b deletes them. After the post-deploy backfill (runbook R9), essentially no subject reaches it. 5.3b then deletes four lines and changes no shape.
- Choice: **`student_trend`'s inline v1 fallback stays** (`api/readiness.py:157-168`), for the same reason. The profile's arrow and its trend line must be the same claim: when the summary falls back to v1, the line must too. 5.3b deletes both together. The v2 half switches to `v2_score_points` so it shares the one query.
- Choice: **`topic_evidence` mirrors the same rule.** It reads the topic's `topic_mastery` row from the latest ready snapshot. With no snapshot, it reads v1 `TopicReadiness` as today, so a v1-served bar and its drill-down header agree. Either way an absent score is `None` with `"no_data"`, never `0.0` / `"none"` (`PROD-2`).
- Produces: `latest_ready_snapshot(db, student_id, subject_id)` (public) and `topic_mastery_row(db, snapshot, topic_id) -> FactorEvaluation | None` in `readiness_summary_v2.py`, so the router stays thin (`BE-2`).
- Produces: `build_report_facts` reads `build_summary_v2`, so a report states exactly the numbers the profile shows. Weak topics are `score <= WEAK_THRESHOLD` over topics carrying evidence. Trend comes from `direction`/`month_delta`. Homework comes from the `homework_*` counts.
- Choice: reports drop their own trend rule (a `>1`/`<-1` delta across all history, `reports.py:118`) for the shared `trend_direction` 3-point band. Two definitions of "improved" is how a report and a profile end up contradicting each other.

- [ ] **Step 1: Test factory.** Add to `tests/factories.py`:

```python
async def write_v2_snapshot(
    session,
    *,
    student_id: int,
    subject_id: int,
    score: float | None,
    predicted_grade: str | None = None,
    topics: dict[int, tuple[float | None, FactorConfidence]] | None = None,
    homework: tuple[int, int] | None = None,  # (assignment_count, submitted_count)
    created_at: datetime | None = None,
    status: AiSynthesisStatus = AiSynthesisStatus.ready,
) -> str:
    """One completed v2 run: the factor rows a reader needs plus the snapshot
    synthesized from them, sharing one evaluation_run_id. Replaces every test
    fixture that wrote TopicReadiness/ReadinessHistory (5.3a)."""
    run_id = str(uuid.uuid4())
    for topic_id, (topic_score, confidence) in (topics or {}).items():
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id, student_id=student_id, subject_id=subject_id,
                topic_id=topic_id, factor=ReadinessFactor.topic_mastery, score=topic_score,
                confidence=confidence, evidence_count=0 if topic_score is None else 3, detail={},
            )
        )
    if homework is not None:
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id, student_id=student_id, subject_id=subject_id,
                topic_id=None, factor=ReadinessFactor.homework_performance, score=None,
                confidence=FactorConfidence.no_data, evidence_count=0,
                detail={"assignment_count": homework[0], "submitted_count": homework[1]},
            )
        )
    session.add(
        ReadinessSnapshot(
            evaluation_run_id=run_id, student_id=student_id, subject_id=subject_id,
            status=status, score=score, predicted_grade=predicted_grade, weak_topics=[],
            rationale="fixture", recommended_revision=None,
            **({"created_at": created_at} if created_at else {}),
        )
    )
    await session.flush()
    return run_id
```

- [ ] **Step 2: Tests first.** Add to `test_readiness_cutover.py`, replacing `:117-135`:

```python
async def test_a_subject_with_no_snapshot_and_no_v1_data_is_present_not_dropped(client, tutor, world):  # noqa: F811
    """The branch 5.3b relies on: no v2 run and nothing in v1 either. The
    subject still appears, as "not enough data yet", from v2 — never omitted
    and never a 0 (PROD-2)."""
    resp = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )
    subject = resp.json()["subjects"][0]
    assert subject["engine"] == "v2"
    assert subject["score"] is None
    assert subject["predicted_grade"] is None and subject["direction"] is None
    assert subject["topics"] == [] and subject["topics_with_evidence"] == 0
    assert subject["topic_count"] == 2
    assert subject["computed_at"] is None


async def test_a_failed_synthesis_is_not_served_as_a_score(client, tutor, world):  # noqa: F811
    await _write_snapshot(world, score=None, status=AiSynthesisStatus.failed)
    subject = (
        await client.get(
            f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
        )
    ).json()["subjects"][0]
    assert subject["score"] is None
    assert subject["rationale"] is None  # the failed run's text is never surfaced


async def test_v1_still_answers_when_it_has_a_score_and_v2_has_none(client, tutor, world):  # noqa: F811
    """Rollback-safe cutover until 5.3b: v1 still writes, so its number is real."""
    async with async_session() as session:
        session.add(TopicReadiness(student_id=world["student_id"], topic_id=world["topic1"],
                                   score=70.0, confidence=ReadinessConfidence.high, evidence_count=3))
        await session.commit()
    subject = (
        await client.get(
            f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
        )
    ).json()["subjects"][0]
    assert subject["engine"] == "v1"
    assert subject["score"] == 70.0


async def test_topic_drill_down_reads_the_v2_run(client, tutor, world):  # noqa: F811
    await _write_snapshot(world, topic_score=55.0)
    body = (await client.get(
        f"/api/v1/readiness/students/{world['student_id']}/topics/{world['topic1']}/evidence",
        headers=tutor["headers"],
    )).json()
    assert body["score"] == 55.0
    assert body["confidence"] == "high"


async def test_topic_drill_down_without_data_is_absent_not_zero(client, tutor, world):  # noqa: F811
    body = (await client.get(
        f"/api/v1/readiness/students/{world['student_id']}/topics/{world['topic2']}/evidence",
        headers=tutor["headers"],
    )).json()
    assert body["score"] is None
    assert body["confidence"] == "no_data"
```

Add a CRM test in `test_crm.py`: seed `write_v2_snapshot(score=66.0, predicted_grade="6")`, call the CRM endpoint that `test_crm.py:119` uses, and assert the subject's readiness score is `66.0`. That proves the CRM reads v2.

Create `test_report_facts.py`. It uses the `world` fixture from `test_readiness_api`, calls `build_report_facts` directly, seeds two snapshots 40 days apart (`50.0` then `72.0`) with topic rows `{topic1: (80.0, high), topic2: (45.0, high)}` and `homework=(5, 4)`, and asserts:

```python
    assert "Overall readiness: 72.0%" in facts
    assert "Weakest topics: Ionic bonding (45%)" in facts   # 45 <= WEAK_THRESHOLD
    assert "Atomic structure" not in facts.split("Weakest topics:")[1]
    assert "Trend: improved" in facts
    assert "Homework: submitted 4 of 5 assignments" in facts
```

It also covers a subject with no snapshot, which must contain "No readiness data yet for this subject.".

- [ ] **Step 3: Run** these and confirm they FAIL. The no-data subject currently comes back `engine == "v1"`, the drill-down returns `0.0`, and the report reads `TopicReadiness`.
- [ ] **Step 4: Implement `build_summary_v2`:**

```python
async def _subject_without_snapshot(
    db: AsyncSession, student: User, subject: Subject
) -> SubjectReadiness:
    """No ready snapshot yet: v2 never ran for this subject, or every run's AI
    synthesis failed. The subject is still shown — as "not enough data yet",
    never omitted and never a 0 (PROD-2). Marked-work averaging is real data
    that does not depend on either engine, so it is still reported (PROD-1)."""
    topic_count = (
        await db.scalar(select(func.count(Topic.id)).where(Topic.subject_id == subject.id))
    ) or 0
    boundaries = await resolve_grade_boundaries(db, student.organization_id, subject)
    averaging = await subject_averaging(db, student.id, subject.id)
    return SubjectReadiness(
        subject_id=subject.id,
        subject_name=subject.name,
        exam_board=subject.exam_board,
        grade_scale=subject.grade_scale,
        score=None,
        predicted_grade=None,
        status=None,
        averaging_score=averaging.score,
        averaging_grade=(
            predict_grade(averaging.score, boundaries)
            if averaging.score is not None and boundaries
            else None
        ),
        marked_piece_count=averaging.marked_piece_count,
        topic_count=topic_count,
        topics=[],
        weak_topics=[],
    )


async def build_summary_v2(
    db: AsyncSession, student: User, subject_ids: list[int]
) -> StudentReadinessSummary:
    everything_updating, updating = await in_flight_subjects(db, student.id)

    subjects_out: list[SubjectReadiness] = []
    without_snapshot: list[int] = []
    for subject_id in subject_ids:
        subject = await db.get(Subject, subject_id)
        if subject is None:
            continue
        snapshot = await latest_ready_snapshot(db, student.id, subject_id)
        if snapshot is None:
            out = await _subject_without_snapshot(db, student, subject)
            without_snapshot.append(subject_id)
        else:
            out = await _subject_from_snapshot(db, student, subject, snapshot)
            out.computed_at = snapshot.created_at
        out.is_updating = everything_updating or subject_id in updating
        subjects_out.append(out)

    if without_snapshot:
        # Until 5.3b: v1 still writes, so where it has a real score for a
        # subject v2 has not answered yet, that number is served and labelled
        # engine="v1". Where v1 has nothing either, the v2 no-snapshot shape
        # above stands — which is exactly what every subject gets once 5.3b
        # deletes these lines.
        position = {s.subject_id: i for i, s in enumerate(subjects_out)}
        legacy = await build_summary(db, student, without_snapshot)
        for legacy_subject in legacy.subjects:
            if legacy_subject.score is None:
                continue
            legacy_subject.engine = "v1"
            legacy_subject.is_updating = subjects_out[
                position[legacy_subject.subject_id]
            ].is_updating
            subjects_out[position[legacy_subject.subject_id]] = legacy_subject

    subjects_out.sort(key=lambda s: subject_ids.index(s.subject_id))
    return StudentReadinessSummary(
        student_id=student.id, student_name=student.name, subjects=subjects_out
    )


async def topic_mastery_row(
    db: AsyncSession, snapshot: ReadinessSnapshot, topic_id: int
) -> FactorEvaluation | None:
    """One topic's Topic Mastery row from the run a snapshot was built from —
    so the drill-down header is the same number as the topic's bar."""
    return await db.scalar(
        select(FactorEvaluation).where(
            FactorEvaluation.evaluation_run_id == snapshot.evaluation_run_id,
            FactorEvaluation.factor == ReadinessFactor.topic_mastery,
            FactorEvaluation.topic_id == topic_id,
        )
    )
```

  Rewrite the module docstring's "Fallback to v1" bullet to describe the narrowed rule and name 5.3b.
- [ ] **Step 5: `topic_evidence`** (`api/readiness.py:95-132`):

```python
    snapshot = await latest_ready_snapshot(db, student_id, topic.subject_id)
    score: float | None = None
    confidence = FactorConfidence.no_data.value
    if snapshot is not None:
        row = await topic_mastery_row(db, snapshot, topic_id)
        if row is not None and row.score is not None and row.confidence != FactorConfidence.no_data:
            score, confidence = row.score, row.confidence.value
    else:
        # Until 5.3b: the summary serves v1 for a subject v2 has not answered,
        # so the drill-down header must read the same engine as the bar.
        legacy = await db.scalar(select(TopicReadiness).where(
            TopicReadiness.student_id == student_id, TopicReadiness.topic_id == topic_id))
        if legacy is not None:
            score, confidence = legacy.score, legacy.confidence.value
```

  Pass `score=score, confidence=confidence`. Set `TopicEvidence.score: float | None` in the schema with a `PROD-2` comment. In `student_trend`, replace the v2 query (`:143-156`) with `[TrendPoint(recorded_at=at, score=s) for at, s in await v2_score_points(db, student_id, subject_id)]` and keep the v1 branch with a "until 5.3b, paired with the summary fallback" comment.
- [ ] **Step 6: CRM.** Change `student_crm.py:29` to `from app.services.readiness_summary_v2 import build_summary_v2`, and `:99` to `await build_summary_v2(session, student, subject_ids)`. The return type is the same.
- [ ] **Step 7: Reports.** Replace the body of `build_report_facts` (`:50-144`):

```python
async def build_report_facts(session: AsyncSession, student: User, subject_ids: list[int]) -> str:
    """The factual block the report prompt writes from — the same numbers the
    student's profile shows, because both read build_summary_v2."""
    lines: list[str] = [f"Student: {student.name}"]
    codes = dict(
        (await session.execute(select(Subject.id, Subject.code).where(Subject.id.in_(subject_ids or [0])))).all()
    )
    summary = await build_summary_v2(session, student, subject_ids)
    for s in summary.subjects:
        lines.append(f"\n## {s.subject_name} ({s.exam_board} {codes.get(s.subject_id, '')})")
        if s.score is None:
            lines.append("No readiness data yet for this subject.")
            continue
        # One source since 2.4 (AV-11): no boundaries set means no predicted
        # grade in the report either — the sentence drops rather than carrying a
        # dash a model would then have to explain (PROD-2).
        lines.append(
            f"Overall readiness: {s.score}% (estimated grade: {s.predicted_grade})"
            if s.predicted_grade
            else f"Overall readiness: {s.score}% (no grade boundaries set for this subject)"
        )
        strong = sorted(s.topics, key=lambda t: t.score, reverse=True)[:3]
        weak = sorted((t for t in s.topics if t.score <= WEAK_THRESHOLD), key=lambda t: t.score)[:5]
        if strong:
            lines.append("Strongest topics: " + ", ".join(f"{t.topic_title} ({t.score:.0f}%)" for t in strong))
        if weak:
            lines.append("Weakest topics: " + ", ".join(f"{t.topic_title} ({t.score:.0f}%)" for t in weak))
        if s.direction is not None:
            word = {"up": "improved", "down": "declined", "flat": "held steady"}[s.direction]
            moved = f" ({s.month_delta:+.1f} points in the last 30 days)" if s.month_delta is not None else ""
            lines.append(f"Trend: {word}{moved}")
        if s.homework_assignment_count:
            lines.append(
                f"Homework: submitted {s.homework_submitted_count} of {s.homework_assignment_count} assignments"
            )
    return "\n".join(lines)
```

  Delete the now-unused imports. Check first that `func`, `Assignment`, `Group`, `GroupMember` and `Submission` are unused elsewhere in `reports.py`. **The REPORTS prompt text is unchanged**, so there is no version bump; the facts block is data.
- [ ] **Step 8: Frontend.** `TopicEvidence.score: number | null`. At `StudentDetailPage.tsx:130`, render `Readiness {Math.round(score)}% ({confidence} confidence)` only when `score !== null`, and otherwise `Not enough data yet —`. Keep the rest of the sentence. Regenerate the types.
- [ ] **Step 9: Run** the full backend suite, `npm test` and `npm run build`, and confirm they PASS. Then port whatever reds: `test_reports.py` if it asserted v1 lines, and `test_authorization.py` if a topic-evidence case asserted `0.0`.
- [ ] **Step 10: Discrimination check.** Delete the `if legacy_subject.score is None: continue` line and confirm `test_a_subject_with_no_snapshot_and_no_v1_data_is_present_not_dropped` fails (`engine == "v1"`). Point `student_crm` back at `build_summary` and confirm the CRM test fails. Restore both.
- [ ] **Step 11: Commit** with `git add backend/app/services/readiness_summary_v2.py backend/app/services/student_crm.py backend/app/services/reports.py backend/app/api/readiness.py backend/app/schemas/readiness.py backend/tests/factories.py backend/tests/test_readiness_cutover.py backend/tests/test_crm.py backend/tests/test_report_facts.py frontend/src/api/readiness.ts frontend/src/tutor/StudentDetailPage.tsx frontend/openapi.json frontend/src/api/schema.d.ts` and the message "Student readers, CRM, drill-down and reports read v2 (5.3a, AV-78)".

---

### Task 3: One v2 class aggregation — home, class page, class cards, Group Analytics

**Implementer:** `ecc:tdd-guide`

**Files:**
- Create: `backend/app/services/class_readiness.py`
- Modify: `backend/app/services/groups.py:11-25` (imports), `:141-172` (`covered`), `:193-277` (delete `weighted_learner_scores` and `class_health`, which move)
- Modify: `backend/app/services/today.py:17-41,137-176,179-299`
- Modify: `backend/app/api/analytics.py:1-86` (readiness half; `agreement` at `:88-127` untouched)
- Modify: `backend/app/schemas/today.py:57-73` (`ClassLearnerRow`)
- Modify: `backend/app/api/today.py:1-12` (docstring); `backend/app/services/narrative.py:527` (check the comment still names a real function)
- Modify: `frontend/src/api/today.ts:49-56`, `frontend/src/tutor/ClassOverview.tsx:21-42`
- Test port: `backend/tests/test_class_overview.py:55-85` and callers, `test_groups.py:240-460`, `test_today_endpoint.py:86-110`, `test_coverage.py:67-120,164-190`, `test_readiness_api.py:243-271`, `test_direction.py:71-193`
- Test new: `backend/tests/test_class_readiness.py`; `frontend/src/test/ClassOverview.test.tsx` (completion case)
- Regenerate: `frontend/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Produces: `latest_learner_snapshots(session, group_ids) -> {group_id: {student_id: LearnerSnapshot}}`, which runs **one query for any number of classes**. It reads each enrolled learner's latest `ready` snapshot in that class's subject, including a no-evidence one with `score=None`. This is the same "latest ready" rule `build_summary_v2` uses, so a learner is never scored on the class page while showing "not enough data yet" on their profile.
- Produces: `class_health(session, group_ids) -> {group_id: (score | None, scored_count)}`. The contract is unchanged; only the source moves. Callers now pass ids.
- Produces: `class_readiness(session, group_id) -> ClassReadiness(score, scored, topic_means, homework)`. That is one call to `latest_learner_snapshots` plus **one** factor query: 2 queries per class, flat in roster size.
- The class score is the mean of scored learners' snapshot scores (decision 13). The class grade is `predict_grade(score, boundaries_for(org_boundaries, subject))`, the path `today.py:147-150` already uses. The boundary source is the same table as `resolve_grade_boundaries` (`grade_boundaries.py:77-150`).
- Choice: **a learner row shows the snapshot's own `predicted_grade`** (hidden when no boundaries), not a re-mapping of its score. That is exactly `_subject_from_snapshot`'s rule (`readiness_summary_v2.py:180-189`), so the class row and the student's profile print the same grade.
- Choice: **class weak topics keep medium/high confidence only** (`readiness_shared.CONFIDENT`), the rule `today.py:229` applied in v1. Group Analytics used "anything but none" (`analytics.py:59`). Unifying on one rule is decision 15's point, and a single low-confidence mark should not name a class-wide weakness. The list is unthresholded and lowest-first, as both surfaces were.
- Choice: `students_with_evidence` (class cards, strip, class page) now means **learners whose latest ready snapshot has a score**. v1 meant "a medium/high `TopicReadiness` row". "N of M with evidence" now describes the same learners the class score is averaged over.
- Produces: `ClassLearnerRow.homework_assignment_count: int | None = None` and `homework_submitted_count: int | None = None`, read from the learner's latest run's `homework_performance.detail`. They are `None` when that row or either key is absent, never `0` (`PROD-2`).

- [ ] **Step 1: Tests first.** Create `test_class_readiness.py`, reusing `_class_with`/`_learner`-style helpers built on `write_v2_snapshot`:

```python
async def test_class_score_is_the_mean_of_scored_learners_and_counts_the_rest(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    b = await _student(client, tutor, group["id"], "B", "b01")
    c = await _student(client, tutor, group["id"], "C", "c01")
    await _snap(a["id"], subject_id, 80.0)
    await _snap(b["id"], subject_id, 60.0)
    await _snap(c["id"], subject_id, None)  # a no-evidence run: counted, not zeroed
    async with async_session() as session:
        assert (await class_health(session, [group["id"]]))[group["id"]] == (70.0, 2)


async def test_only_the_latest_ready_snapshot_counts(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    a = await _student(client, tutor, group["id"], "A", "a01")
    now = datetime.now(timezone.utc)
    await _snap(a["id"], subject_id, 30.0, created_at=now - timedelta(days=3))
    await _snap(a["id"], subject_id, 90.0, created_at=now - timedelta(days=1))
    await _snap(a["id"], subject_id, None, status=AiSynthesisStatus.failed, created_at=now)
    async with async_session() as session:
        assert (await class_health(session, [group["id"]]))[group["id"]] == (90.0, 1)


async def test_another_subjects_snapshot_does_not_leak_into_the_class(client, tutor, subject_id):
    ...  # snapshot in a second subject only -> (None, 0)


async def test_class_topic_means_come_from_each_learners_latest_run_only(client, tutor, subject_id):
    # Older run says the topic is 10; latest says 70 and 50 -> mean 60, 2 learners.
    # A low-confidence row in the latest run is excluded.
    ...


async def test_class_readiness_query_count_is_flat_in_roster_size(client, tutor, subject_id):
    # Use test_today_endpoint.py:220-227's count_queries(); 1 learner vs 6 learners -> equal.
    ...
```

  Fill in the `...` bodies in the same style; they are specified by their comments. Add to `test_class_overview.py`:

```python
async def test_learner_row_carries_homework_completion(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 70.0, homework=(5, 4))
    row = (await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])).json()["learners"][0]
    assert (row["homework_assignment_count"], row["homework_submitted_count"]) == (5, 4)


async def test_learner_without_homework_row_reports_null_not_zero(client, tutor, subject_id):
    group = await _class_with(client, tutor, subject_id)
    await _learner(client, tutor, group["id"], "Aya", "aya01", 70.0)
    row = (await client.get(f"/api/v1/today/classes/{group['id']}", headers=tutor["headers"])).json()["learners"][0]
    assert row["homework_assignment_count"] is None and row["homework_submitted_count"] is None
```

  **Port `_learner`** (`test_class_overview.py:55-85`). It writes one `write_v2_snapshot` per `history` value, oldest first, 5 days apart, with the final snapshot at `score` and `topics={topic_id: (score, FactorConfidence.high)}`. An empty `history` writes just the one. It takes a `homework=` argument. Every existing assertion in that file then holds unchanged, which is the proof the port preserves behaviour. Port `test_groups.py:257-271` `_give_topic_readiness` to `_snap(...)`. **Delete** `test_class_health_weights_by_topic_weight` and `test_class_health_counts_only_confident_readiness`, because both pin v1 formulas decision 13 replaces. Replace them with the two new tests above. Adjust the other `class_health` tests to pass `[g.id]`. Port `test_today_endpoint.py:86-110` `_give_readiness` to a snapshot with `predicted_grade` set. Port `test_coverage.py`: `add_readiness` becomes `_snap`. `test_low_confidence_does_not_count` becomes `test_a_no_evidence_snapshot_does_not_count` (score `None` → 0). `:164-190` call `build_summary_v2` with `topics={topic1: (70.0, high)}` and assert `1/2` and `0/2`. Port `test_readiness_api.py:243-271` (`test_group_analytics_and_agreement`) to seed a snapshot instead of a mock. Port the v1 API half of `test_direction.py:71-193` from `record_history` to that file's own `write_snapshots` (`:199-218`), deleting the cases the v2 section already covers (`:222-238`: rising, single, no-score). Keep `:242-259` for 5.3b.
- [ ] **Step 2: Run** these and confirm they FAIL.
- [ ] **Step 3: Implement `services/class_readiness.py`:**

```python
"""A class's readiness picture, from Readiness Engine v2 (decisions 13, 15).

One definition, read by the tutor home strip and the class page
(services/today.py), the class cards' coverage count (services/groups.py) and
Group Analytics (api/analytics.py). Before 5.3a each of those aggregated v1
TopicReadiness rows its own way, and Group Analytics did it with a query per
learner — so the same class could carry three different scores (RISK-5, PERF-1).

The class score is the mean of each enrolled learner's **latest ready** v2
snapshot score — the same snapshot their own profile shows. A learner whose
latest run found no evidence is omitted and counted, never averaged in as 0
(PROD-2). Everything here is a fixed number of queries per call, whatever the
roster size.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiSynthesisStatus,
    FactorEvaluation,
    Group,
    GroupMember,
    ReadinessFactor,
    ReadinessSnapshot,
    Topic,
    User,
)
from app.services.readiness_shared import CONFIDENT


@dataclass(frozen=True)
class LearnerSnapshot:
    student_id: int
    student_name: str
    score: float | None  # None: the latest run found no evidence
    predicted_grade: str | None
    evaluation_run_id: str


@dataclass(frozen=True)
class TopicMean:
    topic_id: int
    topic_code: str
    topic_title: str
    avg_score: float
    student_count: int


@dataclass(frozen=True)
class ClassReadiness:
    score: float | None
    #: Scored learners only, lowest first.
    scored: list[LearnerSnapshot]
    #: Topic Mastery averaged over scored learners' latest runs, lowest first.
    topic_means: list[TopicMean]
    #: student_id -> (assignment_count, submitted_count); absent = no homework row.
    homework: dict[int, tuple[int, int]]


async def latest_learner_snapshots(
    session: AsyncSession, group_ids: list[int]
) -> dict[int, dict[int, LearnerSnapshot]]:
    """Each enrolled learner's latest ready snapshot in their class's subject,
    for every given class, in one query.

    "Latest ready" is build_summary_v2's rule, deliberately: a failed synthesis
    is skipped, and a no-evidence run (ready, score None) *is* the latest — so
    a learner is never scored here while their profile says "not enough data
    yet". Partitioned by (group, student), not student alone: one student in
    two classes of different subjects has a different latest snapshot in each.
    SEC-7: group_ids arrive scoped to the authenticated tutor by every caller.
    """
    if not group_ids:
        return {}
    ranked = (
        select(
            GroupMember.group_id.label("group_id"),
            ReadinessSnapshot.student_id.label("student_id"),
            User.name.label("student_name"),
            ReadinessSnapshot.score.label("score"),
            ReadinessSnapshot.predicted_grade.label("predicted_grade"),
            ReadinessSnapshot.evaluation_run_id.label("run_id"),
            func.row_number()
            .over(
                partition_by=(GroupMember.group_id, ReadinessSnapshot.student_id),
                order_by=(ReadinessSnapshot.created_at.desc(), ReadinessSnapshot.id.desc()),
            )
            .label("rn"),
        )
        .select_from(GroupMember)
        .join(Group, Group.id == GroupMember.group_id)
        .join(User, User.id == GroupMember.student_id)
        .join(
            ReadinessSnapshot,
            (ReadinessSnapshot.student_id == GroupMember.student_id)
            # Subjects are org-owned (2.2), so the subject match is also what
            # keeps another subject's — or tenant's — score out of this class.
            & (ReadinessSnapshot.subject_id == Group.subject_id),
        )
        .where(
            GroupMember.group_id.in_(group_ids),
            ReadinessSnapshot.status == AiSynthesisStatus.ready,
        )
        .subquery()
    )
    out: dict[int, dict[int, LearnerSnapshot]] = {gid: {} for gid in group_ids}
    for row in (await session.execute(select(ranked).where(ranked.c.rn == 1))).all():
        out[row.group_id][row.student_id] = LearnerSnapshot(
            student_id=row.student_id,
            student_name=row.student_name,
            score=row.score,
            predicted_grade=row.predicted_grade,
            evaluation_run_id=row.run_id,
        )
    return out


def _mean(learners: dict[int, LearnerSnapshot]) -> tuple[float | None, int]:
    # Numerator and denominator from one filtered list — a None score is an
    # omitted learner, never a 0 in the average (PROD-2).
    scores = [s.score for s in learners.values() if s.score is not None]
    return (round(sum(scores) / len(scores), 1), len(scores)) if scores else (None, 0)


async def class_health(
    session: AsyncSession, group_ids: list[int]
) -> dict[int, tuple[float | None, int]]:
    """{group_id: (class score or None, scored learner count)} for every class,
    in one query. (None, 0) for a class with nobody scored — never 0.0."""
    snapshots = await latest_learner_snapshots(session, group_ids)
    return {gid: _mean(snapshots[gid]) for gid in group_ids}


async def class_readiness(session: AsyncSession, group_id: int) -> ClassReadiness:
    """The class page / Group Analytics detail: two queries, whatever the roster."""
    learners = (await latest_learner_snapshots(session, [group_id]))[group_id]
    score, _ = _mean(learners)
    scored = sorted(
        (s for s in learners.values() if s.score is not None), key=lambda s: s.score or 0.0
    )
    topic_scores: dict[int, list[float]] = defaultdict(list)
    meta: dict[int, tuple[str, str]] = {}
    homework: dict[int, tuple[int, int]] = {}
    run_ids = [s.evaluation_run_id for s in scored]
    if run_ids:
        # Both factors from the learners' own latest runs in one statement —
        # an older run's topic score must not outvote the current one.
        rows = (
            await session.execute(
                select(
                    FactorEvaluation.student_id,
                    FactorEvaluation.factor,
                    FactorEvaluation.topic_id,
                    FactorEvaluation.score,
                    FactorEvaluation.confidence,
                    FactorEvaluation.detail,
                    Topic.code,
                    Topic.title,
                )
                .outerjoin(Topic, Topic.id == FactorEvaluation.topic_id)
                .where(
                    FactorEvaluation.evaluation_run_id.in_(run_ids),
                    FactorEvaluation.factor.in_(
                        (ReadinessFactor.topic_mastery, ReadinessFactor.homework_performance)
                    ),
                )
            )
        ).all()
        for r in rows:
            if r.factor == ReadinessFactor.homework_performance and r.topic_id is None:
                assigned = r.detail.get("assignment_count")
                submitted = r.detail.get("submitted_count")
                if assigned is not None and submitted is not None:
                    homework[r.student_id] = (assigned, submitted)
            elif (
                r.factor == ReadinessFactor.topic_mastery
                and r.topic_id is not None
                and r.score is not None
                and r.confidence in CONFIDENT
            ):
                topic_scores[r.topic_id].append(r.score)
                meta[r.topic_id] = (r.code, r.title)
    topic_means = sorted(
        (
            TopicMean(
                topic_id=tid,
                topic_code=meta[tid][0],
                topic_title=meta[tid][1],
                avg_score=round(sum(v) / len(v), 1),
                student_count=len(v),
            )
            for tid, v in topic_scores.items()
        ),
        key=lambda t: t.avg_score,
    )
    return ClassReadiness(score=score, scored=scored, topic_means=topic_means, homework=homework)
```

- [ ] **Step 4: Rewire the readers.**
  - `groups.py`: delete `weighted_learner_scores` and `class_health` (`:193-277`). Replace `covered` (`:141-172`) with `covered = {gid: _mean(l)[1] for gid, l in (await latest_learner_snapshots(session, group_ids)).items()}`, importing `_mean` or inlining the count. Rewrite the comment above it: the coverage numerator is now the scored-learner count, and the `DISTINCT` reasoning goes because the query already yields one row per learner. Drop the `TopicReadiness`/`Topic`/`CONFIDENT` imports.
  - `today.py`: `build_today` calls `class_health(db, [g.id for g in groups])` from `class_readiness`. Rewrite `build_class_overview` from `:196` on:

```python
    overrides = await org_boundaries(db, user.organization_id)
    boundaries = boundaries_for(overrides, group.subject)
    summary = (await group_summaries(db, [group.id]))[group.id]
    detail = await class_readiness(db, group.id)
    # Every scored learner's series in one query, not one per learner (PERF-1).
    series = await v2_score_series(db, [s.student_id for s in detail.scored], group.subject_id)

    learners: list[ClassLearnerRow] = []
    for s in detail.scored:
        # The snapshot's own grade — what the learner's profile prints — shown
        # only while boundaries exist to stand behind it (PROD-2).
        grade = s.predicted_grade if boundaries else None
        hw = detail.homework.get(s.student_id)
        learners.append(
            ClassLearnerRow(
                student_id=s.student_id,
                student_name=s.student_name,
                score=s.score,
                predicted_grade=grade,
                status=grade_band(grade, boundaries),
                direction=trend_direction(scores_of(series.get(s.student_id, []))),
                homework_assignment_count=hw[0] if hw else None,
                homework_submitted_count=hw[1] if hw else None,
            )
        )
    class_grade = (
        predict_grade(detail.score, boundaries) if detail.score is not None and boundaries else None
    )
```

    The `ClassOverview(...)` construction keeps its fields, with `score=detail.score`, `weak_topics=[ClassWeakTopic(topic_code=t.topic_code, topic_title=t.topic_title, avg_score=t.avg_score, student_count=t.student_count) for t in detail.topic_means[:5]]`, and `learners` already lowest-first. Rewrite the docstring's v1/RISK-5 paragraph: score, grade and arrow now all come from the learner's v2 snapshot series, the same claim as their profile. Drop the `defaultdict`, `ReadinessHistory`, `TopicReadiness`, `Topic`, `CONFIDENT` and `weighted_learner_scores` imports.
  - `api/analytics.py` `group_analytics`: keep the authorization at `:33-35`. Replace `:37-86` with `detail = await class_readiness(db, group_id)`, `weak_students = [WeakStudent(student_id=s.student_id, student_name=s.student_name, subject_name=subject_name, score=s.score) for s in detail.scored]` (already lowest-first; `s.score` is non-None here), and `weak_topics = [TopicHeat(topic_code=t.topic_code, topic_title=t.topic_title, avg_score=t.avg_score, student_count=t.student_count) for t in detail.topic_means]`. **Do not touch `:88-127`** (agreement). Remove `TopicReadiness`, `ReadinessConfidence`, `User` and `Topic` if they are now unused.
  - `schemas/today.py`: add the two fields to `ClassLearnerRow`, with a comment mirroring `schemas/readiness.py:54-58`.
  - `api/today.py:1-12` docstring: Group Analytics now shares the aggregation, so rewrite the "left in place" paragraph. `narrative.py:527`: `class_health()` still exists and is still the fan-out remover, so confirm and leave it.
- [ ] **Step 5: Frontend.** Add `homework_assignment_count: number | null; homework_submitted_count: number | null;` to `ClassLearnerRow` in `api/today.ts`, with the same doc comment as `api/readiness.ts:52-54`. In `ClassOverview.tsx` `LearnerRow`, after the status badge:

```tsx
      {/* A fact, not part of the score (AV-32) — same rule and loose `!= null`
          as ReadinessView's profile line (deploy skew leaves these undefined). */}
      {row.homework_assignment_count != null && row.homework_submitted_count != null && (
        <span className="text-sm text-ink-500">
          {row.homework_submitted_count} of {row.homework_assignment_count} handed in
        </span>
      )}
```

  In `test/ClassOverview.test.tsx`, add a learner with `5`/`4` and assert "4 of 5 handed in", and one with nulls and assert no "handed in". Add the two fields (null) to the `learner()` helper and to `test/ClassReadiness.test.tsx:98`'s fixture if TypeScript demands it. Regenerate the types.
- [ ] **Step 6: Run** the full backend and frontend gates and confirm they PASS. `test_today_endpoint.py:212` (the query-count test) must still pass after its `_give_readiness` port.
- [ ] **Step 7: Discrimination checks.**
  - Remove `.where(ranked.c.rn == 1)` and confirm `test_only_the_latest_ready_snapshot_counts` fails.
  - Change `_mean` to `sum(scores)/len(learners)` and confirm the mean test fails.
  - Return `0` instead of skipping when `assignment_count` is absent, and confirm the null-completion test fails.
  - Swap the series to one `v2_score_points` call per learner and confirm the flat query-count test fails.
  - Restore all four.
- [ ] **Step 8: Commit** with `git add backend/app/services/class_readiness.py backend/app/services/groups.py backend/app/services/today.py backend/app/api/analytics.py backend/app/api/today.py backend/app/schemas/today.py backend/tests/test_class_readiness.py backend/tests/test_class_overview.py backend/tests/test_groups.py backend/tests/test_today_endpoint.py backend/tests/test_coverage.py backend/tests/test_readiness_api.py backend/tests/test_direction.py frontend/src/api/today.ts frontend/src/tutor/ClassOverview.tsx frontend/src/test/ClassOverview.test.tsx frontend/src/test/ClassReadiness.test.tsx frontend/openapi.json frontend/src/api/schema.d.ts` and the message "One v2 class aggregation for home, class page and analytics (5.3a, AV-78)".

---

### Task 4: The tutor's estimate is a labelled, decaying prior in v2 Topic Mastery

**Implementer:** `ecc:tdd-guide`

**Files:**
- Modify: `backend/app/services/readiness_factors.py:44-78` (`topic_mastery`)
- Modify: `backend/app/services/readiness_v2.py:338-355` (load estimates, pass them in; coverage's `mastered`)
- Modify: `backend/app/services/prompts.py:216-230` (one rule), `:387` (`v2` → `v3`)
- Modify: `backend/app/schemas/readiness.py:6-12` (`TopicReadinessOut.tutor_estimate: bool = False`)
- Modify: `backend/app/services/readiness_summary_v2.py` (`_subject_from_snapshot` sets it); `backend/app/services/reports.py` (labels it)
- Modify: `backend/app/api/assessments.py:280-289` (docstring "Known gap" closes)
- Modify: `frontend/src/api/readiness.ts:5-12`, `frontend/src/components/ReadinessView.tsx:117-135`
- Test: `backend/tests/test_readiness_factors.py` (the prior), `backend/tests/test_readiness_v2.py` (end to end), `backend/tests/test_report_facts.py` (the label)
- Regenerate: `frontend/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Produces: `TutorEstimate(pct: float, occurred_at: datetime)` and `topic_mastery(questions, now=None, estimate: TutorEstimate | None = None)`. The semantics are v1's `SEEDED_SOURCES` (`readiness.py:52-60,125-141`), carried over:
  - **The estimate alone carries the topic.** Score = the estimate.
  - **It gives way to marked work, not only to time.** Its weight is `TUTOR_ESTIMATE_WEIGHT × decay ÷ (1 + marked questions)`.
  - **Time decay still applies to it**, independently.
  - **It is never deleted, only outweighed.** `evidence_count` includes it, and the `Evidence` row stays readable (`PROD-1`).
- Choice: `TUTOR_ESTIMATE_WEIGHT = 0.4`, v1's value. A v2 question of medium difficulty weighs `1.0` (`DIFFICULTY_WEIGHT`), the same as v1's homework piece. The divisor counts **marked questions**, v2's unit of marked work, so the estimate recedes a little faster than in v1, where the unit was a whole piece. That matches "marked work overtakes".
- Choice: **the estimate never raises confidence.** Estimate-only is `low`, and with marked questions the confidence is `_confidence_from_count(len(questions))`, as without it. `low` keeps an estimate-only topic out of class weak topics (`CONFIDENT` is medium/high) while it still shows as a bar. `no_data` would hide it entirely (`readiness_summary_v2.py:139-141`).
- **Owner decision: coverage's `practiced` flag excludes `tutor_estimate`.** In `readiness_v2.py` (`practiced_ids`, ~:247-254) add `Evidence.source_type != EvidenceSource.tutor_estimate` to the `where`. A tutor's estimate is not practice. Other sources (homework, mocks, observations) still count. Test: a student with only a seeded estimate on a topic has `practiced=False` for it, and the same student plus one marked question has `practiced=True`. Discrimination: drop the filter, and the first assertion fails.
- Choice: **coverage's `mastered` flag ignores an estimate-only score** (`readiness_v2.py` `mastery_by_topic`). A self-declared 80 must not assert syllabus mastery (`PROD-8`). With marked questions the prior-inclusive score is used, as for the bar.
- Produces: `FactorEvaluation.detail["tutor_estimate"] = {"pct": float, "share": float}` only when an estimate contributed, and `TopicReadinessOut.tutor_estimate: bool`. That field is the label the profile and reports show (`PROD-8`, `UX-20`).

- [ ] **Step 1: Pure tests** in `test_readiness_factors.py`. They are the port of `test_seeded_evidence.py:32-99`; the v1 file stays until 5.3b.

```python
NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


def _q(pct, days_ago=0, difficulty="medium"):
    return MarkedQuestion(difficulty=difficulty, pct=pct, occurred_at=NOW - timedelta(days=days_ago))


def _estimate(pct, days_ago=0):
    return TutorEstimate(pct=pct, occurred_at=NOW - timedelta(days=days_ago))


def test_an_estimate_alone_carries_the_topic_at_low_confidence():
    result = topic_mastery([], NOW, estimate=_estimate(40.0))
    assert result.score == 40.0
    assert result.confidence == FactorConfidence.low  # scored, but never confident
    assert result.evidence_count == 1
    assert result.detail["tutor_estimate"] == {"pct": 40.0, "share": 1.0}


def test_the_estimate_gives_way_to_marked_questions_with_no_time_passing():
    """The gate (decision 14): same day, same estimate, more marked work."""
    scores = [
        topic_mastery([_q(100.0)] * n, NOW, estimate=_estimate(0.0)).score for n in range(1, 4)
    ]
    assert scores == sorted(scores) and scores[0] < scores[-1]
    assert scores[-1] > 95.0  # 300 / (3 + 0.4/4) = 96.8


def test_the_estimate_is_never_deleted_only_outweighed():
    result = topic_mastery([_q(100.0)] * 5, NOW, estimate=_estimate(0.0))
    assert result.evidence_count == 6
    assert result.score < 100.0


def test_time_decay_still_applies_to_the_estimate():
    old = topic_mastery([_q(40.0)], NOW, estimate=_estimate(80.0, days_ago=365))
    assert old.score < 45.0


def test_the_estimate_never_raises_confidence():
    with_estimate = topic_mastery([_q(70.0)], NOW, estimate=_estimate(90.0))
    assert with_estimate.confidence == topic_mastery([_q(70.0)], NOW).confidence


def test_no_estimate_no_label():
    assert "tutor_estimate" not in topic_mastery([_q(70.0)], NOW).detail


def test_nothing_at_all_is_no_data():
    assert topic_mastery([], NOW) is NO_DATA
```

- [ ] **Step 2: Run** and confirm it FAILs, because `TutorEstimate` does not exist yet.
- [ ] **Step 3: Implement** in `readiness_factors.py`:

```python
# A tutor's starting estimate, relative to a medium-difficulty marked question
# (1.0). v1's weight for the same source (services/readiness.py SOURCE_WEIGHTS),
# carried over by decision 14: worth having — a class with nothing marked shows
# a new tutor nothing — and worth the least, because it is the only input that
# is not a mark on a piece of work (PROD-8).
TUTOR_ESTIMATE_WEIGHT = 0.4


@dataclass(frozen=True)
class TutorEstimate:
    """The tutor's self-declared starting score for one topic (Evidence with
    source_type=tutor_estimate)."""

    pct: float  # 0..100
    occurred_at: datetime


def topic_mastery(
    questions: list[MarkedQuestion],
    now: datetime | None = None,
    estimate: TutorEstimate | None = None,
) -> FactorResult:
    """Decay-weighted average across difficulty tiers — succeeding on harder
    questions counts for more, so familiarity with easy questions alone
    doesn't read as mastery.

    A tutor's estimate joins as a prior that gives way. Time decay alone would
    not do that: the half-life discounts an estimate and a mark equally, so on
    a quiet topic a September guess would keep its full relative weight into
    May. Dividing its weight by one more than the marked questions makes each
    mark push it further out of the answer; it is never deleted, because the
    row is the record of what the score was built from (PROD-1)."""
    if not questions and estimate is None:
        return NO_DATA
    now = now or datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_sum = 0.0
    by_tier: dict[str, list[float]] = {}
    for q in questions:
        w = DIFFICULTY_WEIGHT.get(q.difficulty, 1.0) * _decay(_age_days(q.occurred_at, now))
        total_weight += w
        weighted_sum += w * q.pct
        by_tier.setdefault(q.difficulty or "unrated", []).append(q.pct)
    detail: dict = {
        "by_difficulty": {tier: round(sum(v) / len(v), 1) for tier, v in by_tier.items()}
    }
    if estimate is not None:
        w = (
            TUTOR_ESTIMATE_WEIGHT
            * _decay(_age_days(estimate.occurred_at, now))
            / (1 + len(questions))
        )
        total_weight += w
        weighted_sum += w * estimate.pct
        # The label every reader shows (PROD-8): how much of this score is the
        # tutor's own judgement rather than marked work.
        detail["tutor_estimate"] = {
            "pct": round(estimate.pct, 1),
            "share": round(w / total_weight, 2),
        }
    score = round(weighted_sum / total_weight, 1) if total_weight > 0 else None
    return FactorResult(
        score=score,
        # An estimate is never evidence of certainty: alone it is `low` (scored,
        # so the bar shows; below CONFIDENT, so it names no class weakness), and
        # beside marked work confidence comes from the marked work only.
        confidence=(
            _confidence_from_count(len(questions)) if questions else FactorConfidence.low
        ),
        evidence_count=len(questions) + (1 if estimate is not None else 0),
        detail=detail,
    )
```

- [ ] **Step 4: Gatherer** (`readiness_v2.py` `evaluate_subject_factors`). Before the topic loop, load every estimate in one query (`PERF-1`):

```python
    estimates = {
        e.topic_id: TutorEstimate(pct=e.score_pct, occurred_at=e.occurred_at)
        for e in (
            await session.scalars(
                select(Evidence).where(
                    Evidence.student_id == student_id,
                    Evidence.source_type == EvidenceSource.tutor_estimate,
                    Evidence.topic_id.in_([t.id for t in topics] or [0]),
                )
            )
        ).all()
    }
```

  In the loop, call `topic_mastery(questions, now, estimate=estimates.get(topic.id))` and set `mastery_by_topic[topic.id] = result.score if questions else None`, with the comment: "an estimate alone never claims mastery for coverage (PROD-8)". `seed_readiness` keeps one row per topic (`source_ref` upsert, `assessments.py:326-346`), so `.get` sees at most one.
- [ ] **Step 5: Label it everywhere it is shown.**
  - `schemas/readiness.py`: `TopicReadinessOut.tutor_estimate: bool = False`, with a `PROD-8` comment.
  - `_subject_from_snapshot`: `tutor_estimate="tutor_estimate" in (row.detail or {})`.
  - `reports.py`: `f"{t.topic_title} ({t.score:.0f}%{', includes tutor estimate' if t.tutor_estimate else ''})"` in both topic lists.
  - `prompts.py` READINESS: add the rule "- A Topic Mastery row whose detail carries `tutor_estimate` rests partly (see `share`) or wholly on the tutor's self-declared starting estimate, not marked work; when it drives the score, say so in the rationale." Change "each already computed from real evidence" to "each computed from the evidence and inputs shown". Bump `"readiness"` to `v3`.
  - Frontend `api/readiness.ts` `TopicReadiness`: `tutor_estimate: boolean`. In `ReadinessView.tsx`'s topic row, after the title, render `{t.tutor_estimate && <span className="text-xs text-ink-500">includes tutor estimate</span>}`.
  - Rewrite the `assessments.py:280-289` docstring paragraph: v2 Topic Mastery now reads the estimate as a decaying prior (decision 14). Observations and entered mocks remain Evidence-only under v2. Keep that half of the known gap and name it.
- [ ] **Step 6: End-to-end test** in `test_readiness_v2.py`:

```python
async def test_a_seed_estimate_scores_a_topic_with_no_marked_work(client, tutor, world, monkeypatch, fake_ai):
    resp = await client.post(
        f"/api/v1/students/{world['student_id']}/seed-readiness",
        json={"topics": [{"topic_id": world["topic1"], "score_pct": 40}]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        fake_ai(ReadinessSynthesis(score=40, weak_topics=[], rationale="seeded", recommended_revision="-")),
    )
    async with async_session() as session:
        await compute_readiness_v2(session, {"student_id": world["student_id"], "subject_id": world["subject_id"]})
    subject = (await client.get(
        f"/api/v1/readiness/students/{world['student_id']}", headers=tutor["headers"]
    )).json()["subjects"][0]
    topic = next(t for t in subject["topics"] if t["topic_id"] == world["topic1"])
    assert topic["score"] == 40.0 and topic["confidence"] == "low"
    assert topic["tutor_estimate"] is True
```

  Check the seed route's real prefix in `api/assessments.py`'s router before writing the URL. Add a frontend assertion in the existing `ReadinessView` test (or a new one) that "includes tutor estimate" renders when true.
- [ ] **Step 7: Run** the full gates and confirm they PASS. Regenerate the types.
- [ ] **Step 8: Discrimination checks.**
  - Drop `/ (1 + len(questions))` and confirm `test_the_estimate_gives_way_to_marked_questions_with_no_time_passing` fails.
  - Make estimate-only confidence `_confidence_from_count(1)` → `low`; that one still passes, so instead make it `medium` and confirm `test_an_estimate_alone_carries_the_topic_at_low_confidence` fails.
  - Remove `estimate=` in the gatherer and confirm the end-to-end test fails.
  - Restore all three.
- [ ] **Step 9: Commit** with `git add backend/app/services/readiness_factors.py backend/app/services/readiness_v2.py backend/app/services/prompts.py backend/app/services/readiness_summary_v2.py backend/app/services/reports.py backend/app/schemas/readiness.py backend/app/api/assessments.py backend/tests/test_readiness_factors.py backend/tests/test_readiness_v2.py backend/tests/test_report_facts.py frontend/src/api/readiness.ts frontend/src/components/ReadinessView.tsx frontend/src/test frontend/openapi.json frontend/src/api/schema.d.ts` and the message "Tutor estimates become a labelled, decaying prior in v2 (5.3a, decision 14)".

---

### Task 5: The demo seed produces v2 snapshots, with no AI call

**Implementer:** `ecc:tdd-guide`

**Files:**
- Modify: `backend/seed/demo.py:64,551-555`
- Test: new `backend/tests/test_demo_seed.py`

**Interfaces:**
- Produces: `seed.demo.write_demo_snapshot(session, student, subject_id, now)`. It runs the real Layer 1 (`evaluate_subject_factors`) and writes a `ready` snapshot whose score is Layer 1's own weighted reference (`_weighted_reference_score`). The grade comes from `predict_grade` through the org's boundaries (`PROD-6`). The rationale says plainly that no AI synthesis ran.
- Choice: **deterministic, never the AI**, even when a key is set. With no key the real job writes `failed` snapshots and the demo would show nothing (Verified facts). With a key it would spend money on every demo load. The reference score is the number the engine already clamps the AI to (`readiness_v2_ai.py:147-151`), so it is the engine's own answer, not an invented one. The seed is not product code, which is why the private helpers are imported here and nowhere else.
- v1 `recompute_student` stays in the demo (v1 still writes; 5.3b removes it).

- [ ] **Step 1: Test first.** `test_demo_seed.py` runs `seed.demo.main()` against the test database, with `get_settings().anthropic_api_key` unset or monkeypatched empty. It then asserts:
  - every `(demo student, subject)` with evidence has exactly one `ready` snapshot, with a non-None score for `demo-student@example.com`'s Chemistry;
  - no `ai_usage_events` row exists;
  - `build_summary_v2` for that student returns `engine == "v2"`.

  Also monkeypatch `app.services.readiness_v2_ai.structured_complete` to raise, which proves it is never called. Read `main()` first: if it opens `app.db.async_session` directly, the conftest StaticPool session factory is the same object, so this works. If `main()` also calls `seed.load_syllabus`, run that first the way `test_chapters.py:19` does.
- [ ] **Step 2: Run** and confirm it FAILs, because no snapshots exist.
- [ ] **Step 3: Implement:**

```python
async def write_demo_snapshot(session, student: User, subject_id: int, now: datetime) -> None:
    """A v2 snapshot for demo data without calling a model (QA-8 in spirit).

    Layer 1 runs for real; the score is Layer 1's own weighted reference — the
    value compute_readiness_v2 clamps any AI answer to within ±10 of — so the
    demo shows the engine's deterministic answer, labelled as exactly that."""
    subject = await session.get(Subject, subject_id)
    run_id = str(uuid.uuid4())
    rows = await evaluate_subject_factors(session, student.id, subject_id, run_id, now)
    weights = await _resolve_weight_dict(session, student.organization_id)
    reference = _weighted_reference_score(rows, weights)
    score = round(reference, 1) if reference is not None else None
    boundaries = await resolve_grade_boundaries(session, student.organization_id, subject)
    session.add(
        ReadinessSnapshot(
            evaluation_run_id=run_id,
            student_id=student.id,
            subject_id=subject_id,
            status=AiSynthesisStatus.ready,
            score=score,
            predicted_grade=predict_grade(score, boundaries) if score is not None and boundaries else None,
            weak_topics=[],
            rationale=(
                "Demo data: the weighted average of the factor scores. No AI synthesis ran."
                if score is not None
                else "No evidence yet for this subject."
            ),
            recommended_revision=None,
        )
    )
```

  At `:551-555`, after the v1 loop, call `write_demo_snapshot(session, student, subject.id, now)` for each student in each seeded subject, then `await session.commit()`.
- [ ] **Step 4: Run** the test and the full suite, and confirm they PASS.
- [ ] **Step 5: Discrimination check.** Swap the call for `compute_readiness_v2(session, {"student_id": ...})` and confirm the test fails, either on the raising `structured_complete` or on the `failed` status. Restore.
- [ ] **Step 6: Commit** with `git add backend/seed/demo.py backend/tests/test_demo_seed.py` and the message "Demo seed writes v2 snapshots without an AI call (5.3a)".

---

## After the tasks (parent, not implementer)

1. **Two reviewers per task**, per the budget: `ecc:python-reviewer` (or `ecc:react-reviewer` for the frontend half of Tasks 3–4) plus `ecc:silent-failure-hunter`. Name the targets and rules in each prompt:
   - `class_readiness.py` (window query, `_mean`, the factor split): `PERF-1`, `PROD-2`, `SEC-7`, `SEC-8`.
   - `readiness_summary_v2.py` `build_summary_v2` (the fallback-behind-branch swap), `readiness_factors.py` `topic_mastery`: `BE-4`, `PROD-8`.
   - `prompts.py:387`: `AI-7`. `schemas/*` and generated types: `FE-4`.
2. **Parent reads the whole diff.** Look hardest at:
   - every rewritten comment (`CODE-12`, `CODE-13`);
   - that `ClassLearnerRow` grades equal the profile's grade for the same learner;
   - that `api/analytics.py:88-127` is byte-identical.
3. **Phase sweep** (one `ecc:code-reviewer` on the integrated branch). The contracts to check: 5.1's `homework_performance.detail` keys ↔ Task 3's completion read; Task 1's `CONFIDENT` ↔ Task 3's class weak topics ↔ 5.6's future threshold; Task 2's no-snapshot shape ↔ 5.3b's fallback deletion.
4. Push, open the PR, read the review bots' inline comments, fix, merge (memory `merge-after-fixing-review-bots`).
5. **After the deploy is green, the owner runs `python -m seed.recompute_readiness` (runbook R9).** The class view now shows a learner as scored only once they have a ready v2 snapshot, and Task 4 changes Topic Mastery for every seeded student. This machine has no production access.
6. **Local docs** (`GOV-1`):
   - §01 Known Gaps: the class view, Group Analytics, CRM and reports are on v2. RISK-5 is narrowed to "v1 fallback for subjects with no v2 snapshot", which closes in 5.3b.
   - §09: the READINESS prompt is `v3`.
   - `risk-register.md`: the RISK-5 status.
   - The `CLAUDE.md` Readiness bullet: `analytics.py`, `reports.py` and `student_crm.py` no longer read v1.

---

## Pre-flight conflict table

| Where | What collides | Resolution in this plan |
|---|---|---|
| `readiness_factors.py:21` → `readiness.py` | v2 maths imports v1 | Task 1 moves `HALF_LIFE_DAYS`/`_decay`/`_age_days` into `readiness_factors`; v1 re-imports |
| `readiness_summary.py:38` `CONFIDENT` | Built on the v1 enum that 5.3b deletes | New `readiness_shared.CONFIDENT` on `FactorConfidence`; v1 keeps a local copy until Task 3 frees its importers |
| `readiness_summary.py:62-67` and `:162-167` | The same comment twice | Keep one, beside `v1_score_points` |
| `test_readiness_cutover.py:117-135` | Assert `engine=="v1"` with no v1 data | Rewritten in Task 2; not listed in the map |
| `test_new_capabilities.py:147-196`, `test_readiness_api.py:77-123` | Only pass via the v1 fallback | Fallback kept behind the no-snapshot branch; 5.3b deletes both |
| `test_readiness_api.py:243-271` | Group Analytics fed by a mock through v1 | Ported to a v2 snapshot in Task 3 |
| `test_groups.py` topic-weight and confidence tests | Pin v1 formulas decision 13 replaces | Deleted in Task 3 and replaced by mean / latest-run tests |
| `test_coverage.py:101-105` | "low confidence does not count" is a v1 rule | Becomes "a no-evidence snapshot does not count" |
| `api/readiness.py:120-121` | Fabricated `0.0`/`"none"` | `score: float \| None`, `"no_data"`; frontend guards `null` |
| `api/groups.py:241` | Router calls the `group_analytics` router | Pre-existing; the response shape is unchanged, so `class_brief` still works; not widened |
| `api/assessments.py:280-289` | Docstring says v2 ignores the estimate | Rewritten in Task 4 |
| `today.py:187-193`, `api/today.py:1-12`, `readiness_summary_v2.py:1-20` | Docstrings describe v1 reads or the old fallback | Rewritten in the task that changes the behaviour |
| `frontend/src/api/today.ts`, `api/readiness.ts` | Hand-written interfaces (`FE-4`) | Fields added in place; aliasing would widen unions; noted for 5.3b |
| `services/readiness.py` `SOURCE_WEIGHTS` | `PROD-10` names a table in a module 5.3b deletes | Out of 5.3a scope; 5.3b must re-home or supersede `PROD-10` |
| `readiness_v2.py:237-245` coverage `practiced` | Counts a `tutor_estimate` Evidence row as practised | Pre-existing, untouched; see Questions |
| Migrations | none | Head stays `0054`; no schema change |

---

## Owner answers (2026-09-23)

1. **The v1 fallback stays until 5.3b**, as planned.
2. **Coverage counts marked work only.** `tutor_estimate` is excluded from `practiced` (Task 4).
3. **"Includes tutor estimate" shows everywhere the score is shown**: tutor, student and parent views, and reports.
