"""The student's own view of their mistake pattern (4.5).

`GET /api/v1/me/mistakes` is the same computation as the tutor's rollup with
two things removed: severity, and the per-topic/per-chapter breakdown. What
this file pins is mostly the removal. Severity is an internal weighting signal
and reads as a verdict to the person who made the mistakes, so a response that
carries it "for the client to ignore" is the failure, not a convenience —
hence `test_no_severity_anywhere_in_the_response`, which walks the serialized
body rather than naming the fields it expects to be gone.
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    Mistake,
    MistakeSource,
    MistakeTopic,
    PastPaperQuestion,
    QuestionMark,
    Subject,
    Submission,
    SubmissionStatus,
)
from app.models.base import utcnow
from tests.factories import make_mistake_category, make_past_paper, make_subject


async def _settled_submission(session, *, subject_id, organization_id, student_id, analysed, marks):
    """A finalized past-paper submission carrying `marks` question marks.

    Past paper rather than assignment for the reason 4.4's file gives: the
    rollup joins `AssessableWork`, so the kind of work must not matter
    (`API-20`).
    """
    paper = await make_past_paper(session, subject_id=subject_id, organization_id=organization_id)
    submission = Submission(
        work_id=paper.work_id,
        student_id=student_id,
        status=SubmissionStatus.finalized,
        mistakes_analysed_at=utcnow() if analysed else None,
    )
    session.add(submission)
    await session.flush()
    mark_ids = []
    for position in range(marks):
        question = PastPaperQuestion(
            past_paper_id=paper.id,
            position=position,
            number=str(position + 1),
            text_summary="Question",
            max_marks=4,
            has_mark_scheme=True,
        )
        session.add(question)
        await session.flush()
        mark = QuestionMark(
            submission_id=submission.id, past_paper_question_id=question.id, final_marks=1
        )
        session.add(mark)
        await session.flush()
        mark_ids.append(mark.id)
    return mark_ids


async def _add_mistake(session, *, student_id, mark_id, category_id, severity, topic_ids=()):
    mistake = Mistake(
        student_id=student_id,
        question_mark_id=mark_id,
        category_id=category_id,
        severity=severity,
        source=MistakeSource.ai,
    )
    session.add(mistake)
    await session.flush()
    for topic_id in topic_ids:
        session.add(MistakeTopic(mistake_id=mistake.id, topic_id=topic_id))
    return mistake


async def _enrol(session, *, student_id, subject_id, organization_id, name):
    """Put the student in a group for this subject.

    Enrolment, not organization membership, is what `visible_subject_ids`
    scopes a student by (`SEC-8`) — so a subject only reaches this endpoint
    through a group the student is actually in.
    """
    group = Group(
        name=name,
        subject_id=subject_id,
        organization_id=organization_id,
        # The tutor the `group` fixture already made — this student's own tutor,
        # so these subjects reach them by the same route the first one did.
        tutor_id=await session.scalar(select(Group.tutor_id).order_by(Group.id).limit(1)),
    )
    session.add(group)
    await session.flush()
    session.add(GroupMember(group_id=group.id, student_id=student_id))
    await session.flush()
    return group


@pytest.fixture
async def pattern(client, tutor, subject, student):
    """Four subjects covering every state the student's section has to tell apart.

    Chemistry (the `subject` fixture, already enrolled via `group`): five
    mistakes, three careless and two method. Physics: examined, no mistakes.
    Biology: enrolled but nothing examined. Geography: *not* enrolled, and
    seeded with mistakes anyway so its absence is a real exclusion rather than
    an empty subject that would look the same either way.
    """
    async with async_session() as session:
        subject_id = subject["id"]
        organization_id = (await session.get(Subject, subject_id)).organization_id
        student_id = student["user"]["id"]

        careless = await make_mistake_category(
            session, organization_id=organization_id, subject_id=subject_id, name="careless"
        )
        method = await make_mistake_category(
            session, organization_id=organization_id, subject_id=subject_id, name="method"
        )
        marks = await _settled_submission(
            session,
            subject_id=subject_id,
            organization_id=organization_id,
            student_id=student_id,
            analysed=True,
            marks=4,
        )
        # Two mistakes on one question, one on a question testing two topics,
        # one on a bare question with no topic links at all. The student's view
        # has no per-topic rows, so all four are simply mistakes here — which is
        # exactly the projection that must not lose one.
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=marks[0],
            category_id=careless.id,
            severity=1,
            topic_ids=[subject["topic1"]],
        )
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=marks[0],
            category_id=method.id,
            severity=3,
            topic_ids=[subject["topic1"]],
        )
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=marks[1],
            category_id=careless.id,
            severity=2,
            topic_ids=[subject["topic1"], subject["topic2"]],
        )
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=marks[2],
            category_id=careless.id,
            severity=2,
        )
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=marks[3],
            category_id=method.id,
            severity=1,
            topic_ids=[subject["topic2"]],
        )

        examined = await make_subject(
            session, organization_id=organization_id, code="4PH1", name="Physics"
        )
        await _enrol(
            session,
            student_id=student_id,
            subject_id=examined.id,
            organization_id=organization_id,
            name="Phys Y10",
        )
        await _settled_submission(
            session,
            subject_id=examined.id,
            organization_id=organization_id,
            student_id=student_id,
            analysed=True,
            marks=6,
        )

        untouched = await make_subject(
            session, organization_id=organization_id, code="4BI1", name="Biology"
        )
        await _enrol(
            session,
            student_id=student_id,
            subject_id=untouched.id,
            organization_id=organization_id,
            name="Bio Y10",
        )
        # A submission nothing has examined: settled work exists, so "no data"
        # here is the tagging job not having run, not the absence of work.
        await _settled_submission(
            session,
            subject_id=untouched.id,
            organization_id=organization_id,
            student_id=student_id,
            analysed=False,
            marks=3,
        )

        unenrolled = await make_subject(
            session, organization_id=organization_id, code="4GE1", name="Geography"
        )
        other_category = await make_mistake_category(
            session, organization_id=organization_id, subject_id=unenrolled.id, name="careless"
        )
        other_marks = await _settled_submission(
            session,
            subject_id=unenrolled.id,
            organization_id=organization_id,
            student_id=student_id,
            analysed=True,
            marks=2,
        )
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=other_marks[0],
            category_id=other_category.id,
            severity=3,
        )
        await session.commit()
        return {
            "chemistry": subject_id,
            "physics": examined.id,
            "biology": untouched.id,
            "geography": unenrolled.id,
        }


async def _get(client, student):
    resp = await client.get("/api/v1/me/mistakes", headers=student["headers"])
    assert resp.status_code == 200, resp.text
    return {entry["subject_name"]: entry for entry in resp.json()}


async def test_a_student_sees_their_own_pattern_by_category(client, student, pattern):
    """The point of the surface: what kinds of mistake this student makes, and
    how many. The counts are distinct mistakes, so the two on one question and
    the one spanning two topics each count once."""
    body = await _get(client, student)

    chemistry = body["Chemistry"]
    assert chemistry["subject_id"] == pattern["chemistry"]
    assert chemistry["analysed_questions"] == 4
    assert chemistry["total_mistakes"] == 5
    assert {(c["category_name"], c["mistakes"]) for c in chemistry["categories"]} == {
        ("careless", 3),
        ("method", 2),
    }


async def test_no_severity_anywhere_in_the_response(client, student, pattern):
    """The whole reason this endpoint has its own schema rather than reusing the
    tutor's (`StudentMistakeRollup`).

    Walked recursively rather than asserted field by field: reusing the tutor's
    model, or adding a nested one that carries severity later, is precisely the
    change a per-field assertion would not catch.
    """
    resp = await client.get("/api/v1/me/mistakes", headers=student["headers"])
    assert resp.status_code == 200, resp.text

    def walk(node, path="$"):
        if isinstance(node, dict):
            for key, value in node.items():
                assert "severity" not in key.lower(), f"severity leaked at {path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    body = resp.json()
    # Guard the guard: an empty body would pass the walk trivially.
    assert any(entry["total_mistakes"] > 0 for entry in body)
    walk(body)
    assert "severity" not in resp.text.lower()


async def test_a_subject_the_student_is_not_enrolled_in_does_not_appear(client, student, pattern):
    """Geography has settled, examined work and a tagged mistake on it, and the
    student is in no group for it. Enrolment is the scope (`SEC-8`), so the
    subject is absent entirely — not present with zeroes."""
    body = await _get(client, student)

    assert "Geography" not in body
    assert {"Chemistry", "Physics", "Biology"} == set(body)


async def test_nothing_examined_is_distinguishable_from_examined_with_no_mistakes(
    client, student, pattern
):
    """`PROD-2`. Biology has settled work nobody has examined; Physics has six
    examined questions and a clean record. Both have `total_mistakes == 0`, so
    `analysed_questions` is the only thing that tells them apart — if it
    collapsed to zero for both, the student's page would call an unexamined
    subject clean."""
    body = await _get(client, student)

    assert body["Biology"]["analysed_questions"] == 0
    assert body["Biology"]["total_mistakes"] == 0
    assert body["Physics"]["analysed_questions"] == 6
    assert body["Physics"]["total_mistakes"] == 0
    assert body["Physics"]["categories"] == []


async def test_a_tutor_cannot_call_the_student_route(client, tutor, student, pattern):
    """`QA-12`. The gate is `StudentUser` in the signature (`SEC-11`, `BE-17`);
    a tutor reads their students' mistakes through the tutor rollup, which
    carries severity because a tutor is the person severity is for.

    The second half is the control that matters more: there is no
    `student_id` anywhere in this request — no path segment and no query
    parameter — so there is nothing for a caller to substitute. A student
    naming another student is not rejected here, it is unexpressible, and
    `/me/mistakes/<anyone>` is simply not a route.
    """
    forbidden = await client.get("/api/v1/me/mistakes", headers=tutor["headers"])
    assert forbidden.status_code == 403, forbidden.text

    other_id = student["user"]["id"] + 1
    assert (
        await client.get(f"/api/v1/me/mistakes/{other_id}", headers=student["headers"])
    ).status_code == 404
    # And a `student_id` smuggled in as a query parameter is ignored, not honoured:
    # the answer is byte-identical to the one with no parameter at all.
    smuggled = await client.get(
        "/api/v1/me/mistakes", params={"student_id": other_id}, headers=student["headers"]
    )
    plain = await client.get("/api/v1/me/mistakes", headers=student["headers"])
    assert smuggled.status_code == 200
    assert smuggled.json() == plain.json()


async def test_the_route_needs_a_token(client, pattern):
    """`QA-12`: unauthenticated is 401, not an empty list."""
    assert (await client.get("/api/v1/me/mistakes")).status_code == 401
