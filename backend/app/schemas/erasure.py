from datetime import datetime

from pydantic import BaseModel


class DataExportOut(BaseModel):
    """Where a child's data export is up to. `expires_at` is set once it is ready:
    the file is deleted then, and asking again makes a new one."""

    id: int
    status: str
    expires_at: datetime | None
    error: str | None
