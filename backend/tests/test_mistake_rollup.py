"""The per-topic and per-chapter rollup of a student's tagged mistakes (4.4).

Read time, all time, one student and one subject. What this file pins down is
mostly what must *not* vanish: the three ways a row silently leaves an
aggregation (no topic link, no chapter, one mistake on several topics) are each
a reachable state today, and each of them fails by producing a smaller number
rather than an error (`PROD-2`, `RISK-5`).
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Chapter,
    Mistake,
    MistakeCategory,
    MistakeSource,
    MistakeTopic,
    PastPaperQuestion,
    QuestionMark,
    Subject,
    Submission,
    SubmissionStatus,
    Topic,
)
from app.models.base import utcnow
from tests.factories import (
    make_mistake_category,
    make_past_paper,
    make_subject,
    other_org_subject,
)


async def _add_mistake(session, *, student_id, mark_id, category_id, severity, topic_ids, source):
    mistake = Mistake(
        student_id=student_id,
        question_mark_id=mark_id,
        category_id=category_id,
        severity=severity,
        source=source,
    )
    session.add(mistake)
    await session.flush()
    for topic_id in topic_ids:
        session.add(MistakeTopic(mistake_id=mistake.id, topic_id=topic_id))
    return mistake


async def _settled_submission(session, *, subject_id, organization_id, student_id, analysed, marks):
    """A finalized past-paper submission with `marks` question marks on it.

    A past paper because it is the plainest work a tutor owns at organization
    level, and because the rollup must not care which kind of work a mistake
    was made on — the query joins `AssessableWork`, not `Assignment` (`API-20`).
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


@pytest.fixture
async def rollup(client, tutor, subject, student):
    """Five mistakes covering every shape the rollup has to survive.

    topic1 sits in a chapter, topic3 sits in the same chapter, topic2 has no
    chapter at all. M3 is on a question testing two topics of one chapter; M4
    is on a bare question with no topics; M5 was entered by a tutor.
    """
    async with async_session() as session:
        subject_id = subject["id"]
        organization_id = (await session.get(Subject, subject_id)).organization_id

        chapter = Chapter(subject_id=subject_id, code="C1", title="Bonding", position=0)
        session.add(chapter)
        await session.flush()
        topic1 = await session.get(Topic, subject["topic1"])
        topic1.chapter_id = chapter.id
        topic3 = Topic(
            subject_id=subject_id, code="1.9", title="Electrolysis", chapter_id=chapter.id
        )
        session.add(topic3)
        await session.flush()

        careless = await make_mistake_category(
            session, organization_id=organization_id, subject_id=subject_id, name="careless"
        )
        method = await make_mistake_category(
            session, organization_id=organization_id, subject_id=subject_id, name="method"
        )

        student_id = student["user"]["id"]
        marks = await _settled_submission(
            session,
            subject_id=subject_id,
            organization_id=organization_id,
            student_id=student_id,
            analysed=True,
            marks=4,
        )
        common = {"student_id": student_id, "source": MistakeSource.ai}
        await _add_mistake(
            session,
            mark_id=marks[0],
            category_id=careless.id,
            severity=1,
            topic_ids=[topic1.id],
            **common,
        )
        await _add_mistake(
            session,
            mark_id=marks[0],
            category_id=method.id,
            severity=3,
            topic_ids=[topic1.id],
            **common,
        )
        await _add_mistake(
            session,
            mark_id=marks[1],
            category_id=careless.id,
            severity=2,
            topic_ids=[topic1.id, topic3.id],
            **common,
        )
        await _add_mistake(
            session,
            mark_id=marks[2],
            category_id=careless.id,
            severity=2,
            topic_ids=[],
            **common,
        )
        # Tutor-entered, not AI-tagged. Everything below counts it identically.
        await _add_mistake(
            session,
            student_id=student_id,
            mark_id=marks[3],
            category_id=method.id,
            severity=1,
            topic_ids=[subject["topic2"]],
            source=MistakeSource.tutor,
        )
        await session.commit()
        return {
            "subject_id": subject_id,
            "organization_id": organization_id,
            "student_id": student_id,
            "chapter_id": chapter.id,
            "topic1": topic1.id,
            "topic2": subject["topic2"],
            "topic3": topic3.id,
        }


