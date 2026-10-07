"""Shared scaffolding for the redo tests: a finalized attempt of each kind, built through
the real pipeline, and the helpers both test files use.

Not a test module. The two autouse fixtures here are imported by each test file
that needs them, so they apply there and cannot leak into the rest of the suite.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import (
    AttemptRedo,
    Evidence,
    EvidenceSource,
    Job,
    JobStatus,
    MarkOverrideAudit,
    MistakeCategory,
    MistakeRevisionAudit,
    MistakeSource,
    QuestionMark,
    RemarkRequest,
    RemarkRequestStatus,
    Submission,
    UserRole,
)
from app.models.base import utcnow
from app.security import create_access_token
from app.services.readiness_v2 import evaluate_subject_factors
from app.workers.jobs import process_one_job
from tests.conftest import PNG_BYTES
from tests.factories import (
    add_mistake,
    make_user,
    org_id,
)
from tests.test_auto_marking import _confident_result, assignment_all_scheme  # noqa: F401
from tests.test_mocks import mock_paper  # noqa: F401 — fixture
from tests.test_past_papers import _log_attempt, past_paper  # noqa: F401 — fixture

API = "/api/v1"
KINDS = ["homework", "past_paper", "mock"]


@pytest.fixture(autouse=True)
def _no_real_ai(monkeypatch, fake_ai):
    """Nothing here may reach a provider (`QA-8`). Marking is faked per scenario;
    tagging is answered with "no mistakes", and the readiness run is queued
    behind its debounce window and must never start."""
    from app.services.mistake_tagging import MistakeTaggingResult

    async def _boom(**_kwargs):
        raise AssertionError("a test reached a real AI call")

    monkeypatch.setattr(
        "app.services.mistake_tagging.structured_complete",
        fake_ai(MistakeTaggingResult(mistakes=[])),
    )
    monkeypatch.setattr("app.services.readiness_v2_ai.structured_complete", _boom)


@pytest.fixture(autouse=True)
async def _enforce_foreign_keys():
    """The suite runs SQLite with foreign keys off, which is how a delete in the
    wrong order passes here and fails on Postgres (`RISK-3`). The removal's
    whole job is deleting in key order, so these tests turn enforcement on."""
    from app.db import engine

    async with engine.connect() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.commit()
    yield
    async with engine.connect() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        await conn.commit()


async def _drain_due() -> None:
    """Run every job that is due now. Jobs scheduled behind the debounce window
    stay queued, so the readiness run is never started (`QA-6`)."""
    while await process_one_job():
        pass


async def _clear_readiness_jobs() -> None:
    async with async_session() as session:
        for job in await session.scalars(select(Job).where(Job.type == "compute_readiness_v2")):
            job.status = JobStatus.done
        await session.commit()


async def _readiness_jobs() -> list[Job]:
    async with async_session() as session:
        return list(
            await session.scalars(
                select(Job).where(
                    Job.type == "compute_readiness_v2", Job.status == JobStatus.pending
                )
            )
        )


# ---- a finalized attempt of each kind, built through the real pipeline -------


@dataclass
class Attempt:
    kind: str
    client: httpx.AsyncClient
    tutor: dict
    student: dict
    subject: dict
    group: dict
    parent_id: int
    hand_in: Callable[[], Awaitable[httpx.Response]]
    submission_id: int


async def _only_submission_id() -> int:
    async with async_session() as session:
        return (await session.scalars(select(Submission.id))).one()


def _homework_hand_in(client, student, assignment_id):
    async def hand_in():
        return await client.post(
            f"{API}/assignments/{assignment_id}/submissions",
            files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
            headers=student["headers"],
        )

    return hand_in


def _past_paper_hand_in(client, student, paper_id):
    async def hand_in():
        return await _log_attempt(client, student, paper_id)

    return hand_in


def _mock_hand_in(client, student, mock_id):
    async def hand_in():
        # Opening first, as the real page does, so the clock row exists.
        await client.post(f"{API}/mocks/{mock_id}/open", headers=student["headers"])
        return await client.post(
            f"{API}/mocks/{mock_id}/submissions",
            data={"typed_answer": "my answers"},
            headers=student["headers"],
        )

    return hand_in


async def _finalized(kind, client, tutor, student, subject, group, parent_id, hand_in):
    assert (await hand_in()).status_code == 201
    await _drain_due()
    return Attempt(
        kind,
        client,
        tutor,
        student,
        subject,
        group,
        parent_id,
        hand_in,
        await _only_submission_id(),
    )


@pytest.fixture
async def homework_attempt(
    client,
    tutor,
    student,
    subject,
    group,
    assignment_all_scheme,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    hand_in = _homework_hand_in(client, student, assignment_all_scheme)
    return await _finalized(
        "homework", client, tutor, student, subject, group, assignment_all_scheme, hand_in
    )


@pytest.fixture
async def past_paper_attempt(
    client,
    tutor,
    student,
    subject,
    group,
    past_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    hand_in = _past_paper_hand_in(client, student, past_paper["id"])
    return await _finalized(
        "past_paper", client, tutor, student, subject, group, past_paper["id"], hand_in
    )


@pytest.fixture
async def mock_attempt(
    client,
    tutor,
    student,
    subject,
    group,
    mock_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    hand_in = _mock_hand_in(client, student, mock_paper["id"])
    return await _finalized(
        "mock", client, tutor, student, subject, group, mock_paper["id"], hand_in
    )


@pytest.fixture(params=KINDS)
def attempt(request):
    """The student's first attempt at each kind of work, handed in, marked and
    auto-finalized through the real pipeline."""
    return request.getfixturevalue(f"{request.param}_attempt")


async def _redo(attempt: Attempt, headers=None, submission_id=None) -> httpx.Response:
    return await attempt.client.post(
        f"{API}/submissions/{submission_id or attempt.submission_id}/redo",
        headers=attempt.tutor["headers"] if headers is None else headers,
    )


# ---- what the old attempt carried ---------------------------------------------


def _iso(row: Any, *columns: str) -> dict:
    return {
        column: getattr(row, column).isoformat()
        if isinstance(getattr(row, column), datetime)
        else getattr(row, column)
        for column in columns
    }


AUDIT_COLUMNS = (
    "id",
    "question_mark_id",
    "old_marks",
    "new_marks",
    "changed_by_id",
    "reason",
    "created_at",
)


@dataclass
class Carried:
    """Ids and expected values of the rows seeded onto the old attempt."""

    mark_ids: list[int]
    audit: list[dict]
    remark_id: int
    mistake_id: int
    revision_audit_id: int
    unrelated_evidence_id: int
    category_name: str


async def _carry_rows(attempt: Attempt) -> Carried:
    """Hang the rest of what a real attempt accumulates off the first mark: two
    override audit rows, a resolved remark request, a tagged mistake with a topic
    link, and a revision audit row. Plus an evidence row that is not this
    attempt's, which must survive."""
    student_id = attempt.student["user"]["id"]
    tutor_id = attempt.tutor["user"]["id"]
    async with async_session() as session:
        marks = list(
            await session.scalars(
                select(QuestionMark)
                .where(QuestionMark.submission_id == attempt.submission_id)
                .order_by(QuestionMark.id)
            )
        )
        first = marks[0]
        base = utcnow() - timedelta(days=3)
        session.add_all(
            [
                MarkOverrideAudit(
                    question_mark_id=first.id,
                    old_marks=1,
                    new_marks=2,
                    changed_by_id=tutor_id,
                    reason="remark_request",
                    created_at=base,
                ),
                MarkOverrideAudit(
                    question_mark_id=first.id,
                    old_marks=2,
                    new_marks=1,
                    changed_by_id=tutor_id,
                    reason=None,
                    created_at=base + timedelta(hours=1),
                ),
            ]
        )
        remark = RemarkRequest(
            question_mark_id=first.id,
            requested_by_id=student_id,
            reason="please recheck",
            status=RemarkRequestStatus.resolved,
        )
        session.add(remark)
        # A subject starts with the tutor's default categories, so use one.
        category = (
            await session.scalars(
                select(MistakeCategory)
                .where(MistakeCategory.subject_id == attempt.subject["id"])
                .order_by(MistakeCategory.id)
            )
        ).first()
        assert category is not None
        mistake = await add_mistake(
            session,
            student_id=student_id,
            mark_id=first.id,
            category_id=category.id,
            severity=2,
            topic_ids=[attempt.subject["topic1"]],
            source=MistakeSource.tutor,
        )
        revision = MistakeRevisionAudit(
            mistake_id=mistake.id,
            old_category_id=category.id,
            new_category_id=category.id,
            old_severity=1,
            new_severity=2,
            changed_by_id=tutor_id,
        )
        unrelated = Evidence(
            student_id=student_id,
            topic_id=attempt.subject["topic1"],
            source_type=EvidenceSource.homework,
            score_pct=50.0,
            max_marks=4,
            source_ref="submission:424242",
        )
        session.add_all([revision, unrelated])
        await session.commit()
        audit_rows = await session.scalars(select(MarkOverrideAudit).order_by(MarkOverrideAudit.id))
        return Carried(
            mark_ids=[m.id for m in marks],
            audit=[_iso(row, *AUDIT_COLUMNS) for row in audit_rows],
            remark_id=remark.id,
            mistake_id=mistake.id,
            revision_audit_id=revision.id,
            unrelated_evidence_id=unrelated.id,
            category_name=category.name,
        )


