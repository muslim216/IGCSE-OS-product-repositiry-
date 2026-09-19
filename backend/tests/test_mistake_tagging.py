"""The AI tagging job (4.2, AV-40).

A settled submission is examined once: every question that lost marks is
tagged with the tutor's own categories and with the topics that question
tests. The job writes only `source="ai"` rows and replaces only its own on a
re-run, which is what makes it safe to re-run (E17, decision 8) and what makes
the tutor's re-tag button safe in 4.3.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models import (
    Mistake,
    MistakeSource,
    MistakeTopic,
    QuestionMark,
    Submission,
    SubmissionStatus,
    Topic,
    WorkKind,
)
from app.services.work import create_work
from tests.factories import make_mistake_category, make_subject


@pytest.fixture
async def org_and_subject(tutor):
    """An (organization_id, subject_id) pair in the tutor's own organization —
    the same setup `test_mistake_categories.py`'s fixture of the same name
    uses."""
    async with async_session() as session:
        subject = await make_subject(session)
        await session.commit()
        return subject.organization_id, subject.id


@pytest.fixture
async def topics(org_and_subject):
    """Two Topic rows on the subject — what a multi-topic question tests."""
    _, subject_id = org_and_subject
    async with async_session() as session:
        t1 = Topic(subject_id=subject_id, code="1.1", title="Topic one")
        t2 = Topic(subject_id=subject_id, code="1.2", title="Topic two")
        session.add_all([t1, t2])
        await session.commit()
        return [t1.id, t2.id]


@pytest.fixture
async def mistake_row(tutor, org_and_subject):
    """A submission, a QuestionMark, a MistakeCategory
    (`tests/factories.make_mistake_category`) and one Mistake with
    `source=MistakeSource.ai`, returning its id."""
    org_id, subject_id = org_and_subject
    async with async_session() as session:
        work = await create_work(
            session,
            kind=WorkKind.homework,
            organization_id=org_id,
            subject_id=subject_id,
            title="HW",
        )
        submission = Submission(
            work_id=work.id,
            student_id=tutor["user"]["id"],
            status=SubmissionStatus.finalized,
        )
        session.add(submission)
        await session.flush()
        mark = QuestionMark(submission_id=submission.id, final_marks=0)
        session.add(mark)
        await session.flush()
        category = await make_mistake_category(
            session, organization_id=org_id, subject_id=subject_id
        )
        mistake = Mistake(
            student_id=tutor["user"]["id"],
            question_mark_id=mark.id,
            category_id=category.id,
            severity=1,
            source=MistakeSource.ai,
        )
        session.add(mistake)
        await session.commit()
        return mistake.id


async def test_a_mistake_records_every_topic_its_question_tests(mistake_row, topics):
    """Decision 11: a question carrying two topics produces one mistake
    against both, never one topic picked out of two and never a skipped
    question. `Mistake.topic_id` held exactly one, which is why it is a link
    table now."""
    async with async_session() as session:
        session.add_all([MistakeTopic(mistake_id=mistake_row, topic_id=t) for t in topics[:2]])
        await session.commit()

    async with async_session() as session:
        linked = (
            await session.scalars(
                select(MistakeTopic.topic_id).where(MistakeTopic.mistake_id == mistake_row)
            )
        ).all()
    assert sorted(linked) == sorted(topics[:2])


async def test_one_topic_cannot_be_linked_to_one_mistake_twice(mistake_row, topics):
    """The link table is the set of topics a question tests, so a repeat is
    not a second fact. Without the constraint a re-tag that half-ran would
    double every topic and the 4.4 rollups would count them twice."""
    async with async_session() as session:
        session.add(MistakeTopic(mistake_id=mistake_row, topic_id=topics[0]))
        await session.commit()

    async with async_session() as session:
        session.add(MistakeTopic(mistake_id=mistake_row, topic_id=topics[0]))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_a_mistake_says_who_made_it(mistake_row):
    """E17 rests entirely on this column: the job deletes `source="ai"` rows
    and nothing else, so a mistake with no source would be deleted or spared
    by accident rather than by rule."""
    async with async_session() as session:
        mistake = await session.get(Mistake, mistake_row)
        assert mistake.source is MistakeSource.ai
