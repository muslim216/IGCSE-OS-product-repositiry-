"""Erasing a child's data (launch audit P-3, part 3): who may ask, the sign-in
lock, the 14-day undo, and that after the sweep nothing about the child is left
anywhere while a classmate is untouched."""

import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.api.deps import is_erasing
from app.db import async_session, engine
from app.models import (
    AiFeature,
    AiUsageEvent,
    AttemptRedo,
    AttendanceSource,
    AttendanceState,
    Base,
    CustomCriterionScoreAudit,
    DismissedPrompt,
    ErasureRequest,
    ErasureRequestStatus,
    Evidence,
    EvidenceSource,
    FactorConfidence,
    GroupRemoval,
    Job,
    JobStatus,
    Lesson,
    LessonAttendance,
    LessonObservation,
    MarkOverrideAudit,
    MeetingParticipant,
    MistakeSource,
    Narrative,
    NarrativeAudience,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationPreference,
    Organization,
    ParentCommunication,
    ParentLink,
    ParentLinkRemoval,
    PastPaper,
    PastPaperAttempt,
    QuestionMark,
    RemarkRequest,
    Report,
    ReportAudience,
    ReportStatus,
    StudentProfile,
    StudentSubject,
    Submission,
    SubmissionFile,
    SubmissionStatus,
    TutorNote,
    TutorObservation,
    User,
    UserRole,
    WeeklySend,
    WeeklySendAudience,
)
from app.models.integrations import MeetingProvider
from app.security import create_access_token, verify_password
from app.services import data_export, erasure, retention, storage
from app.services.notifications.triggers import announce_marked_work
from tests.factories import (
    add_contact,
    add_mistake,
    link_parent,
    make_mistake_category,
    make_past_paper,
    make_user,
    org_id,
    register_other_tutor,
    register_parent,
    settled_submission,
    write_v2_snapshot,
)
from tests.test_data_export import (  # noqa: F401  (fixtures and helpers)
    _admin,
    _drain,
    _export,
    _org_of,
    _own_upload_dir,
    world,
)

GENERIC = "Incorrect email/username or password"
CHILD = "Zephyrine Quillfeather"
CHILD_EMAIL = "zephyrine.q@example.com"
CHILD_USERNAME = "zephyrine.q"
#: Tables the sweep wipes or anonymises that the big test does not seed, and why.
UNSEEDED = {
    "assessment_scores": "needs an assessment fixture; deleted by the same by-student loop",
    "mock_openings": "needs a mock fixture; deleted by the same by-student loop",
    "custom_criterion_scores": "needs a criterion fixture; deleted by the same by-student loop",
}
NOW = datetime.now(timezone.utc)


def _url(student_id: int, *, parent: bool = False) -> str:
    return f"/api/v1/{'me/children' if parent else 'students'}/{student_id}/erasure"


async def _ask(client, headers, student_id, name="Sara", *, parent=False):
    return await client.post(
        _url(student_id, parent=parent), json={"confirm_name": name}, headers=headers
    )


async def _login(client, email="sara@example.com", password="password123"):
    return await client.post("/api/v1/auth/login", json={"identifier": email, "password": password})


async def _make_due(request_id: int) -> None:
    async with async_session() as session:
        request = await session.get(ErasureRequest, request_id)
        request.scheduled_for = NOW - timedelta(minutes=1)
        await session.commit()


async def _sweep() -> int:
    async with async_session() as session:
        return await erasure.erase_due(session, datetime.now(timezone.utc))


# ------------------------------------------------------------- who may ask


async def test_a_tutor_a_linked_parent_and_an_admin_can_each_ask(client, tutor, student, world):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    admin = await _admin(await _org_of(tutor))

    # The tutor first; the others find the same pending request, so each role is
    # exercised on a cancelled-and-asked-again child.
    for headers, role, is_parent in (
        (tutor["headers"], "tutor", False),
        (parent["headers"], "parent", True),
        (admin["headers"], "admin", False),
    ):
        resp = await _ask(client, headers, sid, parent=is_parent)
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["requested_role"] == role
        assert set(body) == {"id", "status", "scheduled_for", "requested_role", "created_at"}
        scheduled = datetime.fromisoformat(body["scheduled_for"])
        scheduled = scheduled if scheduled.tzinfo else scheduled.replace(tzinfo=timezone.utc)
        assert (
            timedelta(days=13, hours=23)
            < scheduled - datetime.now(timezone.utc)
            <= timedelta(days=14)
        )
        assert (
            await client.delete(_url(sid, parent=is_parent), headers=headers)
        ).status_code == 204


