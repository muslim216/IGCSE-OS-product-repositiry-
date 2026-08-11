from datetime import datetime

from pydantic import BaseModel


class NarrativeOut(BaseModel):
    """The latest stored narrative for one target, or a stated absence.

    `text` is None — never "" — when nothing has been generated yet, so a surface
    renders the absence in words rather than an empty panel (PROD-2, UX-19). No
    review fields: there is no review step (D2), and adding one "just in case"
    would invite a workflow to grow around it.
    """

    text: str | None
    generated_at: datetime | None
    prompt_version: str | None
