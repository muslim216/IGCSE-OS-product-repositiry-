"""The grade-boundary editor's contract."""

from pydantic import BaseModel, Field, field_validator, model_validator


class GradeBand(BaseModel):
    grade: str = Field(min_length=1, max_length=16)
    # The lowest percentage that earns this grade. `min` mirrors the key already
    # used in Subject.grade_boundaries so one shape serves both sources.
    min: float = Field(ge=0, le=100)


class GradeBoundariesIn(BaseModel):
    boundaries: list[GradeBand] = Field(min_length=2)

    @field_validator("boundaries")
    @classmethod
    def _unique_grades(cls, bands: list[GradeBand]) -> list[GradeBand]:
        labels = [b.grade for b in bands]
        if len(set(labels)) != len(labels):
            raise ValueError("each grade may appear once")
        return bands

    @model_validator(mode="after")
    def _strictly_descending(self) -> "GradeBoundariesIn":
        """Highest grade first, and every cut-off strictly below the one above.

        predict_grade walks this list top to bottom and returns the first grade
        whose minimum the score meets, so an out-of-order list does not fail —
        it silently returns the wrong grade for every student in the
        organization. Two bands sharing a cut-off are the same failure: one of
        them can never be awarded.
        """
        mins = [b.min for b in self.boundaries]
        if any(later >= earlier for earlier, later in zip(mins, mins[1:], strict=False)):
            raise ValueError("boundaries must be highest grade first, each below the one above")
        return self


class GradeBoundariesOut(BaseModel):
    subject_id: int
    subject_name: str
    grade_scale: str
    # Where this list came from:
    #   "organization" — this tutor's own numbers
    #   "subject"      — the global default shipped with the syllabus
    #   "none"         — nothing is set; the list below is a published starting
    #                    point that has not been confirmed and must be labelled
    #                    as such wherever it is shown (PROD-8)
    source: str
    boundaries: list[GradeBand]
