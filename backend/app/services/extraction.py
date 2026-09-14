"""AI extraction: read a classified PDF (and optional mark scheme) and produce
the assignment's question list for the tutor to review."""

import asyncio

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiFeature,
    Assignment,
    AssignmentQuestion,
    AssignmentStatus,
    Booklet,
    BookletStatus,
    Classified,
    Group,
    Mock,
    MockQuestion,
    MockQuestionTopic,
    MockStatus,
    PastPaper,
    PastPaperQuestion,
    PastPaperQuestionTopic,
    QuestionMark,
    QuestionTopic,
    Topic,
)
from app.services import pdf, storage
from app.services.ai import file_block, record_usage, require_parsed, structured_complete
from app.services.knowledge import build_tutor_context


class ExtractedQuestion(BaseModel):
    number: str = Field(description="Question number/label exactly as printed, e.g. '1', '3b'")
    text_summary: str = Field(description="One-line summary of what the question asks")
    max_marks: int = Field(description="Maximum marks for this question")
    topic_codes: list[str] = Field(description="Syllabus topic codes this question tests")
    has_mark_scheme: bool = Field(
        description="True only if an official mark scheme / answer for this question is present in the provided documents"
    )


class ExtractionResult(BaseModel):
    questions: list[ExtractedQuestion]


class PastPaperExtractionResult(ExtractionResult):
    """Extraction result for a full past paper — same question list, plus the
    paper's own identity read off the document (the tutor no longer types it,
    task S3a)."""

    title: str = Field(
        description="The paper's full name exactly as printed on the document, e.g. "
        "'Cambridge IGCSE Physics 0625/41 Paper 4 Theory (Extended) October/November 2026'"
    )
    session_label: str = Field(
        description="The exam session printed on the paper, e.g. 'October/November 2026'"
    )
    paper_number: str = Field(
        description="The paper/component number printed on the paper, e.g. 'Paper 4'"
    )


class ExtractedPaper(BaseModel):
    """One whole exam paper found inside an uploaded booklet."""

    title: str = Field(description="The paper's full name exactly as printed on its front page")
    session_label: str = Field(
        description="The exam session printed on the paper, e.g. 'November 2026'"
    )
    paper_number: str = Field(
        description="The paper/component number printed on it, e.g. 'Paper 2'"
    )
    first_page: int = Field(
        description="1-based page of the uploaded document this paper starts on"
    )
    last_page: int = Field(
        description="1-based page of the uploaded document this paper ends on, inclusive"
    )


class BookletExtractionResult(BaseModel):
    papers: list[ExtractedPaper]


async def _clear_questions(session: AsyncSession, assignment_id: int) -> None:
    existing = (
        await session.scalars(
            select(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment_id)
        )
    ).all()
    if not existing:
        return
    await session.execute(
        delete(QuestionTopic).where(QuestionTopic.question_id.in_([q.id for q in existing]))
    )
    await session.execute(
        delete(AssignmentQuestion).where(AssignmentQuestion.assignment_id == assignment_id)
    )