async def _get(client, tutor, student_id, subject_id):
    resp = await client.get(
        f"/api/v1/students/{student_id}/mistakes",
        params={"subject_id": subject_id},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _topic(body, topic_id):
    return next(t for t in body["topics"] if t["topic_id"] == topic_id)


async def test_counts_and_severity_per_topic_and_chapter(client, tutor, rollup):
    """The rollup's whole purpose: which part of the syllabus this student keeps
    losing marks on, and how heavily. If the category breakdown or the severity
    sum drifts, a tutor plans the next lesson against a picture of the student
    that is not the one in the marks."""
    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])

    topic1 = _topic(body, rollup["topic1"])
    assert topic1["topic_title"] == "Atomic structure"
    assert topic1["chapter_id"] == rollup["chapter_id"]
    assert topic1["tally"]["mistakes"] == 3
    assert topic1["tally"]["severity_total"] == 6
    assert {
        (c["category_name"], c["mistakes"], c["severity_total"])
        for c in topic1["tally"]["categories"]
    } == {
        ("careless", 2, 3),
        ("method", 1, 3),
    }

    chapter = next(c for c in body["chapters"] if c["chapter_id"] == rollup["chapter_id"])
    # Three, not four: the two-topic mistake touches two topics of this chapter
    # and is still one mistake the student made.
    assert chapter["tally"]["mistakes"] == 3
    assert chapter["tally"]["severity_total"] == 6
    assert body["analysed_questions"] == 4


async def test_a_mistake_with_no_topic_links_is_not_lost(client, tutor, rollup):
    """A question whose extraction found no topics produces a mistake linked to
    nothing (decision 15). An inner join to Topic drops it, and the per-topic
    rows then stop reconciling with the subject count the readiness factor uses
    — a smaller number, no error, nothing to notice (`RISK-5`)."""
    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])

    assert body["topicless"]["mistakes"] == 1
    assert body["topicless"]["severity_total"] == 2
    assert [c["category_name"] for c in body["topicless"]["categories"]] == ["careless"]
    # Four of the five mistakes are linked to a topic, and one of those four is
    # linked to two — so the topic rows add to five while the untopic'd one is
    # in none of them. It is still in the subject total.
    assert sum(t["tally"]["mistakes"] for t in body["topics"]) == 5
    assert body["total"]["mistakes"] == 5


async def test_a_topic_with_no_chapter_is_not_lost(client, tutor, rollup):
    """`topics.chapter_id` is nullable until syllabus extraction is chapter-first
    (task 2.3), so most topics in production have no chapter today. An inner
    join to Chapter would silently empty the chapter view for exactly the
    tenants who have not migrated."""
    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])

    topic2 = _topic(body, rollup["topic2"])
    assert topic2["chapter_id"] is None
    assert topic2["tally"]["mistakes"] == 1
    assert body["chapterless"]["mistakes"] == 1
    assert body["chapterless"]["severity_total"] == 1
    assert [c["chapter_id"] for c in body["chapters"]] == [rollup["chapter_id"]]


async def test_a_two_topic_mistake_counts_twice_by_topic_and_once_in_total(client, tutor, rollup):
    """Decision 11: every topic a question tests, never a skip. That makes the
    per-topic rows deliberately un-summable, so the subject total has to come
    from distinct mistakes — otherwise every multi-topic question inflates the
    one number a tutor would read as "how much is going wrong"."""
    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])

    assert _topic(body, rollup["topic3"])["tally"]["mistakes"] == 1
    assert _topic(body, rollup["topic1"])["tally"]["mistakes"] == 3
    # Five mistakes, five topic rows — and the two numbers agreeing here is a
    # coincidence of this fixture, not a rule. That is the point: only `total`
    # is the subject figure.
    assert body["total"]["mistakes"] == 5
    assert body["total"]["severity_total"] == 9
    assert {(c["category_name"], c["mistakes"]) for c in body["total"]["categories"]} == {
        ("careless", 3),
        ("method", 2),
    }


