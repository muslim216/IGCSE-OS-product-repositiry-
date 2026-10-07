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
