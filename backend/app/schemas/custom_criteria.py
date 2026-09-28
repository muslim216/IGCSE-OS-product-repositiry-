"""The custom-criteria contract (task 5.4b).

`source: "tutor"` rides on every score so a client can never render one as if
the platform had measured it — 5.4c labels these "tutor-entered" wherever they
appear (`PROD-8`, `UX-20`).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


def _strip(value: object, info: ValidationInfo) -> object:
    # Trimmed before the length bounds apply, so an all-whitespace name fails
    # `min_length` and a blank description becomes absent rather than spaces.
    if not isinstance(value, str):
        return value
    value = value.strip()
    return (value or None) if info.field_name == "description" else value


class CustomCriterionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    # Null applies the criterion to every subject.
    subject_id: int | None = None

    _trim = field_validator("name", "description", mode="before")(_strip)


class CustomCriterionUpdate(BaseModel):
    # `forbid` so a `subject_id` in the body is refused rather than silently
    # ignored — the subject is fixed at creation, and a tutor who tried to move
    # one should be told it did not happen.
    model_config = ConfigDict(extra="forbid")

    # Omittable but never null: Pydantic does not validate a default, so an
    # omitted field stays None while an explicit `null` fails the `str`/`bool`
    # type — and the published contract says the same thing (`FE-4`).
    name: str = Field(default=None, min_length=1, max_length=120)  # type: ignore[assignment]
    description: str | None = Field(default=None, max_length=2000)
    archived: bool = None  # type: ignore[assignment]

    _trim = field_validator("name", "description", mode="before")(_strip)


class CustomCriterionOut(BaseModel):
    id: int
    name: str
    description: str | None
    subject_id: int | None
    archived_at: datetime | None
    created_by_id: int
    created_at: datetime


class CustomCriterionScoreIn(BaseModel):
    # Strict: lax mode would store `true` as 1 and "50" as 50, and a client bug
    # would then read as a tutor's real judgement, audit row and all.
    score: int = Field(ge=0, le=100, strict=True)


class StudentCriterionScoreOut(BaseModel):
    criterion_id: int
    name: str
    description: str | None
    subject_id: int | None
    # Null is unscored — never 0 (`PROD-2`). The two below are null with it.
    score: int | None
    updated_at: datetime | None
    updated_by_id: int | None
    source: Literal["tutor"] = "tutor"
