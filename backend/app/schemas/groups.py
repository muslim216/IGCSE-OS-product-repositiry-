from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.auth import UserOut


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_board: str
    code: str
    name: str
    grade_scale: str


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    title: str
    parent_id: int | None
    weight: float


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    subject_id: int


class GroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class GroupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: SubjectOut
    member_count: int = 0


class GroupDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: SubjectOut
    members: list[UserOut]


class InviteOut(BaseModel):
    code: str
    kind: str
    expires_at: datetime | None


class InvitePreview(BaseModel):
    """What a visitor sees before accepting an invite."""

    kind: str
    group_name: str | None = None
    subject_name: str | None = None
    tutor_name: str | None = None
    student_name: str | None = None


class StudentCreate(BaseModel):
    """Tutor-created account for a student without an email address."""

    name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)


class StudentPasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class StudentRegisterRequest(BaseModel):
    invite_code: str
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ParentRegisterRequest(BaseModel):
    link_code: str
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class JoinRequest(BaseModel):
    invite_code: str


class LessonCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    duration_min: int = Field(default=60, ge=15, le=480)
    title: str | None = Field(default=None, max_length=128)


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    weekday: int
    start_time: time
    duration_min: int
    title: str | None


class UpcomingLesson(BaseModel):
    group_id: int
    group_name: str
    subject_name: str
    weekday: int
    start_time: time
    duration_min: int
    title: str | None
