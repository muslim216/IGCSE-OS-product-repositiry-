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


class NextLesson(BaseModel):
    """The next occurrence of a group's weekly timetable."""

    weekday: int
    start_time: time
    duration_min: int
    title: str | None


class GroupSummary(BaseModel):
    """The aggregates a class card needs at a glance."""

    member_count: int = 0
    published_assignment_count: int = 0
    awaiting_review_count: int = 0
    next_lesson: NextLesson | None = None


class GroupOut(GroupSummary):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: SubjectOut


class GroupDetail(GroupSummary):
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


class ScheduleSlotCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_time: time
    duration_min: int = Field(default=60, ge=15, le=480)
    title: str | None = Field(default=None, max_length=128)


class ScheduleSlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    weekday: int
    start_time: time
    duration_min: int
    title: str | None


class ClassBrief(BaseModel):
    brief: str


class UpcomingScheduleSlot(BaseModel):
    id: int
    group_id: int
    group_name: str
    subject_name: str
    weekday: int
    start_time: time
    duration_min: int
    title: str | None