async def _count(model, *where) -> int:
    async with async_session() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where)) or 0


async def _factor_scores(attempt: Attempt, now: datetime) -> list[tuple[str, float]]:
    """Every factor that has a score, at a pinned clock so before and after are
    directly comparable. A factor with no evidence has no score at all."""
    async with async_session() as session:
        rows = await evaluate_subject_factors(
            session, attempt.student["user"]["id"], attempt.subject["id"], "pin", now
        )
        scores = [(row.factor.value, row.score) for row in rows if row.score is not None]
        await session.rollback()
        return scores


async def _only_redo() -> AttemptRedo:
    async with async_session() as session:
        return (await session.scalars(select(AttemptRedo))).one()


async def _assert_untouched(attempt: Attempt) -> None:
    assert await _count(Submission, Submission.id == attempt.submission_id) == 1
    assert await _count(QuestionMark) == 2
    assert await _count(AttemptRedo) == 0


async def _colleague_headers() -> dict:
    async with async_session() as session:
        colleague = await make_user(
            session,
            organization_id=await org_id(session),
            role=UserRole.tutor,
            name="Colleague",
            email="colleague@example.com",
        )
        await session.commit()
        token = create_access_token(colleague.id, colleague.token_version)
    return {"Authorization": f"Bearer {token}"}


async def _extra_class(attempt: Attempt, *, other_subject: bool = False) -> int:
    """A second live class of the same tutor with this student in it, so deleting
    or leaving the first one leaves the tutor still teaching the student — the
    only state in which a redo's "could they hand it in again" check can answer
    on its own, rather than the tutor having lost the student altogether."""
    from app.models import Group, GroupMember, Subject
    from tests.factories import subject_defaults

    async with async_session() as session:
        subject_id = attempt.subject["id"]
        if other_subject:
            other = Subject(
                **await subject_defaults(session),
                exam_board="Edexcel IGCSE",
                code="4PH1",
                name="Physics",
                grade_scale="9-1",
            )
            session.add(other)
            await session.flush()
            subject_id = other.id
        group = Group(
            organization_id=await org_id(session),
            tutor_id=attempt.tutor["user"]["id"],
            subject_id=subject_id,
            name="Second class",
        )
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, student_id=attempt.student["user"]["id"]))
        await session.commit()
        return group.id