async def extract_assignment(session: AsyncSession, payload: dict) -> None:
    assignment_id = payload["assignment_id"]
    assignment = await session.get(Assignment, assignment_id)
    if assignment is None:
        return
    if assignment.classified_id is None:
        assignment.status = AssignmentStatus.review
        return
    # Idempotency: extraction replaces the assignment's question list rather
    # than appending to it, so a worker retry (or a tutor-triggered
    # re-extraction) can't leave the assignment with two copies of every
    # question. Extraction only ever runs on an unpublished assignment, so no
    # QuestionMark rows reference these questions yet.
    await _clear_questions(session, assignment.id)
    try:
        await _run_extraction(session, assignment)
        # Publish straight away so students aren't blocked on the tutor coming
        # back for a second pass. _run_extraction raises when no questions were
        # found, so a published assignment always has at least one question —
        # and the tutor can still edit the list until someone submits.
        assignment.status = AssignmentStatus.published
        assignment.extraction_error = None
    except Exception as exc:
        assignment.status = AssignmentStatus.extraction_failed
        assignment.extraction_error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _run_extraction(session: AsyncSession, assignment: Assignment) -> None:
    classified = await session.get(Classified, assignment.classified_id)
    group = await session.get(Group, assignment.group_id)
    assert classified is not None
    assert group is not None
    topics = (
        await session.scalars(select(Topic).where(Topic.subject_id == group.subject_id))
    ).all()
    topic_list = "\n".join(f"- {t.code}: {t.title}" for t in topics)

    content: list[dict] = [
        file_block(await storage.read_file(classified.file_path), classified.file_mime)
    ]
    if classified.mark_scheme_path and classified.mark_scheme_mime:
        content.append(
            file_block(
                await storage.read_file(classified.mark_scheme_path), classified.mark_scheme_mime
            )
        )
    range_note = (
        f"Extract ONLY this part of the booklet: {assignment.question_range}."
        if assignment.question_range
        else "Extract ALL questions in the booklet."
    )
    content.append(
        {
            "type": "text",
            "text": (
                f"{range_note}\n\nSyllabus topics for this subject:\n{topic_list}\n\n"
                "Return the full question list."
            ),
        }
    )

    kb_context = await build_tutor_context(session, group.tutor_id, group.subject_id)

    response = await structured_complete(
        surface="extraction",
        content=content,
        output_format=ExtractionResult,
        max_tokens=16000,
        extra_system=[kb_context] if kb_context else [],
    )
    await record_usage(
        session,
        response,
        organization_id=group.organization_id,
        tutor_id=group.tutor_id,
        student_id=None,
        feature=AiFeature.extraction,
    )
    result = require_parsed(response)
    if not result.questions:
        raise ValueError("No questions were found in the document")

    topic_by_code = {t.code: t for t in topics}
    for position, q in enumerate(result.questions):
        question = AssignmentQuestion(
            assignment_id=assignment.id,
            position=position,
            number=q.number[:16],
            text_summary=q.text_summary,
            max_marks=max(1, q.max_marks),
            has_mark_scheme=q.has_mark_scheme,
        )
        session.add(question)
        await session.flush()
        for code in q.topic_codes:
            topic = topic_by_code.get(code)
            if topic is not None:
                session.add(QuestionTopic(question_id=question.id, topic_id=topic.id))


async def extract_past_paper(session: AsyncSession, payload: dict) -> None:
    """Job handler: pull the question list out of an uploaded past paper.

    Same shape as extract_assignment — a past paper is a full-paper classified
    with exam metadata, so it reuses the extraction prompt and the same
    replace-don't-append idempotency rule."""
    past_paper_id = payload["past_paper_id"]
    paper = await session.get(PastPaper, past_paper_id)
    if paper is None or paper.paper_path is None:
        return
    if not await _clear_past_paper_questions(session, paper.id):
        return
    try:
        await _run_past_paper_extraction(session, paper)
        paper.extraction_error = None
    except Exception as exc:
        paper.extraction_error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _clear_past_paper_questions(session: AsyncSession, past_paper_id: int) -> bool:
    """Empty the question list so extraction can rebuild it.

    Returns False when the list is settled and must not be rebuilt — the caller
    has to abandon the whole job then, not just skip the delete. Returning None
    and letting extraction run on regardless is the bug this signature exists to
    make impossible: the delete is skipped but the insert is not, so the paper
    ends up holding two question lists.
    """
    existing = (
        await session.scalars(
            select(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == past_paper_id)
        )
    ).all()
    if not existing:
        return True
    question_ids = [q.id for q in existing]
    # Once anyone has been marked against this question list it is settled: a
    # re-run (an orphan reclaim, `BE-6`) must not delete rows `question_marks`
    # points at — on Postgres that is an FK violation that fails the job for
    # good — and must not add a second list beside it either.
    if await session.scalar(
        select(QuestionMark.id)
        .where(QuestionMark.past_paper_question_id.in_(question_ids))
        .limit(1)
    ):
        return False
    await session.execute(
        delete(PastPaperQuestionTopic).where(PastPaperQuestionTopic.question_id.in_(question_ids))
    )
    await session.execute(
        delete(PastPaperQuestion).where(PastPaperQuestion.past_paper_id == past_paper_id)
    )
    return True


