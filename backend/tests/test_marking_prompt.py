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

from sqlalchemy import select

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


async def test_an_unattached_scheme_never_auto_finalizes_however_confident(
    client, tutor, world, monkeypatch, fake_ai
):
    """The gate and the attachment must agree, not just the prose.

    `PastPaperQuestion.has_mark_scheme` defaults to **True** (readiness_v2.py),
    where the homework column defaults to False. So a paper stored without a
    scheme file — or whose questions were never extracted — carries questions
    all claiming coverage. Gating auto-finalize on that flag alone let a
    confident mark be written final, counted as Evidence and fed into readiness,
    against a scheme no model ever read and no tutor ever saw (AI-11, ADR-0009).

    Fixing only the prompt's sentence, as an earlier pass did, leaves the model
    correctly told there is no scheme while the mark still counts — which is
    why this asserts the stored mark, not the prompt text.
    """
    from app.models import MarkConfidence, QuestionMark, SubmissionFile
    from app.services.marking import MarkingResult, QuestionMarkDraft, mark_submission

    org_id = await _org_id(tutor)
    async with async_session() as session:
        paper = PastPaper(
            organization_id=org_id,
            tutor_id=tutor["user"]["id"],
            subject_id=world["subject_id"],
            session_label="June 2026",
            paper_number="Paper 1",
            booklet_path=_write("papers/booklet2.pdf"),
            booklet_mime="application/pdf",
            # No mark_scheme_path: nothing for the model to mark against.
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
                # The model default — not a deliberate claim by anyone.
                has_mark_scheme=True,
            )
        )
        submission = Submission(
            student_id=world["student_id"], past_paper_id=paper.id, attempted_at=date.today()
        )
        session.add(submission)
        await session.flush()
        session.add(
            SubmissionFile(
                submission_id=submission.id,
                position=0,
                path=_write("submissions/page1.pdf"),
                name="page1.pdf",
                mime="application/pdf",
            )
        )
        await session.commit()
        submission_id = submission.id

    monkeypatch.setattr(
        "app.services.marking.structured_complete",
        fake_ai(
            MarkingResult(
                questions=[
                    QuestionMarkDraft(
                        number="1",
                        transcription="x = 4",
                        proposed_marks=5,
                        feedback="Correct.",
                        confidence="high",
                    )
                ]
            )
        ),
    )

    # The job handler, not _run_marking — it is what production calls, and it
    # eager-loads the submission's files the way the worker does.
    async with async_session() as session:
        await mark_submission(session, {"submission_id": submission_id})
        await session.commit()

    async with async_session() as session:
        mark = await session.scalar(
            select(QuestionMark).where(QuestionMark.submission_id == submission_id)
        )
        assert mark is not None
        # The AI's number is kept as a suggestion...
        assert mark.ai_marks == 5
        assert mark.ai_confidence is MarkConfidence.high
        # ...but nothing counts it without a scheme behind it.
        assert mark.auto_finalized is False
        assert mark.needs_review is True
        assert mark.final_marks is None
