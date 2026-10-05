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
    FactorConfidence,
    FactorEvaluation,
    MistakeCategory,
    Organization,
    ReadinessFactor,
    ReadinessSnapshot,
    Subject,
    SubjectLevel,
    Topic,
)
from app.services.grade_boundaries import defaults_for_scale, set_org_boundaries


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


# --- Notifications (task 8.1) -------------------------------------------------


async def register_parent(client, tutor, student, email="parent@example.com") -> dict:
    """A parent linked to `student` through the real invite flow."""
    code = await client.post(
        f"/api/v1/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
    )
    reg = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code.json()["code"],
            "name": "Parent",
            "email": email,
            "password": "password123",
        },
    )
    assert reg.status_code == 201, reg.text
    return {
        "user": reg.json()["user"],
        "headers": {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"},
    }


async def register_other_tutor(client, email="other@example.com") -> dict:
    """A tutor in a different organization, for cross-tenant negative tests."""
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": email, "password": "password123"},
    )
    assert reg.status_code == 201, reg.text
    return {
        "user": reg.json()["user"],
        "headers": {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"},
    }


class FakeChannel:
    """A delivery adapter that records sends and replays scripted outcomes.

    `outcomes` is consumed one per send: a string is the provider message id, an
    exception is raised. When it runs out every send succeeds.
    """

    def __init__(self, name: str, *, available: bool = True, outcomes=None) -> None:
        self.name = name
        self._available = available
        self.outcomes = list(outcomes or [])
        self.sent: list[dict] = []

    def available(self) -> bool:
        return self._available

    async def send(self, address, template, params, link_url, *, language="en") -> str:
        self.sent.append(
            {
                "address": address,
                "template": template,
                "params": params,
                "link_url": link_url,
                "language": language,
            }
        )
        outcome = self.outcomes.pop(0) if self.outcomes else f"{self.name}-msg-{len(self.sent)}"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def patch_channels(monkeypatch, *, whatsapp=None, email=None) -> dict:
    """Substitute the delivery adapters; returns them keyed by channel."""
    from app.models import NotificationChannel
    from app.services.notifications import service

    fakes = {
        NotificationChannel.whatsapp: whatsapp or FakeChannel("whatsapp"),
        NotificationChannel.email: email or FakeChannel("email"),
    }
    monkeypatch.setattr(service, "channel_registry", lambda: fakes)
    return fakes


async def add_contact(
    session, user_id: int, *, channel, address: str, confirmed: bool = True, organization_id=None
):
    """A ContactPoint row, confirmed by default."""
    from app.models import ContactPoint, User
    from app.models.base import utcnow

    user = await session.get(User, user_id)
    contact = ContactPoint(
        organization_id=organization_id or user.organization_id,
        user_id=user_id,
        channel=channel,
        address=address,
        confirmed_at=utcnow() if confirmed else None,
    )
    session.add(contact)
    await session.flush()
    return contact