async def _run_past_paper_extraction(session: AsyncSession, paper: PastPaper) -> None:
    assert paper.paper_path is not None
    assert paper.paper_mime is not None
    topics = (
        await session.scalars(select(Topic).where(Topic.subject_id == paper.subject_id))
    ).all()
    topic_list = "\n".join(f"- {t.code}: {t.title}" for t in topics)

    content: list[dict] = [file_block(await storage.read_file(paper.paper_path), paper.paper_mime)]
    if paper.mark_scheme_path and paper.mark_scheme_mime:
        content.append(
            file_block(await storage.read_file(paper.mark_scheme_path), paper.mark_scheme_mime)
        )
    content.append(
        {
            "type": "text",
            "text": (
                "This is a full past paper"
                + (f" worth {paper.total_marks} marks" if paper.total_marks else "")
                + ". Extract every question in it, in order.\n\n"
                f"Syllabus topics for this subject:\n{topic_list}\n\n"
                "Return the full question list."
            ),
        }
    )

    response = await structured_complete(
        surface="extraction",
        content=content,
        output_format=PastPaperExtractionResult,
        max_tokens=16000,
    )
    if paper.tutor_id is not None:
        await record_usage(
            session,
            response,
            organization_id=paper.organization_id,
            tutor_id=paper.tutor_id,
            student_id=None,
            feature=AiFeature.extraction,
        )
    result = require_parsed(response)
    if not result.questions:
        raise ValueError("No questions were found in the past paper")
    # Clamped to the column widths, the same way `q.number[:16]` is three lines
    # below. Nothing bounds what a model reads off a document, and an over-long
    # value does not fail cleanly: the assignment is flushed inside the question
    # loop, so Postgres raises there, the transaction aborts, and the `commit()`
    # that would have recorded `extraction_error` for the tutor raises too. The
    # paper then sits "Untitled paper" for good with nothing explaining why.
    # SQLite does not enforce VARCHAR length, so no test would ever show it
    # (`RISK-3`).
    # Written once, on the run that first names the paper, and never again.
    #
    # A plain overwrite is idempotent against the same payload, which is all
    # `BE-6` asks for — but it is not idempotent against a *tutor edit*, and
    # that is the state task 3.5 creates: an upload's papers are named by the
    # AI, corrected by the tutor, and only then do their question lists get
    # extracted. That second job would land here and overwrite the correction
    # with a fresh read of a file holding a dozen papers — frequently wrong as
    # well as unwanted, with no audit row. `PROD-7` gives the tutor final
    # authority over everything the AI produces, and `mark_submission` already
    # takes this exact posture: it never overwrites a tutor-finalized mark.
    if paper.title is None:
        paper.title = result.title[:255]
        paper.session_label = result.session_label[:64]
        paper.paper_number = result.paper_number[:32]

    topic_by_code = {t.code: t for t in topics}
    for position, q in enumerate(result.questions):
        question = PastPaperQuestion(
            past_paper_id=paper.id,
            position=position,
            number=q.number[:16],
            text_summary=q.text_summary,
            max_marks=max(1, q.max_marks),
            # A past paper always ships with its official scheme (enforced at
            # upload), so coverage is per-question from the extractor.
            has_mark_scheme=q.has_mark_scheme,
            ai_model=response.model,
            ai_prompt_version=response.prompt_version,
        )
        session.add(question)
        await session.flush()
        for code in q.topic_codes:
            topic = topic_by_code.get(code)
            if topic is not None:
                session.add(PastPaperQuestionTopic(question_id=question.id, topic_id=topic.id))
    if paper.total_marks is None:
        paper.total_marks = sum(max(1, q.max_marks) for q in result.questions)


async def extract_mock(session: AsyncSession, payload: dict) -> None:
    """Job handler: pull the question list out of a mock paper (task 3.4, AV-26).

    Same shape as extract_past_paper — a mock is a tutor's own full paper, so it
    reuses the extraction prompt and the same replace-don't-append idempotency
    rule (`BE-6`). Unlike a past paper it carries a status, because a mock is not
    visible to the students it is set for until extraction has produced
    something to sit."""
    mock_id = payload["mock_id"]
    mock = await session.get(Mock, mock_id)
    if mock is None:
        return
    if not await _clear_mock_questions(session, mock.id):
        return
    try:
        await _run_mock_extraction(session, mock)
        mock.status = MockStatus.published
        mock.extraction_error = None
    except Exception as exc:
        mock.status = MockStatus.extraction_failed
        mock.extraction_error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _clear_mock_questions(session: AsyncSession, mock_id: int) -> bool:
    """As `_clear_past_paper_questions` — False means the list is settled and
    the caller must abandon the job rather than rebuild it."""
    existing = (
        await session.scalars(select(MockQuestion).where(MockQuestion.mock_id == mock_id))
    ).all()
    if not existing:
        return True
    question_ids = [q.id for q in existing]
    # Once anyone has been marked against this question list it is settled: a
    # re-run (an orphan reclaim, `BE-6`) must not delete rows `question_marks`
    # points at — on Postgres that is an FK violation that fails the job for
    # good — and must not add a second list beside it either.
    if await session.scalar(
        select(QuestionMark.id).where(QuestionMark.mock_question_id.in_(question_ids)).limit(1)
    ):
        return False
    await session.execute(
        delete(MockQuestionTopic).where(MockQuestionTopic.question_id.in_(question_ids))
    )
    await session.execute(delete(MockQuestion).where(MockQuestion.mock_id == mock_id))
    return True


