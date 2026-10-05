"""Shared construction helpers for tests.

`Subject` gained two NOT NULL columns in task 2.2 — `organization_id` and
`level` — and roughly twenty-five fixtures build one directly. These exist so
that stays one edit next time rather than twenty-five.
"""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models import (
    AiSynthesisStatus,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    FactorConfidence,
    FactorEvaluation,
    MistakeCategory,
    Organization,
    ParentLink,
    QuestionTopic,
    ReadinessFactor,
    ReadinessSnapshot,
    Subject,
    SubjectLevel,
    Submission,
    SubmissionStatus,
    Topic,
    User,
    UserRole,
    WorkKind,
)
from app.security import hash_password
from app.services.grade_boundaries import defaults_for_scale, set_org_boundaries
from app.services.work import create_work


async def org_id(session) -> int:
    """The organization the calling test's fixtures already created.

    Most fixtures build a subject after the `tutor` fixture has registered an
    account, which creates an organization; this finds it rather than making a
    second one. Tests that genuinely need a *second* tenant create it explicitly
    — see `other_org_subject`.
    """
    existing = await session.scalar(select(Organization.id).order_by(Organization.id))
    if existing is not None:
        return existing
    org = Organization(name="Test Organization")
    session.add(org)
    await session.flush()
    return org.id


async def make_subject(
    session,
    *,
    organization_id: int | None = None,
    grade_boundaries: list[dict] | None = None,
    **kwargs,
) -> Subject:
    """A Subject with the columns every test needs and none of them care about,
    plus its organization's grade boundaries."""
    bands = grade_boundaries
    kwargs.setdefault("exam_board", "Edexcel IGCSE")
    kwargs.setdefault("code", "4CH1")
    kwargs.setdefault("name", "Chemistry")
    kwargs.setdefault("grade_scale", "9-1")
    kwargs.setdefault("level", SubjectLevel.igcse)
    subject = Subject(
        organization_id=organization_id if organization_id is not None else await org_id(session),
        **kwargs,
    )
    session.add(subject)
    await session.flush()
    # Grade boundaries are org-scoped rows since task 2.4 (AV-11), and a subject
    # without them has no predicted grade anywhere — correct behaviour, but not
    # what most tests are about. Set them here so `make_subject` still returns a
    # subject whose grades work; a test about the *absence* asks for it with
    # `grade_boundaries=[]`.
    await set_org_boundaries(
        session,
        subject.organization_id,
        subject.id,
        defaults_for_scale(kwargs["grade_scale"]) if bands is None else bands,
    )
    return subject


async def make_mistake_category(
    session, *, organization_id: int, subject_id: int, name: str = "careless", **kwargs
) -> MistakeCategory:
    """A MistakeCategory row for tests building a `Mistake` directly.

    `Mistake.category_id` became a required FK in 4.1 — the enum a test used
    to point at with a bare value is gone, so a row has to exist first.
    """
    category = MistakeCategory(
        organization_id=organization_id, subject_id=subject_id, name=name, **kwargs
    )
    session.add(category)
    await session.flush()
    return category


async def other_org_subject(session, **kwargs) -> Subject:
    """A subject belonging to a *different* tenant, for cross-org negative tests."""
    org = Organization(name="Another Organization")
    session.add(org)
    await session.flush()
    return await make_subject(session, organization_id=org.id, **kwargs)


async def subject_defaults(session) -> dict:
    """The two columns task 2.2 made mandatory, as kwargs.

    Spread into an existing `Subject(...)` so each test keeps stating the fields
    it actually cares about: `Subject(**await subject_defaults(session), code=...)`.
    """
    return {"organization_id": await org_id(session), "level": SubjectLevel.igcse}


NINE_TO_ONE_BOUNDS = [
    {"grade": "9", "min": 90},
    {"grade": "8", "min": 80},
    {"grade": "7", "min": 70},
    {"grade": "6", "min": 60},
    {"grade": "5", "min": 50},
    {"grade": "4", "min": 40},
    {"grade": "U", "min": 0},
]


