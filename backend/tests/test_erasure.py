"""Erasing a child's data (launch audit P-3, part 3): who may ask, the sign-in
lock, the 14-day undo, and that after the sweep nothing about the child is left
anywhere while a classmate is untouched."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.api.deps import is_erasing
from app.db import async_session, engine
from app.models import (
    AiFeature,
    AiUsageEvent,
    AttemptRedo,
    Base,
    CustomCriterionScoreAudit,
    ErasureRequest,
    ErasureRequestStatus,
    Lesson,
    MarkOverrideAudit,
    MeetingParticipant,
    MistakeSource,
    Notification,
    NotificationChannel,
    QuestionMark,
    RemarkRequest,
    Report,
    ReportAudience,
    ReportStatus,
    Submission,
    SubmissionFile,
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
        assert await erasure.cancel_erasure(session, student_row)
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
        await real(session, request, now)

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
    assert verify_password("", erasure.UNUSABLE_PASSWORD) is False
    assert verify_password("!erased", erasure.UNUSABLE_PASSWORD) is False
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


async def _seed_child(client, tutor, group, subject, who: dict, parent: dict | None, tag: str):
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
                    previous_submission_id=987654,
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
                email=f"{tag}@example.com",
                matched_student_id=sid,
            )
        )
        await add_contact(
            session, sid, channel=NotificationChannel.email, address=f"{tag}@example.com"
        )
        await write_v2_snapshot(
            session, student_id=sid, subject_id=subject["id"], score=55.0, topics={}
        )
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
    sara_parent = await register_parent(client, tutor, student)
    omar_parent = await register_parent(
        client, tutor, world["omar"], email="omar-parent@example.com"
    )
    sara_keys = await _seed_child(client, tutor, group, subject, student, sara_parent, "sara") + [
        world["sara_key"]
    ]
    omar_keys = await _seed_child(
        client, tutor, group, subject, world["omar"], omar_parent, "omar"
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
                        {"child_name": "Sara", "child_id": sid, "classes": []},
                        {"child_name": "Zed", "child_id": zed.id, "classes": []},
                    ],
                    "dropped_links": 0,
                },
                paragraphs=[
                    {"about": "Sara", "child_id": sid, "text": "Sara did well"},
                    {"about": "Zed", "child_id": zed.id, "text": "Zed did well"},
                ],
            )
        )
        await session.commit()
        omar_before = (await data_export.collect(session, await session.get(User, oid)))[0][
            "tables"
        ]
        name, email = "Sara", "sara@example.com"
        omar_notes = await _everything()
        omar_notifications = sorted(
            n["id"]
            for n in omar_notes["notifications"]
            if n["recipient_user_id"] in (oid, omar_parent["user"]["id"])
        )

    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    # Real foreign keys, as Postgres has: SQLite is told to enforce them now, so
    # a wrong order fails here and not only in CI's Postgres job.
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
    try:
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
    assert name.lower() not in dump
    assert email not in dump
    assert "note-about-sara" not in dump
    assert "zed" in dump  # the sibling's block survived

    # (c) every stored file of the child is gone, and nothing is still owed
    for key in sara_keys:
        assert not await storage.get_storage().exists(key), key
    for key in omar_keys:
        assert await storage.get_storage().exists(key), key
    request = next(r for r in after["erasure_requests"] if r["id"] == asked["id"])
    assert request["status"] == ErasureRequestStatus.done
    assert request["pending_paths"] is None
    assert request["completed_at"] is not None

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
    assert row["email"] is None and row["username"] is None
    assert row["role"] == UserRole.student
    assert row["deleted_at"] is not None
    assert not verify_password("password123", row["password_hash"])
    assert (await _login(client)).status_code == 401
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


async def test_a_file_that_will_not_delete_stays_owed_until_the_next_sweep(
    client, tutor, group, subject, student, world, monkeypatch
):
    sid = student["user"]["id"]
    asked = (await _ask(client, tutor["headers"], sid)).json()
    await _make_due(asked["id"])
    page = world["sara_key"]
    real = storage.delete_file
    calls = []

    async def fails_once(key: str) -> None:
        calls.append(key)
        if key == page and calls.count(page) == 1:
            raise OSError("disk busy")
        await real(key)

    monkeypatch.setattr(storage, "delete_file", fails_once)
    assert await _sweep() == 1
    async with async_session() as session:
        row = await session.get(ErasureRequest, asked["id"])
        assert row.status == ErasureRequestStatus.done
        assert row.pending_paths == [page]
    assert await storage.get_storage().exists(page)

    assert await _sweep() == 0
    assert not await storage.get_storage().exists(page)
    async with async_session() as session:
        assert (await session.get(ErasureRequest, asked["id"])).pending_paths is None

    # A key already gone is not an error either.
    async with async_session() as session:
        row = await session.get(ErasureRequest, asked["id"])
        row.pending_paths = [page]
        await session.commit()
    assert await _sweep() == 0
    async with async_session() as session:
        assert (await session.get(ErasureRequest, asked["id"])).pending_paths is None


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
