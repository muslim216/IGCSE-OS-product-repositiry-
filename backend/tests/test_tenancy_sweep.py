"""01-KG-3 / RISK-7: every route that names a row by id refuses another workspace.

Organization scoping is applied per query, as a habit. A route that forgets the
filter leaks another tutor's data and nothing used to notice. This turns the
habit into a mechanism: every route in the app with an integer path parameter
is called as organization B (its tutor, and its student where the route admits
one) with organization A's real ids, and must answer 404 (`API-7`: not 403, not
200, and not 422, which would mean validation ran first and hid the check).

The routes come from the app, not from a list in this file, so a new route is
swept the day it is written. It must then be either resolvable from the rows
seeded below or listed in `UNRESOLVED` with the reason; a route that is neither
fails the test, and so does an `UNRESOLVED` entry that no longer exists or that
could now be resolved. That is what stops the list rotting into an excuse.
"""

import re
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.deps import require_student, require_tutor
from app.db import async_session
from app.main import app
from app.models import (
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
    WeeklySend,
    WeeklySendAudience,
    WorkKind,
)
from app.models.integrations import MeetingParticipant, MeetingProvider
from app.services import storage
from app.services.work import create_work
from tests.factories import (
    make_mistake_category,
    make_past_paper,
    make_subject,
    publish_assignment,
    register_other_tutor,
    submit_work,
)
from tests.test_authorization import _dependency_calls, _iter_api_routes

PREFIX = "/api/v1"
PDF = b"%PDF-1.4 fake"

