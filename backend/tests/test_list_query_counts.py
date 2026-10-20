"""Lists that grow with a tutor's work ask the database the same number of times
however long they are (audit DB-04): the review queue, a class's homework, and
the tutor's assessments. The counts on each row stay right."""

from datetime import date

from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import (
    Assessment,
    AssessmentScore,
    AssessmentType,
    Assignment,
    AssignmentQuestion,
    QuestionMark,
    RemarkRequest,
    RemarkRequestStatus,
    Submission,
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

    # Data a join fan-out or a wrong grouping would miscount: a second student's
    # hand-in to HW 1 with both marks unsure and both under an open remark, and
    # a resolved remark on HW 2 that must not count.
    sid2 = await _enrol(g["id"], org, "Ben", "ben@example.com")
    async with async_session() as s:
        hw1 = await s.scalar(select(Assignment).where(Assignment.title == "HW 1"))
        hw2 = await s.scalar(select(Assignment).where(Assignment.title == "HW 2"))
        q_ids = (
            await s.scalars(
                select(AssignmentQuestion.id).where(AssignmentQuestion.assignment_id == hw1.id)
            )
        ).all()
        ben = await submit_work(
            s,
            assignment=hw1,
            student_id=sid2,
            status=SubmissionStatus.needs_review,
            submitted_at=_at(21),
        )
        await s.flush()
        marks = [
            QuestionMark(submission_id=ben.id, question_id=q, needs_review=True) for q in q_ids
        ]
        s.add_all(marks)
        await s.flush()
        s.add_all(
            RemarkRequest(
                question_mark_id=m.id, requested_by_id=sid2, status=RemarkRequestStatus.open
            )
            for m in marks
        )
        ann_hw2_sure = await s.scalar(
            select(QuestionMark)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .where(Submission.work_id == hw2.work_id, QuestionMark.needs_review.is_(False))
        )
        s.add(
            RemarkRequest(
                question_mark_id=ann_hw2_sure.id,
                requested_by_id=sid,
                status=RemarkRequestStatus.resolved,
            )
        )
        await s.commit()

    queue_after, queue = await _queries_for(
        client, "/api/v1/submissions/review-queue", tutor["headers"]
    )
    homework_after, homework = await _queries_for(client, homework_url, tutor["headers"])
    assert queue_after == queue_before
    assert homework_after == homework_before

    assert len(queue) == 6
    counts = {
        (row["student_name"], row["assignment_title"]): (
            row["unsure_count"],
            row["remark_request_count"],
        )
        for row in queue
    }
    assert counts[("Ben", "HW 1")] == (2, 2)
    assert counts[("Ann", "HW 1")] == (1, 1)
    assert counts[("Ann", "HW 2")] == (1, 0)  # the resolved remark does not count
    by_title = {row["title"]: row for row in homework}
    assert len(by_title) == 5
    assert by_title["HW 1"]["submission_count"] == 2
    assert all((row["question_count"], row["total_marks"]) == (2, 6) for row in by_title.values())
    assert all(by_title[f"HW {i}"]["submission_count"] == 1 for i in range(2, 6))


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
