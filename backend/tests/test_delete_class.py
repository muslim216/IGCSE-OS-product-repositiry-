"""Deleting a class: it disappears and stops sending, the students' record stays.

The class is soft-deleted (`Group.deleted_at`). Everything forward-looking treats it
as gone; submissions, marks, evidence and enrolment are untouched, so no student's
readiness changes (`PROD-5`).
"""

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Assignment,
    Evidence,
    Group,
    GroupMember,
    Job,
    JobStatus,
    Mock,
    MockStatus,
    Notification,
    NotificationKind,
    QuestionMark,
    ReadinessSnapshot,
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
from app.services.readiness_v2 import evaluate_subject_factors
from app.services.readiness_v2_ai import ReadinessSynthesis, enqueue_readiness_v2_debounced
from app.services.today import tutor_groups
from app.services.work import create_work
from app.workers.jobs import process_one_job
from tests.conftest import PNG_BYTES
from tests.factories import (
    make_past_paper,
    make_user,
    org_id,
    publish_assignment,
    register_other_tutor,
    register_parent,
)
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


async def _published_mock(s, tutor, group, subject):
    """A published mock set for the class, added to the session but not committed."""
    organization_id = await org_id(s)
    work = await create_work(
        s,
        kind=WorkKind.mock,
        organization_id=organization_id,
        subject_id=subject["id"],
        title="Mock",
    )
    mock = Mock(
        work_id=work.id,
        organization_id=organization_id,
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
    return work, mock


async def test_a_mock_not_yet_sat_leaves_the_tutor_and_the_student(
    client, tutor, group, student, subject
):
    async with async_session() as s:
        work, mock = await _published_mock(s, tutor, group, subject)
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


async def _drain() -> int:
    """Run every queued job to completion, fast-forwarding the debounce window
    (QA-6: never the worker loop)."""
    for ran in range(60):
        async with async_session() as s:
            for job in (await s.scalars(select(Job).where(Job.status == JobStatus.pending))).all():
                job.run_after = None
            await s.commit()
        if not await process_one_job():
            return ran
    raise AssertionError("the job queue did not drain")


async def _mark_and_finalize(client, tutor, student, aid):
    await _hand_in(client, student, aid)
    assert await process_one_job() is True
    th = tutor["headers"]
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
    return sid


async def _latest_snapshot(student_id: int, subject_id: int):
    async with async_session() as s:
        return await s.scalar(
            select(ReadinessSnapshot)
            .where(
                ReadinessSnapshot.student_id == student_id,
                ReadinessSnapshot.subject_id == subject_id,
            )
            .order_by(ReadinessSnapshot.id.desc())
        )


async def _factors(student_id: int, subject_id: int, now):
    """Layer 1 at a pinned clock, so two reads can be compared exactly."""
    async with async_session() as s:
        rows = await evaluate_subject_factors(s, student_id, subject_id, "pin", now)
        out = [(r.factor.value, r.topic_id, r.score, r.confidence.value, r.detail) for r in rows]
        await s.rollback()
        return sorted(out, key=repr)


async def _recompute(student_id: int, subject_id: int) -> None:
    async with async_session() as s:
        await enqueue_readiness_v2_debounced(s, student_id, subject_id)
        await s.commit()
    await _drain()


def _ai(monkeypatch, fake_ai):
    monkeypatch.setattr(
        "app.services.readiness_v2_ai.structured_complete",
        fake_ai(ReadinessSynthesis(score=50.0, rationale="r", recommended_revision="-")),
    )


async def test_readiness_is_identical_after_deletion(
    client, tutor, group, student, published_assignment, subject, monkeypatch, fake_ai
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    _ai(monkeypatch, fake_ai)
    aid, uid, sub_id = published_assignment["id"], student["user"]["id"], subject["id"]
    sid = await _mark_and_finalize(client, tutor, student, aid)
    assert await _drain() > 0
    await _recompute(student["user"]["id"], subject["id"])  # a trend needs two runs

    # A real v2 snapshot with a score, built by the job queue, not an empty payload.
    before = await _latest_snapshot(uid, sub_id)
    assert before is not None
    assert before.score is not None
    now = datetime.now(timezone.utc)
    factors_before = await _factors(uid, sub_id, now)
    assert any(f[0] == "homework_performance" and f[2] is not None for f in factors_before)
    evidence_before = await _evidence_snapshot()
    assert evidence_before
    sh = student["headers"]
    mine_before = (await client.get(f"{API}/readiness/me", headers=sh)).json()
    assert mine_before["subjects"][0]["score"] is not None
    marked_before = (await client.get(f"{API}/assignments/{aid}/my-submission", headers=sh)).json()

    assert (await _delete(client, tutor, group)).status_code == 204
    await _recompute(uid, sub_id)

    after = await _latest_snapshot(uid, sub_id)
    assert after.id != before.id, "a fresh recompute really ran"
    assert (after.score, after.predicted_grade) == (before.score, before.predicted_grade)
    assert await _factors(uid, sub_id, now) == factors_before
    assert await _evidence_snapshot() == evidence_before
    mine_after = (await client.get(f"{API}/readiness/me", headers=sh)).json()
    for body in (mine_before, mine_after):
        for row in body["subjects"]:
            row.pop("computed_at")  # the only thing a fresh run is allowed to change
    assert mine_after == mine_before
    # The student still reads their marked work and it still lists; enrolment stays.
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


async def test_homework_not_yet_due_at_deletion_is_never_counted_as_missed(
    client, tutor, group, student, published_assignment, subject, monkeypatch, fake_ai
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    _ai(monkeypatch, fake_ai)
    aid, uid, sub_id = published_assignment["id"], student["user"]["id"], subject["id"]
    await _mark_and_finalize(client, tutor, student, aid)
    today = datetime.now(timezone.utc)
    await _homework(group, subject, title="Overdue", due_at=today - timedelta(days=3))
    await _homework(group, subject, title="Open", due_at=today + timedelta(days=5))
    await _homework(group, subject, title="Undated", due_at=None)

    def hw(factors):
        return next(f for f in factors if f[0] == "homework_performance")

    before = hw(await _factors(uid, sub_id, today))
    assert before[4]["assignment_count"] == 4  # marked + overdue + two still open

    assert (await _delete(client, tutor, group)).status_code == 204

    after = hw(await _factors(uid, sub_id, today))
    # The score is accuracy on marked work and does not move.
    assert after[2] == before[2]
    assert after[4]["accuracy"] == before[4]["accuracy"]
    # The overdue piece still counts as missed; the two the student can no longer
    # hand in do not.
    assert after[4]["assignment_count"] == 2
    assert after[4]["submitted_count"] == before[4]["submitted_count"] == 1
    # And the open one does not become a miss when its date passes.
    later = hw(await _factors(uid, sub_id, today + timedelta(days=30)))
    assert later[4] == after[4]
    # The student's own list and the CRM row follow the same rule.
    crm = await client.get(f"{API}/students/{uid}/crm", headers=student["headers"])
    if crm.status_code == 200:
        titles = {h["title"] for h in crm.json()["homework"]}
        assert "Open" not in titles
        assert "Undated" not in titles
        assert "Overdue" in titles


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


# ------------------------------------------- the tutor-student relationship ends


async def _second_class_with(client, tutor, subject, student):
    resp = await client.post(
        f"{API}/groups",
        json={"name": "Chem Y11", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    gid = resp.json()["id"]
    invite = await client.post(f"{API}/groups/{gid}/invites", headers=tutor["headers"])
    join = await client.post(
        f"{API}/auth/join",
        json={"invite_code": invite.json()["code"]},
        headers=student["headers"],
    )
    assert join.status_code == 204, join.text
    return gid


def _student_probes(uid):
    """(method, path, json) for everything a tutor does about one student."""
    return [
        ("GET", f"/students/{uid}/crm", None),
        ("PUT", f"/students/{uid}/profile", {"notes": "x"}),
        ("POST", f"/students/{uid}/notes", {"body": "note"}),
        ("POST", f"/students/{uid}/communications", {"body": "call"}),
        ("POST", f"/students/{uid}/parent-code", None),
        ("GET", f"/students/{uid}/contacts", None),
        ("GET", f"/students/{uid}/weekly-sends", None),
        ("GET", f"/students/{uid}/observations", None),
        ("POST", "/observations", {"student_id": uid, "comment": "good"}),
        ("GET", f"/readiness/students/{uid}", None),
        ("GET", f"/students/{uid}/attendance", None),
    ]


async def _probe(client, headers, probes):
    out = {}
    for method, path, body in probes:
        resp = await client.request(method, API + path, json=body, headers=headers)
        out[(method, path)] = resp.status_code
    return out


async def test_deleting_the_only_class_ends_the_tutors_access_to_the_student(
    client, tutor, group, student, published_assignment, subject
):
    uid = student["user"]["id"]
    probes = _student_probes(uid)
    before = await _probe(client, tutor["headers"], probes)
    assert all(code < 400 for code in before.values()), before

    await _delete(client, tutor, group)

    after = await _probe(client, tutor["headers"], probes)
    assert set(after.values()) == {404}, after
    # An assessment mark and a report are refused too, and a report is not queued.
    resp = await client.post(
        f"{API}/assessments",
        json={
            "subject_id": subject["id"],
            "title": "T",
            "type": "mock",
            "date": "2026-10-01",
            "scores": [
                {"student_id": uid, "topic_id": subject["topic1"], "marks": 1, "max_marks": 2}
            ],
        },
        headers=tutor["headers"],
    )
    assert resp.status_code in (403, 404)
    resp = await client.post(
        f"{API}/reports/generate",
        json={"student_id": uid, "audience": "tutor"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404
    async with async_session() as s:
        assert (await s.scalar(select(Job.id).where(Job.type == "generate_report"))) is None


async def test_a_tutor_who_still_teaches_the_student_elsewhere_keeps_everything(
    client, tutor, group, student, published_assignment, subject
):
    uid = student["user"]["id"]
    await _second_class_with(client, tutor, subject, student)
    probes = _student_probes(uid)
    await _delete(client, tutor, group)
    after = await _probe(client, tutor["headers"], probes)
    assert all(code < 400 for code in after.values()), after


async def test_work_already_handed_in_can_still_be_marked_after_the_relationship_ends(
    client, tutor, group, student, published_assignment, monkeypatch
):
    monkeypatch.setattr("app.services.marking._run_marking", fake_marking)
    aid = published_assignment["id"]
    await _hand_in(client, student, aid)
    assert await process_one_job() is True
    th = tutor["headers"]
    sid = (await client.get(f"{API}/submissions/review-queue", headers=th)).json()[0][
        "submission_id"
    ]
    await _delete(client, tutor, group)
    assert (
        await client.get(f"{API}/students/{student['user']['id']}/crm", headers=th)
    ).status_code == 404
    queue = (await client.get(f"{API}/submissions/review-queue", headers=th)).json()
    assert [q["submission_id"] for q in queue] == [sid]
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


# ------------------------------------------------- student-side forward access


async def test_a_deleted_class_gives_no_past_papers_unless_another_class_does(
    client, tutor, group, student, subject
):
    async with async_session() as s:
        paper = await make_past_paper(
            s,
            subject_id=subject["id"],
            organization_id=await org_id(s),
            tutor_id=tutor["user"]["id"],
            title="P1",
        )
        s.add(
            Submission(
                work_id=paper.work_id,
                student_id=student["user"]["id"],
                status=SubmissionStatus.finalized,
            )
        )
        await s.commit()
        pid = paper.id
    sh = student["headers"]
    assert [p["id"] for p in (await client.get(f"{API}/past-papers", headers=sh)).json()] == [pid]

    await _delete(client, tutor, group)
    assert (await client.get(f"{API}/past-papers", headers=sh)).json() == []
    assert (await client.get(f"{API}/past-papers/{pid}", headers=sh)).status_code == 404
    assert (await client.get(f"{API}/past-papers/{pid}/paper", headers=sh)).status_code == 404
    # History: their own attempt stays readable, the paper itself does not reopen.
    assert (await client.get(f"{API}/past-papers/{pid}/my-attempt", headers=sh)).status_code == 200
    resp = await client.post(
        f"{API}/past-papers/{pid}/attempts",
        data={"attempted_at": "2026-10-01"},
        files={"files": ("p.png", PNG_BYTES, "image/png")},
        headers=sh,
    )
    assert resp.status_code == 404


async def test_another_live_class_in_the_subject_keeps_the_past_papers(
    client, tutor, group, student, subject
):
    async with async_session() as s:
        paper = await make_past_paper(
            s, subject_id=subject["id"], organization_id=await org_id(s), title="P1"
        )
        await s.commit()
        pid = paper.id
    await _second_class_with(client, tutor, subject, student)
    await _delete(client, tutor, group)
    resp = await client.get(f"{API}/past-papers/{pid}", headers=student["headers"])
    assert resp.status_code == 200


async def test_the_question_paper_of_unsubmitted_homework_is_no_longer_downloadable(
    client, tutor, group, student, published_assignment, classified
):
    sh = student["headers"]
    url = f"{API}/classifieds/{classified['id']}/file"
    assert (await client.get(url, headers=sh)).status_code == 200
    await _delete(client, tutor, group)
    assert (await client.get(url, headers=sh)).status_code == 404


async def test_the_question_paper_of_handed_in_homework_stays_downloadable(
    client, tutor, group, student, published_assignment, classified
):
    await _hand_in(client, student, published_assignment["id"])
    await _delete(client, tutor, group)
    url = f"{API}/classifieds/{classified['id']}/file"
    assert (await client.get(url, headers=student["headers"])).status_code == 200


async def test_a_handed_in_mock_can_be_read_but_not_sat_or_opened_again(
    client, tutor, group, student, subject
):
    async with async_session() as s:
        work, mock = await _published_mock(s, tutor, group, subject)
        await s.flush()
        s.add(
            Submission(
                work_id=work.id,
                student_id=student["user"]["id"],
                status=SubmissionStatus.finalized,
            )
        )
        await s.commit()
        mid = mock.id
    sh = student["headers"]
    await _delete(client, tutor, group)
    assert (await client.get(f"{API}/mocks/{mid}", headers=sh)).status_code == 200
    assert (await client.get(f"{API}/mocks/{mid}/my-submission", headers=sh)).status_code == 200
    assert (await client.post(f"{API}/mocks/{mid}/open", headers=sh)).status_code == 404
    resp = await client.post(
        f"{API}/mocks/{mid}/submissions",
        files=[("files", ("p.png", PNG_BYTES, "image/png"))],
        headers=sh,
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------- jobs


async def test_an_extraction_queued_before_deletion_makes_no_model_call(
    client, tutor, group, classified, monkeypatch
):
    async def boom(*_a, **_k):
        raise AssertionError("no model call for a deleted class")

    monkeypatch.setattr("app.services.extraction._run_extraction", boom)
    resp = await client.post(
        f"{API}/assignments",
        json={"group_id": group["id"], "classified_id": classified["id"], "title": "HW"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201
    aid = resp.json()["id"]
    await _delete(client, tutor, group)
    assert await process_one_job() is True  # runs, returns early, and is safe to repeat
    async with async_session() as s:
        job = await s.scalar(select(Job).where(Job.type == "extract_assignment"))
        assert job.status is JobStatus.done
        assert (await s.get(Assignment, aid)).status.value == "extracting"


# -------------------------------------------------------------- who may delete


async def test_a_second_delete_is_a_404_at_the_route(client, tutor, group):
    assert (await _delete(client, tutor, group)).status_code == 204
    assert (await _delete(client, tutor, group)).status_code == 404


async def test_an_admin_may_delete_in_their_organization_but_not_in_another(client, tutor, group):
    other = await register_other_tutor(client)
    async with async_session() as s:
        same = await make_user(
            s, organization_id=await org_id(s), role=UserRole.admin, name="A", email="a@example.com"
        )
        foreign = await make_user(
            s,
            organization_id=(await s.get(User, other["user"]["id"])).organization_id,
            role=UserRole.admin,
            name="B",
            email="b@example.com",
        )
        await s.commit()
        same_h = {"Authorization": f"Bearer {create_access_token(same.id, same.token_version)}"}
        foreign_h = {
            "Authorization": f"Bearer {create_access_token(foreign.id, foreign.token_version)}"
        }
    assert (await _delete(client, {"headers": foreign_h}, group)).status_code == 404
    assert await _deleted_at(group["id"]) is None
    assert (await _delete(client, {"headers": same_h}, group)).status_code == 204
    assert await _deleted_at(group["id"]) is not None


async def test_a_parent_gets_the_role_refusal(client, tutor, group, student):
    parent = await register_parent(client, tutor, student)
    resp = await _delete(client, parent, group)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Tutor account required"
    assert await _deleted_at(group["id"]) is None
