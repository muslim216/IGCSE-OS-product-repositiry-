# Phase 4.0 — Mistake join and the fabricated 100 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Mistake Analysis readiness factor count every kind of work, and stop it reporting a confident 100.0 for students whose work was never examined for mistakes.

**Architecture:** Two defects, one PR, because they are the same measurement. The factor's queries currently inner-join `Assignment`, which silently drops past-paper and mock submissions from both the mistake list and the denominator; they are rewritten to join `AssessableWork`, which every kind of work has. The pure function's denominator changes from "questions marked" to "questions examined for mistakes", gated on a new `submissions.mistakes_analysed_at` column that nothing sets yet — so the factor is correctly omitted for everyone until 4.2 ships.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, Alembic, pytest (SQLite in-memory).

**Spec:** `docs/agents/phase-4-spec.md` — section "PR 4.0". Read it before Task 1.

## Global Constraints

- `api/ → services/ → models/`. A lower layer never imports a higher one (`BE-1`).
- Decision math stays pure — dataclasses in, values out, no session (`BE-4`, `CODE-3`).
- Never render a missing measurement as `0` or `0%`; a factor without evidence is omitted (`PROD-2`).
- Migrations are hand-written, sequentially numbered, `down_revision` chained (`DB-15`).
- Every migration has a working `downgrade()` (`DB-16`).
- Altering a table uses `batch_alter_table(..., naming_convention=NAMING)` (`DB-17`).
- **Reflect constraint names, never assume them** (`RISK-3` — this has bitten three times).
- Comments explain *why*. Never delete an existing one without confirming its reasoning no longer holds (`CODE-12`, `CODE-13`).
- `docs/**` and `CLAUDE.md` are updated but **never committed**. Stage code by path.
- Docker is unavailable. Verify migrations with
  `DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic upgrade head` and **check the exit code** — never pipe to `tail` and read the output.

## File Structure

- `backend/alembic/versions/0050_submission_mistakes_analysed_at.py` — **create**. One nullable column. Nothing else.
- `backend/app/models/homework.py` — **modify**. Declare the column on `Submission` so the test schema matches production (`BE-3`).
- `backend/app/services/readiness_factors.py:244-264` — **modify**. Pure function; denominator becomes analysed questions.
- `backend/app/services/readiness_v2.py:275-308` — **modify**. Both queries join `AssessableWork`; drop `Assignment` and `Group` from this function.
- `backend/tests/test_readiness_factors.py` — **modify**. Pure-function cases.
- `backend/tests/test_readiness_v2.py` — **modify**. Cross-kind cases.

---

### Task 1: The `mistakes_analysed_at` column

**Files:**
- Create: `backend/alembic/versions/0050_submission_mistakes_analysed_at.py`
- Modify: `backend/app/models/homework.py` (the `Submission` class, near `finalized_at`)

**Interfaces:**
- Consumes: nothing.
- Produces: `Submission.mistakes_analysed_at: Mapped[datetime | None]`. Task 3 filters on it; PR 4.2 sets it.

- [ ] **Step 1: Read the previous migration first**

Run: `sed -n '1,40p' backend/alembic/versions/0049_submission_drops_the_three_keys.py`

Copy its revision-id style and its `NAMING` dict **verbatim** into the new file. Do not retype either from memory — the naming convention is what `DB-17` turns on, and a wrong one is a `RISK-3` failure that SQLite will hide from you.

- [ ] **Step 2: Add the column to the model**

In `backend/app/models/homework.py`, inside `class Submission`, directly after `finalized_at`:

```python
    # Set by the tag_mistakes job (4.2) when a submission has been examined
    # for mistakes. This is what separates "no mistakes were found" from
    # "nobody has looked yet" — without it the Mistake Analysis factor scored
    # a confident 100.0 for every student, because an empty mistakes table
    # looks exactly like a clean record (PROD-2).
    mistakes_analysed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Verify `DateTime` is already imported in that file; add it to the `sqlalchemy` import line if not.

- [ ] **Step 3: Write the migration**

```python
"""submissions gain mistakes_analysed_at

Revision ID: 0050
Revises: 0049
"""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