async def _run_mock_extraction(session: AsyncSession, mock: Mock) -> None:
    topics = (await session.scalars(select(Topic).where(Topic.subject_id == mock.subject_id))).all()
    topic_list = "\n".join(f"- {t.code}: {t.title}" for t in topics)

    content: list[dict] = [file_block(await storage.read_file(mock.paper_path), mock.paper_mime)]
    if mock.mark_scheme_path and mock.mark_scheme_mime:
        content.append(
            file_block(await storage.read_file(mock.mark_scheme_path), mock.mark_scheme_mime)
        )
    content.append(
        {
            "type": "text",
            "text": (
                f"This is {mock.title}, a mock exam paper"
                + (f" worth {mock.total_marks} marks" if mock.total_marks else "")
                + ". Extract every question in it, in order.\n\n"
                f"Syllabus topics for this subject:\n{topic_list}\n\n"
                "Return the full question list."
            ),
        }
    )

    kb_context = await build_tutor_context(session, mock.tutor_id, mock.subject_id)
    response = await structured_complete(
        surface="extraction",
        content=content,
        output_format=ExtractionResult,
        max_tokens=16000,
        extra_system=[kb_context] if kb_context else [],
    )
    await record_usage(
        session,
        response,
        organization_id=mock.organization_id,
        tutor_id=mock.tutor_id,
        student_id=None,
        feature=AiFeature.extraction,
    )
    result = require_parsed(response)
    if not result.questions:
        raise ValueError("No questions were found in the mock paper")

    topic_by_code = {t.code: t for t in topics}
    for position, q in enumerate(result.questions):
        question = MockQuestion(
            mock_id=mock.id,
            position=position,
            number=q.number[:16],
            text_summary=q.text_summary,
            max_marks=max(1, q.max_marks),
            # A mock's scheme is optional, so coverage is per-question from the
            # extractor and only means anything when a scheme was attached at
            # all — _mock_source ANDs the two before a mark may auto-finalize.
            has_mark_scheme=q.has_mark_scheme,
            ai_model=response.model,
            ai_prompt_version=response.prompt_version,
        )
        session.add(question)
        await session.flush()
        for code in q.topic_codes:
            topic = topic_by_code.get(code)
            if topic is not None:
                session.add(MockQuestionTopic(question_id=question.id, topic_id=topic.id))
    if mock.total_marks is None:
        mock.total_marks = sum(max(1, q.max_marks) for q in result.questions)


async def extract_booklet(session: AsyncSession, payload: dict) -> None:
    """Job handler: read an uploaded booklet into a draft list of the papers inside it.

    Same shape as extract_past_paper, one level up: this reads the *table of
    papers*, not the question list, and writes it to `booklet.draft` for the
    tutor to correct before it becomes PastPaper rows."""
    booklet = await session.get(Booklet, payload["booklet_id"])
    if booklet is None or booklet.file_path is None or booklet.file_mime is None:
        return
    # An applied booklet's paper list is settled — it already became PastPaper
    # rows. A re-run (an orphan reclaim, `BE-6`) must not overwrite the draft
    # those rows were created from, which is the tutor's corrected list, not the
    # AI's (`PROD-7`).
    if booklet.status is BookletStatus.applied:
        return
    try:
        await _run_booklet_extraction(session, booklet)
        booklet.status = BookletStatus.review
        booklet.error = None
    except Exception as exc:
        booklet.status = BookletStatus.extraction_failed
        booklet.error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _read_papers(
    session: AsyncSession, booklet: Booklet, path: str, mime: str
) -> list[ExtractedPaper]:
    """One AI pass over one document, metered. The booklet file and the mark
    scheme each get their own call: page ranges are the whole point of the
    output, and a scheme's page 4 is not the paper's page 4 — one call over both
    documents returns ranges with no way to tell which document they index."""
    response = await structured_complete(
        surface="booklet",
        content=[file_block(await storage.read_file(path), mime)],
        output_format=BookletExtractionResult,
        max_tokens=16000,
    )
    if booklet.tutor_id is not None:
        await record_usage(
            session,
            response,
            organization_id=booklet.organization_id,
            tutor_id=booklet.tutor_id,
            student_id=None,
            feature=AiFeature.extraction,
        )
    return require_parsed(response).papers


