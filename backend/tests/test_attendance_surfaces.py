"""Attendance read surfaces for student, parent and tutor (task 7.2, AV-44)."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.db import async_session
from app.models import (
    AttendanceSource,
    AttendanceState,
    Group,
    GroupMember,
    Organization,
    User,
)
from tests.test_attendance import _lesson, _other_tutor, _put
from tests.test_custom_criteria import _parent_of, _second_student

API = "/api/v1"


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


async def _mark(client, tutor, group, sid, offset, state):
    lesson = await _lesson(client, tutor, group, date=_day(offset))
    if state is not None:
        resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": state}])
        assert resp.status_code == 200, resp.text
    return lesson


@pytest.fixture
async def history(client, tutor, group, student):
    """Two present, one absent, one not taken, plus a lesson in the future."""
    sid = student["user"]["id"]
    # Joined long before the lessons: an enrolment row is created "now" in tests.
    async with async_session() as s:
        await s.execute(
            update(GroupMember)
            .where(GroupMember.student_id == sid)
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=60))
        )
        await s.commit()
    await _mark(client, tutor, group, sid, 10, "present")
    await _mark(client, tutor, group, sid, 8, "present")
    await _mark(client, tutor, group, sid, 6, "absent")
    await _mark(client, tutor, group, sid, 4, None)
    await _mark(client, tutor, group, sid, -5, "present")  # future: not counted
    return sid


async def test_student_reads_own_counts_and_excludes_not_taken_from_rate(client, student, history):
    resp = await client.get(f"{API}/me/attendance", headers=student["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["lessons"], body["present"], body["absent"], body["not_taken"]) == (4, 2, 1, 1)
    assert body["rate"] == pytest.approx(2 / 3)
    assert len(body["classes"]) == 1
    cls = body["classes"][0]
    assert cls["group_name"] == "Chem Y10"
    assert cls["rate"] == pytest.approx(2 / 3)
    assert cls["not_taken"] == 1
    assert [r["state"] for r in cls["recent"]] == [None, "absent", "present", "present"]


async def test_no_marks_gives_null_rate_not_zero(client, tutor, group, student):
    await _lesson(client, tutor, group, date=_day(3))
    body = (await client.get(f"{API}/me/attendance", headers=student["headers"])).json()
    assert body["rate"] is None
    assert body["present"] == 0 and body["absent"] == 0
    # Joined today, so a lesson three days ago was held before they joined.
    assert body["lessons"] == 0


async def test_lesson_before_joining_is_not_counted_as_not_taken(client, tutor, group, student):
    async with async_session() as s:
        await s.execute(
            update(GroupMember)
            .where(GroupMember.student_id == student["user"]["id"])
            .values(created_at=datetime.now(timezone.utc) - timedelta(days=2))
        )
        await s.commit()
    await _lesson(client, tutor, group, date=_day(3))
    await _lesson(client, tutor, group, date=_day(1))
    body = (await client.get(f"{API}/me/attendance", headers=student["headers"])).json()
    assert (body["lessons"], body["not_taken"]) == (1, 1)


async def test_a_marked_lesson_counts_even_if_before_joining(client, tutor, group, student):
    await _mark(client, tutor, group, student["user"]["id"], 3, "absent")
    body = (await client.get(f"{API}/me/attendance", headers=student["headers"])).json()
    assert (body["lessons"], body["absent"]) == (1, 1)


async def test_tutor_reads_a_students_attendance(client, tutor, history):
    resp = await client.get(f"{API}/students/{history}/attendance", headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json()["present"] == 2


async def test_linked_parent_reads_child_attendance(client, tutor, student, history):
    parent = await _parent_of(client, tutor["headers"], history, "p1@example.com")
    resp = await client.get(f"{API}/students/{history}/attendance", headers=parent)
    assert resp.status_code == 200
    assert resp.json()["absent"] == 1


async def test_unlinked_parent_gets_404(client, tutor, group, student, history):
    other = await _second_student(client, tutor["headers"], group["id"])
    parent = await _parent_of(client, tutor["headers"], other["id"], "p2@example.com")
    resp = await client.get(f"{API}/students/{history}/attendance", headers=parent)
    assert resp.status_code == 404


async def test_student_cannot_read_another_students_attendance(client, tutor, group, history):
    other = await _second_student(client, tutor["headers"], group["id"])
    resp = await client.get(f"{API}/students/{history}/attendance", headers=other["headers"])
    assert resp.status_code == 404


async def test_other_organizations_tutor_gets_404(client, history):
    headers, _ = await _other_tutor(client, "rival@example.com")
    resp = await client.get(f"{API}/students/{history}/attendance", headers=headers)
    assert resp.status_code == 404


async def test_tutor_cannot_use_the_student_endpoint_and_anon_is_refused(client, tutor):
    assert (await client.get(f"{API}/me/attendance", headers=tutor["headers"])).status_code == 403
    assert (await client.get(f"{API}/me/attendance")).status_code == 401
    assert (await client.get(f"{API}/students/1/attendance")).status_code == 401


async def test_unknown_student_is_404(client, tutor):
    resp = await client.get(f"{API}/students/99999/attendance", headers=tutor["headers"])
    assert resp.status_code == 404


async def test_service_never_reads_another_organizations_lessons(client, history):
    from app.models import User
    from app.services.attendance import student_attendance

    _, rival = await _other_tutor(client, "rival2@example.com")
    async with async_session() as s:
        rival_org = (await s.get(User, rival["id"])).organization_id
        result = await student_attendance(s, student_id=history, organization_id=rival_org)
    assert result.classes == []
    assert result.rate is None


async def _today_lesson(client, tutor, group, **extra):
    return await _lesson(client, tutor, group, date=date.today().isoformat(), **extra)


async def _attendance_at(student_id, group_org, now):
    from app.services.attendance import student_attendance

    async with async_session() as s:
        return await student_attendance(
            s, student_id=student_id, organization_id=group_org, now=now
        )


async def test_today_counts_only_once_the_lesson_has_ended(client, tutor, group, student):
    sid = student["user"]["id"]
    async with async_session() as s:
        await s.execute(
            update(GroupMember)
            .where(GroupMember.student_id == sid)
            .values(created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        )
        org_id = (await s.get(User, tutor["user"]["id"])).organization_id
        await s.commit()
    day = "2026-03-10"
    for extra in (
        {},  # no start time: unknown end, counts from tomorrow
        {"start_time": "13:00:00", "duration_min": 60},  # ends 14:00, after "now"
        {"start_time": "09:00:00", "duration_min": 60},  # ended 10:00
    ):
        await _lesson(client, tutor, group, date=day, **extra)

    noon = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    result = await _attendance_at(sid, org_id, noon)
    assert (result.lessons, result.not_taken) == (1, 1)

    # The next morning every one of them is over, or is a past day.
    tomorrow = datetime(2026, 3, 11, 8, 0, tzinfo=timezone.utc)
    result = await _attendance_at(sid, org_id, tomorrow)
    assert (result.lessons, result.not_taken) == (3, 3)


async def _second_tutor_class(group, student_id, mark_state):
    """A same-organization tutor T2 teaching class B, which the student also sits in."""
    from app.models import Lesson, LessonAttendance, User, UserRole
    from app.models.base import utcnow
    from app.security import create_access_token

    async with async_session() as s:
        a = await s.get(Group, group["id"])
        t2 = User(
            email="t2@example.com",
            password_hash="x",
            role=UserRole.tutor,
            name="T2",
            organization_id=a.organization_id,
        )
        s.add(t2)
        await s.flush()
        b = Group(
            organization_id=a.organization_id,
            tutor_id=t2.id,
            subject_id=a.subject_id,
            name="Class B",
        )
        s.add(b)
        await s.flush()
        s.add(GroupMember(group_id=b.id, student_id=student_id))
        # Yesterday in UTC, not the machine's local `date.today()`: east of UTC that is
        # already tomorrow for a UTC organization, and a future lesson is not counted.
        held = datetime.now(timezone.utc).date() - timedelta(days=1)
        lesson = Lesson(organization_id=a.organization_id, group_id=b.id, date=held)
        s.add(lesson)
        await s.flush()
        s.add(
            LessonAttendance(
                organization_id=a.organization_id,
                lesson_id=lesson.id,
                student_id=student_id,
                state=mark_state,
                source=AttendanceSource.tutor,
                recorded_at=utcnow(),
            )
        )
        await s.commit()
        return {"Authorization": f"Bearer {create_access_token(t2.id, 0)}"}


async def test_a_tutor_sees_only_the_classes_they_teach(client, tutor, group, student, history):
    t2 = await _second_tutor_class(group, history, AttendanceState.absent)
    url = f"{API}/students/{history}/attendance"

    t1_body = (await client.get(url, headers=tutor["headers"])).json()
    assert [c["group_name"] for c in t1_body["classes"]] == ["Chem Y10"]
    assert t1_body["absent"] == 1  # class A's own absence only, not B's

    t2_body = (await client.get(url, headers=t2)).json()
    assert [c["group_name"] for c in t2_body["classes"]] == ["Class B"]
    assert (t2_body["lessons"], t2_body["absent"]) == (1, 1)

    # The student still sees both classes.
    own = (await client.get(f"{API}/me/attendance", headers=student["headers"])).json()
    assert len(own["classes"]) == 2


async def test_join_cutoff_uses_the_organizations_timezone(client, tutor, group, student):
    sid = student["user"]["id"]
    boundary = date.today() - timedelta(days=5)
    # 20:00 UTC on `boundary` is already the next morning in Auckland (UTC+12/13).
    joined_utc = datetime(boundary.year, boundary.month, boundary.day, 20, 0)
    async with async_session() as s:
        org_id = (await s.get(User, tutor["user"]["id"])).organization_id
        (await s.get(Organization, org_id)).timezone = "Pacific/Auckland"
        await s.execute(
            update(GroupMember).where(GroupMember.student_id == sid).values(created_at=joined_utc)
        )
        await s.commit()
    await _lesson(client, tutor, group, date=boundary.isoformat())
    await _lesson(client, tutor, group, date=(boundary + timedelta(days=1)).isoformat())
    body = (await client.get(f"{API}/me/attendance", headers=student["headers"])).json()
    # Joined on boundary+1 locally, so the boundary-day lesson predates them.
    assert body["lessons"] == 1
    assert body["classes"][0]["recent"][0]["date"] == (boundary + timedelta(days=1)).isoformat()


async def test_a_lesson_is_read_on_its_classs_clock_not_the_organizations(
    client, tutor, group, student
):
    """Org Dubai (UTC+4), tutor London (UTC+1 in July): an 18:00-19:00 lesson is the
    tutor's wall clock. At 17:30 UTC it is 18:30 in London (still running) but 21:30
    in Dubai, so reading it on the org clock would wrongly count it as not taken."""
    sid = student["user"]["id"]
    async with async_session() as s:
        tutor_row = await s.get(User, tutor["user"]["id"])
        tutor_row.time_zone = "Europe/London"
        org = await s.get(Organization, tutor_row.organization_id)
        org.timezone = "Asia/Dubai"
        org_id = org.id
        await s.execute(
            update(GroupMember)
            .where(GroupMember.student_id == sid)
            .values(created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        )
        await s.commit()
    await _lesson(client, tutor, group, date="2026-07-14", start_time="18:00:00", duration_min=60)

    running = await _attendance_at(sid, org_id, datetime(2026, 7, 14, 17, 30, tzinfo=timezone.utc))
    assert running.lessons == 0
    over = await _attendance_at(sid, org_id, datetime(2026, 7, 14, 18, 30, tzinfo=timezone.utc))
    assert (over.lessons, over.not_taken) == (1, 1)
