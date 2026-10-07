"""A tutor letting a student redo a locked attempt.

Since #145 a student cannot replace an attempt that has a final mark. This is the
tutor's way out when the wrong file went in: the old attempt is moved into an
append-only `attempt_redos` record and its live rows are deleted, so nothing that
reads submissions, marks, mistakes or evidence can still count it
(`services/attempt_redo.py`). These tests hold that for all three kinds of work.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.main import app
from app.models import (
    AttemptRedo,
    Evidence,
    EvidenceSource,
    Job,
    JobStatus,
    MarkOverrideAudit,
    Mistake,
    MistakeCategory,
    MistakeRevisionAudit,
    MistakeSource,
    MistakeTopic,
    MockOpening,
    PastPaperAttempt,
    QuestionMark,
    RemarkRequest,
    RemarkRequestStatus,
    Submission,
    SubmissionFile,
    SubmissionStatus,
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
    register_other_tutor,
    register_parent,
)
from tests.test_authorization import _iter_api_routes
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


async def test_foreign_keys_really_are_enforced_in_this_module():
    """Guards the fixture above: if enforcement silently stopped, the delete-order
    tests would go on passing while proving nothing."""
    async with async_session() as session:
        session.add(QuestionMark(submission_id=424242))
        with pytest.raises(IntegrityError):
            await session.commit()


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


# ---- the happy path, for every kind --------------------------------------------


async def test_the_student_can_hand_in_again_and_it_is_marked_normally(attempt):
    assert (await _redo(attempt)).status_code == 201

    again = await attempt.hand_in()
    assert again.status_code == 201, again.text
    await _drain_due()

    async with async_session() as session:
        submissions = list(await session.scalars(select(Submission)))
        assert len(submissions) == 1
        new = submissions[0]
        assert new.status == SubmissionStatus.auto_finalized
        marks = list(
            await session.scalars(select(QuestionMark).where(QuestionMark.submission_id == new.id))
        )
        assert sorted(m.final_marks for m in marks) == [2, 3]
    # Only the new attempt counts: evidence exists for it and for nothing earlier.
    async with async_session() as session:
        refs = set(await session.scalars(select(Evidence.source_ref)))
    assert refs == {f"submission:{new.id}"}


async def test_nothing_of_the_old_attempt_remains_and_readiness_stops_counting_it(attempt):
    carried = await _carry_rows(attempt)
    now = datetime.now(timezone.utc)
    before = await _factor_scores(attempt, now)
    if attempt.kind != "mock":
        # Mocks are kept out of topic scores on purpose, so there is nothing to see move.
        assert before, "the finalized attempt should have produced readiness evidence"
    await _clear_readiness_jobs()

    response = await _redo(attempt)
    assert response.status_code == 201, response.text

    sid = attempt.submission_id
    assert await _count(Submission, Submission.id == sid) == 0
    assert await _count(SubmissionFile, SubmissionFile.submission_id == sid) == 0
    assert await _count(QuestionMark, QuestionMark.submission_id == sid) == 0
    assert await _count(Mistake, Mistake.id == carried.mistake_id) == 0
    assert await _count(MistakeTopic, MistakeTopic.mistake_id == carried.mistake_id) == 0
    assert await _count(RemarkRequest, RemarkRequest.id == carried.remark_id) == 0
    assert await _count(MarkOverrideAudit) == 0
    assert await _count(Evidence, Evidence.source_ref == f"submission:{sid}") == 0
    assert await _count(PastPaperAttempt) == 0

    # What is not this attempt's is untouched, including the tutor's revision
    # trail (`test_the_audit_outlives_the_mistake_it_explains`).
    assert await _count(Evidence, Evidence.id == carried.unrelated_evidence_id) == 1
    assert (
        await _count(MistakeRevisionAudit, MistakeRevisionAudit.id == carried.revision_audit_id)
        == 1
    )

    queued = await _readiness_jobs()
    assert [(j.payload["student_id"], j.payload["subject_id"]) for j in queued] == [
        (attempt.student["user"]["id"], attempt.subject["id"])
    ]
    assert await _factor_scores(attempt, now) == []


# ---- the record -----------------------------------------------------------------


async def _only_redo() -> AttemptRedo:
    async with async_session() as session:
        return (await session.scalars(select(AttemptRedo))).one()


async def test_the_record_keeps_the_old_attempt_whole(attempt):
    carried = await _carry_rows(attempt)
    async with async_session() as session:
        paths = [
            f.path
            for f in await session.scalars(
                select(SubmissionFile).where(SubmissionFile.submission_id == attempt.submission_id)
            )
        ]
    response = await _redo(attempt)
    assert response.status_code == 201, response.text

    redo = await _only_redo()
    assert redo.previous_submission_id == attempt.submission_id
    assert redo.allowed_by_id == attempt.tutor["user"]["id"]
    assert redo.student_id == attempt.student["user"]["id"]
    assert (redo.previous_final_marks, redo.previous_max_marks) == (5, 6)

    record = redo.record
    assert (
        record["kind"]
        == {"homework": "homework", "past_paper": "past_paper", "mock": "mock"}[attempt.kind]
    )
    assert record["submission"]["status"] == "auto_finalized"
    assert [m["id"] for m in record["marks"]] == carried.mark_ids
    first = record["marks"][0]
    assert first["final_marks"] == 2
    assert first["question"]["number"] == "1"
    assert first["override_audit"] == carried.audit
    assert first["remark_request"]["id"] == carried.remark_id
    assert first["remark_request"]["reason"] == "please recheck"
    assert first["mistakes"][0]["category_name"] == carried.category_name
    assert first["mistakes"][0]["topic_ids"] == [attempt.subject["topic1"]]
    if paths:
        assert [f["path"] for f in record["files"]] == paths


async def test_a_mock_record_carries_its_clock(
    client, tutor, student, mock_paper, monkeypatch, fake_ai
):  # noqa: F811
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    hand_in = _mock_hand_in(client, student, mock_paper["id"])
    assert (await hand_in()).status_code == 201
    await _drain_due()
    async with async_session() as session:
        opened_at = (await session.scalars(select(MockOpening.opened_at))).one()
    sid = await _only_submission_id()

    redo = await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])
    assert redo.status_code == 201, redo.text

    record = (await _only_redo()).record
    assert record["mock_opening"]["opened_at"] == opened_at.isoformat()


async def test_only_the_final_questions_are_totalled_when_the_attempt_is_half_decided(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    """Q1 is scheme-backed and confident so it counts; Q2 has no scheme, so it
    waits for the tutor. One final mark locks the attempt, and the record totals
    only that question — 2 of 2, not 2 of 6, and never a 0 for the undecided one."""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    hand_in = _homework_hand_in(client, student, published_assignment["id"])
    assert (await hand_in()).status_code == 201
    await _drain_due()
    sid = await _only_submission_id()
    async with async_session() as session:
        assert (await session.get(Submission, sid)).status == SubmissionStatus.needs_review

    assert (
        await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])
    ).status_code == 201

    redo = await _only_redo()
    assert (redo.previous_final_marks, redo.previous_max_marks) == (2, 2)
    undecided = [m for m in redo.record["marks"] if m["final_marks"] is None]
    assert len(undecided) == 1


# ---- a mock's clock ---------------------------------------------------------------


async def test_a_redone_mock_starts_its_clock_again_even_after_the_window_closed(
    client,
    tutor,
    student,
    mock_paper,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    """The opening row is deleted with the attempt, so reopening starts a fresh
    90 minutes. Nothing about a mock ever blocked a late hand-in (`AV-116`), so a
    window that has already closed does not stop the redo either: the student
    gets the whole duration again and the new sitting is not flagged late."""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    hand_in = _mock_hand_in(client, student, mock_paper["id"])
    assert (await hand_in()).status_code == 201
    await _drain_due()
    sid = await _only_submission_id()
    long_ago = utcnow() - timedelta(days=2)
    async with async_session() as session:
        opening = (await session.scalars(select(MockOpening))).one()
        opening.opened_at = long_ago
        await session.commit()

    assert (
        await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])
    ).status_code == 201
    assert await _count(MockOpening) == 0

    reopened = await client.post(f"{API}/mocks/{mock_paper['id']}/open", headers=student["headers"])
    assert reopened.status_code == 200
    assert reopened.json()["overdue"] is False
    assert reopened.json()["seconds_remaining"] > 89 * 60
    again = await client.post(
        f"{API}/mocks/{mock_paper['id']}/submissions",
        data={"typed_answer": "second go"},
        headers=student["headers"],
    )
    assert again.status_code == 201, again.text
    assert again.json()["submitted_late"] is False


# ---- what is refused -----------------------------------------------------------------


async def test_an_attempt_with_no_final_mark_is_refused_and_unchanged(
    client, tutor, student, published_assignment
):
    hand_in = _homework_hand_in(client, student, published_assignment["id"])
    assert (await hand_in()).status_code == 201  # handed in, not marked
    sid = await _only_submission_id()

    response = await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This attempt has no final mark yet, so the student can already replace it."
    )
    assert await _count(Submission, Submission.id == sid) == 1
    assert await _count(AttemptRedo) == 0


async def test_an_attempt_being_marked_right_now_is_refused_and_unchanged(attempt):
    async with async_session() as session:
        (await session.get(Submission, attempt.submission_id)).status = SubmissionStatus.marking
        await session.commit()

    response = await _redo(attempt)

    assert response.status_code == 409
    assert "being marked" in response.json()["detail"]
    assert await _count(Submission, Submission.id == attempt.submission_id) == 1
    assert await _count(QuestionMark) == 2
    assert await _count(AttemptRedo) == 0


async def test_a_second_redo_of_the_same_attempt_is_a_404(attempt):
    assert (await _redo(attempt)).status_code == 201
    assert (await _redo(attempt)).status_code == 404
    assert await _count(AttemptRedo) == 1


async def test_a_redo_of_something_that_never_existed_is_a_404(attempt):
    assert (await _redo(attempt, submission_id=999999)).status_code == 404


# ---- who may ask (QA-12) ----------------------------------------------------------------


async def _assert_untouched(attempt: Attempt) -> None:
    assert await _count(Submission, Submission.id == attempt.submission_id) == 1
    assert await _count(QuestionMark) == 2
    assert await _count(AttemptRedo) == 0


async def test_a_student_and_a_parent_cannot_redo_and_nothing_changes(attempt):
    parent = await register_parent(attempt.client, attempt.tutor, attempt.student)

    assert (await _redo(attempt, headers=attempt.student["headers"])).status_code == 403
    assert (await _redo(attempt, headers=parent["headers"])).status_code == 403
    await _assert_untouched(attempt)


async def test_no_token_is_a_401(attempt):
    response = await attempt.client.post(f"{API}/submissions/{attempt.submission_id}/redo")
    assert response.status_code == 401
    await _assert_untouched(attempt)


async def test_a_tutor_in_another_organization_gets_a_404(attempt):
    other = await register_other_tutor(attempt.client)
    assert (await _redo(attempt, headers=other["headers"])).status_code == 404
    await _assert_untouched(attempt)


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


async def test_a_colleague_who_does_not_teach_the_class_gets_a_404(
    client,
    tutor,
    student,
    assignment_all_scheme,
    monkeypatch,
    fake_ai,
    subject,
    group,  # noqa: F811
):
    """Homework belongs to whoever teaches the class (`_tutor_owns`), so a second
    tutor in the same organization is refused like a stranger. (A past paper
    belongs to the organization there, and the redo follows that rule rather than
    adding its own.)"""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    assert (await _homework_hand_in(client, student, assignment_all_scheme)()).status_code == 201
    await _drain_due()
    sid = await _only_submission_id()

    response = await client.post(
        f"{API}/submissions/{sid}/redo", headers=await _colleague_headers()
    )

    assert response.status_code == 404
    assert await _count(Submission, Submission.id == sid) == 1
    assert await _count(AttemptRedo) == 0


# ---- the tutor's read of the record -------------------------------------------------------


async def test_the_tutor_reads_the_redos_for_a_student_newest_first(attempt):
    assert (await _redo(attempt)).status_code == 201
    assert (await attempt.hand_in()).status_code == 201
    await _drain_due()
    second_id = await _only_submission_id()
    assert (await _redo(attempt, submission_id=second_id)).status_code == 201

    student_id = attempt.student["user"]["id"]
    listed = await attempt.client.get(
        f"{API}/students/{student_id}/redos", headers=attempt.tutor["headers"]
    )

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 2
    assert [r["id"] for r in rows] == sorted((r["id"] for r in rows), reverse=True)
    newest = rows[0]
    assert newest["allowed_by_id"] == attempt.tutor["user"]["id"]
    assert newest["allowed_by_name"] == "Test Tutor"
    assert newest["work_kind"] == attempt.kind
    assert newest["work_title"]
    assert (newest["previous_final_marks"], newest["previous_max_marks"]) == (5, 6)
    # The snapshot is kept, not served.
    assert "record" not in newest


async def test_a_student_with_no_redos_has_an_empty_list(client, tutor, student):
    listed = await client.get(
        f"{API}/students/{student['user']['id']}/redos", headers=tutor["headers"]
    )
    assert listed.status_code == 200
    assert listed.json() == []


async def test_the_redo_list_is_only_for_a_student_the_tutor_teaches(attempt):
    assert (await _redo(attempt)).status_code == 201
    url = f"{API}/students/{attempt.student['user']['id']}/redos"
    other = await register_other_tutor(attempt.client)
    parent = await register_parent(attempt.client, attempt.tutor, attempt.student)

    assert (await attempt.client.get(url, headers=other["headers"])).status_code == 404
    assert (await attempt.client.get(url, headers=await _colleague_headers())).status_code == 404
    assert (await attempt.client.get(url, headers=attempt.student["headers"])).status_code == 403
    assert (await attempt.client.get(url, headers=parent["headers"])).status_code == 403
    assert (await attempt.client.get(url)).status_code == 401


# ---- the review page's flag --------------------------------------------------------------------


async def test_the_review_page_is_told_when_a_redo_is_on_offer(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    hand_in = _homework_hand_in(client, student, published_assignment["id"])
    assert (await hand_in()).status_code == 201
    sid = await _only_submission_id()
    unmarked = await client.get(f"{API}/submissions/{sid}", headers=tutor["headers"])
    assert unmarked.json()["can_redo"] is False

    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    await _drain_due()
    locked = await client.get(f"{API}/submissions/{sid}", headers=tutor["headers"])
    assert locked.json()["can_redo"] is True

    async with async_session() as session:
        (await session.get(Submission, sid)).status = SubmissionStatus.marking
        await session.commit()
    marking = await client.get(f"{API}/submissions/{sid}", headers=tutor["headers"])
    assert marking.json()["can_redo"] is False


# ---- jobs that outlive the attempt (BE-6, BE-9) ----------------------------------------------------


async def test_queued_jobs_for_the_removed_submission_run_quietly_and_write_nothing(attempt):
    assert (await _redo(attempt)).status_code == 201
    async with async_session() as session:
        for job_type in ("mark_submission", "tag_mistakes"):
            session.add(Job(type=job_type, payload={"submission_id": attempt.submission_id}))
        await session.commit()

    await _drain_due()

    async with async_session() as session:
        stale = list(
            await session.scalars(
                select(Job).where(Job.type.in_(["mark_submission", "tag_mistakes"]))
            )
        )
        assert stale
        assert {j.status for j in stale} == {JobStatus.done}
    assert await _count(Submission) == 0
    assert await _count(QuestionMark) == 0
    assert await _count(Mistake) == 0


# ---- the record cannot be edited ----------------------------------------------------------------------


def test_no_route_updates_or_deletes_a_redo_record():
    found = {
        (method, route.path)
        for route in _iter_api_routes(app)
        for method in route.methods - {"HEAD"}
        if "redo" in route.path
    }
    assert found == {
        ("POST", "/submissions/{submission_id}/redo"),
        ("GET", "/students/{student_id}/redos"),
    }
