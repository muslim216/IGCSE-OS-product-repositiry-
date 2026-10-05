from datetime import datetime

from pydantic import BaseModel

from app.models import WeeklySendAudience
from app.services.weekly_send_facts import ParentFacts, StudentFacts, TutorFacts


class WeeklySendParagraph(BaseModel):
    """A stored narrative as it stood at the send: who or what it is about, and
    the text. The same row the class page or parent screen was showing."""

    about: str
    text: str


class WeeklySendListItem(BaseModel):
    id: int
    audience: WeeklySendAudience
    recipient_user_id: int
    recipient_name: str
    week_start: datetime
    week_end: datetime


class WeeklySendOut(BaseModel):
    """One reader's week. Exactly one of `tutor`, `student`, `parent` is set —
    the one `audience` names — so a client reads a typed fact set rather than
    guessing the shape of a blob (`FE-4`)."""

    id: int
    audience: WeeklySendAudience
    recipient_user_id: int
    week_start: datetime
    week_end: datetime
    tutor: TutorFacts | None = None
    student: StudentFacts | None = None
    parent: ParentFacts | None = None
    paragraphs: list[WeeklySendParagraph]
