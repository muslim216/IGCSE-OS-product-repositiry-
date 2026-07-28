from datetime import datetime

from pydantic import BaseModel


class ActivityItem(BaseModel):
    """One thing that has happened and may want the reader's attention."""

    kind: str
    label: str
    sublabel: str | None = None
    # Client-side route, so the header can link straight to the thing.
    link: str
    occurred_at: datetime


class ActivitySummary(BaseModel):
    count: int
    items: list[ActivityItem]
