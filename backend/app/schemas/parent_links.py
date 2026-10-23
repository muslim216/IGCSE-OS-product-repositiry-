from datetime import datetime

from pydantic import BaseModel


class LinkedParentOut(BaseModel):
    """One adult who can read a child's record. `id` is the link's, which is what
    removing it takes."""

    id: int
    parent_id: int
    name: str
    email: str
    linked_at: datetime
