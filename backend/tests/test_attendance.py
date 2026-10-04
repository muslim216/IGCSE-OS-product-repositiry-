"""Lesson attendance, lesson mode and start time (task 7.1, AV-44, AV-109)."""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    AttendanceSource,
    AttendanceState,
    Evidence,
    Job,
    Lesson,
    LessonAttendance,
    User,
)
from app.models.base import utcnow
from app.services import attendance as svc
from tests.test_plan_lessons import make_subject  # noqa: F401 - helper


async def _lesson(client, tutor, group, **extra) -> dict:
    resp = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": "2026-07-14", **extra},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _url(lesson) -> str:
    return f"/api/v1/lessons/{lesson['id']}/attendance"


async def _put(client, headers, lesson, entries):
    return await client.put(_url(lesson), json={"entries": entries}, headers=headers)


async def _other_tutor(client, email):
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": email, "password": "password123"},
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}, reg.json()["user"]


async def test_unmarked_students_show_none_not_absent(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    resp = await client.get(_url(lesson), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == [
        {
            "student_id": student["user"]["id"],
            "name": "Sara",
            "state": None,
            "source": None,
            "recorded_at": None,
        }
    ]


async def test_mark_overwrite_and_clear(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "present"}])
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert (row["state"], row["source"]) == ("present", "tutor")
    assert row["recorded_at"] is not None

    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "absent"}])
    assert resp.json()[0]["state"] == "absent"
    async with async_session() as s:
        assert len((await s.scalars(select(LessonAttendance))).all()) == 1
        assert (await s.scalar(select(LessonAttendance.recorded_by_id))) == tutor["user"]["id"]

    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": None}])
    assert resp.json()[0]["state"] is None
    async with async_session() as s:
        assert (await s.scalars(select(LessonAttendance))).all() == []


async def test_a_student_who_left_keeps_their_mark_in_the_register(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "present"}])
    from app.models import GroupMember

    async with async_session() as s:
        for m in await s.scalars(select(GroupMember)):
            await s.delete(m)
        await s.commit()
    rows = (await client.get(_url(lesson), headers=tutor["headers"])).json()
    assert [(r["student_id"], r["state"]) for r in rows] == [(sid, "present")]


async def test_mode_and_start_time_round_trip(client, tutor, group):
    default = await _lesson(client, tutor, group)
    assert (default["mode"], default["start_time"], default["origin"]) == (
        "in_person",
        None,
        "tutor",
    )
    lesson = await _lesson(client, tutor, group, mode="online", start_time="16:30:00")
    assert (lesson["mode"], lesson["start_time"]) == ("online", "16:30:00")
    patched = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"mode": "in_person", "start_time": "09:00:00"},
        headers=tutor["headers"],
    )
    assert (patched.json()["mode"], patched.json()["start_time"]) == ("in_person", "09:00:00")
    got = await client.get(f"/api/v1/lessons/{lesson['id']}", headers=tutor["headers"])
    assert got.json()["start_time"] == "09:00:00"
    bad = await client.post(
        "/api/v1/lessons",
        json={"group_id": group["id"], "date": "2026-07-14", "mode": "hybrid"},
        headers=tutor["headers"],
    )
    assert bad.status_code == 422


