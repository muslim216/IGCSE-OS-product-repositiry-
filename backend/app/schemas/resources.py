from datetime import datetime

from pydantic import BaseModel


class ResourceOut(BaseModel):
    id: int
    group_id: int
    kind: str
    title: str
    url: str | None
    file_name: str | None
    created_at: datetime
