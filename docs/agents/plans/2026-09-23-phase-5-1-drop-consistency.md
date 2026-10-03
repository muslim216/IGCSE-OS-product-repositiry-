# Phase 5.1 — Drop consistency; homework is accuracy only — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Readiness Engine stops scoring `consistency`, homework performance becomes marked accuracy alone, and homework completion appears on the tutor's student profile as a stated fact — never inside a score.

**Architecture:** Three layers, three tasks. (1) Pure factor maths in `services/readiness_factors.py` (`BE-4`). (2) The engine, weights, prompt and migration that stop producing `consistency`. (3) A read-only completion fact on the v2 readiness summary and the profile page. The `ReadinessFactor.consistency` **enum member stays, retired** — see "Verified facts".

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async, Alembic, React 18 + TanStack Query.

**Spec:** `docs/agents/phase-5-spec.md` — section "5.1" and settled decision 5 (punctuality invisible until 8.2). Plan doc: `docs/avora-new-state-august-16.md` L1284 (AV-30, AV-32).

---

## Global Constraints

- **Branch** `feat/phase-5-1-drop-consistency` off the latest `claude/igcse-os-planning-q8be0t`. One PR; tasks are commits.
- **`docs/**` and `CLAUDE.md` are never committed.** Stage by path: `git add backend/app backend/tests backend/alembic frontend/src frontend/openapi.json`.
- **Migrations hand-written, numbered, working `downgrade()`**, up → down → up (`DB-15`, `DB-16`). Altering an existing table uses `batch_alter_table(..., naming_convention=NAMING)` with `NAMING` copied verbatim from `0051_mistake_categories.py:24-27` (`DB-17`). No migration imports app code.
- **Never render a missing measurement as 0** (`PROD-2`, `UX-19`). A factor without evidence is omitted.
- **Prompts live in `services/prompts.py` with a `version` bumped on meaningful change** (`AI-6`, `AI-7`).
- **Response-schema change → regenerate types in the same PR** (`FE-4`): from `backend/`, `python -c "import json;from app.main import app;print(json.dumps(app.openapi(),indent=2))" > ../frontend/openapi.json`; from `frontend/`, `npm run generate:api`.
- **Semantic token classes** only in new frontend markup (`UX-2`): `text-ink-500`, `bg-surface`, `border-line`.
- **Comments explain why; never delete an existing comment** without confirming its reasoning is gone (`CODE-12`, `CODE-13`).
- **Local gate before push.** `backend/`: `.venv/bin/python -m pytest > /tmp/p.txt 2>&1; echo $?`, `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/python -m mypy app/services app/schemas`. `frontend/`: `npm test`, `npm run lint`, `npm run build`, `npx prettier --check src/`. **Never pipe pytest to `tail`.**

### Verified facts — do not re-derive

- **`ReadinessFactor.consistency` must NOT be removed from the enum.** `api/readiness_v2.py:46-52` loads *every* `FactorEvaluation` row of a snapshot's run with no factor filter, and production holds historical runs containing `factor="consistency"`. The column is a non-native `Enum` (`DB-5`, no CHECK constraint — `0016_readiness_v2_schema.py:137-148`), so SQLAlchemy would raise `LookupError` loading those rows. Keep the member with a comment: retired by AV-30, never written, kept so historical rows load. `factor_evaluations` is append-only by design (`models/readiness_v2.py:422-425`) — do not delete old rows.
- Every other `consistency` reference is live code to delete: `readiness_factors.py:280-310` (`ConsistencyPoint`, `consistency()`), `readiness_v2.py:52` (import), `:199-209` (`_consistency_points`), `:447-456` (the call), `readiness_v2_ai.py:138` (`FACTOR_WEIGHT_ATTR`), `models/readiness_v2.py:401` (`weight_consistency`), `schemas/readiness.py:210,221`, `api/readiness_weights.py:26`, `frontend/src/tutor/PreferencesPage.tsx:16,54-55`, `frontend/src/api/readiness.ts:193`.
- **"Seven factors" text** to change to six: `prompts.py:217`, `readiness_v2_ai.py:144,178`, `api/readiness_weights.py:1`, `PreferencesPage.tsx:20,121`. Prompt registry `prompts.py:383` — `"readiness"` is `v1` → `v2`.
- **`HomeworkPoint.pct is None` conflates two things today** (`readiness_v2.py:174-176`): not submitted, *and* submitted but not yet settled (awaiting marking). So today's `completion_rate` counts a student who handed work in yesterday as not having done it. A completion *fact* must not say that. Task 1 splits the point into `submitted: bool` and `pct: float | None`.
- **The no-marks branch fabricates a zero** (`readiness_factors.py:135-143`): with nothing settled, `completion_rate` is 0 and the factor scores `0.0` with a real confidence — a `PROD-2` violation this task removes.
- `on_time_rate` in the homework `detail` is exposed through `FactorEvaluationOut.detail` (`api/readiness_v2.py:84-91`). Decision 5 makes punctuality invisible until 8.2, so it leaves `detail` and `HomeworkPoint.on_time` is deleted. 8.2 re-derives it from `submitted_at`/`due_at`.
- **The class view is built on v1 tables** (`services/today.py:220-265` reads `TopicReadiness`/`ReadinessHistory`). Completion on the class view therefore ships with **5.3**, which repoints that code to v2 — building it here would be rewritten a PR later. The profile reads v2 via `services/readiness_summary_v2.py:_subject_from_snapshot` (`:89`), so it ships here.
- `readiness_weights` has `server_default="1.0"` on `weight_consistency` (`0016:123`) — the downgrade re-adds it with the same default.