async def test_unexamined_work_contributes_nothing(client, tutor, subject, student, rollup):
    """`mistakes_analysed_at` is the gate the readiness factor counts its
    denominator on. Counting mistakes from a submission the denominator does not
    count as examined is the two-halves-of-one-ratio bug written down at
    `readiness_v2.py:304-312`, and it understates a score with nothing logged."""
    async with async_session() as session:
        careless = await make_mistake_category(
            session,
            organization_id=rollup["organization_id"],
            subject_id=rollup["subject_id"],
            name="unexamined",
        )
        marks = await _settled_submission(
            session,
            subject_id=rollup["subject_id"],
            organization_id=rollup["organization_id"],
            student_id=rollup["student_id"],
            analysed=False,
            marks=1,
        )
        await _add_mistake(
            session,
            student_id=rollup["student_id"],
            mark_id=marks[0],
            category_id=careless.id,
            severity=3,
            topic_ids=[rollup["topic1"]],
            source=MistakeSource.ai,
        )
        await session.commit()

    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])
    assert body["total"]["mistakes"] == 5
    assert _topic(body, rollup["topic1"])["tally"]["mistakes"] == 3
    # The unexamined question is out of the denominator too, not just the
    # numerator — both halves carry the same gate or the ratio is nonsense.
    assert body["analysed_questions"] == 4


async def test_a_tutor_entered_mistake_counts_like_an_ai_one(client, tutor, rollup):
    """`Mistake.source` says who wrote the row so the tagging job can replace
    its own without touching a tutor's (E17). It is not a statement about what
    counts — filtering on it would drop precisely the observations somebody
    qualified made by hand (`PROD-7`)."""
    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])

    # The tutor-entered mistake is the only one on topic2, and the only one in
    # the no-chapter bucket.
    assert _topic(body, rollup["topic2"])["tally"]["mistakes"] == 1
    assert body["chapterless"]["mistakes"] == 1
    assert body["total"]["mistakes"] == 5


async def test_a_subject_with_no_mistakes_is_empty_not_an_error(client, tutor, rollup):
    """Nothing fabricated and nothing raised. The caller distinguishes "clean
    record" from "nobody has looked" by `analysed_questions`, which is why it is
    returned even when every bucket is empty (`PROD-2`, `UX-19`)."""
    async with async_session() as session:
        other = await make_subject(session, code="4PH1", name="Physics")
        other_id = other.id
        await session.commit()

    body = await _get(client, tutor, rollup["student_id"], other_id)
    assert body["total"] == {"mistakes": 0, "severity_total": 0, "categories": []}
    assert body["topics"] == []
    assert body["chapters"] == []
    assert body["topicless"]["mistakes"] == 0
    assert body["chapterless"]["mistakes"] == 0
    assert body["analysed_questions"] == 0


