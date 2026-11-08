from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from app.models import Chapter, Subject, SubjectLevel, Topic


class SyllabusTopicIn(BaseModel):
    code: str
    title: str
    weight: float = 1.0
    children: list[SyllabusTopicIn] = []


class SyllabusChapterIn(BaseModel):
    code: str
    title: str
    topics: list[SyllabusTopicIn] = []


# The draft as stored and as the review page reads it: deliberately lenient.
# Limits live on `SyllabusDraftChecked`, not here. The GET reads every stored
# draft through this model, so a limit here would turn a draft stored before it
# existed into a 500 on the page the tutor needs to fix it (T-033). A comment,
# not a docstring, so the API's published schema is unchanged.
class SyllabusDraft(BaseModel):
    exam_board: str
    code: str
    name: str
    # Optional in the draft, required to apply. The extractor proposes a level
    # only where the document states one (task 2.3), and AV-7 forbids assuming an
    # IGCSE-shaped world, so the tutor states it during review otherwise. Apply
    # refuses a draft that still has none.
    level: SubjectLevel | None = None
    grade_scale: str
    # Chapter-first since task 2.3 (AV-9). Grade boundaries are no longer part of
    # the draft — a syllabus document does not publish them, so they are
    # tutor-entered (task 2.4, AV-11).
    chapters: list[SyllabusChapterIn]


def _column_length(model: Any, name: str) -> int:
    """The declared length of a String column, so these limits cannot drift
    from what the database will actually take."""
    length = getattr(model.__table__.c[name].type, "length", None)
    if not isinstance(length, int):
        raise TypeError(f"{model.__name__}.{name} has no declared length")
    return length


EXAM_BOARD_MAX = _column_length(Subject, "exam_board")
SUBJECT_CODE_MAX = _column_length(Subject, "code")
SUBJECT_NAME_MAX = _column_length(Subject, "name")
GRADE_SCALE_MAX = _column_length(Subject, "grade_scale")
CHAPTER_CODE_MAX = _column_length(Chapter, "code")
CHAPTER_TITLE_MAX = _column_length(Chapter, "title")
TOPIC_CODE_MAX = _column_length(Topic, "code")
TOPIC_TITLE_MAX = _column_length(Topic, "title")
WEIGHT_MAX = 100.0
# Chapter, topic, sub-topic: the depth syllabuses print and the most the
# extraction produces (T-025). Deeper nodes can only come from a hand-made body.
TREE_DEPTH_MAX = 3

# Lone surrogates too: they cannot be encoded as UTF-8, so Postgres cannot
# store them, and no syllabus is written with one.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f\ud800-\udfff]")


def position_label(indices: tuple[int, ...] | list[int]) -> str:
    """Where a row sits, counted from one as the tutor counts rows on screen:
    "Chapter 1, topic 2, sub-topic 1"."""
    names = ["Chapter", "topic"] + ["sub-topic"] * max(len(indices) - 2, 0)
    return ", ".join(f"{name} {index + 1}" for name, index in zip(names, indices, strict=False))


def _printable(value: str) -> str:
    # Postgres refuses NUL in text outright, and the other control characters
    # are never part of a syllabus code or title.
    if CONTROL_CHARACTERS.search(value):
        raise PydanticCustomError("control_character", "contains a control character")
    return value


def _text(max_length: int | None = None, min_length: int = 0) -> Any:
    return StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)


_Printable = AfterValidator(_printable)
ExamBoard = Annotated[str, _text(EXAM_BOARD_MAX), _Printable]
SubjectCode = Annotated[str, _text(SUBJECT_CODE_MAX, 1), _Printable]
SubjectName = Annotated[str, _text(SUBJECT_NAME_MAX), _Printable]
# No length here: an empty or over-long scale is refused at apply, in words that
# tell the tutor to choose one, and may be saved meanwhile (T-033).
GradeScale = Annotated[str, _text(), _Printable]
ChapterCode = Annotated[str, _text(CHAPTER_CODE_MAX, 1), _Printable]
ChapterTitle = Annotated[str, _text(CHAPTER_TITLE_MAX, 1), _Printable]
TopicCode = Annotated[str, _text(TOPIC_CODE_MAX, 1), _Printable]
TopicTitle = Annotated[str, _text(TOPIC_TITLE_MAX, 1), _Printable]


class SyllabusTopicChecked(BaseModel):
    code: TopicCode
    title: TopicTitle
    weight: float = Field(default=1.0, gt=0, le=WEIGHT_MAX, allow_inf_nan=False)
    children: list[SyllabusTopicChecked] = []


class SyllabusChapterChecked(BaseModel):
    code: ChapterCode
    title: ChapterTitle
    topics: list[SyllabusTopicChecked] = []


class SyllabusDraftChecked(BaseModel):
    """A draft that will fit the tables it is applied into.

    What apply holds a draft to, so a value too long for its column is a 422
    naming it rather than a 500 from the database (T-033). The draft PUT does
    not: it is lenient on purpose, so a half-typed value saves.
    `services.syllabus_extraction.check_draft` is the way in: it tidies the
    draft first and turns a failure into plain words.
    """

    exam_board: ExamBoard
    code: SubjectCode
    name: SubjectName
    level: SubjectLevel | None = None
    grade_scale: GradeScale
    chapters: list[SyllabusChapterChecked]

    @model_validator(mode="after")
    def _tree_is_applicable(self) -> SyllabusDraftChecked:
        for c, chapter in enumerate(self.chapters):
            for t, topic in enumerate(chapter.topics):
                _check_node(topic, at=(c, t), above=())
        return self


def _check_node(node: SyllabusTopicChecked, *, at: tuple[int, ...], above: tuple[str, ...]) -> None:
    # The code names the row and the position finds it, since two rows may
    # share a code. `at` counts the chapter, so its length is the depth.
    where = {"code": node.code, "where": position_label(at)}
    if len(at) > TREE_DEPTH_MAX:
        raise PydanticCustomError(
            "too_deep",
            "Topic {code} ({where}) is too deep: a syllabus goes chapter, topic, "
            "sub-topic, no further",
            where,
        )
    # Apply files a topic under the row already holding its code, so a node
    # sharing a code with a topic above it would become its own ancestor.
    if node.code in above:
        raise PydanticCustomError(
            "repeats_ancestor",
            "Topic {code} ({where}) has the same code as a topic it sits under",
            where,
        )
    for k, child in enumerate(node.children):
        _check_node(child, at=(*at, k), above=(*above, node.code))


class SyllabusUploadOut(BaseModel):
    id: int
    title: str
    file_name: str
    status: str
    error: str | None
    subject_id: int | None
    created_at: datetime


class SyllabusUploadDetail(SyllabusUploadOut):
    draft: SyllabusDraft | None
