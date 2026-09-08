"""The per-subject marking rules' contract (`AV-75`, `AV-111`)."""

from pydantic import BaseModel, Field, field_validator

#: Hard cap on the stored text.
#:
#: These rules are destined for every marking prompt for the subject (Phase 3's
#: context assembler), so their length is a per-call cost paid on every
#: submission, and an unbounded field is an unbounded prompt. 8000 characters is
#: roughly two thousand tokens — room for a page of genuine marking policy, well
#: short of a pasted syllabus. Enforced here rather than only in the editor: a
#: frontend limit is a courtesy, not a control.
MAX_MARKING_RULES = 8000


class MarkingRulesIn(BaseModel):
    rules: str = Field(max_length=MAX_MARKING_RULES)

    @field_validator("rules", mode="before")
    @classmethod
    def _trimmed(cls, value: object) -> object:
        """Whitespace-only input is no rules at all.

        Storing "   " would make `marking_rules` truthy, so Phase 3 would paste
        an empty instruction block into every marking prompt for the subject and
        the editor would report rules that say nothing.

        `mode="before"`, so the length cap below measures the *trimmed* text.
        Trimming only ever shortens a string, so the cap cannot be bypassed —
        but measuring the raw value rejected 7,999 characters with a trailing
        newline, which is a confusing 422 for a body that would have stored
        fine (cubic).
        """
        return value.strip() if isinstance(value, str) else value


class MarkingRulesOut(BaseModel):
    subject_id: int
    subject_name: str
    #: Empty string, never null: the editor binds a textarea to it, and "no
    #: rules" is a legitimate finished state (`AV-87` — this is the one
    #: onboarding step a tutor may skip), not a missing value.
    rules: str
    #: Whether anything is actually set, so a surface can say "not set" without
    #: inferring it from an empty string (`PROD-2`).
    configured: bool
