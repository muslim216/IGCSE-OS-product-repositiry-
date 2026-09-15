"""Shared construction helpers for tests.

`Subject` gained two NOT NULL columns in task 2.2 — `organization_id` and
`level` — and roughly twenty-five fixtures build one directly. These exist so
that stays one edit next time rather than twenty-five.
"""

from sqlalchemy import select

from app.models import Organization, Subject, SubjectLevel
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