async def test_a_wrong_name_is_a_422_and_leaves_no_row_and_the_name_is_forgiving(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    resp = await _ask(client, tutor["headers"], sid, "Omar")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "The name you typed doesn't match this student's name."
    async with async_session() as session:
        assert (await session.scalars(select(ErasureRequest))).all() == []
        assert (await session.get(User, sid)).erasure_requested_at is None
    assert (await _ask(client, tutor["headers"], sid, "   sARA ")).status_code == 202


async def test_everyone_else_is_refused(client, tutor, student, group, world):
    """QA-12: the student, another organization, a colleague who does not teach
    the child, an unlinked parent, no token."""
    sid = student["user"]["id"]
    other_org = await register_other_tutor(client)
    stranger = await register_parent(client, tutor, world["omar"], email="p2@example.com")
    async with async_session() as session:
        colleague = await make_user(
            session,
            organization_id=await _org_of(tutor),
            role=UserRole.tutor,
            name="Colleague",
            email="colleague@example.com",
        )
        await session.commit()
        colleague_headers = {
            "Authorization": f"Bearer {create_access_token(colleague.id, colleague.token_version)}"
        }

    assert (await _ask(client, student["headers"], sid)).status_code == 403
    assert (await _ask(client, student["headers"], sid, parent=True)).status_code == 403
    assert (await _ask(client, stranger["headers"], sid)).status_code == 403
    for headers in (other_org["headers"], colleague_headers):
        assert (await _ask(client, headers, sid)).status_code == 404
        assert (await client.get(_url(sid), headers=headers)).status_code == 404
        assert (await client.delete(_url(sid), headers=headers)).status_code == 404
    assert (await _ask(client, stranger["headers"], sid, parent=True)).status_code == 404
    assert (
        await client.get(_url(sid, parent=True), headers=stranger["headers"])
    ).status_code == 404
    assert (
        await client.delete(_url(sid, parent=True), headers=stranger["headers"])
    ).status_code == 404
    assert (await client.post(_url(sid), json={"confirm_name": "Sara"})).status_code == 401
    # A foreign admin.
    async with async_session() as session:
        from app.models import Organization

        elsewhere = Organization(name="Elsewhere")
        session.add(elsewhere)
        await session.commit()
        elsewhere_id = elsewhere.id
    foreign_admin = await _admin(elsewhere_id)
    assert (await _ask(client, foreign_admin["headers"], sid)).status_code == 404
    async with async_session() as session:
        assert (await session.scalars(select(ErasureRequest))).all() == []
        assert (await session.get(User, sid)).erasure_requested_at is None


async def test_the_status_route_shows_the_pending_request_or_null(client, tutor, student, world):
    sid = student["user"]["id"]
    assert (await client.get(_url(sid), headers=tutor["headers"])).json() is None
    assert (await client.delete(_url(sid), headers=tutor["headers"])).status_code == 404
    asked = (await _ask(client, tutor["headers"], sid)).json()
    listed = (await client.get(_url(sid), headers=tutor["headers"])).json()
    # SQLite hands datetimes back naive; the rest is the same row.
    assert (listed["id"], listed["status"], listed["requested_role"]) == (
        asked["id"],
        "pending",
        "tutor",
    )


# ------------------------------------------------------------------ sign-in


async def test_after_a_request_the_child_cannot_sign_in_or_use_what_they_hold(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    before = await _login(client)
    assert before.status_code == 200
    refresh = before.cookies.get("igcse_refresh")
    assert (await client.get("/api/v1/auth/me", headers=student["headers"])).status_code == 200

    first = await _ask(client, tutor["headers"], sid)
    # A second request returns the same pending row, not another.
    second = await _ask(client, tutor["headers"], sid)
    assert first.json()["id"] == second.json()["id"]
    async with async_session() as session:
        assert len((await session.scalars(select(ErasureRequest))).all()) == 1

    refused = await _login(client)
    assert refused.status_code == 401
    assert refused.json()["detail"] == GENERIC
    assert (await client.get("/api/v1/auth/me", headers=student["headers"])).status_code == 401
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401

    # The second lock, on its own: a token minted at the *current* version.
    async with async_session() as session:
        version = (await session.get(User, sid)).token_version
    fresh = {"Authorization": f"Bearer {create_access_token(sid, version)}"}
    assert (await client.get("/api/v1/auth/me", headers=fresh)).status_code == 401


async def test_cancelling_lets_the_child_back_in_and_a_new_request_is_allowed(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    assert (await _login(client)).status_code == 401
    assert (await client.delete(_url(sid), headers=tutor["headers"])).status_code == 204
    assert (await client.get(_url(sid), headers=tutor["headers"])).json() is None
    assert (await _login(client)).status_code == 200
    async with async_session() as session:
        row = await session.get(ErasureRequest, asked["id"])
        assert row.status == ErasureRequestStatus.cancelled
        assert row.cancelled_at is not None
    again = await _ask(client, tutor["headers"], sid)
    assert again.status_code == 202
    assert again.json()["id"] != asked["id"]


# -------------------------------------------------------------- the sweep


async def test_the_sweep_waits_for_the_window_and_a_cancel_that_won_is_respected(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    assert await _sweep() == 0
    async with async_session() as session:
        assert (await session.get(User, sid)).deleted_at is None

    await _make_due(asked["id"])
    assert (await client.delete(_url(sid), headers=tutor["headers"])).status_code == 204
    assert await _sweep() == 0
    async with async_session() as session:
        assert (await session.get(User, sid)).name == "Sara"


async def test_a_cancel_between_the_listing_and_the_wipe_wins(
    client, tutor, student, world, monkeypatch
):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    real = erasure._due_ids

    async def listed_then_cancelled(session, now):
        ids = await real(session, now)
        assert ids == [asked["id"]]
        student_row = await session.get(User, sid)
        assert await erasure.cancel_erasure(session, student_row, student_row)
        return ids

    monkeypatch.setattr(erasure, "_due_ids", listed_then_cancelled)
    assert await _sweep() == 0
    async with async_session() as session:
        assert (await session.get(User, sid)).name == "Sara"
        assert (await session.get(ErasureRequest, asked["id"])).status == (
            ErasureRequestStatus.cancelled
        )


async def test_one_child_failing_does_not_stop_the_next_and_fails_the_job(
    client, tutor, student, world, monkeypatch
):
    sid, oid = student["user"]["id"], world["omar"]["user"]["id"]
    first = (await _ask(client, tutor["headers"], sid)).json()
    second = (await _ask(client, tutor["headers"], oid, "Omar")).json()
    await _make_due(first["id"])
    await _make_due(second["id"])
    real = erasure.erase_student

    async def flaky(session, request, now):
        if request.student_id == sid:
            raise RuntimeError("boom")
        return await real(session, request, now)

    monkeypatch.setattr(erasure, "erase_student", flaky)
    with pytest.raises(RuntimeError, match="failed"):
        await _sweep()
    async with async_session() as session:
        assert (await session.get(User, sid)).name == "Sara"
        assert (await session.get(User, oid)).name == "Deleted student"
        assert (await session.get(ErasureRequest, first["id"])).status == (
            ErasureRequestStatus.pending
        )


async def test_the_daily_retention_sweep_runs_the_erasure_step(client, tutor, student, world):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    async with async_session() as session:
        await retention.sweep_retention(session, {})
        assert (await session.get(User, sid)).deleted_at is not None


def test_the_blank_password_can_never_verify():
    assert verify_password("", erasure.NEVER_MATCHING_HASH) is False
    assert verify_password("!erased", erasure.NEVER_MATCHING_HASH) is False
    assert is_erasing(User(erasure_requested_at=NOW))
    assert is_erasing(User(deleted_at=NOW))
    assert not is_erasing(User())


# -------------------------------------------------- hidden while it is pending


async def _roster(client, tutor, group) -> list[str]:
    resp = await client.get(f"/api/v1/groups/{group['id']}", headers=tutor["headers"])
    return [m["name"] for m in resp.json()["members"]]


async def test_a_pending_child_drops_out_of_the_class_and_every_message(
    client, tutor, group, subject, student, world
):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    assert "Sara" in await _roster(client, tutor, group)
    await _ask(client, tutor["headers"], sid)
    assert await _roster(client, tutor, group) == ["Omar"]
    # Still reachable by the people who can undo it.
    assert (await client.get("/api/v1/students", headers=tutor["headers"])).status_code == 200
    assert "Sara" in [
        s["name"]
        for s in (await client.get("/api/v1/students", headers=tutor["headers"])).json()["items"]
    ]
    children = await client.get("/api/v1/me/children", headers=parent["headers"])
    assert [c["id"] for c in children.json()] == [sid]

    from app.services import weekly_send, weekly_send_facts

    async with async_session() as session:
        org = await org_id(session)
        recipients = {u.name for u in await weekly_send._recipients(session, org)}
        assert "Sara" not in recipients
        assert "Parent" not in recipients  # Sara's only parent
        assert "Omar" in recipients
        submission = await session.scalar(select(Submission).where(Submission.student_id == sid))
        await announce_marked_work(session, submission, subject["id"])
        await session.commit()
        assert (await session.scalars(select(Notification))).all() == []

        # A parent with a pending child and a sibling: one block, and no false
        # "dropped link" for the pending one.
        zed = await make_user(
            session, organization_id=org, role=UserRole.student, name="Zed", email="zed@example.com"
        )
        await link_parent(session, parent["user"]["id"], zed.id)
        await session.commit()
        window = (NOW - timedelta(days=7), NOW)
        facts = await weekly_send_facts.build_parent_facts(
            session, await session.get(User, parent["user"]["id"]), window
        )
        assert [c.child_name for c in facts.children] == ["Zed"]
        assert facts.dropped_links == 0


# --------------------------------------------------------------- nothing survives


STUDENT_COLUMNS = {"student_id", "user_id", "recipient_user_id", "matched_student_id"}
USERS_FK = "users.id"


async def _seed_child(
    client, tutor, group, subject, who: dict, parent: dict | None, tag: str, name: str, address: str
):
    """Everything the export tests seed for a child, and the rest of what Avora
    keeps. Returns the storage keys that belong to them."""
    sid = who["user"]["id"]
    tutor_id = tutor["user"]["id"]
    keys: list[str] = []
    async with async_session() as session:
        org = await org_id(session)
        submission = await session.scalar(select(Submission).where(Submission.student_id == sid))
        mark = await session.scalar(
            select(QuestionMark).where(QuestionMark.submission_id == submission.id)
        )
        category = await make_mistake_category(
            session, organization_id=org, subject_id=subject["id"], name=f"cat-{sid}"
        )
        await add_mistake(
            session,
            student_id=sid,
            mark_id=mark.id,
            category_id=category.id,
            severity=2,
            topic_ids=[subject["topic1"]],
            source=MistakeSource.ai,
        )
        # A replaced attempt: its pages live only inside the redo record.
        redo_key = storage.new_key(org, "application/pdf")
        await storage.get_storage().upload(
            redo_key, b"%PDF-1.4 OLD-" + tag.encode(), "application/pdf"
        )
        keys.append(redo_key)
        session.add_all(
            [
                MarkOverrideAudit(
                    question_mark_id=mark.id, old_marks=1, new_marks=2, changed_by_id=tutor_id
                ),
                CustomCriterionScoreAudit(
                    organization_id=org,
                    student_id=sid,
                    criterion_id=1,
                    old_score=1,
                    new_score=2,
                    changed_by_id=tutor_id,
                ),
                AiUsageEvent(
                    organization_id=org,
                    tutor_id=tutor_id,
                    student_id=sid,
                    feature=AiFeature.marking,
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=1.5,
                ),
                RemarkRequest(
                    question_mark_id=mark.id, requested_by_id=sid, reason=f"reason-{tag}"
                ),
                Report(
                    student_id=sid,
                    generated_by_id=tutor_id,
                    audience=ReportAudience.parent,
                    status=ReportStatus.ready,
                    title=f"report-{tag}",
                    content=f"content-{tag}",
                ),
                AttemptRedo(
                    organization_id=org,
                    work_id=submission.work_id,
                    student_id=sid,
                    allowed_by_id=tutor_id,
                    previous_submission_id=500_000 + sid,
                    record={"files": [{"path": redo_key}], "note": f"old-{tag}"},
                ),
                WeeklySend(
                    organization_id=org,
                    recipient_user_id=sid,
                    audience=WeeklySendAudience.student,
                    week_start=NOW - timedelta(days=7),
                    week_end=NOW,
                    facts={"student_name": f"{tag}-self", "classes": []},
                    paragraphs=[],
                ),
            ]
        )
        lesson = Lesson(organization_id=org, group_id=group["id"], date=date(2026, 9, 2))
        session.add(lesson)
        await session.flush()
        session.add(
            MeetingParticipant(
                organization_id=org,
                lesson_id=lesson.id,
                provider=MeetingProvider.zoom,
                display_name=f"guest-{tag}",
                email=address,
                matched_student_id=sid,
            )
        )
        await add_contact(session, sid, channel=NotificationChannel.email, address=address)
        await write_v2_snapshot(
            session,
            student_id=sid,
            subject_id=subject["id"],
            score=55.0,
            topics={subject["topic1"]: (60.0, FactorConfidence.medium)},
        )
        # One row of every other kind the sweep has to find.
        if (
            await session.scalar(select(StudentProfile.id).where(StudentProfile.student_id == sid))
            is None
        ):
            session.add(
                StudentProfile(student_id=sid, organization_id=org, parent_name=f"Parent of {name}")
            )
        if (
            await session.scalar(select(StudentSubject.id).where(StudentSubject.student_id == sid))
            is None
        ):
            session.add(StudentSubject(student_id=sid, subject_id=subject["id"]))
        paper_id = await session.scalar(select(PastPaper.id))
        session.add_all(
            [
                ParentCommunication(student_id=sid, tutor_id=tutor_id, body=f"Spoke about {name}"),
                LessonObservation(lesson_id=lesson.id, student_id=sid, body=f"{name} was quiet"),
                TutorObservation(tutor_id=tutor_id, student_id=sid, comment=f"{name} improving"),
                LessonAttendance(
                    organization_id=org,
                    lesson_id=lesson.id,
                    student_id=sid,
                    state=AttendanceState.present,
                    source=AttendanceSource.tutor,
                    recorded_at=NOW,
                ),
                Evidence(
                    student_id=sid,
                    topic_id=subject["topic1"],
                    source_type=EvidenceSource.homework,
                    score_pct=70.0,
                ),
                Narrative(
                    organization_id=org,
                    audience=NarrativeAudience.parent_student,
                    student_id=sid,
                    text=f"{name} is doing well",
                    prompt_version="t",
                    model="m",
                ),
                PastPaperAttempt(
                    past_paper_id=paper_id,
                    student_id=sid,
                    max_marks=10,
                    attempted_at=date(2026, 9, 1),
                ),
                GroupRemoval(
                    organization_id=org, group_id=group["id"], user_id=sid, removed_at=NOW
                ),
                NotificationPreference(
                    user_id=sid,
                    kind=NotificationKind.weekly_send,
                    channel=NotificationChannel.email,
                    enabled=False,
                ),
                DismissedPrompt(organization_id=org, user_id=sid, key="a-prompt"),
                ParentLinkRemoval(
                    organization_id=org,
                    link_id=777,
                    parent_id=None,
                    student_id=sid,
                    removed_by_id=tutor_id,
                    removed_by_role="tutor",
                ),
            ]
        )
        # A replaced attempt: gone from `submissions` now, but a parent was told
        # about it, and only the redo record still names it.
        old_paper = await make_past_paper(session, subject_id=subject["id"], organization_id=org)
        old = Submission(
            id=500_000 + sid,
            work_id=old_paper.work_id,
            student_id=sid,
            status=SubmissionStatus.finalized,
        )
        session.add(old)
        await session.flush()
        await session.refresh(old)  # loads `work`, which the announcement reads
        await announce_marked_work(session, old, subject["id"])
        await session.delete(old)
        await session.flush()
        await announce_marked_work(session, submission, subject["id"])
        files = await session.scalars(
            select(SubmissionFile.path).where(SubmissionFile.submission_id == submission.id)
        )
        keys += list(files.all())
        await session.commit()
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        from app.models import DataExport

        keys.append((await session.get(DataExport, export["id"])).storage_key)
    return keys


async def _break_a_key() -> None:
    """An insert that names a user who does not exist: refused only when the
    database enforces foreign keys."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO dismissed_prompts (organization_id, user_id, key) "
                "VALUES (1, 987654321, 'canary')"
            )
        )


async def _everything() -> dict[str, list[dict]]:
    out = {}
    async with engine.connect() as conn:
        for table in Base.metadata.sorted_tables:
            rows = (await conn.execute(select(table))).all()
            out[table.name] = [dict(r._mapping) for r in rows]
    return out


def _user_columns(table) -> list[str]:
    names = {fk.parent.name for fk in table.foreign_keys if fk.column.table.name == "users"}
    return sorted(
        names
        | (STUDENT_COLUMNS & {c.name for c in table.columns})
        | ({"suggested_student_id"} & {c.name for c in table.columns})
    )


@pytest.mark.parametrize("chunk", [None, 1])
async def test_after_the_sweep_nothing_about_the_child_is_left_and_a_classmate_is_untouched(
    client, tutor, group, subject, student, world, monkeypatch, chunk
):
    if chunk:
        monkeypatch.setattr(erasure, "ID_CHUNK", chunk)
    sid, oid = student["user"]["id"], world["omar"]["user"]["id"]
    # A name, address and username that collide with nothing else in the database,
    # so finding any of them afterwards can only mean a leftover.
    async with async_session() as session:
        row = await session.get(User, sid)
        row.name, row.email, row.username = CHILD, CHILD_EMAIL, CHILD_USERNAME
        await session.commit()
    sara_parent = await register_parent(client, tutor, student)
    omar_parent = await register_parent(
        client, tutor, world["omar"], email="omar-parent@example.com"
    )
    sara_keys = await _seed_child(
        client, tutor, group, subject, student, sara_parent, "sara", CHILD, CHILD_EMAIL
    ) + [world["sara_key"]]
    omar_keys = await _seed_child(
        client,
        tutor,
        group,
        subject,
        world["omar"],
        omar_parent,
        "omar",
        "Omar",
        "omar@example.com",
    ) + [world["omar_key"]]

    # A sibling of Sara's under the same parent, with an announcement of their
    # own: it must outlive Sara's.
    async with async_session() as session:
        org = await org_id(session)
        zed = await make_user(
            session, organization_id=org, role=UserRole.student, name="Zed", email="zed@example.com"
        )
        await link_parent(session, sara_parent["user"]["id"], zed.id)
        await settled_submission(
            session,
            subject_id=subject["id"],
            organization_id=org,
            student_id=zed.id,
            analysed=False,
            marks=1,
        )
        zed_submission = await session.scalar(
            select(Submission).where(Submission.student_id == zed.id)
        )
        await announce_marked_work(session, zed_submission, subject["id"])
        zed_id = zed.id
        session.add(
            WeeklySend(
                organization_id=org,
                recipient_user_id=sara_parent["user"]["id"],
                audience=WeeklySendAudience.parent,
                week_start=NOW - timedelta(days=7),
                week_end=NOW,
                facts={
                    "children": [
                        {"child_name": CHILD, "child_id": sid, "classes": []},
                        {"child_name": "Zed", "child_id": zed.id, "classes": []},
                    ],
                    "dropped_links": 0,
                },
                paragraphs=[
                    {"about": CHILD, "child_id": sid, "text": f"{CHILD} did well"},
                    {"about": "Zed", "child_id": zed.id, "text": "Zed did well"},
                ],
            )
        )
        await session.commit()
        omar_before = (await data_export.collect(session, await session.get(User, oid)))[0][
            "tables"
        ]
        omar_notes = await _everything()
        omar_notifications = sorted(
            n["id"]
            for n in omar_notes["notifications"]
            if n["recipient_user_id"] in (oid, omar_parent["user"]["id"])
        )

    asked = (await _ask(client, tutor["headers"], sid, CHILD)).json()
    await _make_due(asked["id"])

    # Every table the sweep claims to wipe or anonymise must have something of the
    # child's in it now, or "nothing is left" proves nothing about that table.
    seeded = await _everything()
    # The replaced attempt's announcement to the parent is really there to be found.
    old_key = f"marked_work:{500_000 + sid}:{sara_parent['user']['id']}"
    assert old_key in {n["idempotency_key"] for n in seeded["notifications"]}
    child_submissions = [r["id"] for r in seeded["submissions"] if r["student_id"] == sid]
    child_submissions.append(500_000 + sid)
    marks = [r["id"] for r in seeded["question_marks"] if r["submission_id"] in child_submissions]
    mistakes = [r["id"] for r in seeded["mistakes"] if r["student_id"] == sid]
    unseeded = []
    for table in sorted(erasure.ERASED | set(erasure.ANONYMISED)):
        rows = seeded[table]
        if table == "users":
            hits = [r for r in rows if r["id"] == sid]
        elif table in ("question_marks", "submission_files"):
            hits = [r for r in rows if r["submission_id"] in child_submissions]
        elif table == "mistake_topics":
            hits = [r for r in rows if r["mistake_id"] in mistakes]
        elif table == "mark_override_audit":
            hits = [r for r in rows if r["question_mark_id"] in marks]
        else:
            columns = _user_columns(Base.metadata.tables[table])
            hits = [r for r in rows if any(r[c] == sid for c in columns)]
        if not hits and table not in UNSEEDED:
            unseeded.append(table)
        assert not (hits and table in UNSEEDED), f"{table} is seeded now; drop it from UNSEEDED"
    assert not unseeded, f"seed something of the child's in {unseeded}, or list them in UNSEEDED"

    # Real foreign keys, as Postgres has: SQLite is told to enforce them now, so
    # a wrong order fails here and not only in CI's Postgres job. Proved to be on,
    # not assumed: a statement that breaks a key must be refused.
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar() == 1
        with pytest.raises(IntegrityError):
            await _break_a_key()
        async with async_session() as session:
            await retention.sweep_retention(session, {})
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA foreign_keys=OFF"))

    after = await _everything()
    # Running it again is harmless.
    assert await _sweep() == 0
    assert await _everything() == after

    # (a) no key to the child anywhere but the users row and the audit request
    for table in Base.metadata.sorted_tables:
        if table.name in ("users", "erasure_requests"):
            continue
        for column in _user_columns(table):
            hits = [r for r in after[table.name] if r[column] == sid]
            assert not hits, f"{table.name}.{column} still points at the child"
    assert not [u for u in after["users"] if u["created_by_id"] == sid]

    # (b) neither the name nor the address in any row of any table
    dump = json.dumps(after, default=str).lower()
    for needle in (CHILD.lower(), "zephyrine", "quillfeather", CHILD_EMAIL, CHILD_USERNAME):
        assert needle not in dump, needle
    assert "note-about-sara" not in dump
    assert "zed" in dump  # the sibling's block survived
    # And no stored record still names the child by id or points at their work,
    # in any table that is not kept on purpose.
    ids = "|".join(str(i) for i in child_submissions)
    pattern = re.compile(rf'"(student_id|child_id)": {sid}\b|"submission_id": ({ids})\b')
    for table, rows in after.items():
        if table in erasure.KEPT or table == "users":
            continue
        assert not pattern.search(json.dumps(rows, default=str)), f"{table} still names the child"

    # (c) every stored file of the child is gone, and nothing is still owed
    for key in sara_keys:
        assert not await storage.get_storage().exists(key), key
    for key in omar_keys:
        assert await storage.get_storage().exists(key), key
    request = next(r for r in after["erasure_requests"] if r["id"] == asked["id"])
    assert request["status"] == ErasureRequestStatus.done
    assert request["pending_paths"] is None
    assert request["completed_at"] is not None
    async with engine.connect() as conn:
        # SQL NULL, not the JSON value null: the next sweep must not pick it up.
        assert (
            await conn.execute(
                text("SELECT pending_paths IS NULL FROM erasure_requests WHERE id = :i"),
                {"i": asked["id"]},
            )
        ).scalar() == 1

    # (d) the classmate is untouched
    async with async_session() as session:
        omar_after = (await data_export.collect(session, await session.get(User, oid)))[0]["tables"]
    assert omar_after == omar_before
    assert (
        sorted(
            n["id"]
            for n in after["notifications"]
            if n["recipient_user_id"] in (oid, omar_parent["user"]["id"])
        )
        == omar_notifications
    )

    # The sibling's own announcement to the shared parent survives; Sara's does not.
    kept = [
        n for n in after["notifications"] if n["recipient_user_id"] == sara_parent["user"]["id"]
    ]
    assert len(kept) == 1
    assert f"marked_work:{zed_submission.id}:" in kept[0]["idempotency_key"]
    (send,) = [
        s for s in after["weekly_sends"] if s["recipient_user_id"] == sara_parent["user"]["id"]
    ]
    assert [c["child_id"] for c in send["facts"]["children"]] == [zed_id]
    assert [p["child_id"] for p in send["paragraphs"]] == [zed_id]

    # (e) the tutor's own records stay, with their links cut
    audit = after["mark_override_audit"]
    assert any(a["question_mark_id"] is None for a in audit)
    assert any(a["question_mark_id"] is not None for a in audit)  # Omar's
    assert any(a["student_id"] is None for a in after["custom_criterion_score_audit"])
    usage = [a for a in after["ai_usage_events"] if a["student_id"] is None]
    assert len(usage) == 1
    assert [a for a in after["ai_usage_events"] if a["student_id"] == oid]

    # (f) the users row is the blank placeholder and cannot sign in
    (row,) = [u for u in after["users"] if u["id"] == sid]
    assert row["name"] == "Deleted student"
    assert row["email"] is None
    assert row["username"] is None
    assert row["role"] == UserRole.student
    assert row["deleted_at"] is not None
    assert not verify_password("password123", row["password_hash"])
    assert (await _login(client, CHILD_EMAIL)).status_code == 401
    assert (await _login(client, CHILD_USERNAME)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=student["headers"])).status_code == 401

    # The placeholder is in no listing, and not reachable by anyone.
    assert await _roster(client, tutor, group) == ["Omar"]
    listed = (await client.get("/api/v1/students", headers=tutor["headers"])).json()["items"]
    assert "Deleted student" not in [s["name"] for s in listed]
    assert (await client.get("/api/v1/me/children", headers=sara_parent["headers"])).json() != []
    children = (await client.get("/api/v1/me/children", headers=sara_parent["headers"])).json()
    assert [c["id"] for c in children] == [zed_id]
    admin = await _admin(await _org_of(tutor))
    assert (await _ask(client, admin["headers"], sid, "Deleted student")).status_code == 404
    assert (await client.get(_url(sid), headers=admin["headers"])).status_code == 404


async def test_notifications_are_matched_by_what_they_say_not_by_a_shared_name(
    client, tutor, group, subject, student, world
):
    """A parent of two children called Sara: only the one erased loses their
    announcements."""
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    async with async_session() as session:
        org = await org_id(session)
        namesake = await make_user(
            session,
            organization_id=org,
            role=UserRole.student,
            name="Sara",
            email="sara2@example.com",
        )
        await link_parent(session, parent["user"]["id"], namesake.id)
        await settled_submission(
            session,
            subject_id=subject["id"],
            organization_id=org,
            student_id=namesake.id,
            analysed=False,
            marks=1,
        )
        for owner in (sid, namesake.id):
            submission = await session.scalar(
                select(Submission).where(Submission.student_id == owner)
            )
            await announce_marked_work(session, submission, subject["id"])
        namesake_submission = await session.scalar(
            select(Submission).where(Submission.student_id == namesake.id)
        )
        await session.commit()
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    await _sweep()
    async with async_session() as session:
        mine = (
            await session.scalars(
                select(Notification).where(Notification.recipient_user_id == parent["user"]["id"])
            )
        ).all()
    assert [n.idempotency_key for n in mine] == [
        f"marked_work:{namesake_submission.id}:{parent['user']['id']}"
    ]


# ---------------------------------------------------------------- the guard


def _keyed_tables() -> set[str]:
    keyed = set()
    for table in Base.metadata.tables.values():
        names = {c.name for c in table.columns}
        if any(fk.column.table.name == "users" for fk in table.foreign_keys) or names & (
            STUDENT_COLUMNS | {"suggested_student_id"}
        ):
            keyed.add(table.name)
    return keyed


def test_every_table_holding_a_key_to_a_user_is_decided():
    """A new table keyed to a user must be erased, anonymised, kept or marked
    staff-only on purpose, and in exactly one of them."""
    groups = [erasure.ERASED, set(erasure.ANONYMISED), set(erasure.KEPT), set(erasure.STAFF_ONLY)]
    for i, one in enumerate(groups):
        for other in groups[i + 1 :]:
            assert not one & other, sorted(one & other)
    decided = set().union(*groups)
    undecided = _keyed_tables() - decided
    assert not undecided, f"decide what erasure does with: {sorted(undecided)}"
    assert not decided - set(Base.metadata.tables), "listed but not a table"

    # And whatever hangs off a table that is erased.
    erased = erasure.ERASED
    hanging = {
        table.name
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name in erased and table.name not in decided
    }
    assert not hanging, f"hangs off an erased table; decide it: {sorted(hanging)}"


def test_the_erase_order_never_deletes_a_row_something_later_still_points_at():
    """The order is pinned so a reshuffle is a decision. That it is *right* is
    proved by the sweep above, which runs with the database enforcing foreign
    keys (Postgres does; SQLite does not unless told)."""
    names = [step.__name__ for step in erasure.ERASE_ORDER]
    assert names == [
        "_unlink_audits",
        "_meeting_rows",
        "_marks_and_mistakes",
        "_submissions",
        "_the_rest",
        "_credentials",
        "_readers_of_the_child",
        "_queued_work",
        "_anonymise_user",
    ]
    assert names.index("_marks_and_mistakes") < names.index("_submissions")
    assert names.index("_unlink_audits") < names.index("_submissions")
    # The users row goes last, once nothing else needs the child's name.
    assert names[-1] == "_anonymise_user"
    assert names.index("_readers_of_the_child") < names.index("_anonymise_user")


async def test_a_wiped_child_is_a_404_for_a_parent_whose_link_was_cut(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    asked = (await _ask(client, parent["headers"], sid, parent=True)).json()
    assert (await client.get(_url(sid, parent=True), headers=parent["headers"])).json()[
        "id"
    ] == asked["id"]
    await _make_due(asked["id"])
    await _sweep()
    assert (await client.get(_url(sid, parent=True), headers=parent["headers"])).status_code == 404
    assert (
        await client.delete(_url(sid, parent=True), headers=parent["headers"])
    ).status_code == 404


# ----------------------------------------------------- review round 1: more proof


async def _outsiders(client, tutor, world) -> dict[str, tuple[dict, bool]]:
    """Everyone who must not be able to touch a child they have no claim on:
    (headers, goes through the parent routes)."""
    other_org = await register_other_tutor(client)
    stranger = await register_parent(client, tutor, world["omar"], email="stranger@example.com")
    async with async_session() as session:
        colleague = await make_user(
            session,
            organization_id=await _org_of(tutor),
            role=UserRole.tutor,
            name="Colleague",
            email="colleague2@example.com",
        )
        elsewhere = Organization(name="Elsewhere")
        session.add(elsewhere)
        await session.commit()
        colleague_headers = {
            "Authorization": f"Bearer {create_access_token(colleague.id, colleague.token_version)}"
        }
        elsewhere_id = elsewhere.id
    foreign_admin = await _admin(elsewhere_id)
    return {
        "other org's tutor": (other_org["headers"], False),
        "colleague who does not teach the child": (colleague_headers, False),
        "foreign admin": (foreign_admin["headers"], False),
        "unlinked parent": (stranger["headers"], True),
    }


async def test_an_outsider_cannot_undo_a_pending_request(client, tutor, student, world):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    for who, (headers, is_parent) in (await _outsiders(client, tutor, world)).items():
        resp = await client.delete(_url(sid, parent=is_parent), headers=headers)
        assert resp.status_code == 404, who
    async with async_session() as session:
        assert (await session.get(ErasureRequest, asked["id"])).status == (
            ErasureRequestStatus.pending
        )
        assert (await session.get(User, sid)).erasure_requested_at is not None
    assert (await client.get(_url(sid), headers=tutor["headers"])).json()["id"] == asked["id"]


async def _announce_homework(session, parent_id: int, student_id: int, name: str, key_id: int):
    """What `announce_homework_set` leaves for a parent, with its real key."""
    org = await org_id(session)
    session.add(
        Notification(
            organization_id=org,
            recipient_user_id=parent_id,
            kind=NotificationKind.homework_set,
            template="avora_homework_set",
            params={"student_name": name, "subject_name": "Chemistry", "due_date": "soon"},
            link_path="/parent",
            idempotency_key=f"homework_set:{key_id}:{student_id}:{parent_id}",
        )
    )


async def test_a_parent_whose_access_was_ended_cannot_act_but_their_messages_go(
    client, tutor, group, subject, student, world
):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    pid = parent["user"]["id"]
    async with async_session() as session:
        org = await org_id(session)
        submission = await session.scalar(select(Submission).where(Submission.student_id == sid))
        await announce_marked_work(session, submission, subject["id"])
        await _announce_homework(session, pid, sid, "Sara", 41)
        session.add(
            WeeklySend(
                organization_id=org,
                recipient_user_id=pid,
                audience=WeeklySendAudience.parent,
                week_start=NOW - timedelta(days=7),
                week_end=NOW,
                facts={"children": [{"child_name": "Sara", "child_id": sid, "classes": []}]},
                paragraphs=[{"about": "Sara", "child_id": sid, "text": "Sara is well"}],
            )
        )
        # The link is ended: a removal row remembers who the parent was.
        link = await session.scalar(select(ParentLink).where(ParentLink.parent_id == pid))
        session.add(
            ParentLinkRemoval(
                organization_id=org,
                link_id=link.id,
                parent_id=pid,
                student_id=sid,
                removed_by_id=pid,
                removed_by_role="parent",
            )
        )
        await session.delete(link)
        await session.commit()

    assert (await _ask(client, parent["headers"], sid, parent=True)).status_code == 404
    assert (
        await client.delete(_url(sid, parent=True), headers=parent["headers"])
    ).status_code == 404
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    await _sweep()
    async with async_session() as session:
        assert (
            await session.scalars(select(Notification).where(Notification.recipient_user_id == pid))
        ).all() == []
        assert (
            await session.scalars(select(WeeklySend).where(WeeklySend.recipient_user_id == pid))
        ).all() == []


async def _job(status: JobStatus, **payload) -> int:
    async with async_session() as session:
        job = Job(type="a_test_job", payload=payload, status=status)
        session.add(job)
        await session.commit()
        return job.id


async def test_jobs_naming_the_child_are_removed_and_others_are_left(
    client, tutor, subject, student, world
):
    sid, oid = student["user"]["id"], world["omar"]["user"]["id"]
    old_id = 600_000
    async with async_session() as session:
        submission = await session.scalar(select(Submission).where(Submission.student_id == sid))
        omar_sub = await session.scalar(select(Submission).where(Submission.student_id == oid))
        session.add(
            AttemptRedo(
                organization_id=await org_id(session),
                work_id=submission.work_id,
                student_id=sid,
                allowed_by_id=tutor["user"]["id"],
                previous_submission_id=old_id,
                record={},
            )
        )
        await session.commit()
        sub_id, omar_sub_id = submission.id, omar_sub.id
    doomed = [
        await _job(JobStatus.pending, student_id=sid),
        await _job(JobStatus.pending, submission_id=sub_id),
        await _job(JobStatus.pending, submission_id=old_id),
    ]
    kept = [
        await _job(JobStatus.pending, student_id=oid),
        await _job(JobStatus.pending, submission_id=omar_sub_id),
        await _job(JobStatus.done, student_id=sid),
    ]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    assert await _sweep() == 1
    async with async_session() as session:
        left = {j.id for j in (await session.scalars(select(Job))).all()}
    assert not set(doomed) & left
    assert set(kept) <= left


async def test_a_job_running_for_the_child_stops_the_wipe_and_it_is_retried(
    client, tutor, student, world, caplog
):
    sid = student["user"]["id"]
    running = await _job(JobStatus.running, student_id=sid)
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    with pytest.raises(RuntimeError, match="failed"):
        await _sweep()
    assert "child has running work" in caplog.text
    async with async_session() as session:
        # Rolled back whole: nothing of the child went.
        assert (await session.get(User, sid)).name == "Sara"
        assert (await session.get(ErasureRequest, asked["id"])).status == (
            ErasureRequestStatus.pending
        )
        assert (await session.scalars(select(TutorNote).where(TutorNote.student_id == sid))).all()
        job = await session.get(Job, running)
        job.status = JobStatus.done
        await session.commit()
    assert await _sweep() == 1


async def test_the_parts_of_a_parents_messages_are_matched_each_by_what_it_says(
    client, tutor, subject, student, world
):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    pid = parent["user"]["id"]
    async with async_session() as session:
        org = await org_id(session)
        # Only child: the send goes, and the message that points at it.
        only = WeeklySend(
            organization_id=org,
            recipient_user_id=pid,
            audience=WeeklySendAudience.parent,
            week_start=NOW - timedelta(days=7),
            week_end=NOW,
            facts={"children": [{"child_name": "Sara", "child_id": sid, "classes": []}]},
            paragraphs=[],
        )
        session.add(only)
        await session.flush()
        session.add(
            Notification(
                organization_id=org,
                recipient_user_id=pid,
                kind=NotificationKind.weekly_send,
                template="t",
                params={"whose": "Sara's"},
                link_path=f"/weekly/{only.id}",
                idempotency_key=f"weekly_send:{pid}:x",
            )
        )
        # A send written before ids existed: found by name, and the sibling's
        # block beside it is left.
        legacy = WeeklySend(
            organization_id=org,
            recipient_user_id=pid,
            audience=WeeklySendAudience.parent,
            week_start=NOW - timedelta(days=14),
            week_end=NOW - timedelta(days=7),
            facts={
                "children": [
                    {"child_name": "Sara", "classes": []},
                    {"child_name": "Brother", "classes": []},
                ]
            },
            paragraphs=[
                {"about": "Sara", "text": "Sara legacy"},
                {"about": "Brother", "text": "Brother legacy"},
            ],
        )
        session.add(legacy)
        # A message with no key that says anything: its params fall back to the name.
        for key, name in (("legacy-a", "Sara"), ("legacy-b", "Brother")):
            session.add(
                Notification(
                    organization_id=org,
                    recipient_user_id=pid,
                    kind=NotificationKind.marked_work_ready,
                    template="t",
                    params={"student_name": name, "subject_name": "Chemistry"},
                    link_path="/parent",
                    idempotency_key=key,
                )
            )
        # A namesake sibling: same name, own id in the key.
        await _announce_homework(session, pid, 9999, "Sara", 7)
        await _announce_homework(session, pid, sid, "Sara", 7)
        await session.commit()
        legacy_id = legacy.id
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    await _sweep()
    async with async_session() as session:
        sends = (
            await session.scalars(select(WeeklySend).where(WeeklySend.recipient_user_id == pid))
        ).all()
        assert [s.id for s in sends] == [legacy_id]
        assert [c["child_name"] for c in sends[0].facts["children"]] == ["Brother"]
        assert [p["about"] for p in sends[0].paragraphs] == ["Brother"]
        keys = sorted(
            n.idempotency_key
            for n in (
                await session.scalars(
                    select(Notification).where(Notification.recipient_user_id == pid)
                )
            ).all()
        )
        assert keys == ["homework_set:7:9999:" + str(pid), "legacy-b"]


def test_a_name_typed_with_a_combining_accent_matches():
    assert erasure.names_match("Zoë Ali", "Zoë  ali")
    assert erasure.names_match("ZOË", "zoë")
    assert not erasure.names_match("Zoe", "Zoë")


async def test_a_name_in_either_form_works_through_the_route(client, tutor, student, world):
    sid = student["user"]["id"]
    async with async_session() as session:
        child = await session.get(User, sid)
        child.name = "Zoë"
        await session.commit()
    assert (await _ask(client, tutor["headers"], sid, "Zoë")).status_code == 202


async def test_a_request_that_names_no_student_is_cancelled_not_retried(
    client, tutor, student, world, caplog
):
    async with async_session() as session:
        request = ErasureRequest(
            organization_id=await org_id(session),
            student_id=tutor["user"]["id"],
            requested_by_id=tutor["user"]["id"],
            requested_role=erasure.ErasureRequesterRole.tutor,
            scheduled_for=NOW - timedelta(minutes=1),
        )
        session.add(request)
        await session.commit()
        rid = request.id
    assert await _sweep() == 0
    assert "names no student" in caplog.text
    async with async_session() as session:
        row = await session.get(ErasureRequest, rid)
        assert row.status == ErasureRequestStatus.cancelled
        assert row.cancelled_at is not None
        assert (await session.get(User, tutor["user"]["id"])).deleted_at is None
    assert await _sweep() == 0


async def test_owed_files_fail_the_job_loudly_and_never_mask_other_failures(
    client, tutor, student, world, monkeypatch, caplog
):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    page = world["sara_key"]
    real = storage.delete_file

    async def stuck(key: str) -> None:
        if key == page:
            raise OSError("disk busy")
        await real(key)

    monkeypatch.setattr(storage, "delete_file", stuck)
    with pytest.raises(RuntimeError, match="still owed"):
        await _sweep()
    # The count and the request, never the key (it is an internal address).
    assert f"[{asked['id']}]" in caplog.text
    assert page not in [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]

    # An exception inside the file step is a failure too, not silence.
    async def broken(session):
        raise ConnectionError("db went away")

    monkeypatch.setattr(erasure, "_delete_pending_files", broken)
    with pytest.raises(RuntimeError, match="deleting owed files broke"):
        await _sweep()
    monkeypatch.undo()
    assert await _sweep() == 0
    assert not await storage.get_storage().exists(page)
    async with async_session() as session:
        assert (await session.get(ErasureRequest, asked["id"])).pending_paths is None
    # A key already gone is not an error.
    async with async_session() as session:
        request = await session.get(ErasureRequest, asked["id"])
        request.pending_paths = [page]
        await session.commit()
    assert await _sweep() == 0
    async with async_session() as session:
        assert (await session.get(ErasureRequest, asked["id"])).pending_paths is None


async def test_a_pending_or_wiped_child_cannot_be_put_back_in_a_class_or_given_a_parent(
    client, tutor, group, student, world
):
    sid = student["user"]["id"]
    code = (
        await client.post(f"/api/v1/students/{sid}/parent-code", headers=tutor["headers"])
    ).json()["code"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    members = f"/api/v1/groups/{group['id']}/members"
    assert (
        await client.post(members, json={"student_id": sid}, headers=tutor["headers"])
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/students/{sid}/parent-code", headers=tutor["headers"])
    ).status_code == 404
    # A code made earlier is no more usable than one that never existed.
    assert (await client.get(f"/api/v1/auth/invites/{code}")).status_code == 404
    body = {"link_code": code, "name": "New", "email": "new@example.com", "password": "password123"}
    assert (await client.post("/api/v1/auth/register/parent", json=body)).status_code == 404
    existing = await register_parent(client, tutor, world["omar"], email="p4@example.com")
    assert (
        await client.post(
            "/api/v1/auth/join", json={"invite_code": code}, headers=existing["headers"]
        )
    ).status_code == 404
    async with async_session() as session:
        assert (
            await session.scalars(select(ParentLink).where(ParentLink.student_id == sid))
        ).all() == []

    # Undone, the same code works again.
    assert (await client.delete(_url(sid), headers=tutor["headers"])).status_code == 204
    assert (await client.get(f"/api/v1/auth/invites/{code}")).status_code == 200
    assert (
        await client.post(members, json={"student_id": sid}, headers=tutor["headers"])
    ).status_code == 204
    # Wiped: gone for good.
    await _ask(client, tutor["headers"], sid)
    async with async_session() as session:
        request = await erasure.pending_request(session, sid)
        rid = request.id
    await _make_due(rid)
    await _sweep()
    assert (
        await client.post(members, json={"student_id": sid}, headers=tutor["headers"])
    ).status_code == 404
    assert asked["id"] != rid


async def test_a_wiped_child_is_not_on_a_roster_even_if_a_membership_survived(
    client, tutor, group, student, world
):
    sid = student["user"]["id"]
    async with async_session() as session:
        child = await session.get(User, sid)
        child.deleted_at = NOW
        await session.commit()
    assert await _roster(client, tutor, group) == ["Omar"]


async def test_a_cancel_is_logged_with_who_cancelled_and_who_asked(
    client, tutor, student, world, caplog
):
    import logging

    caplog.set_level(logging.INFO, logger="app.services.erasure")
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    asked = (await _ask(client, tutor["headers"], sid)).json()
    assert (
        await client.delete(_url(sid, parent=True), headers=parent["headers"])
    ).status_code == 204
    line = next(r.getMessage() for r in caplog.records if "cancelled by" in r.getMessage())
    assert f"erasure {asked['id']}" in line
    assert f"cancelled by user {parent['user']['id']} (parent)" in line
    assert f"requested by user {tutor['user']['id']} (tutor)" in line


async def test_a_meeting_row_with_the_childs_address_goes_only_inside_their_organization(
    client, tutor, group, student, world
):
    sid = student["user"]["id"]
    async with async_session() as session:
        org = await org_id(session)
        elsewhere = Organization(name="Elsewhere 2")
        session.add(elsewhere)
        lesson = Lesson(organization_id=org, group_id=group["id"], date=date(2026, 9, 3))
        session.add(lesson)
        await session.flush()
        for organization_id, display in ((org, "own"), (elsewhere.id, "foreign")):
            session.add(
                MeetingParticipant(
                    organization_id=organization_id,
                    lesson_id=lesson.id,
                    provider=MeetingProvider.zoom,
                    display_name=display,
                    email="Sara@Example.com",
                )
            )
        await session.commit()
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    await _sweep()
    async with async_session() as session:
        left = (await session.scalars(select(MeetingParticipant.display_name))).all()
    assert left == ["foreign"]


async def test_after_an_undo_what_the_child_held_before_stays_dead(client, tutor, student, world):
    sid = student["user"]["id"]
    before = await _login(client)
    refresh = before.cookies.get("igcse_refresh")
    old_access = {"Authorization": f"Bearer {before.json()['tokens']['access_token']}"}
    await _ask(client, tutor["headers"], sid)
    assert (await client.delete(_url(sid), headers=tutor["headers"])).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=old_access)).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers=student["headers"])).status_code == 401
    client.cookies.clear()
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    ).status_code == 401
    assert (await _login(client)).status_code == 200


async def test_the_student_route_only_ever_means_a_student(client, tutor, student, world):
    parent = await register_parent(client, tutor, student)
    for who in (tutor["user"]["id"], parent["user"]["id"]):
        assert (await _ask(client, tutor["headers"], who, "Parent")).status_code == 404
        assert (await _ask(client, tutor["headers"], who, "Test Tutor")).status_code == 404
    assert (
        await _ask(client, parent["headers"], parent["user"]["id"], "Parent", parent=True)
    ).status_code == 404


async def test_a_second_request_that_loses_the_race_returns_the_one_that_won(
    client, tutor, student, world, monkeypatch
):
    sid = student["user"]["id"]
    first = (await _ask(client, tutor["headers"], sid)).json()
    real = erasure.pending_request
    calls = []

    async def blind_once(session, student_id):
        calls.append(student_id)
        return None if len(calls) == 1 else await real(session, student_id)

    monkeypatch.setattr(erasure, "pending_request", blind_once)
    async with async_session() as session:
        student_row = await session.get(User, sid)
        tutor_row = await session.get(User, tutor["user"]["id"])
        found = await erasure.request_erasure(session, student_row, tutor_row, "Sara")
        assert found.id == first["id"]
    assert len(calls) == 2
    async with async_session() as session:
        assert len((await session.scalars(select(ErasureRequest))).all()) == 1


async def test_a_wipe_that_fails_late_leaves_the_child_whole(
    client, tutor, subject, student, world, monkeypatch
):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    async with async_session() as session:
        submission = await session.scalar(select(Submission).where(Submission.student_id == sid))
        await announce_marked_work(session, submission, subject["id"])
        await session.commit()
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])

    async def boom(scope):
        raise RuntimeError("late failure")

    monkeypatch.setattr(erasure, "ERASE_ORDER", (*erasure.ERASE_ORDER[:-1], boom))
    with pytest.raises(RuntimeError, match="failed"):
        await _sweep()
    async with async_session() as session:
        assert (await session.get(User, sid)).name == "Sara"
        assert (await session.get(User, sid)).deleted_at is None
        assert (await session.scalars(select(Submission).where(Submission.student_id == sid))).all()
        assert (await session.scalars(select(TutorNote).where(TutorNote.student_id == sid))).all()
        assert (
            await session.scalars(
                select(Notification).where(Notification.recipient_user_id == parent["user"]["id"])
            )
        ).all()
        row = await session.get(ErasureRequest, asked["id"])
        assert row.status == ErasureRequestStatus.pending
    async with engine.connect() as conn:
        assert (
            await conn.execute(
                text("SELECT pending_paths IS NULL FROM erasure_requests WHERE id = :i"),
                {"i": asked["id"]},
            )
        ).scalar() == 1
    assert await storage.get_storage().exists(world["sara_key"])


#: Which side of the child each key to a user is on. A new column on a table that
#: is already decided must be put in one of the two, so a new student-side key
#: cannot slip past a table-level decision.
CHILD_COLUMNS = {
    ("ai_usage_events", "student_id"),
    ("assessment_scores", "student_id"),
    ("attempt_redos", "student_id"),
    ("contact_points", "confirmed_by_id"),
    ("contact_points", "user_id"),
    ("custom_criterion_score_audit", "student_id"),
    ("custom_criterion_scores", "student_id"),
    ("data_exports", "student_id"),
    ("dismissed_prompts", "user_id"),
    ("erasure_requests", "student_id"),
    ("evidence", "student_id"),
    ("factor_evaluations", "student_id"),
    ("group_members", "student_id"),
    ("group_removals", "user_id"),
    ("invites", "created_by_id"),
    ("invites", "student_id"),
    ("lesson_attendance", "student_id"),
    ("lesson_observations", "student_id"),
    ("meeting_participants", "matched_student_id"),
    ("meeting_participants", "suggested_student_id"),
    ("mistakes", "student_id"),
    ("mock_openings", "student_id"),
    ("narratives", "student_id"),
    ("notification_preferences", "user_id"),
    ("notifications", "recipient_user_id"),
    ("parent_communications", "student_id"),
    ("parent_link_removals", "removed_by_id"),
    ("parent_link_removals", "student_id"),
    ("parent_links", "student_id"),
    ("past_paper_attempts", "student_id"),
    ("readiness_snapshots", "student_id"),
    ("refresh_sessions", "user_id"),
    ("remark_requests", "requested_by_id"),
    ("reports", "student_id"),
    ("student_profiles", "student_id"),
    ("student_subjects", "student_id"),
    ("submissions", "student_id"),
    ("tutor_notes", "student_id"),
    ("tutor_observations", "student_id"),
    ("weekly_sends", "recipient_user_id"),
}
STAFF_COLUMNS = {
    ("ai_usage_events", "tutor_id"),
    ("assessments", "tutor_id"),
    ("attempt_redos", "allowed_by_id"),
    ("booklets", "tutor_id"),
    ("classifieds", "tutor_id"),
    ("custom_criteria", "created_by_id"),
    ("custom_criterion_scores", "updated_by_id"),
    ("data_exports", "requested_by_id"),
    ("erasure_requests", "requested_by_id"),
    ("google_accounts", "tutor_id"),
    ("group_resources", "tutor_id"),
    ("groups", "deleted_by_id"),
    ("groups", "tutor_id"),
    ("knowledge_entries", "tutor_id"),
    ("lesson_attendance", "recorded_by_id"),
    ("lesson_meeting_imports", "requested_by_id"),
    ("mark_override_audit", "changed_by_id"),
    ("meeting_connections", "tutor_id"),
    ("meeting_participants", "resolved_by_id"),
    ("mistake_revision_audit", "changed_by_id"),
    ("mocks", "tutor_id"),
    ("parent_communications", "tutor_id"),
    ("parent_link_removals", "parent_id"),
    ("parent_links", "parent_id"),
    ("past_papers", "tutor_id"),
    ("plan_slots", "cancelled_by_id"),
    ("readiness_weights", "tutor_id"),
    ("reports", "generated_by_id"),
    ("setup_acknowledgements", "acknowledged_by_id"),
    ("submissions", "finalized_by_id"),
    ("syllabus_uploads", "tutor_id"),
    ("taught_before_topics", "created_by_id"),
    ("teaching_plans", "accepted_by_id"),
    ("tutor_notes", "tutor_id"),
    ("tutor_observations", "tutor_id"),
    ("users", "created_by_id"),
}


def test_every_key_to_a_user_is_on_a_named_side_of_the_child():
    actual = {
        (table.name, column)
        for table in Base.metadata.tables.values()
        for column in _user_columns(table)
    }
    assert not CHILD_COLUMNS & STAFF_COLUMNS
    assert actual == CHILD_COLUMNS | STAFF_COLUMNS, (
        f"decide, child or staff: {sorted(actual - CHILD_COLUMNS - STAFF_COLUMNS)}; "
        f"stale: {sorted((CHILD_COLUMNS | STAFF_COLUMNS) - actual)}"
    )
    # A table declared staff-only can have no child-side column at all.
    assert not {t for t, _ in CHILD_COLUMNS} & set(erasure.STAFF_ONLY)


def test_no_message_a_tutor_or_admin_receives_carries_a_childs_name():
    """The kinds sent to staff hold counts, a class's name or the tutor's own
    name; only the parent-facing kinds take a student's name, and those are
    scrubbed by key. A new kind with a name in it must be decided here."""
    from app.services.notifications.templates import TEMPLATES

    named = {k for k, t in TEMPLATES.items() if {"student_name", "child_name"} & set(t.params)}
    assert named == {
        NotificationKind.homework_set,
        NotificationKind.homework_due,
        NotificationKind.marked_work_ready,
    }