---

### Task 1: Homework factor is accuracy only; consistency maths deleted

**Files:**
- Modify: `backend/app/services/readiness_factors.py:118-167` (homework), `:280-310` (delete consistency)
- Modify: `backend/app/services/readiness_v2.py:169-196` (`_homework_points` builds the new point shape)
- Test: `backend/tests/test_readiness_factors.py:81-120` (homework), `:181-205` (delete consistency tests), imports `:7-22`

**Interfaces:**
- Produces: `HomeworkPoint(submitted: bool, pct: float | None)` — `pct` is None unless the submission is settled. `homework_performance(points) -> FactorResult` where `score`/`confidence`/`evidence_count` derive from **settled** points only, and `detail = {"completion_rate": float, "assignment_count": int, "submitted_count": int, "marked_count": int, "accuracy": float | None}`.

- [ ] **Step 1: Replace the homework tests** (`test_readiness_factors.py:81-120`) with:

```python
def test_homework_score_is_accuracy_over_marked_work_only():
    points = [
        HomeworkPoint(submitted=True, pct=80),
        HomeworkPoint(submitted=True, pct=100),
        HomeworkPoint(submitted=False, pct=None),
    ]
    result = homework_performance(points)
    assert result.score == 90.0  # completion no longer blended in (AV-32)
    assert result.evidence_count == 2  # marked pieces, not assignments
    assert result.detail["completion_rate"] == 0.67
    assert result.detail["assignment_count"] == 3
    assert result.detail["marked_count"] == 2


def test_homework_nothing_marked_is_no_data_but_keeps_completion():
    # Handed in, awaiting marking: no accuracy exists yet — never a 0 (PROD-2).
    points = [HomeworkPoint(submitted=True, pct=None), HomeworkPoint(submitted=False, pct=None)]
    result = homework_performance(points)
    assert result.score is None
    assert result.confidence == FactorConfidence.no_data
    assert result.detail["completion_rate"] == 0.5  # submitted counts as done
    assert result.detail["submitted_count"] == 1


def test_homework_submitted_but_unmarked_counts_as_completed():
    points = [HomeworkPoint(submitted=True, pct=None), HomeworkPoint(submitted=True, pct=70)]
    assert homework_performance(points).detail["completion_rate"] == 1.0


def test_homework_detail_carries_no_punctuality():
    # Decision 5: punctuality is invisible until the weekly send (8.2).
    result = homework_performance([HomeworkPoint(submitted=True, pct=50)])
    assert "on_time_rate" not in result.detail


def test_homework_no_assignments_is_no_data():
    assert homework_performance([]) is NO_DATA
```

Delete the consistency tests (`:181-205`) and the `ConsistencyPoint`/`consistency` imports.

- [ ] **Step 2: Run, watch them fail.** `cd backend && .venv/bin/python -m pytest tests/test_readiness_factors.py -q` → FAIL (`HomeworkPoint` has no `submitted`).

- [ ] **Step 3: Implement** in `readiness_factors.py`, replacing `HomeworkPoint` and `homework_performance`:

```python
@dataclass(frozen=True)
class HomeworkPoint:
    submitted: bool  # handed in — whether or not marking has finished
    pct: float | None  # None until the submission is settled


def homework_performance(points: list[HomeworkPoint]) -> FactorResult:
    if not points:
        return NO_DATA
    # Narrowed once so `pct` is non-optional below — a second `is not None`
    # inside the average would divide a shrinking numerator by a fixed
    # denominator, silently scoring a missing measurement as 0 (PROD-2).
    marked = [p.pct for p in points if p.pct is not None]
    submitted_count = sum(1 for p in points if p.submitted)
    # Completion is a fact shown beside readiness, never inside the score
    # (AV-32): acing half the work and skipping the rest is reported as
    # exactly that, not blended into one number that hides which it was.
    detail = {
        "completion_rate": round(submitted_count / len(points), 2),
        "assignment_count": len(points),
        "submitted_count": submitted_count,
        "marked_count": len(marked),
        "accuracy": None,
    }
    if not marked:
        # Nothing marked yet means no accuracy exists — the factor is omitted,
        # not scored 0, while the completion fact above still stands.
        return FactorResult(
            score=None, confidence=FactorConfidence.no_data, evidence_count=0, detail=detail
        )
    accuracy = sum(marked) / len(marked)
    detail["accuracy"] = round(accuracy, 1)
    return FactorResult(
        score=round(accuracy, 1),
        confidence=_confidence_from_count(len(marked)),
        evidence_count=len(marked),
        detail=detail,
    )
```

Delete `ConsistencyPoint` and `consistency()` (`:280-310`) and its section header. Confirm `FactorResult` accepts `score=None` by reading its definition.

- [ ] **Step 4: Update the point builder** `readiness_v2.py:_homework_points` (`:169-196`): unsettled or missing → `HomeworkPoint(submitted=submission is not None and submission.submitted_at is not None, pct=None)`; settled → `HomeworkPoint(submitted=True, pct=pct)`. Delete the `on_time` computation. Leave the `total_max == 0 → 0.0` line alone but note it in the PR as pre-existing (an assignment with no questions is a separate defect).

- [ ] **Step 5: Run.** `.venv/bin/python -m pytest tests/test_readiness_factors.py -q` → PASS.

- [ ] **Step 6: Discrimination check.** Temporarily restore `score = accuracy * 0.7 + completion_rate * 100 * 0.3`; confirm `test_homework_score_is_accuracy_over_marked_work_only` fails; restore.

- [ ] **Step 7: Commit** `git add backend/app/services/readiness_factors.py backend/app/services/readiness_v2.py backend/tests/test_readiness_factors.py` — "Homework performance is marked accuracy only (5.1, AV-32)".

---

### Task 2: The engine stops producing consistency

**Files:**
- Modify: `backend/app/services/readiness_v2.py:52,199-209,447-456`
- Modify: `backend/app/services/readiness_v2_ai.py:138,144,178`
- Modify: `backend/app/models/readiness_v2.py:401` (drop column), `:412` (retire member, comment)
- Modify: `backend/app/schemas/readiness.py:210,221`; `backend/app/api/readiness_weights.py:1,26`
- Modify: `backend/app/services/prompts.py:217` ("seven" → "six"), `:383` (`v1` → `v2`)
- Create: `backend/alembic/versions/0054_drop_consistency_weight.py`
- Test: `backend/tests/test_readiness_v2.py:221-223`, `backend/tests/test_readiness_cutover.py:244-321`
- Regenerate: `frontend/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: Task 1's `HomeworkPoint`/`homework_performance`.
- Produces: an evaluation run writes exactly six factor kinds; `ReadinessWeightsOut`/`ReadinessWeightsUpdate` have no `weight_consistency`.

- [ ] **Step 1: Tests first.**
  - `test_readiness_v2.py:221-223`: replace the `cons` assertions with `assert not any(f == ReadinessFactor.consistency for f, _ in by_factor)`. Also assert `hw.detail["submitted_count"] == 1` beside the homework assertions (`:205-207`).
  - Add `test_historical_consistency_rows_still_load` to `test_readiness_v2.py`: insert a `FactorEvaluation(factor=ReadinessFactor.consistency, …)` row plus a `ReadinessSnapshot` for its run, then GET the v2 student route (read the prefix in `api/readiness_v2.py`) as the tutor and assert `200`.
  - `test_readiness_cutover.py:244-321`: remove every `weight_consistency` key/assertion; add one test that `PUT /readiness/weights` with an extra `weight_consistency` key does not return it.
- [ ] **Step 2: Run** those two files → FAIL.
- [ ] **Step 3: Implement.** Delete the import, `_consistency_points`, the call block, the `FACTOR_WEIGHT_ATTR` entry, the schema fields, the `WEIGHT_FIELDS` entry, the model column. Retire the enum member:

```python
    # Retired by AV-30 (task 5.1): never written by the engine any more. Kept
    # only because factor_evaluations is append-only and holds historical runs
    # with this value — removing the member makes SQLAlchemy raise LookupError
    # loading them (non-native enum, DB-5). Do not reuse the name.
    consistency = "consistency"
