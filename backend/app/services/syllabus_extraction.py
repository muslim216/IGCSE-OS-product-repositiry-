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

import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import release_connection
from app.models import AiFeature, SubjectLevel, SyllabusUpload, SyllabusUploadStatus, User
from app.schemas.syllabus import (
    CHAPTER_CODE_MAX,
    CHAPTER_TITLE_MAX,
    CONTROL_CHARACTERS,
    EXAM_BOARD_MAX,
    GRADE_SCALE_MAX,
    SUBJECT_NAME_MAX,
    TOPIC_CODE_MAX,
    TOPIC_TITLE_MAX,
    WEIGHT_MAX,
    SyllabusDraft,
    SyllabusDraftChecked,
)
from app.services import storage
from app.services.ai import (
    file_block,
    output_ceiling,
    record_usage,
    require_parsed,
    structured_complete,
)
from app.services.grade_boundaries import normalise_grade_scale
from app.services.job_errors import DocumentProblem, safe_job_error


class ExtractedSubtopic(BaseModel):
    code: str = Field(description="Sub-point number exactly as printed, e.g. '1.3.2'")
    title: str = Field(description="Sub-point title; fold any deeper printed points into this text")
    weight: float = Field(
        default=1.0,
        description="Relative importance for readiness weighting; 1.0 unless the syllabus "
        "clearly emphasises some sections over others",
    )


class ExtractedTopic(BaseModel):
    code: str = Field(description="Syllabus section/topic number exactly as printed, e.g. '1.3'")
    title: str = Field(description="Topic title")
    weight: float = Field(
        default=1.0,
        description="Relative importance for readiness weighting; 1.0 unless the syllabus "
        "clearly emphasises some sections over others",
    )
    # A fixed depth, not `list[ExtractedTopic]`: Anthropic refuses a schema whose
    # definitions refer to themselves, so a recursive model failed every syllabus
    # upload (T-025). Chapter -> topic -> sub-topic is the depth syllabuses print,
    # and `Topic.parent_id` and apply take it as they always have;
    # tests/test_output_format_schemas.py keeps every output model acyclic.
    children: list[ExtractedSubtopic] = Field(default_factory=list)


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
        upload.error = safe_job_error(exc)
        await session.commit()
        raise


async def syllabus_read_given_up(session: AsyncSession, payload: dict, error: str) -> None:
    """The `on_give_up` hook for `extract_syllabus` (see `register_handler` in
    app/workers/jobs.py): only an upload still `extracting` is marked failed."""
    await session.execute(
        update(SyllabusUpload)
        .where(
            SyllabusUpload.id == payload["syllabus_upload_id"],
            SyllabusUpload.status == SyllabusUploadStatus.extracting,
        )
        .values(status=SyllabusUploadStatus.extraction_failed, error=error)
    )


async def _run_extraction(session: AsyncSession, upload: SyllabusUpload) -> None:
    content: list[dict] = [file_block(await storage.read_file(upload.file_path), upload.file_mime)]
    content.append(
        {
            "type": "text",
            "text": "Extract the full chapter tree from this syllabus document.",
        }
    )

    tutor = await session.get(User, upload.tutor_id)
    assert tutor is not None
    await release_connection(session)
    response = await structured_complete(
        organization_id=tutor.organization_id,
        surface="syllabus",
        content=content,
        output_format=SyllabusExtractionResult,
        # The whole answer the routed model can give, and the long deadline:
        # no subject can be set up without this read, so its length must never
        # be what fails it (owner, 5 Nov 2026; `ai.ESSENTIAL_SURFACES`). A 16,000
        # limit cut off a real chemistry specification.
        max_tokens=output_ceiling("syllabus"),
        timeout_seconds=get_settings().ai_essential_call_timeout_seconds,
    )
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
        raise DocumentProblem("No chapters were found in the document")
    # Chapters alone are not a syllabus: marks, mistakes and readiness all
    # attach at topic level, so a chapter-only draft applies cleanly into a
    # subject nothing can ever be tracked against. The flat extractor rejected
    # an empty topic list for the same reason (cubic).
    if not any(chapter.topics for chapter in result.chapters):
        raise DocumentProblem("No topics were found in the document")

    # Through `SyllabusDraft`, so a sub-topic is stored with `children: []` like
    # every other node: the review page and the apply step read that list on
    # every node, and `ExtractedSubtopic` has none to dump.
    upload.draft = SyllabusDraft.model_validate(tidy_answer(result.model_dump())).model_dump()


# Whitespace control characters (a line break inside a title) become a space so
# the words either side stay apart; the rest are dropped.
_LINE_BREAKS = re.compile(r"\s*[\t\n\r\v\f\x1c-\x1f\x85\u2028\u2029]\s*")


def _printable(value: str) -> str:
    return CONTROL_CHARACTERS.sub("", _LINE_BREAKS.sub(" ", value)).strip()


