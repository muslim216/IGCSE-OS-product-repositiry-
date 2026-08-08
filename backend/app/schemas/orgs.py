from pydantic import BaseModel, Field


class OrganizationOut(BaseModel):
    id: int
    name: str
    # None means no zone has been captured and the server is answering in UTC.
    # The UI states that rather than showing a silent default, so a tutor whose
    # "today" is wrong can see why.
    timezone: str | None


class OrganizationTimezoneUpdate(BaseModel):
    # Nullable so a tutor can clear it back to the UTC fallback. The IANA name
    # itself is validated against the tz database in the handler — max_length
    # bounds the input, it does not make it meaningful.
    timezone: str | None = Field(default=None, max_length=64)
