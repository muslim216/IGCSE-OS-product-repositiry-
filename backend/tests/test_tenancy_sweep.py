"""01-KG-3 / RISK-7: every route refuses another workspace's rows.

Organization scoping is applied per query, as a habit. A route that forgets the
filter leaks another tutor's data and nothing used to notice. This test is the
mechanism. Three workspaces are seeded, each with a tutor, an admin, a student,
a parent (linked to that student) and one row of every kind a path can name. A is
the target, B the attacker, C a control. A's rows carry a unique marker in their
names and titles. The routes come from `app`, not from a list in this file.

What it asserts, exactly:

1. Path ids. Every route and every method with an integer path parameter is called
   as B's callers with A's real ids and must answer 404 (`API-7`: not 403, not 200,
   not 422, which would mean validation ran before the ownership check). Callers
   are the roles the route admits: tutor and admin for a tutor gate, student for a
   student gate, and all four (tutor, admin, student, parent) for a route open to
   any signed-in user.
2. Ids in a query, form or body. Every field named `*_id` (or an id list `*_ids`)
   in any route's query, form or JSON body, required or optional and nested in
   lists too, is aimed at A's row one field at a time while the rest of the request
   is B's own valid request. It must answer 404. A listing that filters by that id
   may answer 200 only when nothing of A's is in the body.
3. Listings. Every signed-in GET without a path id is called as B's callers.
4. Nothing of A's comes back. A's marker must appear in no response body in 1-3.
   A's own tutor must see the marker in at least ten listings, so this check is not
   hollow.
5. Refusals change nothing. Every table's rows are hashed before and after the
   attacks and must be identical (bar `WRITTEN_BY_READS`).
6. Each attack has a control. The same request, with the caller's own workspace's
   id in place of A's, must answer 2xx, so the 404 is about tenancy and not a
   missing file or a bad body. Exceptions are in `CONTROL_EXCEPTIONS`, each with a
   reason, and a stale one fails.

A 403 is accepted only when it is the role gate's own message ("Tutor account
required" / "Student account required"): that is `SEC-11` refusing the role before
any id is read, not an ownership answer. A route with a path id that is neither
swept nor in `UNRESOLVED`, and an id field neither swept nor in `FIELD_UNRESOLVED`,
fails the test, so a new route is covered the day it is written.

Not covered: ids that are not named `*_id` (a bare `id`, string keys such as
`/auth/invites/{code}`, `/integrations/{provider}`, `/me/dismissals/{key}`), ids
nested deeper than three levels, and routes outside `app.routes`. Public routes
are not listings. `get_current_org_id` / `CurrentOrg` were unused and are deleted
from `api/deps.py`; scoping is per query, and this test is what checks it.
"""

import re
import time
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import get_current_user, require_student, require_tutor
from app.db import async_session, engine
from app.main import app
from app.models import (
    AssignmentStatus,
    Base,
    Booklet,
    Chapter,
    Classified,
    ContactPoint,
    CustomCriterion,
    GroupResource,
    Lesson,
    Mistake,
    MistakeSource,
    Mock,
    MockStatus,
    NotificationChannel,
    PlanBreak,
    PlanSlot,
    QuestionMark,
    Report,
    ReportAudience,
    ResourceKind,
    ScheduleSlot,
    SubmissionFile,
    SubmissionStatus,
    SyllabusUpload,
    TeachingPlan,
    Topic,
    User,
    UserRole,
    WeeklySend,
    WeeklySendAudience,
    WorkKind,
)
from app.models.integrations import MeetingParticipant, MeetingProvider
from app.services import storage
from app.services.work import create_work
from tests.factories import (
    link_parent,
    make_mistake_category,
    make_past_paper,
    make_subject,
    make_user,
    publish_assignment,
    register_other_tutor,
    submit_work,
)
from tests.test_authorization import _dependency_calls, _iter_api_routes

PREFIX = "/api/v1"
PDF = b"%PDF-1.4 fake"
ROLES = ("tutor", "admin", "student", "parent")
#: The role gates' own words. "Not allowed" is a listing refusing a parent, who
#: has no booklets or past papers of their own.
ROLE_REFUSALS = {
    "Tutor account required",
    "Student account required",
    "Not allowed",
    "Only tutors can generate reports",
}

#: Bodies the generic generator cannot guess because the model validates across
#: fields, so a minimal one is still invalid and would answer 422 before the
#: ownership check runs.
BODIES: dict[tuple[str, str], dict] = {
    # An item that is per subject: an account-wide one refuses any subject_id.
    ("POST", "/onboarding/acknowledgements"): {"item": "boundaries"},
    ("POST", "/groups/{group_id}/students"): {
        "name": "New Kid",
        "username": "new.kid",
        "password": "password123",
    },
    ("PATCH", "/groups/{group_id}/plan/slots/{slot_id}"): {"scheduled_date": "2030-01-01"},
    ("PUT", "/subjects/{subject_id}/grade-boundaries"): {
        "boundaries": [{"grade": "9", "min": 90}, {"grade": "U", "min": 0}]
    },
}

#: Routes with an integer path parameter this sweep cannot call as a foreign
#: workspace, each with the reason. Keyed by (METHOD, path-template).
UNRESOLVED: dict[tuple[str, str], str] = {}

#: Id fields this sweep cannot aim at A's row, each with the reason. Keyed by
#: (METHOD, path-template, dotted field path).
FIELD_UNRESOLVED: dict[tuple[str, str, str], str] = {}