async def test_another_organizations_student_is_404(client, tutor, rollup):
    """Tenant scope comes from the authenticated user, never from the path
    (`SEC-7`, `PROD-4`). 404 and not 403: integer keys are enumerable, and a 403
    confirms a student by that id exists somewhere (`API-7`, `SEC-9`)."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Rival", "email": "rival@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    rival = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}

    resp = await client.get(
        f"/api/v1/students/{rollup['student_id']}/mistakes",
        params={"subject_id": rollup["subject_id"]},
        headers=rival,
    )
    assert resp.status_code == 404, resp.text


async def test_a_student_cannot_call_the_tutor_route(client, student, rollup):
    """The gate is in the signature (`user: TutorUser`), so it cannot be
    forgotten — and this route hands over severity, which 4.5 deliberately keeps
    away from the student it describes (`SEC-11`, `BE-17`)."""
    resp = await client.get(
        f"/api/v1/students/{rollup['student_id']}/mistakes",
        params={"subject_id": rollup["subject_id"]},
        headers=student["headers"],
    )
    assert resp.status_code == 403, resp.text


async def test_another_organizations_subject_is_404(client, tutor, rollup):
    """Subjects are global rows owned by one tenant, so scoping a read by
    subject alone leaks across tenants (`SEC-8`). The tutor owns the student
    here; only the subject is someone else's."""
    async with async_session() as session:
        # Another tenant's subject. The student and the caller are otherwise
        # identical to the passing case, so the organization check on the
        # subject is the only thing that can be answering.
        rival_id = (await other_org_subject(session, code="4RV1")).id
        await session.commit()

    resp = await client.get(
        f"/api/v1/students/{rollup['student_id']}/mistakes",
        params={"subject_id": rival_id},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text


async def test_a_mistake_spanning_a_chaptered_and_a_chapterless_topic_is_in_both(
    client, tutor, rollup
):
    """One mistake, two topics, only one of which has a chapter. It belongs in
    that chapter *and* in `chapterless` — the chapter genuinely saw it, and
    dropping it from `chapterless` would hide that part of the syllabus has no
    chapter to file it under (task 2.3, `PROD-2`).

    Pinned because it is the one shape the response cannot express as a sum:
    `chapters[].mistakes + chapterless.mistakes` counts this mistake twice, and
    a client that adds them shows a tutor a number no row supports. The schema
    says so; this proves the service actually behaves that way.
    """
    async with async_session() as session:
        marks = await _settled_submission(
            session,
            subject_id=rollup["subject_id"],
            organization_id=rollup["organization_id"],
            student_id=rollup["student_id"],
            analysed=True,
            marks=1,
        )
        category = await session.scalar(
            select(MistakeCategory).where(MistakeCategory.name == "careless")
        )
        await _add_mistake(
            session,
            student_id=rollup["student_id"],
            mark_id=marks[0],
            category_id=category.id,
            severity=3,
            # topic1 is in the chapter; topic2 has no chapter at all.
            topic_ids=[rollup["topic1"], rollup["topic2"]],
            source=MistakeSource.ai,
        )
        await session.commit()

    body = await _get(client, tutor, rollup["student_id"], rollup["subject_id"])

    assert body["total"]["mistakes"] == 6
    chapter = next(c for c in body["chapters"] if c["chapter_id"] == rollup["chapter_id"])
    assert chapter["tally"]["mistakes"] == 4
    assert body["chapterless"]["mistakes"] == 2
    # The sum is 6 against a true total of 6 only by coincidence of this
    # fixture; what the assertion above pins is that the new mistake is in
    # both, which is why the two must never be added.
    assert _topic(body, rollup["topic1"])["tally"]["mistakes"] == 4
    assert _topic(body, rollup["topic2"])["tally"]["mistakes"] == 2


async def test_examined_and_clean_is_not_the_same_as_never_examined(
    client, tutor, subject, student
):
    """The distinction 4.0 added `mistakes_analysed_at` to make, end to end on
    one subject: work that was examined and had nothing wrong reads as a clean
    record, and work nobody examined reads as no data.

    Both return zero mistakes. `analysed_questions` is the only thing that
    tells them apart, so if it ever stopped being populated the two would
    render identically and a student nobody had looked at would show as
    flawless — the fabricated `100.0` this phase exists to remove (`PROD-2`,
    `UX-19`).
    """
    async with async_session() as session:
        subject_id = subject["id"]
        organization_id = (await session.get(Subject, subject_id)).organization_id
        await _settled_submission(
            session,
            subject_id=subject_id,
            organization_id=organization_id,
            student_id=student["user"]["id"],
            analysed=False,
            marks=3,
        )
        await session.commit()

    unexamined = await _get(client, tutor, student["user"]["id"], subject["id"])
    assert unexamined["total"]["mistakes"] == 0
    assert unexamined["analysed_questions"] == 0

    async with async_session() as session:
        subject_id = subject["id"]
        organization_id = (await session.get(Subject, subject_id)).organization_id
        await _settled_submission(
            session,
            subject_id=subject_id,
            organization_id=organization_id,
            student_id=student["user"]["id"],
            analysed=True,
            marks=3,
        )
        await session.commit()

    clean = await _get(client, tutor, student["user"]["id"], subject["id"])
    # Same zero, different meaning — and the response says which.
    assert clean["total"]["mistakes"] == 0
    assert clean["analysed_questions"] == 3