def _paper_dict(paper: ExtractedPaper) -> dict:
    # Clamped to the widths of the PastPaper columns these become on apply, so
    # an over-long value fails now (visibly, in the draft) rather than at the
    # insert, where SQLite would never have shown it (`RISK-3`).
    return {
        "title": paper.title[:255],
        "session_label": paper.session_label[:64],
        "paper_number": paper.paper_number[:32],
        "first_page": paper.first_page,
        "last_page": paper.last_page,
    }


def _paper_key(paper: ExtractedPaper) -> tuple[str, str]:
    return (paper.session_label.strip().casefold(), paper.paper_number.strip().casefold())


def _papers(count: int) -> str:
    return f"{count} paper" if count == 1 else f"{count} papers"


def _scheme_mismatch(
    papers: list[ExtractedPaper], scheme_papers: list[ExtractedPaper]
) -> str | None:
    """One plain sentence for the tutor when the two documents do not describe
    the same papers, or None when they agree.

    Never resolves the disagreement: which document is right is a judgement
    about two files only the tutor has seen (`PROD-7`), and silently trusting
    either one would attach the wrong scheme to a paper that then auto-finalizes
    marks against it."""
    booklet_keys = [_paper_key(p) for p in papers]
    scheme_keys = [_paper_key(p) for p in scheme_papers]
    if booklet_keys == scheme_keys:
        return None
    if len(booklet_keys) != len(scheme_keys):
        return (
            f"The mark scheme lists {_papers(len(scheme_keys))} but the booklet has "
            f"{len(booklet_keys)}."
        )
    for paper, key in zip(papers, booklet_keys, strict=True):
        if key not in scheme_keys:
            return (
                f"The booklet has {paper.paper_number} ({paper.session_label}) but the "
                "mark scheme does not."
            )
    for paper, key in zip(scheme_papers, scheme_keys, strict=True):
        if key not in booklet_keys:
            return (
                f"The mark scheme has {paper.paper_number} ({paper.session_label}) but the "
                "booklet does not."
            )
    return "The booklet and the mark scheme list the same papers, but in a different order."


async def _run_booklet_extraction(session: AsyncSession, booklet: Booklet) -> None:
    assert booklet.file_path is not None
    assert booklet.file_mime is not None
    papers = await _read_papers(session, booklet, booklet.file_path, booklet.file_mime)
    if not papers:
        raise ValueError("No papers were found in the booklet")

    # Counted here because the bytes are in hand anyway, and because approval
    # needs it: a page range running past the end of the document is refused
    # there, before anything is cut. Counting blocks (`BE-13`), hence the
    # thread. A booklet that is not a PDF cannot be split at all, so a count it
    # cannot produce is left absent rather than guessed (`PROD-2`).
    try:
        booklet.page_count = await asyncio.to_thread(
            pdf.page_count, await storage.read_file(booklet.file_path)
        )
    except ValueError:
        booklet.page_count = None

    scheme_papers: list[ExtractedPaper] | None = None
    mismatch: str | None = None
    if booklet.mark_scheme_path and booklet.mark_scheme_mime:
        try:
            scheme_papers = await _read_papers(
                session, booklet, booklet.mark_scheme_path, booklet.mark_scheme_mime
            )
        except Exception as exc:  # noqa: BLE001 — a bad scheme must not fail the booklet
            # An unreadable mark scheme is not a failed extraction: the papers
            # are what the tutor is approving, and a scheme is what makes a mark
            # eligible to auto-finalize, not what makes the booklet usable. The
            # reason is surfaced in the same field the tutor already reads for
            # scheme trouble rather than swallowed.
            scheme_papers = None
            mismatch = f"The mark scheme could not be read: {exc or exc.__class__.__name__}"
        else:
            mismatch = _scheme_mismatch(papers, scheme_papers)

    # Replaced wholesale, never appended to (`BE-6`).
    booklet.draft = {
        "papers": [_paper_dict(p) for p in papers],
        "scheme_papers": (
            [_paper_dict(p) for p in scheme_papers] if scheme_papers is not None else None
        ),
        "scheme_mismatch": mismatch,
    }