#: Aimed fields where the handler skips an id that is not in the caller's own
#: parent row instead of refusing it, so the answer is 200 with nothing written.
#: Keyed (METHOD, path-template, dotted field path). That is not a leak: the answer
#: to a foreign id is the same as to one that does not exist, so there is no way to
#: tell A's ids from nothing, and the marker and row checks still run on it.
SILENT_200: dict[tuple[str, str, str], str] = {
    ("PUT", "/assignments/{assignment_id}/questions", "[].topic_ids"): (
        "topic ids outside the assignment's own subject are dropped from the question"
    ),
    ("PUT", "/submissions/{submission_id}/marks", "[].question_id"): (
        "save_marks skips question ids that are not on this submission's own paper"
    ),
    ("GET", "/groups/{group_id}/plan/next-lesson", "slot_id"): (
        "the slot is looked up inside the class's own accepted plan, else the answer is null"
    ),
}

#: Aimed fields whose handler answers a foreign id with a validation error (422/409)
#: instead of 404. Accepted only because the answer is word for word what an id
#: that does not exist gets: the test aims the field at 10**9 as well and requires
#: the same status and body, so the answer cannot tell A's rows from nothing.
INDISTINGUISHABLE: dict[tuple[str, str, str], str] = {
    ("POST", "/assessments", "scores.[].student_id"): "a student the tutor does not teach",
    ("POST", "/assessments", "scores.[].topic_id"): "topics of the subject",
    ("PATCH", "/groups/{group_id}/plan/slots/{slot_id}", "chapter_id"): "chapter of the subject",
    ("PUT", "/groups/{group_id}/taught-before", "topic_ids"): "topics of the subject",
    ("POST", "/lessons", "topic_ids"): "topics of the subject",
    ("PUT", "/lessons/{lesson_id}/topics", "topic_ids"): "topics of the subject",
}

#: Routes that need a differently-shaped seeded row than the default for the caller
#: to reach the check at all: (METHOD, path-template) -> {path param: ids key}.
ID_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("PUT", "/assignments/{assignment_id}/questions"): {"assignment_id": "_assignment_review_id"},
}

#: Tables where a request answered 200 for the caller's own row may add rows, with
#: the reason. Rows already there still may not change or disappear.
WRITTEN_BY_READS: dict[str, str] = {
    "assignment_questions": "SILENT_200 PUT .../questions rewrites B's own draft",
}

#: (caller, METHOD, path-template, field) where the owner's own control call is
#: not 2xx, so a refusal there proves less. The field is "" for a path-id call.
_NO_CLAIM_PARENT = "a parent sees only their own child's records; this row is not one"
_NO_CLAIM_STUDENT = "tutor-owned material the student has no claim on"
_NO_CLAIM_ADMIN = "the seeded row belongs to the workspace's tutor; an admin is not that tutor"
_NEEDS_STATE = (
    "the route needs state this seed does not build (an accepted plan, a lesson on the slot's date)"
)
_STATE = (
    "the owner reaches the row and is then refused by a state rule (409): it needs a draft, "
    "failed or unsettled row. The row was found, so a foreign 404 still tells the two apart"
)
_BODY = (
    "the owner reaches the row and is then refused by a rule on the generated body (422) "
    "or an upload the generic body cannot fake"
)
_FORBIDDEN = "the owner is refused by the handler's own rule (an admin who does not teach the student; accounts with email)"

