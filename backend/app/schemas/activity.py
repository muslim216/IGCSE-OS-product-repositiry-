from datetime import datetime

from pydantic import BaseModel


class ActivityItem(BaseModel):
    kind: str
    label: str
    sublabel: str | None = None
    #: Frontend route this item opens.
    link: str
    occurred_at: datetime


class ActivitySummary(BaseModel):
    #: Everything outstanding, which may exceed the items returned.
    count: int
    items: list[ActivityItem]