async def test_deleting_a_lesson_removes_its_attendance(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    await _put(
        client,
        tutor["headers"],
        lesson,
        [{"student_id": student["user"]["id"], "state": "present"}],
    )
    assert (
        await client.delete(f"/api/v1/lessons/{lesson['id']}", headers=tutor["headers"])
    ).status_code == 204
    async with async_session() as s:
        assert (await s.scalars(select(LessonAttendance))).all() == []


async def test_attendance_is_not_readiness_evidence_and_queues_nothing(
    client, tutor, group, student
):
    lesson = await _lesson(client, tutor, group)
    async with async_session() as s:
        jobs_before = len((await s.scalars(select(Job))).all())
    await _put(
        client, tutor["headers"], lesson, [{"student_id": student["user"]["id"], "state": "absent"}]
    )
    async with async_session() as s:
        assert (await s.scalars(select(Evidence))).all() == []
        assert len((await s.scalars(select(Job))).all()) == jobs_before


# --- negative cases (QA-12) -------------------------------------------------


async def test_another_organizations_lesson_is_404(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    headers, _ = await _other_tutor(client, "other-att@example.com")
    assert (await client.get(_url(lesson), headers=headers)).status_code == 404
    resp = await _put(
        client, headers, lesson, [{"student_id": student["user"]["id"], "state": "present"}]
    )
    assert resp.status_code == 404
    async with async_session() as s:
        assert (await s.scalars(select(LessonAttendance))).all() == []


async def test_another_tutors_group_in_the_same_org_is_404(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    async with async_session() as s:
        org_id = (await s.get(User, tutor["user"]["id"])).organization_id
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Colleague", "email": "colleague-att@example.com", "password": "password123"},
    )
    async with async_session() as s:
        colleague = await s.get(User, reg.json()["user"]["id"])
        colleague.organization_id = org_id
        await s.commit()
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    assert (await client.get(_url(lesson), headers=headers)).status_code == 404
    resp = await _put(
        client, headers, lesson, [{"student_id": student["user"]["id"], "state": "present"}]
    )
    assert resp.status_code == 404


async def test_a_student_outside_the_group_is_404_and_nothing_is_written(
    client, tutor, group, student
):
    lesson = await _lesson(client, tutor, group)
    _, stranger = await _other_tutor(client, "stranger-att@example.com")
    resp = await _put(
        client,
        tutor["headers"],
        lesson,
        [
            {"student_id": student["user"]["id"], "state": "present"},
            {"student_id": stranger["id"], "state": "present"},
        ],
    )
    assert resp.status_code == 404
    async with async_session() as s:
        assert (await s.scalars(select(LessonAttendance))).all() == []


async def test_a_student_cannot_read_or_write_the_register(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    assert (await client.get(_url(lesson), headers=student["headers"])).status_code == 403
    resp = await _put(
        client,
        student["headers"],
        lesson,
        [{"student_id": student["user"]["id"], "state": "present"}],
    )
    assert resp.status_code == 403


async def test_a_parent_cannot_read_or_write_the_register(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    code = await client.post(
        f"/api/v1/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
    )
    reg = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code.json()["code"],
            "name": "Parent",
            "email": "parent-att@example.com",
            "password": "password123",
        },
    )
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    assert (await client.get(_url(lesson), headers=headers)).status_code == 403
    assert (await _put(client, headers, lesson, [])).status_code == 403


async def test_no_token_is_401(client, tutor, group):
    lesson = await _lesson(client, tutor, group)
    assert (await client.get(_url(lesson))).status_code == 401


async def test_the_entries_list_is_bounded(client, tutor, group):
    lesson = await _lesson(client, tutor, group)
    entries = [{"student_id": 1, "state": "present"}] * 501
    assert (await _put(client, tutor["headers"], lesson, entries)).status_code == 422


async def test_state_is_present_or_absent_only(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    resp = await _put(
        client, tutor["headers"], lesson, [{"student_id": student["user"]["id"], "state": "late"}]
    )
    assert resp.status_code == 422


# --- the integration rule (service level; 7.3 calls it) ---------------------


async def _service_write(lesson_id, entries, **kw):
    async with async_session() as s:
        lesson = await s.get(Lesson, lesson_id)
        await svc.set_attendance(s, lesson, entries, **kw)


async def test_an_integration_write_never_overwrites_a_tutor_mark(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "absent"}])
    await _service_write(
        lesson["id"],
        [svc.AttendanceEntry(sid, AttendanceState.present)],
        recorded_by=None,
        source=AttendanceSource.zoom,
    )
    async with async_session() as s:
        row = await s.scalar(select(LessonAttendance))
        assert (row.state, row.source) == (AttendanceState.absent, AttendanceSource.tutor)
        assert row.recorded_by_id == tutor["user"]["id"]


async def test_an_integration_write_on_an_empty_row_has_no_recorder(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    async with async_session() as s:
        actor = await s.get(User, tutor["user"]["id"])
        await svc.set_attendance(
            s,
            await s.get(Lesson, lesson["id"]),
            [svc.AttendanceEntry(sid, AttendanceState.present)],
            recorded_by=actor,
            source=AttendanceSource.google_meet,
        )
    async with async_session() as s:
        row = await s.scalar(select(LessonAttendance))
        assert row.source == AttendanceSource.google_meet
        assert row.recorded_by_id is None


async def test_a_tutor_write_overwrites_an_integration_mark(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    await _service_write(
        lesson["id"],
        [svc.AttendanceEntry(sid, AttendanceState.absent)],
        recorded_by=None,
        source=AttendanceSource.zoom,
    )
    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "present"}])
    row = resp.json()[0]
    assert (row["state"], row["source"]) == ("present", "tutor")


# --- review fixes -----------------------------------------------------------


async def test_duplicate_student_ids_in_one_put_collapse_last_wins(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    resp = await _put(
        client,
        tutor["headers"],
        lesson,
        [{"student_id": sid, "state": "present"}, {"student_id": sid, "state": "absent"}],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["state"] == "absent"
    resp = await _put(
        client,
        tutor["headers"],
        lesson,
        [{"student_id": sid, "state": "present"}, {"student_id": sid, "state": None}],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["state"] is None


async def test_a_lost_race_on_the_unique_row_is_409(client, tutor, group, student, monkeypatch):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    real = svc._enrolled_ids

    async def _then_a_rival_writes(session, les):
        ids = await real(session, les)
        # A competing request commits the same (lesson, student) after our read.
        async with async_session() as other:
            other.add(
                LessonAttendance(
                    organization_id=les.organization_id,
                    lesson_id=les.id,
                    student_id=sid,
                    state=AttendanceState.present,
                    source=AttendanceSource.tutor,
                    recorded_by_id=None,
                    recorded_at=utcnow(),
                )
            )
            await other.commit()
        return ids

    monkeypatch.setattr(svc, "_enrolled_ids", _then_a_rival_writes)
    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "absent"}])
    assert resp.status_code == 409
    assert "same time" in resp.json()["detail"]


