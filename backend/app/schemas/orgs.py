from pydantic import BaseModel, Field


class OrganizationOut(BaseModel):
    id: int
    name: str
    # None means no zone has been captured and the server is answering in UTC.
    # The UI states that rather than showing a silent default, so a tutor whose
    # "today" is wrong can see why.
    timezone: str | None
    # The weekly send moment (Mon=0..Sun=6, hour in the organization's zone) and
    # the language the AI writes in (task 8.1).
    weekly_send_weekday: int
    weekly_send_hour: int
    ai_language: str


class OrganizationTimezoneUpdate(BaseModel):
    # Nullable so a tutor can clear it back to the UTC fallback. The IANA name
    # itself is validated against the tz database in the handler — max_length
    # bounds the input, it does not make it meaningful.
    timezone: str | None = Field(default=None, max_length=64)
