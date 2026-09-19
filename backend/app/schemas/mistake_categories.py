"""The mistake-category editor's contract."""

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class MistakeCategoryItem(BaseModel):
    # Present on a category that already exists (so an edit can be matched
    # back to its row); absent on one the tutor is adding.
    id: int | None = None
    name: str = Field(min_length=1, max_length=60)
    # Bounded because 4.2 interpolates this into the tagging prompt. Every
    # other free-text field bound for a prompt in this codebase is capped
    # and trimmed the same way (see `clean_notes` in api/deps.py); an
    # unbounded one is a cost and a latency the tutor never sees coming.
    description: str | None = Field(default=None, max_length=400)

    @field_validator("name", "description", mode="before")
    @classmethod
    def _trimmed(cls, value: object, info: ValidationInfo) -> object:
        """Trim before the length bounds are applied, not after.

        Before, because the bound belongs to what is stored: a 60-character
        name typed with a trailing space is a 60-character name, and refusing
        it asks the tutor to count a character they cannot see. The same for a
        400-character description. An all-whitespace name still fails, on
        `min_length=1`, which is the field that should be saying so.
        """
        if not isinstance(value, str):
            return value
        value = value.strip()
        # A description that trims to nothing is absent, not a description made
        # of spaces. 4.2 interpolates these into the tagging prompt, where a
        # blank label is worse than no label — and padding is paid for on every
        # call.
        return (value or None) if info.field_name == "description" else value


class MistakeCategoriesIn(BaseModel):
    # A sanity bound, not a product limit: 4.2 sends this whole list to the
    # model on every submission it tags, so the list's length is a per-call
    # cost. Nobody sorts mistakes forty ways.
    # min_length=1 mirrors GradeBoundariesIn. An empty list is not a
    # confirmed choice the product can express: saving one archived every
    # category, reported `source="organization"`, and then the next GET
    # found nothing stored, reported `source="none"` and re-offered the
    # published defaults — telling the tutor their deliberate edit had not
    # happened (PROD-8). Making it inexpressible is smaller than teaching
    # every read path to tell "emptied on purpose" from "never set".
    categories: list[MistakeCategoryItem] = Field(min_length=1, max_length=40)

    @field_validator("categories")
    @classmethod
    def _unique_names(cls, items: list[MistakeCategoryItem]) -> list[MistakeCategoryItem]:
        """Reject a duplicate name in the schema, before it reaches the unique
        constraint — the difference between a 422 naming the problem and a 500
        from a constraint violation the tutor never sees explained."""
        names = [item.name.casefold() for item in items]
        if len(set(names)) != len(names):
            raise ValueError("each category name may appear once")
        # The same for ids. Without this, two items carrying one id resolve to
        # the same row twice and the reply lists that category twice — the
        # editor then renders one category as two, each overwriting the other.
        ids = [item.id for item in items if item.id is not None]
        if len(set(ids)) != len(ids):
            raise ValueError("each category may appear once")
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
