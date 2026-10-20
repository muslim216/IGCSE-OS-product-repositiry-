"""Handlers that were safe only because jobs ran one at a time (`CAP-2`). Each
test lands the competing write in the middle of the model call, which is when a
second job, or a tutor, gets in once the worker runs several jobs at once."""

from sqlalchemy import func, select

from app.db import async_session
from app.models import AssignmentQuestion, Job, JobStatus, QuestionMark, Submission
from app.services.extraction import ExtractedQuestion, ExtractionResult
from app.workers.jobs import process_one_job
from tests.conftest import PNG_BYTES
from tests.test_auto_marking import _confident_result, assignment_all_scheme  # noqa: F401


async def test_two_reads_of_one_assignment_leave_one_question_list(
    client,
    tutor,
    group,
    classified,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    answer = fake_ai(
        ExtractionResult(
            questions=[
                ExtractedQuestion(
                    number="1",
                    text_summary="Define an isotope",
                    max_marks=2,
                    topic_codes=[],
                    has_mark_scheme=True,
                )
            ]
        )
    )
    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "classified_id": classified["id"], "title": "HW"},
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]

    async def model(**kwargs):
        # The other read finishes first and saves its list.
        async with async_session() as session:
            session.add(
                AssignmentQuestion(
                    assignment_id=assignment_id,
                    position=0,
                    number="1",
                    text_summary="from the other read",
                    max_marks=2,
                    has_mark_scheme=True,
                )
            )
            await session.commit()
        return await answer(**kwargs)

    monkeypatch.setattr("app.services.extraction.structured_complete", model)
    assert await process_one_job() is True
    async with async_session() as session:
        questions = (
            await session.scalars(
                select(AssignmentQuestion.text_summary).where(
                    AssignmentQuestion.assignment_id == assignment_id
                )
            )
        ).all()
    assert questions == ["from the other read"]


async def test_marks_written_during_the_call_are_not_doubled_or_overwritten(
    client,
    student,
    assignment_all_scheme,  # noqa: F811
    monkeypatch,
    fake_ai,  # noqa: F811
):
    answer = fake_ai(_confident_result())

    async def model(**kwargs):
        # Another job for the same pages, or a tutor, decides every question
        # while this one waits on the model.
        async with async_session() as session:
            questions = (
                await session.scalars(
                    select(AssignmentQuestion.id).where(
                        AssignmentQuestion.assignment_id == assignment_all_scheme
                    )
                )
            ).all()
            submission_id = await session.scalar(select(Submission.id))
            for question_id in questions:
                session.add(
                    QuestionMark(
                        submission_id=submission_id,
                        question_id=question_id,
                        final_marks=1,
                    )
                )
            await session.commit()
        return await answer(**kwargs)

    monkeypatch.setattr("app.services.marking.structured_complete", model)
    await client.post(
        f"/api/v1/assignments/{assignment_all_scheme}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True
    async with async_session() as session:
        count = await session.scalar(select(func.count(QuestionMark.id)))
        finals = (await session.scalars(select(QuestionMark.final_marks))).all()
    assert count == 2  # one set, not two
    assert finals == [1, 1]  # the decisions made meanwhile stand
    async with async_session() as session:
        job = await session.scalar(select(Job).where(Job.type == "mark_submission"))
    # Finished cleanly: not a constraint failure queued to retry the paid call.
    assert (job.status, job.error) == (JobStatus.done, None)
