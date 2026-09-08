"""The teaching-guidance document's contract."""

from datetime import datetime

from pydantic import BaseModel


class TeachingGuidanceOut(BaseModel):
    """What is on file for a subject — or that nothing is.

    `uploaded` is explicit rather than inferred from a null filename: absence is
    a state the surface renders as absence ("no guidance uploaded yet"), never
    as an empty row that looks like a broken one (`PROD-2`, `UX-19`).
    """

    subject_id: int
    subject_name: str
    uploaded: bool
    file_name: str | None = None
    file_mime: str | None = None
    uploaded_at: datetime | None = None
