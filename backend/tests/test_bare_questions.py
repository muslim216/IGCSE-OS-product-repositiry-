"""Task 7 (decision 15): the tutor sees how many questions on a submission
have no linked syllabus topic — derived at read time from the link rows
(`PROD-14`), via `kind.topic_model` so the same query serves every arm
(`API-20`).

Named `test_bare_questions.py`, not `test_mistake_tagging.py` as the plan
says — that file was held by another agent editing this branch concurrently.
"""

from app.db import async_session
from app.models import QuestionTopic
from tests.conftest import PNG_BYTES


async def test_bare_question_count_reports_unlinked_questions(
    client, tutor, student, group, subject
):
    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": group["id"], "title": "No-PDF homework"},
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]

    replace = await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[
            {
                "number": str(n),
                "text_summary": f"Q{n}",
                "max_marks": 2,
                "has_mark_scheme": False,
                "topic_ids": [],
            }
            for n in (1, 2, 3)
        ],
        headers=tutor["headers"],
    )
    assert replace.status_code == 200, replace.text
    questions = replace.json()["questions"]
    assert len(questions) == 3

    publish = await client.post(f"/api/v1/assignments/{aid}/publish", headers=tutor["headers"])
    assert publish.status_code == 200, publish.text

    # Link a topic to exactly one of the three questions, so two remain bare.
    async with async_session() as session:
        session.add(QuestionTopic(question_id=questions[0]["id"], topic_id=subject["topic1"]))
        await session.commit()

    submit = await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert submit.status_code in (200, 201), submit.text

    subs = await client.get(f"/api/v1/assignments/{aid}/submissions", headers=tutor["headers"])
    sid = subs.json()[0]["id"]

    detail = await client.get(f"/api/v1/submissions/{sid}", headers=tutor["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["bare_question_count"] == 2