async def test_a_tutor_mark_made_mid_import_still_wins(client, tutor, group, student, monkeypatch):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    await _service_write(
        lesson["id"],
        [svc.AttendanceEntry(sid, AttendanceState.absent)],
        recorded_by=None,
        source=AttendanceSource.zoom,
    )
    real = svc._enrolled_ids

    async def _then_the_tutor_marks(session, les):
        ids = await real(session, les)
        # The import has already read the Zoom row; the tutor saves after that.
        async with async_session() as other:
            row = await other.scalar(select(LessonAttendance))
            row.state, row.source = AttendanceState.absent, AttendanceSource.tutor
            await other.commit()
        return ids

    monkeypatch.setattr(svc, "_enrolled_ids", _then_the_tutor_marks)
    async with async_session() as s:
        skipped = await svc.set_attendance(
            s,
            await s.get(Lesson, lesson["id"]),
            [svc.AttendanceEntry(sid, AttendanceState.present)],
            recorded_by=None,
            source=AttendanceSource.zoom,
        )
    assert skipped == [sid]
    async with async_session() as s:
        row = await s.scalar(select(LessonAttendance).execution_options(populate_existing=True))
        assert (row.state, row.source) == (AttendanceState.absent, AttendanceSource.tutor)


async def test_a_start_time_with_an_offset_is_refused(client, tutor, group):
    lesson = await _lesson(client, tutor, group)
    resp = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"start_time": "17:00:00+02:00"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422


async def test_a_tutor_can_change_and_clear_a_student_who_left(client, tutor, group, student):
    from app.models import GroupMember

    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "present"}])
    async with async_session() as s:
        for m in await s.scalars(select(GroupMember)):
            await s.delete(m)
        await s.commit()
    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "absent"}])
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["state"] == "absent"
    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": None}])
    assert resp.status_code == 200 and resp.json() == []
    # With no mark left they are a stranger again.
    resp = await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "present"}])
    assert resp.status_code == 404


async def test_an_integration_cannot_write_for_a_student_who_left(client, tutor, group, student):
    from app.models import GroupMember

    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    await _put(client, tutor["headers"], lesson, [{"student_id": sid, "state": "present"}])
    async with async_session() as s:
        for m in await s.scalars(select(GroupMember)):
            await s.delete(m)
        await s.commit()
    with pytest.raises(svc.AttendanceStudentNotFound):
        await _service_write(
            lesson["id"],
            [svc.AttendanceEntry(sid, AttendanceState.absent)],
            recorded_by=None,
            source=AttendanceSource.zoom,
        )


async def test_patch_start_time_null_clears_and_omitting_keeps(client, tutor, group):
    lesson = await _lesson(client, tutor, group, start_time="16:30:00")
    url = f"/api/v1/lessons/{lesson['id']}"
    kept = await client.patch(url, json={"notes": "x"}, headers=tutor["headers"])
    assert kept.json()["start_time"] == "16:30:00"
    cleared = await client.patch(url, json={"start_time": None}, headers=tutor["headers"])
    assert cleared.json()["start_time"] is None
    assert cleared.json()["mode"] == "in_person"


async def test_set_attendance_reports_the_ids_a_tutor_mark_protected(client, tutor, group, student):
    lesson = await _lesson(client, tutor, group)
    sid = student["user"]["id"]
    async with async_session() as s:
        actor = await s.get(User, tutor["user"]["id"])
        les = await s.get(Lesson, lesson["id"])
        entry = [svc.AttendanceEntry(sid, AttendanceState.present)]
        assert await svc.set_attendance(s, les, entry, recorded_by=actor) == []
        skipped = await svc.set_attendance(
            s, les, entry, recorded_by=None, source=AttendanceSource.zoom
        )
    assert skipped == [sid]


async def test_the_group_listing_orders_by_date_then_time_then_id(client, tutor, group):
    a = await _lesson(client, tutor, group, start_time="09:00:00")
    b = await _lesson(client, tutor, group, start_time="15:00:00")
    c = await _lesson(client, tutor, group)  # unknown time sorts last within the day
    d = await _lesson(client, tutor, group)
    # Date outranks time: a later day with no time still comes first.
    later = await _lesson(client, tutor, group, date="2026-07-15")
    earlier = await _lesson(client, tutor, group, date="2026-07-13", start_time="23:00:00")
    resp = await client.get(f"/api/v1/lessons/group/{group['id']}", headers=tutor["headers"])
    assert [r["id"] for r in resp.json()] == [
        later["id"],
        b["id"],
        a["id"],
        d["id"],
        c["id"],
        earlier["id"],
    ]
