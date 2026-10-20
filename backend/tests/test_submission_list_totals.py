"""The tutor's submissions list totals every settled hand-in in one query.

It ran one `SELECT sum(...)` per settled submission, and the page polls it
while marking runs (audit CAP-12)."""

from sqlalchemy import event, select

from app.db import async_session, engine
from app.models import Assignment, AssignmentQuestion, QuestionMark, Submission, SubmissionStatus


async def _student(client, tutor, group, n: int) -> int:
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": f"Student {n}",
            "email": f"student{n}@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["user"]["id"]


async def _seed(published_assignment, students: dict[int, tuple[SubmissionStatus, list]]):
    async with async_session() as db:
        assignment = await db.get(Assignment, published_assignment["id"])
        questions = (
            await db.scalars(
                select(AssignmentQuestion)
                .where(AssignmentQuestion.assignment_id == assignment.id)
                .order_by(AssignmentQuestion.position)
            )
        ).all()
        for student_id, (status, marks) in students.items():
            sub = Submission(work_id=assignment.work_id, student_id=student_id, status=status)
            db.add(sub)
            await db.flush()
            for q, mark in zip(questions, marks, strict=False):
                db.add(QuestionMark(submission_id=sub.id, question_id=q.id, final_marks=mark))
        await db.commit()


async def _list(client, tutor, aid: int) -> tuple[dict[str, dict], int]:
    statements: list[str] = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        resp = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
    assert resp.status_code == 200, resp.text
    sums = sum("sum(question_marks.final_marks)" in s.lower() for s in statements)
    return {row["student_name"]: row for row in resp.json()}, sums


async def test_totals_come_from_one_grouped_query(client, tutor, group, published_assignment):
    ids = [await _student(client, tutor, group, n) for n in range(4)]
    await _seed(
        published_assignment,
        {
            ids[0]: (SubmissionStatus.finalized, [2, 3]),
            ids[1]: (SubmissionStatus.auto_finalized, [1, None]),
            # Settled with no marks at all still reads 0, as it always did.
            ids[2]: (SubmissionStatus.finalized, []),
            # Not settled: no total, however many drafts it has.
            ids[3]: (SubmissionStatus.needs_review, [2, 4]),
        },
    )

    rows, sums = await _list(client, tutor, published_assignment["id"])

    assert rows["Student 0"]["total_final"] == 5
    assert rows["Student 1"]["total_final"] == 1
    assert rows["Student 2"]["total_final"] == 0
    assert rows["Student 3"]["total_final"] is None
    assert {r["total_max"] for r in rows.values()} == {6}
    assert sums == 1


async def test_another_tutor_still_gets_404(client, published_assignment):
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    resp = await client.get(
        f"/api/v1/assignments/{published_assignment['id']}/submissions", headers=headers
    )
    assert resp.status_code == 404