# Copied verbatim from 0049 — see DB-17.
NAMING = {...}


def upgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.add_column(
            sa.Column("mistakes_analysed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("submissions", naming_convention=NAMING) as batch:
        batch.drop_column("mistakes_analysed_at")
```

Replace `NAMING = {...}` with the real dict from Step 1. Match `0049`'s revision-id style exactly — if it uses `revision: str = "0049"`, use that form.

- [ ] **Step 4: Verify the migration up, down, and up again**

```bash
cd backend
rm -f /tmp/x.db
DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic upgrade head; echo "up: $?"
DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic downgrade 0049; echo "down: $?"
DATABASE_URL="sqlite+aiosqlite:////tmp/x.db" .venv/bin/alembic upgrade head; echo "up: $?"
```

Expected: `up: 0`, `down: 0`, `up: 0`. **Read the exit codes.** A non-zero code with plausible-looking output above it is the exact failure mode `RISK-3` describes.

- [ ] **Step 5: Run the suite to confirm nothing broke**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS, same count as on the branch point.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/homework.py backend/alembic/versions/0050_submission_mistakes_analysed_at.py
git commit -m "Submissions record when they were examined for mistakes"
```

---

### Task 2: The denominator becomes analysed work

**Files:**
- Modify: `backend/app/services/readiness_factors.py:244-264`
- Test: `backend/tests/test_readiness_factors.py`

**Interfaces:**
- Consumes: `MistakePoint` (unchanged), `NO_DATA`, `_decay`, `_age_days`, `_confidence_from_count` — all already in this module.
- Produces: `mistake_analysis(mistakes: list[MistakePoint], analysed_questions: int, now: datetime | None = None) -> FactorResult`. Task 3 is its only caller.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_readiness_factors.py`:

```python
def test_mistake_analysis_is_no_data_when_nothing_was_analysed():
    # Marked work that nobody examined for mistakes is not a clean record.
    assert mistake_analysis([], 0) is NO_DATA


def test_mistake_analysis_scores_a_clean_record_when_work_was_analysed():
    result = mistake_analysis([], 12)
    assert result is not NO_DATA
    assert result.score == 100.0
    assert result.detail["analysed_questions"] == 12
```

Check the import line at the top of that file already names `mistake_analysis` and `NO_DATA`; add them if not.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_readiness_factors.py -k mistake_analysis -v`
Expected: FAIL — `detail` has no key `analysed_questions` (the `no_data` case passes already, for the wrong reason: the parameter is merely named differently).

- [ ] **Step 3: Rewrite the function**

Replace `mistake_analysis` in `backend/app/services/readiness_factors.py` with:

```python
def mistake_analysis(
    mistakes: list[MistakePoint], analysed_questions: int, now: datetime | None = None
) -> FactorResult:
    """Fewer, less severe, less-recent mistakes relative to the volume of work
    **examined for mistakes** -> a higher score.

    The denominator is analysed questions, not marked questions, and that
    distinction is the whole point. An empty mistakes table is indistinguishable
    from a flawless student, so counting every marked question here scored a
    confident 100.0 for everyone and fed it into a weighted factor (PROD-2).
    A question is only counted once something has actually looked at it —
    `submissions.mistakes_analysed_at`, set by the tag_mistakes job.

    analysed_questions=0 is "no data". Zero mistakes across analysed work is a
    clean record and scores 100.0, which is a measurement rather than a guess.
    """
    if analysed_questions <= 0:
        return NO_DATA
    now = now or datetime.now(timezone.utc)
    penalty = sum(m.severity * _decay(_age_days(m.occurred_at, now)) for m in mistakes)
    rate = penalty / analysed_questions
    score = max(0.0, 100.0 - rate * 40.0)
    by_category: dict[str, int] = {}
    for m in mistakes:
        by_category[m.category] = by_category.get(m.category, 0) + 1
    return FactorResult(
        score=round(score, 1),
        confidence=_confidence_from_count(analysed_questions, medium_at=5, high_at=15),
        evidence_count=len(mistakes),
        detail={"by_category": by_category, "analysed_questions": analysed_questions},
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && .venv/bin/python -m pytest tests/test_readiness_factors.py -k mistake_analysis -v`
Expected: PASS.

- [ ] **Step 5: Find every other caller and reader of the old names**

```bash
cd backend && grep -rn "mistake_analysis\|total_questions" app/ tests/ frontend/ 2>/dev/null
```

`total_questions` also appears in unrelated factors — only change the ones inside the Mistake Analysis path. If the frontend reads `detail.total_questions` for this factor, update it and regenerate the API types in this PR (`FE-4`, `API-15`). If it does not, note that in the PR body.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/readiness_factors.py backend/tests/test_readiness_factors.py
git commit -m "Mistake Analysis measures work that was actually examined"
```

---

### Task 3: Count every kind of work, not just homework

**Files:**
- Modify: `backend/app/services/readiness_v2.py:275-308` and its import block at lines 18-38
- Test: `backend/tests/test_readiness_v2.py`

**Interfaces:**
- Consumes: `Submission.mistakes_analysed_at` (Task 1), `mistake_analysis(..., analysed_questions, ...)` (Task 2).
- Produces: `_mistake_points_and_analysed(session, student_id, subject_id) -> tuple[list[MistakePoint], int]` — renamed from `_mistake_points_and_total`. Update its call site inside `evaluate_subject_factors`.

- [ ] **Step 1: Check one assumption before writing code**

The old query took the subject from `Group.subject_id`; the new one takes it from `AssessableWork.subject_id`. Confirm those agree for homework:

```bash
cd backend && grep -n "subject_id" app/services/work.py app/api/assignments.py | head -20
```

If `create_work` sets `subject_id` from the group, they agree and this is a pure widening. If they can differ, **stop and report it** — that is a separate defect and changes homework's numbers too.

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_readiness_v2.py`. Build a **mock** submission (not an assignment) with a settled status, `mistakes_analysed_at` set, one `QuestionMark` and one `Mistake`:

```python
async def test_mistake_factor_counts_mocks_and_past_papers(session):
    """A mock's marked questions reach both the mistake list and the
    denominator. They did not before: both queries inner-joined Assignment,
    whose work_id is unique, so every non-homework submission was dropped in
    silence (API-20)."""
    student_id, subject_id, mark = await _mock_submission_with_mistake(session)

    points, analysed = await _mistake_points_and_analysed(session, student_id, subject_id)

    assert analysed == 1
    assert len(points) == 1
```

Write `_mock_submission_with_mistake` as a local helper in the test file, building the mock through `services.work.create_work` — it is the only sanctioned creation path (Known Gap in `services/work.py`). Mirror the existing setup at `tests/test_readiness_v2.py:100-131`, which builds the homework equivalent, and set `mistakes_analysed_at=NOW` on the submission.

- [ ] **Step 3: Run it to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_readiness_v2.py -k mocks_and_past_papers -v`
Expected: FAIL — `assert 0 == 1`. That zero is the live defect.

- [ ] **Step 4: Rewrite the function**

Replace `_mistake_points_and_total` with:

```python
async def _mistake_points_and_analysed(
    session: AsyncSession, student_id: int, subject_id: int
) -> tuple[list[MistakePoint], int]:
    """Mistakes and the count of questions examined for them, across every kind
    of work.

    Joins AssessableWork, not Assignment. Both queries here used to inner-join
    Assignment for the subject, and Assignment.work_id is unique — so past
    paper and mock submissions were dropped from the mistake list *and* the
    denominator, with nothing to show for it (API-20). One parent row carries
    the subject for all three kinds, so there is no arm to forget.
    """
    analysed_questions = (
        await session.scalar(
            select(func.count(QuestionMark.id))
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .join(AssessableWork, AssessableWork.id == Submission.work_id)
            .where(
                Submission.student_id == student_id,
                AssessableWork.subject_id == subject_id,
                Submission.status.in_(SETTLED_STATUSES),
                Submission.mistakes_analysed_at.is_not(None),
            )
        )
    ) or 0
    mistakes = (
        (
            await session.execute(
                select(Mistake)
                .join(QuestionMark, QuestionMark.id == Mistake.question_mark_id)
                .join(Submission, Submission.id == QuestionMark.submission_id)
                .join(AssessableWork, AssessableWork.id == Submission.work_id)
                .where(
                    Mistake.student_id == student_id,
                    AssessableWork.subject_id == subject_id,
                )
            )
        )
        .scalars()
        .all()
    )
    points = [
        MistakePoint(category=m.category.value, severity=m.severity, occurred_at=m.created_at)
        for m in mistakes
    ]
    return points, analysed_questions
```

Add `AssessableWork` to the `from app.models import (...)` block at the top. Remove `Assignment` and `Group` **only if** no other function in the file still uses them — check first with `grep -n "Assignment\|Group" app/services/readiness_v2.py`.

- [ ] **Step 5: Update the call site**

Inside `evaluate_subject_factors`, rename the call and its variables to match. The value now feeds `mistake_analysis(points, analysed_questions)`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/test_readiness_v2.py -v
```
Expected: PASS, including the pre-existing `test_evaluate_subject_factors_end_to_end` and `test_auto_finalized_work_counts_in_every_factor`. Those two construct `Mistake` rows directly (`tests/test_readiness_v2.py:125,351`) — **they will now need `mistakes_analysed_at` set on their submissions**, or the factor reads `NO_DATA` and their assertions change. Set the field; do not weaken the assertions.

- [ ] **Step 7: Add the past-paper case**

Same as Step 2 with a past paper instead of a mock, via `make_past_paper` in `tests/factories.py:98`. Both kinds, because one arm passing does not prove the other.

- [ ] **Step 8: Full suite and linters**

```bash
cd backend && .venv/bin/python -m pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/readiness_v2.py backend/tests/test_readiness_v2.py
git commit -m "Mistakes count on every kind of work, not only homework"
```

---

### Task 4: Documentation, review, PR

**Files:**
- Modify: `docs/governance/risk-register.md`, `docs/volume-1-product-and-ux/01-product-architecture.md` (Known Gaps), `docs/avora-new-state-august-16.md:87-89` — **all left uncommitted**.

- [ ] **Step 1: Update the constitution (`GOV-1`, `CODE-21`)**

The fabricated-100 gap at `docs/avora-new-state-august-16.md:87-89` is now closed; say so and date it. Record in the risk register that the `API-20` cross-kind reader class claimed another instance here, found by inspection rather than by failure.

- [ ] **Step 2: Run the review set**

Four reviewers, because this PR carries a migration:
`ecc:database-reviewer` (it caught the `0049` Postgres bug), `ecc:python-reviewer`, `ecc:silent-failure-hunter`, `ecc:architect`.
Give each the file:line targets from the File Structure section above and the rule IDs from Global Constraints.

- [ ] **Step 3: Open the PR, staging code by path only**

```bash
git add backend/app backend/tests backend/alembic
git status   # confirm no docs/ or CLAUDE.md is staged
```

PR body states: two defects, one measurement; the factor is now correctly omitted for every student until 4.2 ships; `seed.recompute_readiness` is to be run after merge (runbook R9).

- [ ] **Step 4: Read the review bots' inline comments**

```bash
gh api repos/:owner/:repo/pulls/N/comments
```
A green `gh pr checks` is **not** evidence. Fix what they find, push, re-read.

- [ ] **Step 5: After merge, run the recompute**

```bash
cd backend && .venv/bin/python -m seed.recompute_readiness
```
Every student's readiness moves. Nobody got worse — a fabricated full mark stopped counting.
