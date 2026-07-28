from datetime import datetime

from pydantic import BaseModel


class GoogleAccountOut(BaseModel):
    connected: bool
    configured: bool
    google_email: str | None = None
    status: str | None = None
    # Google's consent screen lets users untick individual permissions; without
    # these the import can't work, so the UI has to say which are missing.
    missing_scopes: list[str] = []
    last_error: str | None = None
    connected_at: datetime | None = None


class AuthorizeUrl(BaseModel):
    authorize_url: str


class GoogleCourse(BaseModel):
    course_id: str
    name: str
    section: str | None = None
    linked_group_id: int | None = None


class GoogleCoursework(BaseModel):
    coursework_id: str
    title: str
    linked_assignment_id: int | None = None


class CourseLinkCreate(BaseModel):
    course_id: str
    group_id: int


class CourseLinkOut(BaseModel):
    id: int
    course_id: str
    course_name: str | None
    group_id: int


class RosterEntry(BaseModel):
    google_user_id: str
    google_name: str | None
    google_email: str | None
    mapped_student_id: int | None = None
    suggested_student_id: int | None = None


class UnmatchedStudent(BaseModel):
    """An app student with no Classroom counterpart, so nobody looks missing."""

    student_id: int
    name: str


class RosterOut(BaseModel):
    classroom_students: list[RosterEntry]
    app_students_not_in_classroom: list[UnmatchedStudent]


class RosterMapping(BaseModel):
    google_user_id: str
    student_id: int | None


class ImportRequest(BaseModel):
    assignment_id: int


class ImportResultRow(BaseModel):
    google_user_id: str
    outcome: str
    detail: str | None
    imported_file_count: int


class ImportRunOut(BaseModel):
    id: int
    status: str
    total: int
    imported: int
    skipped: int
    failed: int
    error: str | None
    finished_at: datetime | None
    results: list[ImportResultRow] = []