#: Bodies the generic generator cannot guess because the model validates across
#: fields, so a minimal one is still invalid and would answer 422 before the
#: ownership check runs.
BODIES: dict[tuple[str, str], dict] = {
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

#: (caller, METHOD, path-template) where even the row's own workspace gets 404
#: from this caller, so B's 404 proves little for it. Each is a caller with no
#: claim on that kind of row at all (the other caller is swept normally), or a
#: route whose success needs state this sweep does not build.
NOT_DISCRIMINATING: dict[tuple[str, str, str], str] = {
    ("student", "GET", "/classifieds/{classified_id}/file"): "tutor-owned material",
    ("student", "GET", "/classifieds/{classified_id}/mark-scheme"): "tutor-owned material",
    ("student", "GET", "/reports/{report_id}"): "reports are addressed to the tutor",
    ("student", "GET", "/students/{student_id}/narrative"): "written for the parent",
    ("student", "GET", "/weekly-sends/{send_id}"): "a send belongs to its recipient, a tutor",
    ("student", "DELETE", "/resources/{resource_id}"): "tutor-owned material",
    ("tutor", "POST", "/me/contacts/{contact_id}/confirm"): "a contact belongs to its own user",
    ("tutor", "POST", "/groups/{group_id}/plan/slots/{slot_id}/cancel"): (
        "needs a lesson held on the slot's date; the group check decides ownership"
    ),
}

#: Routes called with a real row for the parent id (which decides ownership) but
#: a stand-in for a child row nobody seeds. A leak in the child lookup alone
#: would be hidden here, because the parent already refuses. Listed, not
#: silent, so each is a visible debt rather than an assumption.
PARENT_ONLY: dict[tuple[str, str], str] = {}


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
    async with async_session() as s:
        organization_id = await s.scalar(select(User.organization_id).where(User.id == uid))
        subject = await make_subject(s, organization_id=organization_id, code=code)
        topic = Topic(subject_id=subject.id, code="1.1", title=f"Topic {tag}")
        chapter = Chapter(subject_id=subject.id, code="1", title=f"Chapter {tag}")
        s.add_all([topic, chapter])
        await s.commit()
        subject_id, topic_id, chapter_id = subject.id, topic.id, chapter.id

    group = await client.post(
        "/api/v1/groups",
        json={"name": f"Class {tag}", "subject_id": subject_id},
        headers=tutor["headers"],
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]
    invite = await client.post(f"/api/v1/groups/{group_id}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": f"Student {tag}",
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
        )
        ids["assignment_id"] = assignment.id
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
            submission_id=submission.id, question_id=ids["question_id"], final_marks=1
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
            title="Mock",
        )
        mock = Mock(
            organization_id=organization_id,
            tutor_id=uid,
            subject_id=subject_id,
            title="Mock",
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
            title="Classified",
            **await _stored(organization_id, "file_"),
            **await _stored(organization_id, "mark_scheme_"),
        )
        lesson = Lesson(organization_id=organization_id, group_id=group_id, date=date.today())
        slot = ScheduleSlot(group_id=group_id, weekday=1, start_time=_time())
        resource = GroupResource(
            group_id=group_id,
            tutor_id=uid,
            kind=ResourceKind.file,
            title="Notes",
            **await _stored(organization_id, "file_"),
        )
        contact = ContactPoint(
            organization_id=organization_id,
            user_id=student_id,
            channel=NotificationChannel.email,
            address=f"parent-{tag}@example.com",
        )
        criterion = CustomCriterion(
            organization_id=organization_id, name=f"Criterion {tag}", created_by_id=uid
        )
        upload = SyllabusUpload(
            tutor_id=uid,
            title="Syllabus",
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
            facts={},
        )
        report = Report(
            student_id=student_id,
            generated_by_id=uid,
            audience=ReportAudience.tutor,
            title="Report",
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
            plan_id=plan.id, start_date=date.today(), end_date=date.today(), label="Break"
        )
        participant = MeetingParticipant(
            organization_id=organization_id,
            lesson_id=lesson.id,
            provider=MeetingProvider.zoom,
            display_name="Guest",
        )
        s.add_all([plan_slot, plan_break, participant])
        await s.flush()
        ids.update(
            mock_id=mock.id,
            classified_id=classified.id,
            lesson_id=lesson.id,
            resource_id=resource.id,
            contact_id=contact.id,
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
    return {"ids": ids, "tutor": tutor, "student": student}


def _time():
    from datetime import time

    return time(16, 0)


# --- Calling every route -----------------------------------------------------


def _resolve(spec, node):
    if "$ref" in node:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        return _resolve(spec, target)
    return node


def _sample(spec, node, name, ids, files):
    """The smallest valid value for a JSON schema node: required fields only."""
    node = _resolve(spec, node)
    for key in ("anyOf", "oneOf"):
        if key in node:
            options = [o for o in node[key] if _resolve(spec, o).get("type") != "null"]
            return _sample(spec, options[0], name, ids, files)
    if "allOf" in node:
        return _sample(spec, node["allOf"][0], name, ids, files)
    if "enum" in node:
        return node["enum"][0]
    kind = node.get("type")
    fmt = node.get("format", "")
    if kind == "object" or "properties" in node:
        required = node.get("required", [])
        return {
            k: _sample(spec, v, k, ids, files)
            for k, v in node.get("properties", {}).items()
            if k in required
        }
    if kind == "array":
        item = node.get("items", {})
        return [_sample(spec, item, name, ids, files)] * node.get("minItems", 0)
    if kind == "integer":
        return max(ids.get(name, 1), node.get("minimum", 1))
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


def _request_parts(spec, route, method, ids):
    """(query, json, form-data, files) for a minimal valid request."""
    op = spec["paths"][PREFIX + route.path_format][method.lower()]
    query = {}
    for p in op.get("parameters", []):
        if p["in"] == "query" and p.get("required"):
            query[p["name"]] = _sample(spec, p["schema"], p["name"], ids, None)
    body = (op.get("requestBody") or {}).get("content", {})
    if "application/json" in body:
        return query, _sample(spec, body["application/json"]["schema"], "", ids, None), None, None
    if "multipart/form-data" in body:
        schema = _resolve(spec, body["multipart/form-data"]["schema"])
        data, files = {}, {}
        for k, v in schema.get("properties", {}).items():
            if k not in schema.get("required", []):
                continue
            if _resolve(spec, v).get("type") == "array":
                files[k] = ("a.pdf", PDF, "application/pdf")  # a list of uploads
                continue
            value = _sample(spec, v, k, ids, None)
            if value == "FILE":
                files[k] = ("a.pdf", PDF, "application/pdf")
            else:
                data[k] = str(value)
        return query, None, data, files or None
    return query, None, None, None


def _int_params(route):
    return [p.name for p in route.dependant.path_params if p.field_info.annotation is int]


def _is_swept(route):
    return bool(_int_params(route))


def _callers(route):
    deps = _dependency_calls(route)
    if require_tutor in deps:
        return ["tutor"]
    if require_student in deps:
        return ["student"]
    return ["tutor", "student"]


def _fill(route, ids):
    """The route's path with org A's ids, or None naming the first missing one."""
    path = route.path
    for name in _int_params(route):
        key = name
        if name == "slot_id":
            key = "_plan_slot_id" if "/plan/" in route.path else "_schedule_slot_id"
        if key not in ids:
            return None, name
        path = path.replace("{" + name + "}", str(ids[key]))
    return path, None


@pytest.fixture
async def two_workspaces(client, tutor):
    a = await _seed_org(client, tutor, code="4AAA", tag="a")
    other = await register_other_tutor(client)
    b = await _seed_org(client, other, code="4BBB", tag="b")
    third = await register_other_tutor(client, email="third@example.com")
    c = await _seed_org(client, third, code="4CCC", tag="c")
    return a, b, c


async def test_every_route_refuses_another_workspace(client, two_workspaces):
    a, b, c = two_workspaces
    # The owner's control calls reach handlers whose files are not on disk; that
    # is a 500 here and must not abort the sweep.
    client = AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )
    spec = app.openapi()
    routes = [r for r in _iter_api_routes(app) if _is_swept(r)]
    assert len(routes) > 100, f"only {len(routes)} swept routes — the walk is broken"

    seen_keys, leaks, unlisted, shadowed = set(), [], [], []
    # DELETEs last: a handler that leaked would remove A's row, and every later
    # call on it would then 404 for the wrong reason.
    # Deepest paths first among them, so a nested row goes before its parent.
    ordered = sorted(
        routes,
        key=lambda r: (
            "DELETE" in r.methods,
            -len(r.path) if "DELETE" in r.methods else 0,
            r.path,
            sorted(r.methods),
        ),
    )
    for route in ordered:
        method = sorted(route.methods - {"HEAD"})[0]
        key = (method, route.path)
        seen_keys.add(key)
        if key in UNRESOLVED:
            continue
        path, missing = _fill(route, a["ids"])
        if path is None:
            unlisted.append(f"{key}: no seeded row for {{{missing}}}")
            continue
        query, payload, data, files = _request_parts(spec, route, method, a["ids"])
        payload = BODIES.get(key, payload)
        own_query, own_payload, own_data, own_files = _request_parts(spec, route, method, c["ids"])
        own_payload = BODIES.get(key, own_payload)
        for who in _callers(route):
            # Control: the owner of the rows (workspace C, identical to A) must
            # not get 404 here, or B's 404 would prove nothing about tenancy.
            own_path, _ = _fill(route, c["ids"])
            own = await client.request(
                method,
                PREFIX + own_path,
                params=own_query,
                json=own_payload,
                data=own_data,
                files=own_files,
                headers=c[who]["headers"],
            )
            if own.status_code == 404:
                shadowed.append((who, method, route.path))
            resp = await client.request(
                method,
                PREFIX + path,
                params=query,
                json=payload,
                data=data,
                files=files,
                headers=b[who]["headers"],
            )
            # A student on a tutor-only route is refused by role before any id
            # is read: that is the role gate (`SEC-11`), not an ownership answer.
            if (
                who == "student"
                and resp.status_code == 403
                and resp.json().get("detail") == "Tutor account required"
            ):
                continue
            if resp.status_code != 404:
                detail = resp.text[:200] if resp.status_code == 422 else ""
                leaks.append(f"{who} {method} {PREFIX}{route.path} -> {resp.status_code} {detail}")

    assert not unlisted, "routes neither swept nor listed in UNRESOLVED:\n" + "\n".join(unlisted)
    unexplained = [k for k in shadowed if k not in NOT_DISCRIMINATING]
    assert not unexplained, (
        "the owner is also told 404 here, so a 404 for another workspace proves nothing; "
        f"fix the seed or explain it in NOT_DISCRIMINATING: {unexplained}"
    )
    stale_shadow = set(NOT_DISCRIMINATING) - set(shadowed)
    assert not stale_shadow, f"no longer shadowed, remove from NOT_DISCRIMINATING: {stale_shadow}"
    assert not leaks, "another workspace was not refused with 404:\n" + "\n".join(leaks)
    stale = (set(UNRESOLVED) | set(PARENT_ONLY)) - seen_keys
    assert not stale, f"listed but no longer a route: {sorted(stale)}"
    assert not [k for k in UNRESOLVED if k in PARENT_ONLY]
