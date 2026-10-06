"""Deleting a class: it disappears and stops sending, the students' record stays.

The class is soft-deleted (`Group.deleted_at`). Everything forward-looking treats it
as gone; submissions, marks, evidence and enrolment are untouched, so no student's
readiness changes (`PROD-5`).
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Evidence,
    Group,
    GroupMember,
    Mock,
    MockStatus,
    Notification,
    NotificationKind,
    QuestionMark,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
    WorkKind,
)
from app.security import create_access_token
from app.services.lesson_autorecord import due_slot_ids, record_planned_lesson
from app.services.lesson_reminders import due_reminders
from app.services.notifications.triggers import announce_homework_set, remind_homework_due
from app.services.plan_progress import class_progress
from app.services.plan_reflow import enqueue_reflow_for_subject
from app.services.today import tutor_groups
from app.services.work import create_work
from app.workers.jobs import process_one_job
from tests.conftest import PNG_BYTES
from tests.factories import make_user, org_id, publish_assignment, register_other_tutor
from tests.plan_world import make_chapters, make_plan
from tests.test_homework import fake_marking

API = "/api/v1"
NOON = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


async def _delete(client, tutor, group):
    return await client.delete(f"{API}/groups/{group['id']}", headers=tutor["headers"])


async def _deleted_at(group_id: int):
    async with async_session() as s:
        return (await s.get(Group, group_id, populate_existing=True)).deleted_at


async def _hand_in(client, student, assignment_id):
    resp = await client.post(
        f"{API}/assignments/{assignment_id}/submissions",
        files=[("files", ("p.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _evidence_snapshot():
    async with async_session() as s:
        rows = (await s.scalars(select(Evidence).order_by(Evidence.id))).all()
        return [
            (e.id, e.student_id, e.topic_id, e.source_type, e.score_pct, e.max_marks, e.source_ref)
            for e in rows
        ]


# ---------------------------------------------------------------- the tutor


async def test_delete_hides_the_class_and_every_route_addressed_to_it(
    client, tutor, group, student
):
    gid = group["id"]
    assert (await _delete(client, tutor, group)).status_code == 204
    assert await _deleted_at(gid) is not None

    listed = await client.get(f"{API}/groups", headers=tutor["headers"])
    assert gid not in [g["id"] for g in listed.json()]

    h = tutor["headers"]
    gets = [
        f"/groups/{gid}",
        f"/groups/{gid}/lessons",
        f"/groups/{gid}/plan",
        f"/groups/{gid}/taught-before",
        f"/groups/{gid}/report",
        f"/groups/{gid}/narrative",
        f"/groups/{gid}/resources",
        f"/analytics/groups/{gid}",
        f"/today/classes/{gid}",
        f"/lessons/group/{gid}",
        f"/assignments/group/{gid}",
    ]
    for path in gets:
        assert (await client.get(API + path, headers=h)).status_code == 404, path
    for path in (f"/groups/{gid}/invites", f"/groups/{gid}/brief"):
        assert (await client.post(API + path, headers=h)).status_code == 404, path
    resp = await client.delete(f"{API}/groups/{gid}/members/{student['user']['id']}", headers=h)
    assert resp.status_code == 404
    # Idempotent in effect: the second call finds nothing.
    assert (await _delete(client, tutor, group)).status_code == 404


async def test_a_deleted_class_takes_no_new_homework_or_mock(
    client, tutor, group, classified, subject
):
    await _delete(client, tutor, group)
    resp = await client.post(
        f"{API}/assignments",
        json={"group_id": group["id"], "classified_id": classified["id"], "title": "HW"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"{API}/assignments/upload",
        data={"group_id": str(group["id"])},
        files={"file": ("q.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"{API}/mocks",
        data={
            "subject_id": str(subject["id"]),
            "title": "Mock",
            "group_id": str(group["id"]),
        },
        files={"paper": ("p.pdf", b"%PDF-1.4 x", "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404


async def test_nobody_else_can_delete_it(client, tutor, group, student):
    # Another organization's tutor: 404, the class is not theirs to know of.
    other = await register_other_tutor(client)
    assert (await _delete(client, other, group)).status_code == 404
    # A colleague in the same organization who is not an admin: 404 too.
    async with async_session() as s:
        colleague = await make_user(
            s,
            organization_id=await org_id(s),
            role=UserRole.tutor,
            name="Colleague",
            email="colleague@example.com",
        )
        await s.commit()
        headers = {
            "Authorization": f"Bearer {create_access_token(colleague.id, colleague.token_version)}"
        }
    assert (await _delete(client, {"headers": headers}, group)).status_code == 404
    # A student fails the role gate in the signature, before the handler runs,
    # and the same way for any id: it says nothing about whether the class exists.
    assert (await _delete(client, student, group)).status_code == 403
    assert (
        await client.delete(f"{API}/groups/99999", headers=student["headers"])
    ).status_code == 403
    assert (await client.delete(f"{API}/groups/{group['id']}")).status_code == 401
    assert await _deleted_at(group["id"]) is None


async def test_the_tutors_lists_follow_the_visible_classes(
    client, tutor, group, student, published_assignment, subject
):
    h = tutor["headers"]
    assert [a["id"] for a in (await client.get(f"{API}/assignments", headers=h)).json()["items"]]
    assert (await client.get(f"{API}/students", headers=h)).json()["items"]
    await _delete(client, tutor, group)
    assert (await client.get(f"{API}/assignments", headers=h)).json()["items"] == []
    assert (await client.get(f"{API}/students", headers=h)).json()["items"] == []
    today = (await client.get(f"{API}/today", headers=h)).json()
    assert today["classes"] == []
    assert today["class_count"] == 0
    assert (await client.get(f"{API}/groups/{group['id']}", headers=h)).status_code == 404
    # The homework itself is not editable any more, but its detail stays readable.
    aid = published_assignment["id"]
    assert (await client.post(f"{API}/assignments/{aid}/publish", headers=h)).status_code == 404
    assert (await client.get(f"{API}/assignments/{aid}", headers=h)).status_code == 200
    assert (await client.get(f"{API}/assignments/{aid}/submissions", headers=h)).status_code == 404


async def test_a_tutor_whose_only_class_is_deleted_is_treated_as_having_none(
    client, tutor, group, subject
):
    ch = await make_chapters(subject)
    await make_plan(group, tutor, [(ch["c1"], NOON.date(), time(12, 10))])
    before = (await client.get(f"{API}/onboarding", headers=tutor["headers"])).json()
    assert before["in_flow"] is False
    await _delete(client, tutor, group)
    after = (await client.get(f"{API}/onboarding", headers=tutor["headers"])).json()
    assert after["in_flow"] is True


# ----------------------------------------------------- students and the invite


async def test_students_lose_the_class_and_whatever_they_have_not_handed_in(
    client, tutor, group, student, published_assignment
):
    h = student["headers"]
    aid = published_assignment["id"]
    assert (await client.get(f"{API}/me/groups", headers=h)).json()
    assert (await client.get(f"{API}/me/assignments", headers=h)).json()
    await _delete(client, tutor, group)
    assert (await client.get(f"{API}/me/groups", headers=h)).json() == []
    assert (await client.get(f"{API}/me/lessons", headers=h)).json() == []
    assert (await client.get(f"{API}/me/assignments", headers=h)).json() == []
    assert (
        await client.get(f"{API}/assignments/{aid}/my-submission", headers=h)
    ).status_code == 404
    resp = await client.post(
        f"{API}/assignments/{aid}/submissions",
        files=[("files", ("p.png", PNG_BYTES, "image/png"))],
        headers=h,
    )
    assert resp.status_code == 404


async def test_an_old_invite_code_fails_like_an_unknown_one(client, tutor, group, student):
    invite = await client.post(f"{API}/groups/{group['id']}/invites", headers=tutor["headers"])
    code = invite.json()["code"]
    assert (await client.get(f"{API}/auth/invites/{code}")).status_code == 200
    await _delete(client, tutor, group)
    unknown = await client.get(f"{API}/auth/invites/NOPE")
    assert (
        (await client.get(f"{API}/auth/invites/{code}")).status_code == unknown.status_code == 404
    )
    reg = await client.post(
        f"{API}/auth/register/student",
        json={
            "invite_code": code,
            "name": "Late",
            "email": "late@example.com",
            "password": "password123",
        },
    )
    assert reg.status_code == 404
    join = await client.post(
        f"{API}/auth/join", json={"invite_code": code}, headers=student["headers"]
    )
    assert join.status_code == 404


async def test_a_mock_not_yet_sat_leaves_the_tutor_and_the_student(
    client, tutor, group, student, subject
):
    async with async_session() as s:
        work = await create_work(
            s,
            kind=WorkKind.mock,
            organization_id=await org_id(s),
            subject_id=subject["id"],
            title="Mock",
        )
        mock = Mock(
            work_id=work.id,
            organization_id=await org_id(s),
            tutor_id=tutor["user"]["id"],
            subject_id=subject["id"],
            group_id=group["id"],
            title="Mock",
            paper_path="p.pdf",
            paper_name="p.pdf",
            paper_mime="application/pdf",
            status=MockStatus.published,
        )
        s.add(mock)
        await s.commit()
        mock_id = mock.id
    assert (await client.get(f"{API}/mocks", headers=tutor["headers"])).json()
    assert (await client.get(f"{API}/mocks/mine", headers=student["headers"])).json()
    await _delete(client, tutor, group)
    assert (await client.get(f"{API}/mocks", headers=tutor["headers"])).json() == []
    assert (await client.get(f"{API}/mocks/mine", headers=student["headers"])).json() == []
    for who in (tutor, student):
        assert (
            await client.get(f"{API}/mocks/{mock_id}", headers=who["headers"])
        ).status_code == 404


# ------------------------------------------------------ what is kept, untouched


async def test_marked_work_evidence_and_readiness_are_identical_after_deletion(
    client, tutor, group, student, published_assignment, monkeypatch
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    await _hand_in(client, student, aid)
    assert await process_one_job() is True
    th, sh = tutor["headers"], student["headers"]
    sid = (await client.get(f"{API}/assignments/{aid}/submissions", headers=th)).json()[0]["id"]
    marks = (await client.get(f"{API}/submissions/{sid}", headers=th)).json()["marks"]
    await client.put(
        f"{API}/submissions/{sid}/marks",
        json=[
            {"question_id": m["question_id"], "final_marks": 1, "final_feedback": "ok"}
            for m in marks
        ],
        headers=th,
    )
    assert (await client.post(f"{API}/submissions/{sid}/finalize", headers=th)).status_code == 200

    evidence_before = await _evidence_snapshot()
    assert evidence_before
    uid = student["user"]["id"]
    readiness_before = (await client.get(f"{API}/readiness/students/{uid}", headers=th)).json()
    mine_before = (await client.get(f"{API}/readiness/me", headers=sh)).json()
    marked_before = (await client.get(f"{API}/assignments/{aid}/my-submission", headers=sh)).json()

    assert (await _delete(client, tutor, group)).status_code == 204

    assert await _evidence_snapshot() == evidence_before
    assert (
        await client.get(f"{API}/readiness/students/{uid}", headers=th)
    ).json() == readiness_before
    assert (await client.get(f"{API}/readiness/me", headers=sh)).json() == mine_before
    # The student still reads their marked work from the deleted class, and it
    # still shows in their list; the enrolment row is untouched.
    assert (
        await client.get(f"{API}/assignments/{aid}/my-submission", headers=sh)
    ).json() == marked_before
    assert [a["id"] for a in (await client.get(f"{API}/me/assignments", headers=sh)).json()] == [
        aid
    ]
    async with async_session() as s:
        assert await s.scalar(select(GroupMember.id).where(GroupMember.student_id == uid))
        assert await s.scalar(select(Submission.id).where(Submission.id == sid))
        assert await s.scalar(select(QuestionMark.id).where(QuestionMark.submission_id == sid))
    # The tutor still reaches the student's record and the work itself.
    assert (await client.get(f"{API}/students/{uid}/crm", headers=th)).status_code == 200
    assert (await client.get(f"{API}/submissions/{sid}", headers=th)).status_code == 200


async def test_work_awaiting_review_stays_in_the_queue_and_can_be_finalized(
    client, tutor, group, student, published_assignment, monkeypatch
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    await _hand_in(client, student, aid)
    assert await process_one_job() is True
    th = tutor["headers"]
    queue = (await client.get(f"{API}/submissions/review-queue", headers=th)).json()
    assert len(queue) == 1
    sid = queue[0]["submission_id"]

    await _delete(client, tutor, group)

    queue = (await client.get(f"{API}/submissions/review-queue", headers=th)).json()
    assert [q["submission_id"] for q in queue] == [sid]
    marks = (await client.get(f"{API}/submissions/{sid}", headers=th)).json()["marks"]
    save = await client.put(
        f"{API}/submissions/{sid}/marks",
        json=[
            {"question_id": m["question_id"], "final_marks": 1, "final_feedback": "ok"}
            for m in marks
        ],
        headers=th,
    )
    assert save.status_code == 200, save.text
    final = await client.post(f"{API}/submissions/{sid}/finalize", headers=th)
    assert final.status_code == 200
    assert final.json()["status"] == "finalized"
    async with async_session() as s:
        assert (await s.get(Submission, sid)).status is SubmissionStatus.finalized
    assert await _evidence_snapshot()


# ------------------------------------------------------- sweeps and triggers


async def _homework(group, subject, **kwargs):
    async with async_session() as s:
        assignment = await publish_assignment(
            s,
            group_id=group["id"],
            subject_id=subject["id"],
            organization_id=await org_id(s),
            **kwargs,
        )
        await s.commit()
        return assignment


async def _notes(kind):
    async with async_session() as s:
        return list(await s.scalars(select(Notification).where(Notification.kind == kind)))


async def test_homework_messages_skip_a_deleted_class(client, tutor, group, student, subject):
    due = await _homework(group, subject, title="Soon", due_at=NOON + timedelta(hours=12))
    await _delete(client, tutor, group)
    async with async_session() as s:
        await remind_homework_due(s, NOON)
        await announce_homework_set(s, due)
        await s.commit()
    assert await _notes(NotificationKind.homework_due) == []
    assert await _notes(NotificationKind.homework_set) == []


async def test_lessons_are_not_recorded_or_reminded_for_a_deleted_class(
    client, tutor, group, student, subject
):
    ch = await make_chapters(subject)
    soon = datetime.now(timezone.utc) + timedelta(minutes=10)
    past = datetime.now(timezone.utc) - timedelta(days=2)
    _, (past_slot, soon_slot) = await make_plan(
        group,
        tutor,
        [
            (ch["c1"], past.date(), time(9, 0)),
            (ch["c1"], soon.date(), soon.time().replace(second=0, microsecond=0)),
        ],
    )
    now = datetime.now(timezone.utc)
    async with async_session() as s:
        assert past_slot in await due_slot_ids(s, now)
        user = await s.get(User, tutor["user"]["id"])
        assert await due_reminders(s, user, now)

    await _delete(client, tutor, group)

    async with async_session() as s:
        assert await due_slot_ids(s, now) == []
        assert await record_planned_lesson(s, past_slot, now=now) is False
        user = await s.get(User, tutor["user"]["id"])
        assert await due_reminders(s, user, now) == []
        assert await class_progress(s, user, now.date()) == {}
        assert list(await tutor_groups(s, user.id)) == []
        assert await enqueue_reflow_for_subject(s, subject["id"]) == 0
    assert (await client.get(f"{API}/today/reminders", headers=tutor["headers"])).json() == []


async def test_the_class_narrative_job_does_nothing_for_a_deleted_class(
    client, tutor, group, monkeypatch
):
    from app.services import narrative

    async def boom(*_a, **_k):
        raise AssertionError("a deleted class must not be summarised")

    monkeypatch.setattr(narrative, "_latest_evidence_at_for_group", boom)
    await _delete(client, tutor, group)
    async with async_session() as s:
        await narrative.generate_narrative(s, {"audience": "tutor_class", "group_id": group["id"]})
