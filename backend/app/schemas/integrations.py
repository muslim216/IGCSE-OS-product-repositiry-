from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.models import MeetingImportStatus, MeetingProvider


class IntegrationStatusOut(BaseModel):
    provider: MeetingProvider
    #: False until the owner registers the provider's app: shown as "not set up
    #: yet", never as an error.
    configured: bool
    connected: bool
    account_email: str | None
    connected_at: datetime | None
    #: What the tutor must know before connecting (e.g. Meet needs Workspace).
    note: str


class IntegrationAuthUrlOut(BaseModel):
    url: str
    state: str


class MeetingParticipantOut(BaseModel):
    id: int
    display_name: str
    email: str | None
    duration_seconds: int
    #: `null` = nobody matched this participant: the tutor decides.
    matched_student_id: int | None
    #: A student whose email matched but whom the provider did not verify: the
    #: tutor confirms with one tap; nothing was marked.
    suggested_student_id: int | None = None
    #: True once a tutor has decided who this is (by resolving it), as opposed to a
    #: provider-verified email match made by the import. A resolved participant is
    #: kept across re-imports and cannot be resolved again.
    resolved: bool


class MeetingImportOut(BaseModel):
    status: MeetingImportStatus
    #: Why it failed (`not_connected`, `auth_failed`, `no_data`, ...); `null` otherwise.
    error_code: str | None
    message: str | None
    finished_at: datetime | None


class LessonMeetingOut(BaseModel):
    provider: MeetingProvider | None
    link: str | None
    last_import: MeetingImportOut | None
    participants: list[MeetingParticipantOut]


class ParticipantResolve(BaseModel):
    student_id: Annotated[int, Field(ge=1)]
