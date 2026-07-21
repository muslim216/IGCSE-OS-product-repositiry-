"""AI extraction: read an uploaded syllabus document and draft the subject's
topic tree (with weights and grade boundaries) for a tutor to review before
it's applied as a real Subject the platform can assign homework and track
readiness against."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import SyllabusUpload, SyllabusUploadStatus
from app.services import storage
from app.services.ai import file_block, get_client


class ExtractedGradeBoundary(BaseModel):
    grade: str = Field(description="Grade label, e.g. '9', 'A*', 'U'")
    min: int = Field(description="Minimum overall percentage for this grade")


class ExtractedTopic(BaseModel):
    code: str = Field(description="Syllabus section/topic number exactly as printed, e.g. '1.3'")
    title: str = Field(description="Topic title")
    weight: float = Field(
        default=1.0,
        description="Relative importance for readiness weighting; 1.0 unless the syllabus "
        "clearly emphasises some sections over others",
    )
    children: list["ExtractedTopic"] = Field(default_factory=list)


class SyllabusExtractionResult(BaseModel):
    exam_board: str = Field(description="Exam board name, e.g. 'Edexcel IGCSE', 'Cambridge O Level'")
    code: str = Field(description="Official syllabus/specification code, e.g. '4CH1', '5070'")
    name: str = Field(description="Subject name, e.g. 'Chemistry'")
    grade_scale: str = Field(description="'9-1' or 'A*-E' etc., as used by this syllabus")
    grade_boundaries: list[ExtractedGradeBoundary]
    topics: list[ExtractedTopic] = Field(
        description="The full topic tree in syllabus order, nesting sub-topics under their section"
    )


SYSTEM_PROMPT = """You are converting an official IGCSE/O Level exam board syllabus document \
into a structured topic tree so a tutoring platform can track a student's readiness against \
every syllabus point.

Rules:
- Extract every assessable topic/sub-topic in the document, preserving the syllabus's own \
numbering and hierarchy (nest sub-points under their parent section).
- Use the syllabus's own section numbers as `code` exactly as printed.
- grade_boundaries should reflect this syllabus's actual grading scale if stated; otherwise \
give a reasonable standard scale for the qualification type and say so is not needed — just \
provide your best estimate.
- Do not invent topics that aren't in the document."""


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
    content: list[dict] = [file_block(storage.read_file(upload.file_path), upload.file_mime)]
    content.append(
        {
            "type": "text",
            "text": "Extract the full topic tree from this syllabus document.",
        }
    )

    client = get_client()
    response = await client.messages.parse(
        model=get_settings().anthropic_model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_format=SyllabusExtractionResult,
    )
    result: SyllabusExtractionResult = response.parsed_output
    if not result.topics:
        raise ValueError("No topics were found in the document")

    upload.draft = result.model_dump()
