"""A tutor letting a student redo a locked attempt.

Since #145 a student cannot replace an attempt that has a final mark. This is the
tutor's way out when the wrong file went in: the old attempt is moved into an
append-only `attempt_redos` record and its live rows are deleted, so nothing that
reads submissions, marks, mistakes or evidence can still count it
(`services/attempt_redo.py`). These tests hold that for all three kinds of work.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.main import app
from app.models import (
    Evidence,
    Job,
    JobStatus,
    MarkOverrideAudit,
    Mistake,
    MistakeRevisionAudit,
    MistakeTopic,
    MockOpening,
    PastPaperAttempt,
    QuestionMark,
    RemarkRequest,
    Submission,
    SubmissionFile,
    SubmissionStatus,
)
from app.models.base import utcnow
from app.services.attempt_redo import AttemptNotLocked
from tests.factories import register_other_tutor, register_parent
from tests.redo_world import (  # noqa: F401 — fixtures and helpers shared by the redo tests
    API,
    KINDS,
    Attempt,
    Carried,
    _assert_untouched,
    _carry_rows,
    _clear_readiness_jobs,
    _colleague_headers,
    _confident_result,
    _count,
    _drain_due,
    _enforce_foreign_keys,
    _factor_scores,
    _finalized,
    _homework_hand_in,
    _mock_hand_in,
    _no_real_ai,
    _only_redo,
    _only_submission_id,
    _past_paper_hand_in,
    _readiness_jobs,
    _redo,
    assignment_all_scheme,
    attempt,
    homework_attempt,
    mock_attempt,
    mock_paper,
    past_paper,
    past_paper_attempt,
)
from tests.test_authorization import _iter_api_routes


async def test_foreign_keys_really_are_enforced_in_this_module():
    """Guards the fixture above: if enforcement silently stopped, the delete-order
    tests would go on passing while proving nothing."""
    async with async_session() as session:
        session.add(QuestionMark(submission_id=424242))
        with pytest.raises(IntegrityError):
            await session.commit()


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


# ---- the tutor's read of the record -------------------------------------------------------


async def test_the_tutor_reads_the_redos_for_a_student_newest_first(attempt):
    assert (await _redo(attempt)).status_code == 201
    assert (await attempt.hand_in()).status_code == 201
    await _drain_due()
    second_id = await _only_submission_id()
    # The second attempt scores differently, so the two rows are told apart by
    # their content and a list in the wrong order cannot pass by accident.
    async with async_session() as session:
        first_mark = await session.scalar(
            select(QuestionMark)
            .where(QuestionMark.submission_id == second_id)
            .order_by(QuestionMark.id)
        )
        first_mark.final_marks = 1
        await session.commit()
    assert (await _redo(attempt, submission_id=second_id)).status_code == 201

    student_id = attempt.student["user"]["id"]
    listed = await attempt.client.get(
        f"{API}/students/{student_id}/redos", headers=attempt.tutor["headers"]
    )

    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 2
    assert [(r["previous_final_marks"], r["previous_max_marks"]) for r in rows] == [(4, 6), (5, 6)]
    assert [(r["previous_questions_marked"], r["previous_question_count"]) for r in rows] == [
        (2, 2),
        (2, 2),
    ]
    newest = rows[0]
    assert newest["allowed_by_id"] == attempt.tutor["user"]["id"]
    assert newest["allowed_by_name"] == "Test Tutor"
    assert newest["work_kind"] == attempt.kind
    assert newest["work_title"]
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
        session.add(Job(type="tag_mistakes", payload={"submission_id": sid}))
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


# ---- what the record holds, beyond the marks ----------------------------------------------


async def test_the_record_carries_the_evidence_it_removed_and_the_topic_links(homework_attempt):
    attempt = homework_attempt
    carried = await _carry_rows(attempt)
    async with async_session() as session:
        built = list(
            await session.scalars(
                select(Evidence).where(Evidence.source_ref == f"submission:{attempt.submission_id}")
            )
        )
    assert built

    assert (await _redo(attempt)).status_code == 201

    record = (await _only_redo()).record
    assert sorted(e["id"] for e in record["evidence"]) == sorted(e.id for e in built)
    assert {e["source_ref"] for e in record["evidence"]} == {f"submission:{attempt.submission_id}"}
    assert {e["topic_id"] for e in record["evidence"]} == {e.topic_id for e in built}
    # The unrelated row was neither recorded nor removed.
    assert carried.unrelated_evidence_id not in {e["id"] for e in record["evidence"]}
    link = record["marks"][0]["mistakes"][0]["topic_links"][0]
    assert link["topic_id"] == attempt.subject["topic1"]
    assert link["mistake_id"] == record["marks"][0]["mistakes"][0]["id"]


async def test_a_past_paper_record_carries_its_rollup_and_self_declared_fields(
    past_paper_attempt,
):
    assert (await _redo(past_paper_attempt)).status_code == 201

    record = (await _only_redo()).record
    assert record["past_paper_attempt"]["raw_marks"] == 5
    assert record["past_paper_attempt"]["max_marks"] == 6
    assert record["submission"]["timed"] is True
    assert record["submission"]["time_taken_minutes"] == 85
    assert record["submission"]["attempted_at"] == "2026-07-01"


async def test_a_settled_attempt_with_no_final_mark_records_no_marks_rather_than_zero(
    client, tutor, student, published_assignment
):
    """Settled by status alone (a tutor signed it off before any mark was set), so
    it is locked and may be redone — and the record has nothing to total."""
    assert (
        await _homework_hand_in(client, student, published_assignment["id"])()
    ).status_code == 201
    sid = await _only_submission_id()
    async with async_session() as session:
        (await session.get(Submission, sid)).status = SubmissionStatus.finalized
        for job in await session.scalars(select(Job)):
            job.status = JobStatus.done
        await session.commit()

    redo = await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])

    assert redo.status_code == 201, redo.text
    body = redo.json()
    assert body["previous_final_marks"] is None
    assert body["previous_max_marks"] is None
    assert (body["previous_questions_marked"], body["previous_question_count"]) == (0, 0)
    row = await _only_redo()
    assert (row.previous_final_marks, row.previous_max_marks) == (None, None)


async def test_a_partly_marked_attempt_says_how_many_questions_the_score_covers(
    client, tutor, student, published_assignment, monkeypatch, fake_ai
):
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    assert (
        await _homework_hand_in(client, student, published_assignment["id"])()
    ).status_code == 201
    await _drain_due()
    sid = await _only_submission_id()

    redo = await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])

    body = redo.json()
    assert (body["previous_final_marks"], body["previous_max_marks"]) == (2, 2)
    assert (body["previous_questions_marked"], body["previous_question_count"]) == (1, 2)


# ---- what the detail read costs ---------------------------------------------------------------


async def _statements_for(client, url, headers) -> int:
    from sqlalchemy import event

    from app.db import engine

    seen: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        response = await client.get(url, headers=headers)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
    assert response.status_code == 200
    return len(seen)


async def test_deciding_can_redo_adds_only_a_handful_of_queries_to_the_detail_read(
    homework_attempt, monkeypatch
):
    attempt = homework_attempt
    url = f"{API}/submissions/{attempt.submission_id}"
    headers = attempt.tutor["headers"]

    async def never_offered(*_args, **_kwargs):
        return AttemptNotLocked("not offered")

    with_rule = await _statements_for(attempt.client, url, headers)
    monkeypatch.setattr("app.api.submissions.redo_refusal", never_offered)
    without_rule = await _statements_for(attempt.client, url, headers)

    # Teaching check, the in-flight job check, and the hand-in gate (class
    # deleted, membership). The student and the marks are already in hand.
    assert with_rule - without_rule <= 4