async def chemistry_with_topics(session, titles: list[str]) -> tuple[int, list[int]]:
    """A 9-1 Chemistry subject with the given topics (codes "1", "2", ...) and
    round-number boundaries, committed. Returns (subject_id, topic_ids) so a
    verdict test can state only the topics it reasons about."""
    subject = Subject(
        **await subject_defaults(session),
        exam_board="Edexcel IGCSE",
        code="4CH1",
        name="Chemistry",
        grade_scale="9-1",
    )
    session.add(subject)
    await session.flush()
    topics = [
        Topic(subject_id=subject.id, code=str(i), title=t, weight=1.0)
        for i, t in enumerate(titles, start=1)
    ]
    session.add_all(topics)
    await set_org_boundaries(session, subject.organization_id, subject.id, NINE_TO_ONE_BOUNDS)
    await session.commit()
    return subject.id, [t.id for t in topics]


async def subject_for_tutor(session, email: str, **kwargs) -> Subject:
    """A subject owned by the organization of the tutor with this email.

    Cross-tenant tests register a rival tutor and then act as them. Since task
    2.2 a subject belongs to one organization, so the rival needs their own —
    reusing the first tutor's id now correctly returns 404, which is the
    behaviour those tests exist to prove, not a setup shortcut.
    """
    from app.models import User

    organization_id = await session.scalar(select(User.organization_id).where(User.email == email))
    kwargs.setdefault("code", "9RIV")
    return await make_subject(session, organization_id=organization_id, **kwargs)


async def make_past_paper(session, *, subject_id: int, organization_id: int, **kwargs):
    """A past paper and the booklet it belongs to.

    Every past paper has a booklet — a single upload becomes a booklet of one
    (task 3.5), so `PastPaper.booklet_id` is NOT NULL. Four test files built a
    `PastPaper` directly and all four broke the moment that column arrived,
    which is the same reason this module exists at all. Build papers through
    here so the next NOT NULL column is one edit, not four.

    Pass `booklet=` to attach the paper to a booklet you already made — that is
    what a real multi-paper booklet looks like.
    """
    from app.models import Booklet, BookletStatus, PastPaper, WorkKind
    from app.services.work import create_work

    booklet = kwargs.pop("booklet", None)
    if booklet is None:
        booklet = Booklet(
            organization_id=organization_id,
            subject_id=subject_id,
            tutor_id=kwargs.get("tutor_id"),
            status=BookletStatus.applied,
            file_path=kwargs.get("paper_path"),
            file_name=kwargs.get("paper_name"),
            file_mime=kwargs.get("paper_mime"),
        )
        session.add(booklet)
        await session.flush()

    work = await create_work(
        session,
        kind=WorkKind.past_paper,
        organization_id=organization_id,
        subject_id=subject_id,
        title=kwargs.get("title"),
    )

    kwargs.setdefault("booklet_index", 1)
    paper = PastPaper(
        organization_id=organization_id,
        subject_id=subject_id,
        booklet_id=booklet.id,
        work_id=work.id,
        **kwargs,
    )
    session.add(paper)
    await session.flush()
    return paper


