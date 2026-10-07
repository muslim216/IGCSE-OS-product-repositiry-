from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AttemptRedoOut(BaseModel):
    """What a tutor sees about an attempt they set aside. The snapshot itself is
    kept but not exposed here: this is the receipt, not the record."""

    id: int
    created_at: datetime
    allowed_by_id: int
    allowed_by_name: str
    work_kind: Literal["homework", "past_paper", "mock"]
    work_title: str
    #: Over the questions that had a final mark, both together. `None` — never 0 —
    #: when none did (`PROD-2`).
    previous_final_marks: int | None
    previous_max_marks: int | None
    #: How many of the attempt's questions had a final mark, out of how many it
    #: had. Lets a screen say "2 of 2 on the 1 of 3 questions marked" instead of
    #: a score over some questions that reads like a score over all of them.
    previous_questions_marked: int
    previous_question_count: int