def _without_control_characters(value: Any) -> Any:
    if isinstance(value, str):
        return _printable(value)
    if isinstance(value, dict):
        return {key: _without_control_characters(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_control_characters(item) for item in value]
    return value


def _cut(value: str, length: int) -> str:
    return value[:length].rstrip()


def _topics(nodes: list[dict]) -> list[dict]:
    found = []
    for node in nodes:
        found.append(node)
        found.extend(_topics(node.get("children") or []))
    return found


def tidy_answer(answer: dict) -> dict:
    """The AI's answer made storable, without failing the read.

    The read has been paid for and may have taken most of an hour, so nothing
    here refuses it (T-033). NUL and other control characters are stripped
    (Postgres refuses NUL in text). Free text is cut to its column: a shortened
    exam board or title is harmless and in front of the tutor at review. Codes
    are never cut, because a cut code is silently a different code; an
    over-long one stays as read and the draft PUT and apply name it for the
    tutor to correct. A grade scale is put in its known form, and one that is
    unknown and too long to store is left empty for the tutor to choose.
    """
    tidy = _without_control_characters(answer)
    tidy["exam_board"] = _cut(tidy["exam_board"], EXAM_BOARD_MAX)
    tidy["name"] = _cut(tidy["name"], SUBJECT_NAME_MAX)
    scale = tidy["grade_scale"]
    tidy["grade_scale"] = normalise_grade_scale(scale) or (
        scale if len(scale) <= GRADE_SCALE_MAX else ""
    )
    for chapter in tidy["chapters"]:
        chapter["title"] = _cut(chapter["title"], CHAPTER_TITLE_MAX)
        for topic in _topics(chapter["topics"]):
            topic["title"] = _cut(topic["title"], TOPIC_TITLE_MAX)
    return tidy


class DraftNotValid(Exception):
    """A draft that cannot be applied, with the reason in words for the tutor."""


def check_draft(raw: object) -> SyllabusDraftChecked:
    """`raw` held to the tables it will be applied into, or `DraftNotValid`.

    The grade scale is put in its known form first, so a draft stored before
    T-033 with the AI's own wording ("A*-E (IAL); A-E (IAS)") applies. Then the
    strict schema; its failures become words naming the field. Those words may
    repeat a code from the draft, the tutor's own text and already on their
    screen, but never Pydantic's echo of the input or anything from the
    database.
    """
    data = dict(raw) if isinstance(raw, dict) else raw
    if isinstance(data, dict):
        scale = data.get("grade_scale")
        scale = scale.strip() if isinstance(scale, str) else ""
        data["grade_scale"] = normalise_grade_scale(scale) or scale
    try:
        return SyllabusDraftChecked.model_validate(data)
    except ValidationError as exc:
        raise DraftNotValid(_in_plain_words(exc, data)) from None


_SUBJECT_FIELDS = {
    "exam_board": "exam board",
    "code": "subject code",
    "name": "subject name",
    "level": "level",
    "grade_scale": "grade scale",
    "chapters": "chapter list",
}
_NODE_FIELDS = {
    "code": "code",
    "title": "title",
    "weight": "weight",
    "topics": "topic list",
    "children": "sub-topic list",
}
_OUR_OWN_WORDS = {"too_deep", "repeats_ancestor"}
_NUMBER_PROBLEMS = {
    "finite_number",
    "greater_than",
    "less_than_equal",
    "float_parsing",
    "float_type",
}
_SHOWN_AT_MOST = 3


def _problem(kind: str, field: str, ctx: dict) -> str:
    if kind == "string_too_long":
        return f"the {field} is longer than {ctx.get('max_length')} characters"
    if kind == "string_too_short":
        return f"the {field} is empty"
    if kind == "missing":
        return f"the {field} is missing"
    if kind == "control_character":
        return f"the {field} contains a control character"
    if kind in _NUMBER_PROBLEMS:
        return f"the {field} must be a number above 0 and at most {WEIGHT_MAX:g}"
    if kind == "enum":
        return f"the {field} must be IGCSE, O Level or A Level"
    return f"the {field} is not valid"


def _node_label(data: object, path: list[tuple[str, int]]) -> str:
    """Where a node sits: by its code when that is a usable one, else by
    position, counted from one as the tutor counts rows on screen."""
    node: object = data
    for key, index in path:
        items = node.get(key) if isinstance(node, dict) else None
        node = items[index] if isinstance(items, list) and index < len(items) else None
    code = node.get("code") if isinstance(node, dict) else None
    if isinstance(code, str):
        code = code.strip()
        longest = CHAPTER_CODE_MAX if len(path) == 1 else TOPIC_CODE_MAX
        if 0 < len(code) <= longest and not CONTROL_CHARACTERS.search(code):
            return f"{'Chapter' if len(path) == 1 else 'Topic'} {code}"
    names = ["Chapter", "topic"] + ["sub-topic"] * (len(path) - 2)
    return ", ".join(f"{name} {index + 1}" for name, (_, index) in zip(names, path, strict=False))


def _sentence(error: Any, data: object) -> str:
    loc = list(error["loc"])
    kind = error["type"]
    if not loc:
        if kind in _OUR_OWN_WORDS:
            return f"{error['msg']}."
        return "The syllabus draft is not valid."
    path: list[tuple[str, int]] = []
    while len(loc) >= 2 and isinstance(loc[0], str) and isinstance(loc[1], int):
        path.append((loc.pop(0), loc.pop(0)))
    if not path:
        field = _SUBJECT_FIELDS.get(str(loc[0]), str(loc[0]).replace("_", " "))
        problem = _problem(kind, field, error.get("ctx") or {})
        return f"{problem[0].upper()}{problem[1:]}."
    label = _node_label(data, path)
    if not loc:
        return f"{label} is not valid."
    field = _NODE_FIELDS.get(str(loc[0]), str(loc[0]).replace("_", " "))
    return f"{label}: {_problem(kind, field, error.get('ctx') or {})}."


def _in_plain_words(exc: ValidationError, data: object) -> str:
    sentences = list(dict.fromkeys(_sentence(error, data) for error in exc.errors()))
    shown = " ".join(sentences[:_SHOWN_AT_MOST])
    hidden = len(sentences) - _SHOWN_AT_MOST
    if hidden > 0:
        shown += f" ({hidden} more to fix.)"
    return shown
