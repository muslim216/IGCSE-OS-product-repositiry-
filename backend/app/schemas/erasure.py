from datetime import datetime

from pydantic import BaseModel, Field


class DataExportOut(BaseModel):
    """Where a child's data export is up to. `expires_at` is set once it is ready:
    the file is deleted then, and asking again makes a new one."""

    id: int
    status: str
    expires_at: datetime | None
    error: str | None


class ErasureRequestIn(BaseModel):
    """The child's full name, typed by whoever asks. Checked server-side; the
    browser's comparison is only a convenience."""

    confirm_name: str = Field(min_length=1, max_length=200)


class ErasureRequestOut(BaseModel):
    """A deletion that is waiting out its undo window. No requester id and no file
    paths: neither is the caller's to see."""

    id: int
    status: str
    scheduled_for: datetime
    requested_role: str
    created_at: datetime
