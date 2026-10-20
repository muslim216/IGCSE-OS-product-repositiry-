"""Lists that grow with a tutor's work ask the database the same number of times
however long they are (audit DB-04): the review queue, a class's homework, and
the tutor's assessments. The counts on each row stay right."""

from datetime import date

from sqlalchemy import event

from app.db import async_session, engine
from app.models import (
    Assessment,
    AssessmentScore,
    AssessmentType,
    AssignmentQuestion,
    QuestionMark,
    RemarkRequest,
    RemarkRequestStatus,
    SubmissionStatus,
)
from tests.factories import publish_assignment, submit_work
from tests.test_tutor_lists import _at, _enrol, _group, _org_id


async def _queries_for(client, url, headers) -> tuple[int, object]:
    n = 0

    def bump(*_):
        nonlocal n
        n += 1

    event.listen(engine.sync_engine, "before_cursor_execute", bump)
    try:
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200, resp.text
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", bump)
    return n, resp.json()


async def _homework_waiting_on_review(group, subject, org, student_id, title, *, remark):
    """A homework with two questions and one hand-in in the review queue: one
    mark the AI was unsure of, one confident, and maybe a remark request."""
    async with async_session() as s:
        a = await publish_assignment(
            s, group_id=group["id"], subject_id=subject["id"], organization_id=org, title=title
        )
        questions = [
            AssignmentQuestion(
                assignment_id=a.id, position=i, number=str(i), text_summary="q", max_marks=3
            )
            for i in (1, 2)
        ]
        s.add_all(questions)
        sub = await submit_work(
            s,
            assignment=a,
            student_id=student_id,
            status=SubmissionStatus.needs_review,
            submitted_at=_at(20),
        )
        await s.flush()
        unsure = QuestionMark(submission_id=sub.id, question_id=questions[0].id, needs_review=True)
        sure = QuestionMark(submission_id=sub.id, question_id=questions[1].id, needs_review=False)
        s.add_all([unsure, sure])
        await s.flush()
        if remark:
            s.add(
                RemarkRequest(
                    question_mark_id=sure.id,
                    requested_by_id=student_id,
                    status=RemarkRequestStatus.open,
                )
            )
        await s.commit()
        return a


async def test_review_queue_and_class_homework_do_not_grow_queries_with_rows(
    client, tutor, subject
):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    sid = await _enrol(g["id"], org, "Ann", "ann@example.com")
    await _homework_waiting_on_review(g, subject, org, sid, "HW 1", remark=True)
    queue_before, _ = await _queries_for(
        client, "/api/v1/submissions/review-queue", tutor["headers"]
    )
    homework_url = f"/api/v1/assignments/group/{g['id']}"
    homework_before, _ = await _queries_for(client, homework_url, tutor["headers"])

    for i in range(2, 6):
        await _homework_waiting_on_review(g, subject, org, sid, f"HW {i}", remark=False)

    queue_after, queue = await _queries_for(
        client, "/api/v1/submissions/review-queue", tutor["headers"]
    )
    homework_after, homework = await _queries_for(client, homework_url, tutor["headers"])
    assert queue_after == queue_before
    assert homework_after == homework_before

    assert len(queue) == 5
    assert all(row["unsure_count"] == 1 for row in queue)
    assert sorted(row["remark_request_count"] for row in queue) == [0, 0, 0, 0, 1]
    assert len(homework) == 5
    assert all(
        (row["question_count"], row["total_marks"], row["submission_count"]) == (2, 6, 1)
        for row in homework
    )


async def test_assessments_do_not_grow_queries_with_rows(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    sid = await _enrol(g["id"], org, "Ann", "ann@example.com")

    async def assessment(title: str, scores: int) -> None:
        async with async_session() as s:
            a = Assessment(
                tutor_id=tutor["user"]["id"],
                subject_id=subject["id"],
                title=title,
                type=AssessmentType.test,
                date=date(2026, 9, 1),
            )
            s.add(a)
            await s.flush()
            s.add_all(
                AssessmentScore(assessment_id=a.id, student_id=sid, marks=1, max_marks=2)
                for _ in range(scores)
            )
            await s.commit()

    await assessment("T1", 2)
    before, _ = await _queries_for(client, "/api/v1/assessments", tutor["headers"])
    for i in range(2, 6):
        await assessment(f"T{i}", 0)
    after, rows = await _queries_for(client, "/api/v1/assessments", tutor["headers"])
    assert after == before
    assert sorted(r["score_count"] for r in rows) == [0, 0, 0, 0, 2]
