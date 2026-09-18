"""The mistake-category editor's contract."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MistakeCategoryItem(BaseModel):
    # Present on a category that already exists (so an edit can be matched
    # back to its row); absent on one the tutor is adding.
    id: int | None = None
    name: str = Field(min_length=1, max_length=60)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _stripped_and_non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be empty")
        return value


class MistakeCategoriesIn(BaseModel):
    categories: list[MistakeCategoryItem]

    @field_validator("categories")
    @classmethod
    def _unique_names(cls, items: list[MistakeCategoryItem]) -> list[MistakeCategoryItem]:
        """Reject a duplicate name in the schema, before it reaches the unique
        constraint — the difference between a 422 naming the problem and a 500
        from a constraint violation the tutor never sees explained."""
        names = [item.name.lower() for item in items]
        if len(set(names)) != len(names):
            raise ValueError("each category name may appear once")
        return items


class MistakeCategoriesOut(BaseModel):
    subject_id: int
    subject_name: str
    # Where this list came from:
    #   "organization" — this organization's own categories
    #   "none"         — nothing is set; the list below is a published
    #                    starting point that has not been confirmed and must
    #                    be labelled as such wherever it is shown (PROD-8)
    source: Literal["organization", "none"]
    categories: list[MistakeCategoryItem]
