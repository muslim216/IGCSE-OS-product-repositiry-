"""AI extraction: read an uploaded syllabus document and draft the subject's
chapter tree (chapters, each holding its markable topics) for a tutor to review
before it's applied as a real Subject the platform can assign homework and track
readiness against.

Chapter-first since task 2.3 (AV-9, AV-10): a chapter is what the teaching plan
schedules and what a classified belongs to, so the draft has to carry it.

Grade boundaries left the draft in the same change: a syllabus document publishes
a specification, not a series' boundaries, so a model asked for them was guessing.
They are tutor-entered (task 2.4, AV-11)."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiFeature, SubjectLevel, SyllabusUpload, SyllabusUploadStatus, User
from app.services import storage
from app.services.ai import file_block, record_usage, require_parsed, structured_complete


class ExtractedTopic(BaseModel):
    code: str = Field(description="Syllabus section/topic number exactly as printed, e.g. '1.3'")
    title: str = Field(description="Topic title")
    weight: float = Field(
        default=1.0,
        description="Relative importance for readiness weighting; 1.0 unless the syllabus "
        "clearly emphasises some sections over others",
    )
    children: list[ExtractedTopic] = Field(default_factory=list)


class ExtractedChapter(BaseModel):
    code: str = Field(description="Chapter/unit number exactly as printed, e.g. '1'")
    title: str = Field(description="Chapter title")
    topics: list[ExtractedTopic] = Field(
        description="The markable topics in this chapter, in syllabus order"
    )


class SyllabusExtractionResult(BaseModel):
    exam_board: str = Field(
        description="Exam board name, e.g. 'Edexcel IGCSE', 'Cambridge O Level'"
    )
    code: str = Field(description="Official syllabus/specification code, e.g. '4CH1', '5070'")
    name: str = Field(description="Subject name, e.g. 'Chemistry'")
    # AV-7 forbids assuming an IGCSE-shaped world, and PROD-2 forbids inventing a
    # value to fill a gap — so this is read off the document or left None for the
    # tutor to state during review. Apply refuses a draft that still has none.
    level: SubjectLevel | None = Field(
        default=None,
        description="The qualification this syllabus is for, ONLY if the document states it. "
        "Leave null if it does not — never guess.",
    )
    grade_scale: str = Field(description="'9-1' or 'A*-E' etc., as used by this syllabus")
    chapters: list[ExtractedChapter] = Field(
        description="The syllabus's chapters/units in order, each holding its own topics"
    )


async def extract_syllabus(session: AsyncSession, payload: dict) -> None:
    upload_id = payload["syllabus_upload_id"]
    upload = await session.get(SyllabusUpload, upload_id)
    if upload is None:
        return
    try:
        await _run_extraction(session, upload)
        upload.status = SyllabusUploadStatus.review
        upload.error = None
    except Exception as exc:
        upload.status = SyllabusUploadStatus.extraction_failed
        upload.error = str(exc) or exc.__class__.__name__
        await session.commit()
        raise


async def _run_extraction(session: AsyncSession, upload: SyllabusUpload) -> None:
    content: list[dict] = [file_block(await storage.read_file(upload.file_path), upload.file_mime)]
    content.append(
        {
            "type": "text",
            "text": "Extract the full chapter tree from this syllabus document.",
        }
    )

    response = await structured_complete(
        surface="syllabus",
        content=content,
        output_format=SyllabusExtractionResult,
        max_tokens=16000,
    )
    tutor = await session.get(User, upload.tutor_id)
    assert tutor is not None
    await record_usage(
        session,
        response,
        organization_id=tutor.organization_id,
        tutor_id=upload.tutor_id,
        student_id=None,
        feature=AiFeature.extraction,
    )
    result = require_parsed(response)
    if not result.chapters:
        raise ValueError("No chapters were found in the document")
    # Chapters alone are not a syllabus: marks, mistakes and readiness all
    # attach at topic level, so a chapter-only draft applies cleanly into a
    # subject nothing can ever be tracked against. The flat extractor rejected
    # an empty topic list for the same reason (cubic).
    if not any(chapter.topics for chapter in result.chapters):
        raise ValueError("No topics were found in the document")

    upload.draft = result.model_dump()
