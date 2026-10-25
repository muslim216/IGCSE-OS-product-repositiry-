"""The second half of the child-data export tests: who gets which copy, the daily
limit, what a failure leaves behind, expiry edge cases, and the guard tables."""

import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    AiFeature,
    AiUsageEvent,
    Base,
    DataExport,
    DataExportStatus,
    Group,
    GroupMember,
    Lesson,
    MarkOverrideAudit,
    MeetingParticipant,
    ParentLink,
    QuestionMark,
    Report,
    ReportAudience,
    ReportStatus,
    Submission,
    SubmissionFile,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.models.integrations import MeetingProvider
from app.security import create_access_token
from app.services import data_export, storage
from app.workers.jobs import enqueue, process_one_job
from tests.factories import make_user, org_id, register_parent, settled_submission
from tests.test_data_export import (  # noqa: F401  (fixtures and helpers)
    PAGE,
    _drain,
    _export,
    _org_of,
    _own_upload_dir,
    _url,
    _zip,
    world,
)


def _data(content: bytes) -> dict:
    return json.loads(_zip(content).read("data.json"))


async def _download(client, headers, sid, export_id, *, parent=False) -> bytes:
    resp = await client.get(_url(sid, export_id, parent=parent, file=True), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.content


async def _seed_private_material(student_id: int, tutor_id: int) -> None:
    async with async_session() as session:
        org = await org_id(session)
        mark = await session.scalar(
            select(QuestionMark)
            .join(Submission, Submission.id == QuestionMark.submission_id)
            .where(Submission.student_id == student_id)
        )
        session.add_all(
            [
                MarkOverrideAudit(
                    question_mark_id=mark.id, old_marks=1, new_marks=2, changed_by_id=tutor_id
                ),
                AiUsageEvent(
                    organization_id=org,
                    tutor_id=tutor_id,
                    student_id=student_id,
                    feature=AiFeature.marking,
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=1.5,
                ),
            ]
        )
        for title, audience, status in (
            ("for-parent-final", ReportAudience.parent, ReportStatus.ready),
            ("for-parent-draft", ReportAudience.parent, ReportStatus.generating),
            ("for-tutor-only", ReportAudience.tutor, ReportStatus.ready),
        ):
            session.add(
                Report(
                    student_id=student_id,
                    generated_by_id=tutor_id,
                    audience=audience,
                    status=status,
                    title=title,
                )
            )
        await session.commit()


async def test_a_parent_copy_leaves_out_the_tutors_private_material_and_a_tutor_copy_does_not(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    await _seed_private_material(sid, tutor["user"]["id"])
    parent = await register_parent(client, tutor, student)

    mine = await _export(client, tutor["headers"], sid)
    theirs = await _export(client, parent["headers"], sid, parent=True)
    await _drain()
    full = _data(await _download(client, tutor["headers"], sid, mine["id"]))["tables"]
    kept = _data(await _download(client, parent["headers"], sid, theirs["id"], parent=True))

    for table in (
        "tutor_notes",
        "mark_override_audit",
        "ai_usage_events",
        "parent_communications",
        "tutor_observations",
        "lesson_observations",
        "mistake_revision_audit",
    ):
        assert table in full
        assert table not in kept["tables"], table
    assert len(full["tutor_notes"]) == 1
    assert len(full["mark_override_audit"]) == 1
    assert len(full["ai_usage_events"]) == 1
    assert {r["title"] for r in full["reports"]} == {
        "for-parent-final",
        "for-parent-draft",
        "for-tutor-only",
    }
    assert [r["title"] for r in kept["tables"]["reports"]] == ["for-parent-final"]
    assert kept["export"]["audience"] == "parent"
    # What the child did is still theirs.
    assert len(kept["tables"]["submissions"]) == 1
    assert kept["tables"]["question_marks"]


async def test_neither_copy_holds_storage_keys_or_other_adults(client, tutor, student, world):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    mine = await _export(client, tutor["headers"], sid)
    theirs = await _export(client, parent["headers"], sid, parent=True)
    await _drain()
    copies = [
        (await _download(client, tutor["headers"], sid, mine["id"])),
        (await _download(client, parent["headers"], sid, theirs["id"], parent=True)),
    ]
    for content in copies:
        text = _zip(content).read("data.json").decode()
        data = json.loads(text)
        assert "org/" not in text
        assert world["sara_key"] not in text
        assert all("path" not in r for r in data["tables"]["submission_files"])
        links = data["tables"]["parent_links"]
        assert links
        assert all(set(r) == {"created_at"} for r in links)
        assert "parent@example.com" not in text


async def test_a_meeting_row_that_guessed_the_classmate_does_not_name_him(
    client, tutor, group, student, world
):
    sid, oid = student["user"]["id"], world["omar"]["user"]["id"]
    async with async_session() as session:
        org = await org_id(session)
        # A real lesson: Postgres enforces the foreign key that SQLite does not.
        lesson = Lesson(organization_id=org, group_id=group["id"], date=date(2026, 9, 2))
        session.add(lesson)
        await session.flush()
        session.add(
            MeetingParticipant(
                organization_id=org,
                lesson_id=lesson.id,
                provider=MeetingProvider.zoom,
                display_name="guest",
                email="guest@example.net",
                matched_student_id=sid,
                suggested_student_id=oid,
            )
        )
        await session.commit()
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    data = _data(await _download(client, tutor["headers"], sid, export["id"]))
    (row,) = data["tables"]["meeting_participants"]
    assert "suggested_student_id" not in row
    assert row["matched_student_id"] == sid


async def test_asking_again_after_a_finished_export_builds_a_new_one_and_the_day_has_a_limit(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    first = await _export(client, tutor["headers"], sid)
    await _drain()
    # A finished export is never handed back: a repeat request carries newer data.
    second = await _export(client, tutor["headers"], sid)
    assert second["id"] != first["id"]
    await _drain()

    async with async_session() as session:
        for row in (await session.scalars(select(DataExport))).all():
            row.status = DataExportStatus.failed
        row = await session.get(DataExport, first["id"])
        session.add(
            DataExport(
                organization_id=row.organization_id,
                student_id=sid,
                requested_by_id=row.requested_by_id,
                status=DataExportStatus.failed,
            )
        )
        await session.commit()
    # Three today already, failed ones counted.
    resp = await client.post(_url(sid), headers=tutor["headers"])
    assert resp.status_code == 429
    # And nothing was queued.
    async with async_session() as session:
        assert len((await session.scalars(select(DataExport))).all()) == 3


async def test_a_colleague_who_also_teaches_the_child_cannot_read_anothers_export(
    client, tutor, student, subject, world
):
    sid = student["user"]["id"]
    mine = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        colleague = await make_user(
            session,
            organization_id=await _org_of(tutor),
            role=UserRole.tutor,
            name="Co",
            email="co@example.com",
        )
        group = Group(
            organization_id=colleague.organization_id,
            tutor_id=colleague.id,
            subject_id=subject["id"],
            name="Second class",
        )
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, student_id=sid))
        await session.commit()
        headers = {"Authorization": f"Bearer {create_access_token(colleague.id, 0)}"}
    assert (await client.post(_url(sid), headers=headers)).status_code == 202
    assert (await client.get(_url(sid, mine["id"]), headers=headers)).status_code == 404
    assert (await client.get(_url(sid, mine["id"], file=True), headers=headers)).status_code == 404


async def test_a_revoked_parent_link_is_a_404_on_the_next_request(client, tutor, student, world):
    sid = student["user"]["id"]
    parent = await register_parent(client, tutor, student)
    export = await _export(client, parent["headers"], sid, parent=True)
    await _drain()
    status = _url(sid, export["id"], parent=True)
    assert (await client.get(status, headers=parent["headers"])).status_code == 200
    async with async_session() as session:
        link = await session.scalar(select(ParentLink).where(ParentLink.student_id == sid))
        await session.delete(link)
        await session.commit()
    assert (await client.get(status, headers=parent["headers"])).status_code == 404
    assert (
        await client.get(_url(sid, export["id"], parent=True, file=True), headers=parent["headers"])
    ).status_code == 404
    assert (await client.post(_url(sid, parent=True), headers=parent["headers"])).status_code == 404


async def test_a_job_redelivered_after_a_crash_finishes_through_the_worker(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    async with async_session() as session:
        key = storage.new_export_key(await org_id(session))
        row = DataExport(
            organization_id=await org_id(session),
            student_id=sid,
            requested_by_id=tutor["user"]["id"],
            status=DataExportStatus.running,
            storage_key=key,
        )
        session.add(row)
        await session.flush()
        await enqueue(session, data_export.EXPORT_JOB, {"export_id": row.id})
        await session.commit()
        export_id = row.id
    assert await process_one_job()
    async with async_session() as session:
        row = await session.get(DataExport, export_id)
        assert row.status == DataExportStatus.ready
        assert row.storage_key == key
    assert await storage.get_storage().exists(key)


async def test_giving_up_marks_the_export_failed_and_deletes_its_file(
    client, tutor, student, world
):
    key = storage.new_export_key(1)
    await storage.get_storage().upload(key, b"half", "application/zip")
    async with async_session() as session:
        row = DataExport(
            organization_id=await org_id(session),
            student_id=student["user"]["id"],
            requested_by_id=tutor["user"]["id"],
            status=DataExportStatus.running,
            storage_key=key,
        )
        session.add(row)
        await session.commit()
        await data_export.export_given_up(session, {"export_id": row.id}, "stopped")
        await session.commit()
        await session.refresh(row)
        assert row.status == DataExportStatus.failed
        assert row.storage_key is None
        assert row.error == data_export.FAILED_MESSAGE
    assert not await storage.get_storage().exists(key)


async def test_a_failed_build_leaves_no_file_and_the_sweep_clears_a_stuck_one(
    client, tutor, student, world, monkeypatch
):
    sid = student["user"]["id"]
    real_upload = storage.get_storage().upload_path

    async def half_then_boom(key, path, mime):
        await real_upload(key, path, mime)
        raise RuntimeError("late failure")

    monkeypatch.setattr(storage.get_storage(), "upload_path", half_then_boom)
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        row = await session.get(DataExport, export["id"])
        assert row.status == DataExportStatus.failed
        assert row.storage_key is None

    # A failed row whose delete failed keeps its key, and the sweep retries it.
    key = storage.new_export_key(1)
    await storage.get_storage().upload(key, b"x", "application/zip")
    async with async_session() as session:
        row = await session.get(DataExport, export["id"])
        row.storage_key = key
        await session.commit()
        await data_export.expire_data_exports(session, datetime.now(timezone.utc))
        await session.refresh(row)
        assert row.status == DataExportStatus.failed
        assert row.storage_key is None
    assert not await storage.get_storage().exists(key)


async def test_expiry_keeps_the_row_ready_when_the_delete_fails_and_expires_it_when_the_file_is_gone(
    client, tutor, student, world, monkeypatch
):
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        row = await session.get(DataExport, export["id"])
        key = row.storage_key
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()

        async def refuse(_key):
            raise RuntimeError("bucket down")

        with monkeypatch.context() as m:
            m.setattr(storage, "delete_file", refuse)
            assert await data_export.expire_data_exports(session, utcnow()) == 0
        await session.refresh(row)
        assert row.status == DataExportStatus.ready
        assert row.storage_key == key

        # The file is already gone: still expired.
        await storage.get_storage().delete(key)
        assert await data_export.expire_data_exports(session, utcnow()) == 1
        await session.refresh(row)
        assert row.status == DataExportStatus.expired
        assert row.storage_key is None


async def test_a_missing_page_leaves_the_others_and_leaks_no_key(client, tutor, student, world):
    sid = student["user"]["id"]
    second_key = storage.new_key(1, "application/pdf")
    await storage.get_storage().upload(second_key, PAGE["omar"].replace(b"OMAR", b"SARA2"), "x")
    async with async_session() as session:
        sub = await session.scalar(select(Submission).where(Submission.student_id == sid))
        session.add(
            SubmissionFile(
                submission_id=sub.id,
                position=2,
                path=second_key,
                name="page2.pdf",
                mime="application/pdf",
            )
        )
        await session.commit()
    await storage.delete_file(world["sara_key"])
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    content = await _download(client, tutor["headers"], sid, export["id"])
    archive = _zip(content)
    pages = [n for n in archive.namelist() if n.startswith("files/")]
    assert len(pages) == 1
    assert archive.read(pages[0]).endswith(b"SARA2-PAGE")
    text = archive.read("data.json").decode()
    data = json.loads(text)
    assert data["files_missing"] == [{"submission_id": sub.id, "name": "sara-page.pdf"}]
    assert "org/" not in text


async def test_a_large_child_does_not_overflow_the_id_lists(
    client, tutor, student, subject, world, monkeypatch
):
    sid = student["user"]["id"]
    async with async_session() as session:
        await settled_submission(
            session,
            subject_id=subject["id"],
            organization_id=await org_id(session),
            student_id=sid,
            analysed=False,
            marks=4,
        )
        await session.commit()
    monkeypatch.setattr(data_export, "ID_CHUNK", 1)
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    data = _data(await _download(client, tutor["headers"], sid, export["id"]))["tables"]
    assert len(data["submissions"]) == 2
    assert len(data["question_marks"]) == 5
    ids = [r["id"] for r in data["question_marks"]]
    assert ids == sorted(ids)


async def test_every_table_reachable_from_an_exported_one_is_decided_and_every_listed_table_is_collected(
    client, tutor, student, world
):
    parents = data_export.EXPORTED - {"users"}
    undecided = {
        table.name
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name in parents
        and table.name not in data_export.EXPORTED
        and table.name not in data_export.NOT_EXPORTED
    }
    assert not undecided, (
        f"hangs off an exported table; export it or exclude it: {sorted(undecided)}"
    )

    async with async_session() as session:
        sara = await session.get(User, student["user"]["id"])
        data, _ = await data_export.collect(session, sara, "full")
    assert set(data["tables"]) == data_export.EXPORTED - {"users"}