async def write_v2_snapshot(
    session,
    *,
    student_id: int,
    subject_id: int,
    score: float | None,
    predicted_grade: str | None = None,
    topics: dict[int, tuple[float | None, FactorConfidence]] | None = None,
    homework: tuple[int, int] | None = None,  # (assignment_count, submitted_count)
    created_at: datetime | None = None,
    status: AiSynthesisStatus = AiSynthesisStatus.ready,
) -> str:
    """One completed v2 run: the factor rows a reader needs plus the snapshot
    synthesized from them, sharing one evaluation_run_id. Replaces every test
    fixture that wrote TopicReadiness/ReadinessHistory (5.3a)."""
    run_id = str(uuid.uuid4())
    for topic_id, (topic_score, confidence) in (topics or {}).items():
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id,
                student_id=student_id,
                subject_id=subject_id,
                topic_id=topic_id,
                factor=ReadinessFactor.topic_mastery,
                score=topic_score,
                confidence=confidence,
                evidence_count=0 if topic_score is None else 3,
                detail={},
            )
        )
    if homework is not None:
        session.add(
            FactorEvaluation(
                evaluation_run_id=run_id,
                student_id=student_id,
                subject_id=subject_id,
                topic_id=None,
                factor=ReadinessFactor.homework_performance,
                score=None,
                confidence=FactorConfidence.no_data,
                evidence_count=0,
                detail={"assignment_count": homework[0], "submitted_count": homework[1]},
            )
        )
    session.add(
        ReadinessSnapshot(
            evaluation_run_id=run_id,
            student_id=student_id,
            subject_id=subject_id,
            status=status,
            score=score,
            predicted_grade=predicted_grade,
            weak_topics=[],
            rationale="fixture",
            recommended_revision=None,
            **({"created_at": created_at} if created_at else {}),
        )
    )
    await session.flush()
    return run_id


async def make_user(
    session, *, organization_id: int, role: UserRole, name: str, email: str, **kwargs
) -> User:
    """A user of any role without going through registration, for tests that need
    a second tenant's tutor or a parent."""
    user = User(
        organization_id=organization_id,
        role=role,
        name=name,
        email=email,
        password_hash=hash_password("password123"),
        **kwargs,
    )
    session.add(user)
    await session.flush()
    return user


async def link_parent(session, parent_id: int, student_id: int) -> None:
    session.add(ParentLink(parent_id=parent_id, student_id=student_id))
    await session.flush()


async def publish_assignment(
    session,
    *,
    group_id: int,
    subject_id: int,
    organization_id: int,
    title: str = "HW",
    due_at: datetime | None = None,
    created_at: datetime | None = None,
    topic_ids: tuple[int, ...] = (),
) -> Assignment:
    """A published assignment (with its work row) carrying one question per given
    topic, so a test can say which chapter it covers."""
    work = await create_work(
        session,
        kind=WorkKind.homework,
        organization_id=organization_id,
        subject_id=subject_id,
        title=title,
    )
    assignment = Assignment(
        group_id=group_id,
        work_id=work.id,
        title=title,
        due_at=due_at,
        status=AssignmentStatus.published,
        **({"created_at": created_at} if created_at else {}),
    )
    session.add(assignment)
    await session.flush()
    for position, topic_id in enumerate(topic_ids):
        question = AssignmentQuestion(
            assignment_id=assignment.id,
            position=position,
            number=str(position + 1),
            text_summary="q",
            max_marks=2,
        )
        session.add(question)
        await session.flush()
        session.add(QuestionTopic(question_id=question.id, topic_id=topic_id))
    await session.flush()
    return assignment


async def submit_work(
    session,
    *,
    assignment: Assignment,
    student_id: int,
    status: SubmissionStatus,
    submitted_at: datetime,
    finalized_at: datetime | None = None,
    **kwargs,
) -> Submission:
    submission = Submission(
        work_id=assignment.work_id,
        student_id=student_id,
        status=status,
        submitted_at=submitted_at,
        finalized_at=finalized_at,
        **kwargs,
    )
    session.add(submission)
    await session.flush()
    return submission


async def set_boundaries(subject_id: int, bounds: list[dict] | None = None) -> None:
    """Round-number 9-1 boundaries for a subject a fixture built without any, in
    its own session (for tests that hold a subject id, not a session)."""
    from app.db import async_session

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
        assert subject is not None
        await set_org_boundaries(
            session, subject.organization_id, subject_id, bounds or NINE_TO_ONE_BOUNDS
        )
        await session.commit()
