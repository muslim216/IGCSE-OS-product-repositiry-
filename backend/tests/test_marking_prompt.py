"""The marking prompt must describe the documents actually attached.

A mark auto-finalizes only when it is scheme-backed and confident (AI-11,
ADR-0009). The model decides "scheme-backed" from what it is given and what the
prompt says it was given, so the two have to agree: told it has an official
mark scheme it cannot see, it can report exactly that, and the mark is written
final with no scheme behind it and no tutor in the loop.

Both attachment paths on PastPaper are nullable — the model says seed rows
predate file upload — and Classified.mark_scheme_mime is nullable independently
of mark_scheme_path, so every mismatch below is a row the database allows.
"""

from datetime import date

from app.config import get_settings
from app.db import async_session
from app.models import (
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Classified,
    PastPaper,
    PastPaperQuestion,
    Submission,
    User,
)
from app.services.marking import _homework_source, _past_paper_source
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


def _write(rel_path: str) -> str:
    """Put real bytes behind a stored path — the source builders read the file,
    so a row pointing at nothing would fail for the wrong reason."""
    import pathlib as _pathlib

    full = _pathlib.Path(get_settings().upload_dir) / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(b"%PDF-1.4 test")
    return rel_path


async def _org_id(tutor) -> int:
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        assert user is not None
        return user.organization_id


async def test_a_past_paper_with_no_mark_scheme_does_not_claim_one(client, tutor, world):
    org_id = await _org_id(tutor)
    async with async_session() as session:
        paper = PastPaper(
            organization_id=org_id,
            tutor_id=tutor["user"]["id"],
            subject_id=world["subject_id"],
            session_label="June 2026",
            paper_number="Paper 1",
            booklet_path=_write("papers/booklet.pdf"),
            booklet_mime="application/pdf",
            # No mark scheme — the state seed data is in.
        )
        session.add(paper)
        await session.flush()
        session.add(
            PastPaperQuestion(
                past_paper_id=paper.id,
                position=1,
                number="1",
                text_summary="Solve for x",
                max_marks=5,
                has_mark_scheme=False,
            )
        )
        submission = Submission(
            student_id=world["student_id"], past_paper_id=paper.id, attempted_at=date.today()
        )
        session.add(submission)
        await session.commit()
        submission_id = submission.id

    async with async_session() as session:
        source = await _past_paper_source(session, await session.get(Submission, submission_id))

    assert source.mark_scheme is None
    assert "mark scheme" not in source.intro
    # The booklet is attached, so it may be named.
    assert source.booklet is not None
    assert "question paper" in source.intro


async def test_a_mark_scheme_with_no_stored_mime_is_not_announced(client, tutor, world):
    """The exact drift a type fix introduced: the attachment requires a path
    *and* a mime, while the sentence keyed on the path alone."""
    org_id = await _org_id(tutor)
    async with async_session() as session:
        classified = Classified(
            organization_id=org_id,
            tutor_id=tutor["user"]["id"],
            subject_id=world["subject_id"],
            title="Algebra sheet",
            file_path=_write("classifieds/sheet.pdf"),
            file_name="sheet.pdf",
            file_mime="application/pdf",
            mark_scheme_path=_write("classifieds/scheme.pdf"),
            mark_scheme_mime=None,  # nullable independently of the path
        )
        session.add(classified)
        await session.flush()
        assignment = Assignment(
            group_id=world["group"]["id"],
            classified_id=classified.id,
            title="Algebra sheet",
            status=AssignmentStatus.published,
        )
        session.add(assignment)
        await session.flush()
        session.add(
            AssignmentQuestion(
                assignment_id=assignment.id,
                position=1,
                number="1",
                text_summary="Solve for x",
                max_marks=5,
            )
        )
        submission = Submission(student_id=world["student_id"], assignment_id=assignment.id)
        session.add(submission)
        await session.commit()
        submission_id = submission.id

    async with async_session() as session:
        source = await _homework_source(session, await session.get(Submission, submission_id))

    assert source.mark_scheme is None
    assert "mark scheme" not in source.intro
