from datetime import datetime

from pydantic import BaseModel, Field


class ClassroomStatus(BaseModel):
    configured: bool
    connected: bool
    google_email: str | None = None
    connected_at: datetime | None = None


class ClassroomAuthUrl(BaseModel):
    url: str
    state: str


class ClassroomConnect(BaseModel):
    code: str = Field(min_length=1)
    # The `state` handed out by /auth-url and echoed back by Google. Verified
    # server-side against the tutor making this call — see security.py.
    state: str = Field(min_length=1)


class ClassroomCourseOut(BaseModel):
    id: str
    name: str


class ClassroomLinkCreate(BaseModel):
    group_id: int
    classroom_course_id: str = Field(min_length=1)
    classroom_course_name: str = Field(min_length=1, max_length=255)


class ClassroomLinkOut(BaseModel):
    id: int
    group_id: int
    group_name: str
    classroom_course_id: str
    classroom_course_name: str
    last_synced_at: datetime | None
