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


class LibraryResourceOut(ResourceOut):
    """A shared file or recording with the class it was shared with, for the
    tutor's Library, which lists material across every class at once."""

    group_name: str