```

  Fix the "seven" wording at the listed lines. Bump `"readiness"` to `v2` in the registry.
- [ ] **Step 4: Migration `0054_drop_consistency_weight.py`**, `revision = "0054"`, `down_revision = "0053"`:

```python
def upgrade() -> None:
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.drop_column("weight_consistency")


def downgrade() -> None:
    # The tutor's old weight is not restored — the column comes back at its
    # original default, which is all 0016 ever guaranteed.
    with op.batch_alter_table("readiness_weights", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("weight_consistency", sa.Float(), nullable=False, server_default="1.0")
        )
```

  Verify on SQLite from `backend/`: `DATABASE_URL=sqlite+aiosqlite:///./m.db .venv/bin/alembic upgrade head`, then `downgrade 0053`, then `upgrade head`; delete `m.db`. Postgres is CI's job.
- [ ] **Step 5: Run** the full backend suite → PASS. Regenerate `openapi.json` and `schema.d.ts`.
- [ ] **Step 6: Discrimination check** — re-add the consistency call block; confirm the "never writes the retired factor" assertion fails; restore. Remove the enum member temporarily; confirm `test_historical_consistency_rows_still_load` fails; restore.
- [ ] **Step 7: Commit** — "The engine stops scoring consistency (5.1, AV-30)".

---

### Task 3: Completion is a fact on the profile; the weights screen loses consistency

**Files:**
- Modify: `backend/app/schemas/readiness.py:22+` (`SubjectReadiness`)
- Modify: `backend/app/services/readiness_summary_v2.py:89-190` (`_subject_from_snapshot`)
- Modify: `frontend/src/tutor/PreferencesPage.tsx:16,20,54-55,121`, `frontend/src/api/readiness.ts:193`
- Modify: `frontend/src/tutor/StudentDetailPage.tsx` (the per-subject card rendered at `:94`)
- Test: the backend file that covers `/readiness/students/{id}` on the v2 path (grep `build_summary_v2` in `backend/tests/`); a new `frontend/src/test/StudentHomeworkCompletion.test.tsx` owning its own fetch stub, per this repo's convention

**Interfaces:**
- Consumes: Task 1's `detail` keys `assignment_count`, `submitted_count`.
- Produces: `SubjectReadiness.homework_assignment_count: int | None = None` and `homework_submitted_count: int | None = None` — both `None` when the snapshot's run has no homework row or the subject fell back to v1 (5.3 removes that fallback). Counts, not a rate: "4 of 5 handed in" carries its own denominator (`PROD-1`).

- [ ] **Step 1: Backend test** — a student with 2 published assignments in a subject, one submitted and unmarked: after a v2 run, `GET /api/v1/readiness/students/{id}` returns `homework_assignment_count == 2`, `homework_submitted_count == 1`. A student with no assignments returns both `None`, not `0`.
- [ ] **Step 2: Implement.** In `_subject_from_snapshot`, extend the existing query at `:94-101` to fetch both `topic_mastery` (topic rows) and `homework_performance` (`topic_id IS NULL`) in one statement, then split by `row.factor` — no second round-trip. Read the two counts from `detail`; leave `None` when absent.
- [ ] **Step 3: Regenerate types** (`FE-4`).
- [ ] **Step 4: Frontend.** In the profile's per-subject card: when both counts are non-null, render `Homework: {submitted} of {assignments} handed in` in `text-ink-500`, beside readiness, not inside the score block; render nothing when null (`PROD-2`). Remove the consistency control and "seven" copy from `PreferencesPage.tsx`, and `weight_consistency` from `api/readiness.ts:193` (if that type is hand-written, alias the generated schema instead, `FE-4`).
- [ ] **Step 5: Frontend test** — stub counts `5`/`4`, assert "4 of 5 handed in" renders; stub nulls, assert no "handed in" text.
- [ ] **Step 6: Full gate** (Global Constraints). Discrimination: make the backend return `0` instead of `None` for no assignments; confirm the null test fails; restore.
- [ ] **Step 7: Commit** — "Homework completion is shown as a fact, never a score (5.1, AV-32)".

---

## After the tasks (parent, not implementer)

1. Two reviewers in parallel — `ecc:python-reviewer` (backend) and `ecc:silent-failure-hunter`, prompts naming the `file:line` targets above and `PROD-2`, `DB-5/6`, `DB-16/17`, `AI-7`, `FE-4`.
2. Parent reads the whole diff.
3. Push, open PR, read the review bots' inline comments, fix, merge.
4. After deploy is green: `python -m seed.recompute_readiness` (runbook R9) — the homework maths changed for every student. Owner runs it; this machine has no production access.
5. Local docs (`GOV-1`): §01/§09 factor list → six and the homework definition.
