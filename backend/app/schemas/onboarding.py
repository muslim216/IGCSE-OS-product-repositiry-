"""The onboarding state's contract (task 9.1a).

Keys are strings, not enums, on purpose: the step list grows (`taught_before`
is next) and a client reading an unknown key should still render it.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.models import SetupItem

StepKind = Literal["defaulted", "optional"]
#: "not_set" is the Optional item with nothing stored, and grade boundaries with
#: no rows: neither has a default in force, so neither may read as "default".
ItemState = Literal["default", "reviewed", "set_by_you", "not_set"]


class StepDone(BaseModel):
    key: str
    done: bool


class ItemStatus(BaseModel):
    key: str
    kind: StepKind
    state: ItemState


class ClassStatus(BaseModel):
    group_id: int
    group_name: str
    steps: list[StepDone]
    complete: bool
    #: The last plan draft ended in a terminal "cannot plan" outcome (everything
    #: taught, too few lessons before the exam, no chapters), so the class counts
    #: as set up with no plan. The class page says why.
    plan_not_needed: bool = False


class SubjectStatus(BaseModel):
    subject_id: int
    subject_name: str
    required: list[StepDone]
    items: list[ItemStatus]
    #: Over the Defaulted items only. `reviewed` and `set_by_you` both count.
    reviewed_count: int
    review_total: int
    classes: list[ClassStatus]


class NextStep(BaseModel):
    key: str
    subject_id: int | None
    group_id: int | None


class OnboardingState(BaseModel):
    complete: bool
    #: True while none of the caller's classes has an accepted teaching plan: the
    #: tutor's home is the setup flow. Not simply `not complete`: a class set up
    #: before a newer required step existed (e.g. `taught_before`) owes that step
    #: on the checklist, but its tutor has crossed the finish line and must not be
    #: sent back into the flow.
    in_flow: bool
    #: Whether the caller set the workspace up (the earliest tutor of the
    #: organization). Time zone, boundaries and marking defaults are theirs; a
    #: later member's flow is their own classes only.
    is_owner: bool = True
    account: ItemStatus
    subjects: list[SubjectStatus]
    next_step: NextStep | None


class AcknowledgementIn(BaseModel):
    item: SetupItem
    #: Bounded to a Postgres integer: an id past int32 fails in the driver, not as a 404.
    subject_id: int | None = Field(default=None, ge=1, le=2**31 - 1)