CONTROL_EXCEPTIONS: dict[tuple[str, str, str, str], str] = {
    ("parent", "GET", "/booklets/{booklet_id}", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/booklets/{booklet_id}/file", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/classifieds/{classified_id}/file", ""): _NO_CLAIM_PARENT,  # owner gets 404
    (
        "parent",
        "GET",
        "/classifieds/{classified_id}/mark-scheme",
        "",
    ): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/groups/{group_id}/resources", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/mocks/{mock_id}", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/mocks/{mock_id}/paper", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/past-papers/{past_paper_id}", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/past-papers/{past_paper_id}/paper", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/reports/{report_id}", ""): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/resources/{resource_id}/file", ""): _NO_CLAIM_PARENT,  # owner gets 404
    (
        "parent",
        "GET",
        "/submissions/{submission_id}/files/{file_id}",
        "",
    ): _NO_CLAIM_PARENT,  # owner gets 404
    ("parent", "GET", "/weekly-sends/{send_id}", ""): _NO_CLAIM_PARENT,  # owner gets 404
    (
        "student",
        "GET",
        "/classifieds/{classified_id}/file",
        "",
    ): _NO_CLAIM_STUDENT,  # owner gets 404
    (
        "student",
        "GET",
        "/classifieds/{classified_id}/mark-scheme",
        "",
    ): _NO_CLAIM_STUDENT,  # owner gets 404
    ("student", "GET", "/reports/{report_id}", ""): _NO_CLAIM_STUDENT,  # owner gets 404
    ("student", "GET", "/students/{student_id}/narrative", ""): _NO_CLAIM_STUDENT,  # owner gets 404
    ("student", "GET", "/weekly-sends/{send_id}", ""): _NO_CLAIM_STUDENT,  # owner gets 404
    ("admin", "POST", "/assignments", "group_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/assignments", "lesson_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/assignments", "classified_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    (
        "admin",
        "POST",
        "/groups/{group_id}/plan/slots/{slot_id}/cancel",
        "",
    ): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/lessons", "plan_slot_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/me/contacts/{contact_id}/confirm", ""): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/mocks", "group_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "PATCH", "/mocks/{mock_id}", ""): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "PATCH", "/mocks/{mock_id}", "group_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/observations", "student_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "POST", "/observations", "topic_id"): _NO_CLAIM_ADMIN,  # owner gets 404
    ("admin", "GET", "/students/{student_id}/observations", ""): _NO_CLAIM_ADMIN,  # owner gets 404
    (
        "admin",
        "POST",
        "/students/{student_id}/seed-readiness",
        "",
    ): _NO_CLAIM_ADMIN,  # owner gets 404
    (
        "admin",
        "POST",
        "/students/{student_id}/seed-readiness",
        "topics.[].topic_id",
    ): _NO_CLAIM_ADMIN,  # owner gets 404
    (
        "tutor",
        "POST",
        "/groups/{group_id}/plan/slots/{slot_id}/cancel",
        "",
    ): _NEEDS_STATE,  # owner gets 404
    ("tutor", "POST", "/lessons", "plan_slot_id"): _NEEDS_STATE,  # owner gets 404
    ("tutor", "POST", "/assignments/{assignment_id}/publish", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/assignments/{assignment_id}/publish", ""): _STATE,  # owner gets 409
    (
        "tutor",
        "POST",
        "/assignments/{assignment_id}/retry-extraction",
        "",
    ): _STATE,  # owner gets 409
    (
        "admin",
        "POST",
        "/assignments/{assignment_id}/retry-extraction",
        "",
    ): _STATE,  # owner gets 409
    ("tutor", "POST", "/booklets/{booklet_id}/approve", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/booklets/{booklet_id}/approve", ""): _STATE,  # owner gets 409
    ("tutor", "PUT", "/booklets/{booklet_id}/draft", ""): _STATE,  # owner gets 409
    ("admin", "PUT", "/booklets/{booklet_id}/draft", ""): _STATE,  # owner gets 409
    ("tutor", "POST", "/booklets/{booklet_id}/retry", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/booklets/{booklet_id}/retry", ""): _STATE,  # owner gets 409
    ("tutor", "POST", "/groups/{group_id}/plan/accept", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/groups/{group_id}/plan/accept", ""): _STATE,  # owner gets 409
    ("tutor", "POST", "/groups/{group_id}/plan/replan", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/groups/{group_id}/plan/replan", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/groups/{group_id}/students", ""): _STATE,  # owner gets 409
    ("tutor", "POST", "/lessons/{lesson_id}/attendance/import", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/lessons/{lesson_id}/attendance/import", ""): _STATE,  # owner gets 409
    (
        "admin",
        "POST",
        "/lessons/{lesson_id}/participants/{participant_id}/resolve",
        "",
    ): _STATE,  # owner gets 409
    (
        "admin",
        "POST",
        "/lessons/{lesson_id}/participants/{participant_id}/resolve",
        "student_id",
    ): _STATE,  # owner gets 409
    ("tutor", "PUT", "/past-papers/{past_paper_id}/paper", ""): _STATE,  # owner gets 409
    ("admin", "PUT", "/past-papers/{past_paper_id}/paper", ""): _STATE,  # owner gets 409
    (
        "tutor",
        "POST",
        "/past-papers/{past_paper_id}/retry-extraction",
        "",
    ): _STATE,  # owner gets 409
    (
        "admin",
        "POST",
        "/past-papers/{past_paper_id}/retry-extraction",
        "",
    ): _STATE,  # owner gets 409
    ("tutor", "POST", "/reports/generate", "student_id"): _STATE,  # owner gets 409
    ("admin", "POST", "/reports/generate", "student_id"): _STATE,  # owner gets 409
    ("tutor", "POST", "/reports/generate", "subject_id"): _STATE,  # owner gets 409
    ("admin", "POST", "/reports/generate", "subject_id"): _STATE,  # owner gets 409
    ("admin", "POST", "/students/{student_id}/subjects", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/students/{student_id}/subjects", "subject_id"): _STATE,  # owner gets 409
    (
        "student",
        "POST",
        "/submissions/{submission_id}/questions/{question_id}/remark-request",
        "",
    ): _STATE,  # owner gets 409
    ("tutor", "POST", "/submissions/{submission_id}/redo", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/submissions/{submission_id}/redo", ""): _STATE,  # owner gets 409
    ("tutor", "POST", "/submissions/{submission_id}/retry-marking", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/submissions/{submission_id}/retry-marking", ""): _STATE,  # owner gets 409
    ("tutor", "POST", "/syllabus-uploads/{upload_id}/retry", ""): _STATE,  # owner gets 409
    ("admin", "POST", "/syllabus-uploads/{upload_id}/retry", ""): _STATE,  # owner gets 409
    ("student", "POST", "/assignments/{assignment_id}/submissions", ""): _BODY,  # owner gets 422
    ("admin", "POST", "/groups/{group_id}/plan/breaks", ""): _BODY,  # owner gets 422
    ("tutor", "PATCH", "/groups/{group_id}/plan/slots/{slot_id}", ""): _BODY,  # owner gets 422
    ("admin", "PATCH", "/groups/{group_id}/plan/slots/{slot_id}", ""): _BODY,  # owner gets 422
    (
        "tutor",
        "PATCH",
        "/groups/{group_id}/plan/slots/{slot_id}",
        "chapter_id",
    ): _BODY,  # owner gets 422
    (
        "admin",
        "PATCH",
        "/groups/{group_id}/plan/slots/{slot_id}",
        "chapter_id",
    ): _BODY,  # owner gets 422
    ("tutor", "POST", "/groups/{group_id}/resources", ""): _BODY,  # owner gets 422
    ("admin", "POST", "/groups/{group_id}/resources", ""): _BODY,  # owner gets 422
    ("student", "POST", "/mocks/{mock_id}/submissions", ""): _BODY,  # owner gets 422
    ("tutor", "PUT", "/students/{student_id}/contacts", ""): _BODY,  # owner gets 422
    ("admin", "PUT", "/students/{student_id}/contacts", ""): _BODY,  # owner gets 422
    ("tutor", "PUT", "/students/{student_id}/contacts", "user_id"): _BODY,  # owner gets 422
    ("admin", "PUT", "/students/{student_id}/contacts", "user_id"): _BODY,  # owner gets 422
    ("tutor", "POST", "/submissions/{submission_id}/finalize", ""): _BODY,  # owner gets 422
    ("admin", "POST", "/submissions/{submission_id}/finalize", ""): _BODY,  # owner gets 422
    ("tutor", "POST", "/syllabus-uploads/{upload_id}/apply", ""): _BODY,  # owner gets 422
    ("admin", "POST", "/syllabus-uploads/{upload_id}/apply", ""): _BODY,  # owner gets 422
    ("admin", "POST", "/assessments", "scores.[].student_id"): _FORBIDDEN,  # owner gets 403
    ("admin", "POST", "/assessments", "scores.[].topic_id"): _FORBIDDEN,  # owner gets 403
    (
        "tutor",
        "POST",
        "/groups/{group_id}/students/{student_id}/reset-password",
        "",
    ): _FORBIDDEN,  # owner gets 403
    (
        "admin",
        "POST",
        "/groups/{group_id}/students/{student_id}/reset-password",
        "",
    ): _FORBIDDEN,  # owner gets 403
}


# --- Seeding -----------------------------------------------------------------


async def _stored(organization_id: int, prefix: str = "") -> dict:
    """A real stored PDF, as column values. A row pointing at no file answers 404
    to its owner too, which would let a missing ownership check hide behind it."""
    key, name, mime = await storage.save_bytes(
        PDF, "application/pdf", "x.pdf", organization_id=organization_id, counted=False
    )
    return {f"{prefix}path": key, f"{prefix}name": name, f"{prefix}mime": mime}


async def _seed_org(client, tutor, *, code: str, tag: str) -> dict:
    """One workspace: a tutor, a class, a student and one row of every kind a
    path can name. Returns the ids by the path-parameter name that reaches them."""
    uid = tutor["user"]["id"]
    marker = f"ORG{tag.upper()}-7f3"  # unique to this workspace, in every name and title
    async with async_session() as s:
        organization_id = await s.scalar(select(User.organization_id).where(User.id == uid))
        (await s.get(User, uid)).name = f"Tutor {marker}"
        subject = await make_subject(
            s, organization_id=organization_id, code=code, name=f"Chemistry {marker}"
        )
        topic = Topic(subject_id=subject.id, code="1.1", title=f"Topic {marker}")
        chapter = Chapter(subject_id=subject.id, code="1", title=f"Chapter {marker}")
        s.add_all([topic, chapter])
        await s.commit()
        subject_id, topic_id, chapter_id = subject.id, topic.id, chapter.id

    group = await client.post(
        "/api/v1/groups",
        json={"name": f"Class {marker}", "subject_id": subject_id},
        headers=tutor["headers"],
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    invite = await client.post(f"/api/v1/groups/{group_id}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": f"Student {marker}",
            "email": f"student-{tag}@example.com",
            "password": "password123",
        },
    )
    assert reg.status_code == 201, reg.text
    student = {
        "user": reg.json()["user"],
        "headers": {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"},
    }
    student_id = student["user"]["id"]

    async with async_session() as s:
        ids = {
            "subject_id": subject_id,
            "topic_id": topic_id,
            "group_id": group_id,
            "student_id": student_id,
            "organization_id": organization_id,
        }
        assignment = await publish_assignment(
            s,
            group_id=group_id,
            subject_id=subject_id,
            organization_id=organization_id,
            topic_ids=(topic_id,),
            title=f"Homework {marker}",
        )
        ids["assignment_id"] = assignment.id
        review = await publish_assignment(
            s,
            group_id=group_id,
            subject_id=subject_id,
            organization_id=organization_id,
            title=f"Draft {marker}",
        )
        review.status = AssignmentStatus.review  # only a draft can have its questions edited
        ids["_assignment_review_id"] = review.id
        from app.models import AssignmentQuestion

        ids["question_id"] = await s.scalar(
            select(AssignmentQuestion.id).where(AssignmentQuestion.assignment_id == assignment.id)
        )
        submission = await submit_work(
            s,
            assignment=assignment,
            student_id=student_id,
            status=SubmissionStatus.needs_review,
            submitted_at=date.today(),
        )
        ids["submission_id"] = submission.id
        file = SubmissionFile(
            submission_id=submission.id,
            position=0,
            **await _stored(organization_id),
        )
        mark = QuestionMark(
            submission_id=submission.id,
            question_id=ids["question_id"],
            ai_marks=1,
            needs_review=True,  # still waiting: a refused save_marks must not move it on
        )
        s.add_all([file, mark])
        await s.flush()
        ids["file_id"] = file.id
        category = await make_mistake_category(
            s, organization_id=organization_id, subject_id=subject_id
        )
        mistake = Mistake(
            student_id=student_id,
            question_mark_id=mark.id,
            category_id=category.id,
            source=MistakeSource.ai,
        )
        s.add(mistake)
        await s.flush()
        ids["mistake_id"] = mistake.id
        ids["category_id"] = category.id
        ids["chapter_id"] = chapter_id

        paper = await make_past_paper(
            s,
            subject_id=subject_id,
            organization_id=organization_id,
            tutor_id=uid,
            **await _stored(organization_id, "paper_"),
            **await _stored(organization_id, "mark_scheme_"),
        )
        booklet = await s.get(Booklet, paper.booklet_id)
        for k, v in (await _stored(organization_id, "mark_scheme_")).items():
            setattr(booklet, k, v)
        ids["past_paper_id"] = paper.id
        ids["booklet_id"] = paper.booklet_id

        work = await create_work(
            s,
            kind=WorkKind.mock,
            organization_id=organization_id,
            subject_id=subject_id,
            title=f"Mock {marker}",
        )
        mock = Mock(
            organization_id=organization_id,
            tutor_id=uid,
            subject_id=subject_id,
            title=f"Mock {marker}",
            group_id=group_id,
            status=MockStatus.published,
            **await _stored(organization_id, "paper_"),
            **await _stored(organization_id, "mark_scheme_"),
            work_id=work.id,
        )
        classified = Classified(
            organization_id=organization_id,
            tutor_id=uid,
            subject_id=subject_id,
            title=f"Classified {marker}",
            **await _stored(organization_id, "file_"),
            **await _stored(organization_id, "mark_scheme_"),
        )
        lesson = Lesson(organization_id=organization_id, group_id=group_id, date=date.today())
        slot = ScheduleSlot(group_id=group_id, weekday=1, start_time=_time())
        resource = GroupResource(
            group_id=group_id,
            tutor_id=uid,
            kind=ResourceKind.file,
            title=f"Notes {marker}",
            **await _stored(organization_id, "file_"),
        )
        contact = ContactPoint(
            organization_id=organization_id,
            user_id=student_id,
            channel=NotificationChannel.email,
            address=f"parent-{marker}@example.com",
        )
        criterion = CustomCriterion(
            organization_id=organization_id, name=f"Criterion {marker}", created_by_id=uid
        )
        upload = SyllabusUpload(
            tutor_id=uid,
            title=f"Syllabus {marker}",
            file_path="s.pdf",
            file_name="s.pdf",
            file_mime="application/pdf",
        )
        send = WeeklySend(
            organization_id=organization_id,
            recipient_user_id=uid,
            audience=WeeklySendAudience.tutor,
            week_start=date.today(),
            week_end=date.today() + timedelta(days=6),
            facts={
                "window_start": "2026-01-05T00:00:00+00:00",
                "window_end": "2026-01-12T00:00:00+00:00",
                "classes": [],
                "review_queue": 0,
                "marked": None,
            },
        )
        report = Report(
            student_id=student_id,
            generated_by_id=uid,
            audience=ReportAudience.tutor,
            title=f"Report {marker}",
        )
        plan = TeachingPlan(
            organization_id=organization_id,
            group_id=group_id,
            exam_date=date.today() + timedelta(days=90),
            lessons_per_week=1,
            lesson_minutes=60,
        )
        s.add_all(
            [
                mock,
                classified,
                lesson,
                slot,
                resource,
                contact,
                criterion,
                upload,
                send,
                report,
                plan,
            ]
        )
        await s.flush()
        plan_slot = PlanSlot(
            plan_id=plan.id, chapter_id=chapter_id, scheduled_date=date.today(), sequence=1
        )
        plan_break = PlanBreak(
            plan_id=plan.id, start_date=date.today(), end_date=date.today(), label=f"Break {marker}"
        )
        participant = MeetingParticipant(
            organization_id=organization_id,
            lesson_id=lesson.id,
            provider=MeetingProvider.zoom,
            display_name=f"Guest {marker}",
        )
        tutor_contact = ContactPoint(
            organization_id=organization_id,
            user_id=uid,
            channel=NotificationChannel.email,
            address=f"tutor-{marker}@example.com",
        )
        await make_user(
            s,
            organization_id=organization_id,
            role=UserRole.admin,
            name=f"Admin {marker}",
            email=f"admin-{tag}@example.com",
        )
        parent = await make_user(
            s,
            organization_id=organization_id,
            role=UserRole.parent,
            name=f"Parent {marker}",
            email=f"parent-{tag}@example.com",
        )
        await link_parent(s, parent.id, student_id)
        s.add_all([plan_slot, plan_break, participant, tutor_contact])
        await s.flush()
        ids["_contact_tutor"] = tutor_contact.id
        ids.update(
            mock_id=mock.id,
            classified_id=classified.id,
            lesson_id=lesson.id,
            resource_id=resource.id,
            contact_id=contact.id,
            _contact_student=contact.id,
            criterion_id=criterion.id,
            upload_id=upload.id,
            send_id=send.id,
            report_id=report.id,
            break_id=plan_break.id,
            participant_id=participant.id,
            _schedule_slot_id=slot.id,
            _plan_slot_id=plan_slot.id,
        )
        await s.commit()
    out = {"ids": ids, "tutor": tutor, "student": student, "marker": marker}
    for role, email in (
        ("admin", f"admin-{tag}@example.com"),
        ("parent", f"parent-{tag}@example.com"),
    ):
        login = await client.post(
            "/api/v1/auth/login", json={"identifier": email, "password": "password123"}
        )
        assert login.status_code == 200, login.text
        out[role] = {
            "headers": {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
        }
    return out


def _time():
    from datetime import time

    return time(16, 0)


# --- Reading the app's own description of each route --------------------------


def _resolve(spec, node):
    if "$ref" in node:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return _resolve(spec, target)
    return node


def _kinds(spec, node, seen=()):
    """The JSON types a schema admits: {"integer"}, {"array:integer"}, ..."""
    node = _resolve(spec, node)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            return set().union(*[_kinds(spec, o, seen) for o in node[key]])
    if node.get("type") == "array":
        return {"array:" + str(k) for k in _kinds(spec, node.get("items", {}), seen)}
    return {node.get("type")}


def _id_key(name, route_path=""):
    """The seeded-id key a parameter or field name stands for."""
    if name.endswith("_ids"):
        name = name[:-1]
    if name == "slot_id":
        return "_plan_slot_id" if "/plan/" in route_path else "_schedule_slot_id"
    return {
        "plan_slot_id": "_plan_slot_id",
        "schedule_slot_id": "_schedule_slot_id",
        "user_id": "student_id",
    }.get(name, name)


def _sample(spec, node, name, ids, route_path):
    """The smallest valid value for a JSON schema node: required fields only."""
    node = _resolve(spec, node)
    for key in ("anyOf", "oneOf"):
        if key in node:
            options = [o for o in node[key] if _resolve(spec, o).get("type") != "null"]
            return _sample(spec, options[0], name, ids, route_path)
    if "allOf" in node:
        return _sample(spec, node["allOf"][0], name, ids, route_path)
    if "enum" in node:
        return node["enum"][0]
    kind = node.get("type")
    fmt = node.get("format", "")
    if kind == "object" or "properties" in node:
        required = node.get("required", [])
        return {
            k: _sample(spec, v, k, ids, route_path)
            for k, v in node.get("properties", {}).items()
            if k in required
        }
    if kind == "array":
        item = _resolve(spec, node.get("items", {}))
        # One element when the items are objects, so a field nested inside a list
        # has something to be set on; id lists stay empty until a field is aimed.
        n = max(node.get("minItems", 0), 1 if item.get("type") == "object" else 0)
        return [_sample(spec, item, name, ids, route_path) for _ in range(n)]
    if kind == "integer":
        return max(ids.get(_id_key(name, route_path), 1), node.get("minimum", 1))
    if kind == "number":
        return max(1.0, node.get("minimum", 1.0))
    if kind == "boolean":
        return True
    if fmt == "binary" or node.get("contentMediaType"):
        return "FILE"
    if "pattern" in node:
        # "^(file|recording)$": take the first alternative.
        return re.sub(r"[\^$()]", "", node["pattern"]).split("|")[0]
    if fmt == "date":
        return "2030-01-01"
    if fmt == "date-time":
        return "2030-01-01T00:00:00Z"
    if fmt == "time":
        return "16:00:00"
    if fmt == "email":
        return "x@example.com"
    return "x" * max(1, node.get("minLength", 1))


def _operation(spec, route, method):
    return spec["paths"][PREFIX + route.path_format][method.lower()]


def _path_int_params(spec, route, method):
    return [
        p["name"]
        for p in _operation(spec, route, method).get("parameters", [])
        if p["in"] == "path" and "integer" in _kinds(spec, p["schema"])
    ]


def _build(spec, route, method, ids, force=None):
    """A minimal valid request: required fields only, every id from `ids`."""
    op = _operation(spec, route, method)
    path = route.path
    for name in _path_int_params(spec, route, method):
        key = _id_key(name, route.path)
        if key not in ids:
            return None, name
        path = path.replace("{" + name + "}", str(ids[key]))
    req = {"path": path, "query": {}, "json": None, "data": None, "files": None}
    for p in op.get("parameters", []):
        if p["in"] == "query" and p.get("required"):
            req["query"][p["name"]] = _sample(spec, p["schema"], p["name"], ids, route.path)
    body = (op.get("requestBody") or {}).get("content", {})
    if "application/json" in body:
        req["json"] = _sample(spec, body["application/json"]["schema"], "", ids, route.path)
        if (method, route.path) in BODIES:
            req["json"] = {**(req["json"] or {}), **BODIES[method, route.path]}
        schema = _resolve(spec, body["application/json"]["schema"])
        if force and isinstance(req["json"], dict) and force not in req["json"]:
            # An optional parent of the aimed field: build it fully, not as {}.
            req["json"][force] = _sample(spec, schema["properties"][force], force, ids, route.path)
    elif "multipart/form-data" in body:
        schema = _resolve(spec, body["multipart/form-data"]["schema"])
        req["data"], req["files"] = {}, {}
        for k, v in schema.get("properties", {}).items():
            if k not in schema.get("required", []):
                continue
            if _resolve(spec, v).get("type") == "array":
                req["files"][k] = ("a.pdf", PDF, "application/pdf")  # a list of uploads
                continue
            value = _sample(spec, v, k, ids, route.path)
            if value == "FILE":
                req["files"][k] = ("a.pdf", PDF, "application/pdf")
            else:
                req["data"][k] = str(value)
        req["files"] = req["files"] or None
    return req, None


def _id_fields(spec, route, method):
    """Every integer field named `*_id` (or an id list `*_ids`) a request can carry
    in its query, form or JSON body, required or not: (where, tokens, is_list)."""
    op = _operation(spec, route, method)
    found = []

    def want(node):
        ks = _kinds(spec, node)
        return bool(ks & {"integer", "array:integer"}), "array:integer" in ks

    for p in op.get("parameters", []):
        if p["in"] == "query" and re.search(r"_ids?$", p["name"]):
            ok, is_list = want(p["schema"])
            if ok:
                found.append(("query", [p["name"]], is_list))

    def walk(node, tokens, depth, refs):
        node = _resolve(spec, node)
        for key in ("anyOf", "oneOf", "allOf"):
            if key in node:
                for o in node[key]:
                    walk(o, tokens, depth, refs)
                return
        if node.get("type") == "array":
            walk(node.get("items", {}), tokens + ["[]"], depth, refs)
            return
        for k, v in node.get("properties", {}).items():
            ok, is_list = want(v)
            if ok and re.search(r"_ids?$", k):
                found.append((where, tokens + [k], is_list))
            if depth < 3:
                walk(v, tokens + [k], depth + 1, refs)

    content = (op.get("requestBody") or {}).get("content", {})
    for ctype, c in content.items():
        where = "json" if ctype == "application/json" else "form"
        walk(c["schema"], [], 0, ())
    return found


def _aim(req, field, value):
    """Set one id field of a built request to `value`."""
    where, tokens, is_list = field
    value = [value] if is_list else value
    if where == "query":
        req["query"][tokens[0]] = value
    elif where == "form":
        req["data"] = req["data"] or {}
        req["data"][tokens[0]] = [str(v) for v in value] if is_list else str(value)
    else:
        node = req["json"]
        for i, tok in enumerate(tokens[:-1]):
            if tok == "[]":
                assert node, f"no list element to aim {tokens} at"
                node = node[0]
            else:
                if tok not in node:
                    # An optional parent: make it, with one element if a list follows.
                    node[tok] = [{}] if tokens[i + 1] == "[]" else {}
                node = node[tok]
        if tokens[-1] == "[]":
            raise AssertionError(tokens)
        node[tokens[-1]] = value


def _callers(route):
    deps = _dependency_calls(route)
    if require_tutor in deps:
        return ("tutor", "admin")  # an admin counts as a tutor (TUTOR_ROLES)
    if require_student in deps:
        return ("student",)
    return ROLES


def _ids_for(ws, who, route_path, method=""):
    """The workspace's ids as seen by one caller: `/me/contacts/{id}` is the
    caller's own contact, which is not the student's."""
    ids = ws["ids"]
    for name, key in ID_OVERRIDES.get((method, route_path), {}).items():
        ids = {**ids, name: ids[key]}
    if route_path.startswith("/me/") and f"_contact_{who}" in ids:
        return {**ids, "contact_id": ids[f"_contact_{who}"]}
    return ids


# --- The sweep ------------------------------------------------------------------


async def _fingerprint():
    """Every table's rows: a refused request must leave all of them alone."""
    out = {}
    async with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            out[table.name] = sorted(repr(r) for r in (await conn.execute(select(table))).all())
    return out


@pytest.fixture
async def workspaces(client, tutor):
    a = await _seed_org(client, tutor, code="4AAA", tag="a")
    b = await _seed_org(client, await register_other_tutor(client), code="4BBB", tag="b")
    c = await _seed_org(
        client, await register_other_tutor(client, email="third@example.com"), code="4CCC", tag="c"
    )
    return a, b, c


async def test_every_route_refuses_another_workspace(client, workspaces, capsys):
    started = time.perf_counter()
    a, b, c = workspaces
    # Handlers whose files or state the seed does not build answer 500 to their
    # owner in the control pass; that must not abort the sweep.
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )
    spec = app.openapi()
    routes = [r for r in _iter_api_routes(app) if f"{PREFIX}{r.path_format}" in spec["paths"]]
    marker = a["marker"].lower().encode()
    stats = {"path": 0, "field": 0, "list": 0, "calls": 0}
    leaks, unlisted, controls, refusals_seen = [], [], [], set()

    async def call(who_ws, who, req):
        stats["calls"] += 1
        return await client.request(
            req["method"],
            PREFIX + req["path"],
            params=req["query"],
            json=req["json"],
            data=req["data"],
            files=req["files"],
            headers=who_ws[who]["headers"],
        )

    def judge(label, resp, *, allow_empty_200=False, silent_200=False):
        """The one verdict on an attack: 404, or a role refusal, or (a list asked
        to filter by someone else's id) a 200 carrying none of A's data."""
        if marker in resp.content.lower():
            leaks.append(f"{label} -> {resp.status_code}: response contains workspace A's data")
        elif resp.status_code == 403 and resp.json().get("detail") in ROLE_REFUSALS:
            refusals_seen.add(label)  # refused by role before any id is read (SEC-11)
        elif resp.status_code == 200 and (allow_empty_200 or silent_200):
            pass  # a filter that matches nothing of A's: no data crossed over
        elif resp.status_code != 404:
            detail = resp.text[:160] if resp.status_code in (422, 403) else ""
            leaks.append(f"{label} -> {resp.status_code} {detail}")

    # DELETEs last, deepest path first: a handler that leaked would remove A's row
    # and every later call on it would 404 for the wrong reason.
    ops = sorted(
        ((r, m) for r in routes for m in sorted(r.methods - {"HEAD"})),
        key=lambda rm: (
            rm[1] == "DELETE",
            -len(rm[0].path) if rm[1] == "DELETE" else 0,
            rm[0].path,
            rm[1],
        ),
    )
    plan = []  # (route, method, kind, field) for the control pass
    before = await _fingerprint()

    # 1. A path id, every method: B's callers with A's ids.
    # 2. An id in the query, form or body: B's own request with one field aimed at A.
    # 3. A listing (no id in the path): nothing of A's may come back.
    for route, method in ops:
        key = (method, route.path)
        if key in UNRESOLVED:
            continue
        has_path_ids = bool(_path_int_params(spec, route, method))
        public = get_current_user not in _dependency_calls(route)
        for who in _callers(route):
            if has_path_ids:
                req, missing = _build(spec, route, method, _ids_for(a, who, route.path, method))
                if req is None:
                    unlisted.append(f"{key}: no seeded row for {{{missing}}}")
                    break
                req["method"] = method
                stats["path"] += 1
                judge(f"{who} {method} {route.path}", await call(b, who, req))
            elif method == "GET" and not public and "{" not in route.path:
                req, missing = _build(spec, route, method, b["ids"])
                req["method"] = method
                stats["list"] += 1
                judge(
                    f"{who} {method} {route.path} (listing)",
                    await call(b, who, req),
                    allow_empty_200=True,
                )
        if has_path_ids or (method == "GET" and not public and "{" not in route.path):
            plan.append((route, method, "path" if has_path_ids else "list", None))
        for field in _id_fields(spec, route, method):
            name = field[1][-1]
            fkey = _id_key(name, route.path)
            if (method, route.path, ".".join(field[1])) in FIELD_UNRESOLVED:
                continue
            if fkey not in a["ids"]:
                unlisted.append(f"{key} {'.'.join(field[1])}: no seeded row for {fkey}")
                continue
            for who in _callers(route):
                force = field[1][0] if len(field[1]) > 1 and field[0] == "json" else None
                req, missing = _build(
                    spec, route, method, _ids_for(b, who, route.path, method), force
                )
                if req is None:
                    unlisted.append(f"{key}: no seeded row for {{{missing}}}")
                    break
                req["method"] = method
                _aim(req, field, a["ids"][fkey])
                stats["field"] += 1
                # A listing that filters by someone else's id may answer 200 with
                # an empty list instead of 404, so long as none of A's data is in it.
                dotted = ".".join(field[1])
                resp = await call(b, who, req)
                if (method, route.path, dotted) in INDISTINGUISHABLE and resp.status_code != 404:
                    ghost, _ = _build(
                        spec, route, method, _ids_for(b, who, route.path, method), force
                    )
                    ghost["method"] = method
                    _aim(ghost, field, 10**9)
                    gresp = await call(b, who, ghost)
                    if (gresp.status_code, gresp.text) == (resp.status_code, resp.text):
                        continue
                    leaks.append(f"{who} {method} {route.path} [{dotted}]: differs from a ghost id")
                    continue
                judge(
                    f"{who} {method} {route.path} [{dotted}]",
                    resp,
                    allow_empty_200=(method == "GET" and not has_path_ids),
                    silent_200=(method, route.path, dotted) in SILENT_200,
                )
            plan.append((route, method, "field", field))

    after = await _fingerprint()
    changed = {
        t: sorted(set(before[t]) ^ set(after[t]))
        for t in before
        # Insert-only for the listed tables: nothing that existed may change or go.
        if (not set(before[t]) <= set(after[t]) if t in WRITTEN_BY_READS else before[t] != after[t])
    }

    # Control pass: the same calls, with ids that belong to the caller's own
    # workspace, must succeed. Otherwise a 404 above might be about something
    # else (a missing file, a bad body) and prove nothing about tenancy.
    for route, method, kind, field in plan:
        # A DELETE can only be shown to succeed once: the next caller finds the row gone.
        for who in _callers(route)[: 1 if method == "DELETE" else None]:
            ws = c if kind == "path" else b
            force = field[1][0] if field and len(field[1]) > 1 and field[0] == "json" else None
            req, _ = _build(spec, route, method, _ids_for(ws, who, route.path, method), force)
            if req is None:
                continue
            req["method"] = method
            if kind == "field":
                fkey = _id_key(field[1][-1], route.path)
                _aim(req, field, ws["ids"][fkey])
            resp = await call(ws, who, req)
            label = (who, method, route.path, ".".join(field[1]) if field else "")
            if resp.status_code == 403 and resp.json().get("detail") in ROLE_REFUSALS:
                continue  # this caller is not admitted to the route at all
            if not 200 <= resp.status_code < 300:
                controls.append((label, resp.status_code))
    # The marker check above is only evidence if the marker can be seen at all.
    a_visible = 0
    for route, method in ops:
        if (
            method == "GET"
            and not _path_int_params(spec, route, method)
            and get_current_user in _dependency_calls(route)
        ):
            req, _ = _build(spec, route, method, a["ids"])
            req["method"] = method
            resp = await call(a, "tutor", req)
            a_visible += marker in resp.content.lower()

    unexplained = sorted(k for k, _ in controls if k not in CONTROL_EXCEPTIONS)
    stale_exceptions = sorted(set(CONTROL_EXCEPTIONS) - {k for k, _ in controls})
    seen_ops = {(m, r.path) for r, m in ops}
    stale = [k for k in UNRESOLVED if k not in seen_ops]
    stale += [k for k in FIELD_UNRESOLVED if k[:2] not in seen_ops]

    with capsys.disabled():
        print(
            f"\ntenancy sweep: {sum(k == 'path' for _, _, k, _ in plan)} path-id operations, "
            f"{sum(k == 'field' for _, _, k, _ in plan)} aimed id fields, "
            f"{sum(k == 'list' for _, _, k, _ in plan)} listings; {stats['path']} path-id calls, {stats['field']} aimed-field calls, "
            f"{stats['list']} listing calls, {stats['calls']} requests in all, "
            f"{len(refusals_seen)} role refusals, A's marker visible to its own tutor in "
            f"{a_visible} listings, {time.perf_counter() - started:.1f}s"
        )
    assert not unlisted, "neither swept nor listed:\n" + "\n".join(unlisted)
    assert not leaks, "another workspace was not refused:\n" + "\n".join(leaks)
    assert not changed, f"refused requests changed rows: {changed}"
    assert a_visible >= 10, f"A's marker shows in only {a_visible} listings; the check is hollow"
    assert not unexplained, (
        "the owner's own call fails, so a refusal proves nothing:\n"
        + "\n".join(f"{k} -> {code}" for k, code in controls if k in unexplained)
    )
    assert not stale_exceptions, (
        f"no longer failing, remove from CONTROL_EXCEPTIONS: {stale_exceptions}"
    )
    assert not stale, f"listed but no longer a route: {stale}"
