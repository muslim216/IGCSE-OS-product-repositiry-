"""A child's data as a ZIP (launch audit P-3, part 2): who can ask, what is in it,
that it holds nothing of a classmate, and that it goes after seven days."""

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import (
    Base,
    DataExport,
    DataExportStatus,
    Organization,
    Submission,
    SubmissionFile,
    TutorNote,
    User,
    UserRole,
)
from app.security import create_access_token, hash_password
from app.services import data_export, retention, storage
from app.workers.jobs import process_one_job
from tests.factories import (
    make_user,
    org_id,
    register_other_tutor,
    register_parent,
    settled_submission,
)

PAGE = {"sara": b"%PDF-1.4 SARA-PAGE", "omar": b"%PDF-1.4 OMAR-PAGE"}
NOTE = {"sara": "note-about-sara-7f3", "omar": "note-about-omar-9c1"}


@pytest.fixture(autouse=True)
def _own_upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))


async def _drain() -> None:
    for _ in range(10):
        if not await process_one_job():
            return


async def _new_student(client, tutor, group, name: str) -> dict:
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": name,
            "email": f"{name.lower()}@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


async def _seed(who: str, student_id: int, tutor_id: int, subject_id: int) -> str:
    """A note, a finalized self-timed attempt and one stored page for a student.
    Returns the page's storage key."""
    async with async_session() as session:
        session.add(TutorNote(student_id=student_id, tutor_id=tutor_id, body=NOTE[who]))
        await settled_submission(
            session,
            subject_id=subject_id,
            organization_id=await org_id(session),
            student_id=student_id,
            analysed=False,
            marks=1,
        )
        submission = await session.scalar(
            select(Submission).where(Submission.student_id == student_id)
        )
        submission.timed = True
        submission.time_taken_minutes = 45
        key = storage.new_key(await org_id(session), "application/pdf")
        await storage.get_storage().upload(key, PAGE[who], "application/pdf")
        session.add(
            SubmissionFile(
                submission_id=submission.id,
                position=1,
                path=key,
                name=f"{who}-page.pdf",
                mime="application/pdf",
            )
        )
        await session.commit()
    return key


@pytest.fixture
async def world(client, tutor, group, subject, student):
    omar = await _new_student(client, tutor, group, "Omar")
    sara_key = await _seed("sara", student["user"]["id"], tutor["user"]["id"], subject["id"])
    omar_key = await _seed("omar", omar["user"]["id"], tutor["user"]["id"], subject["id"])
    return {"omar": omar, "sara_key": sara_key, "omar_key": omar_key}


def _url(student_id: int, export_id: int | None = None, *, parent: bool = False, file=False):
    base = f"/api/v1/{'me/children' if parent else 'students'}/{student_id}/export"
    if export_id is not None:
        base += f"/{export_id}"
    return base + ("/file" if file else "")


async def _export(client, headers, student_id, *, parent=False) -> dict:
    resp = await client.post(_url(student_id, parent=parent), headers=headers)
    assert resp.status_code == 202, resp.text
    return resp.json()


def _zip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


async def test_the_zip_holds_the_students_rows_and_files_and_nothing_of_a_classmate(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    assert export["status"] == "pending"
    await _drain()

    status = await client.get(_url(sid, export["id"]), headers=tutor["headers"])
    assert status.json()["status"] == "ready"
    assert status.json()["expires_at"] is not None

    resp = await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["cache-control"] == "no-store, private"
    archive = _zip(resp.content)
    names = archive.namelist()
    assert "data.json" in names
    pages = [n for n in names if n.startswith("files/")]
    assert len(pages) == 1 and archive.read(pages[0]) == PAGE["sara"]

    text = archive.read("data.json").decode()
    data = json.loads(text)
    assert data["profile"]["name"] == "Sara"
    assert [n["body"] for n in data["tables"]["tutor_notes"]] == [NOTE["sara"]]
    assert len(data["tables"]["submissions"]) == 1
    assert len(data["tables"]["question_marks"]) == 1
    # Nothing of the classmate, in the rows or the files.
    assert NOTE["omar"] not in text and "Omar" not in text and "omar" not in text
    assert all(PAGE["omar"] not in archive.read(n) for n in names)


async def test_self_declared_fields_are_labelled_as_such(client, tutor, student, world):
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    resp = await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    row = json.loads(_zip(resp.content).read("data.json"))["tables"]["submissions"][0]
    assert row["self_declared"]["timed"] is True
    assert row["self_declared"]["time_taken_minutes"] == 45
    assert "timed" not in row and "time_taken_minutes" not in row


async def test_asking_twice_while_one_is_building_returns_the_same_export(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    first = await _export(client, tutor["headers"], sid)
    second = await _export(client, tutor["headers"], sid)
    assert first["id"] == second["id"]
    await _drain()
    third = await _export(client, tutor["headers"], sid)
    assert third["id"] != first["id"]


async def test_a_parent_can_download_their_own_child(client, tutor, student, world):
    parent = await register_parent(client, tutor, student)
    sid = student["user"]["id"]
    export = await _export(client, parent["headers"], sid, parent=True)
    await _drain()
    status = await client.get(_url(sid, export["id"], parent=True), headers=parent["headers"])
    assert status.json()["status"] == "ready"
    resp = await client.get(
        _url(sid, export["id"], parent=True, file=True), headers=parent["headers"]
    )
    assert resp.status_code == 200
    assert json.loads(_zip(resp.content).read("data.json"))["profile"]["name"] == "Sara"


async def _org_of(tutor: dict) -> int:
    async with async_session() as session:
        return (await session.get(User, tutor["user"]["id"])).organization_id


async def _admin(organization_id: int) -> dict:
    async with async_session() as session:
        admin = User(
            email=f"admin-{organization_id}@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.admin,
            name="Admin",
            organization_id=organization_id,
        )
        session.add(admin)
        await session.commit()
        return {"headers": {"Authorization": f"Bearer {create_access_token(admin.id, 0)}"}}


async def test_an_admin_can_download_a_child_of_their_own_organization_only(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    own = await _admin(await _org_of(tutor))
    export = await _export(client, own["headers"], sid)
    await _drain()
    resp = await client.get(_url(sid, export["id"], file=True), headers=own["headers"])
    assert resp.status_code == 200

    async with async_session() as session:
        other = Organization(name="Elsewhere")
        session.add(other)
        await session.commit()
        other_id = other.id
    foreign = await _admin(other_id)
    assert (await client.post(_url(sid), headers=foreign["headers"])).status_code == 404
    assert (
        await client.get(_url(sid, export["id"], file=True), headers=foreign["headers"])
    ).status_code == 404


async def test_everyone_else_is_refused(client, tutor, student, group, world):
    """QA-12: another organization, a tutor who does not teach the child, an
    unlinked parent, the student themselves, no token."""
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    paths = [(_url(sid, export["id"]), "get"), (_url(sid, export["id"], file=True), "get")]

    other_org = await register_other_tutor(client)
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
    stranger_parent = await register_parent(client, tutor, world["omar"], email="p2@example.com")

    for who in (other_org, {"headers": colleague_headers}):
        assert (await client.post(_url(sid), headers=who["headers"])).status_code == 404
        for path, _ in paths:
            assert (await client.get(path, headers=who["headers"])).status_code == 404

    # An unlinked parent, through the parent routes (and the tutor routes, which
    # refuse their role).
    assert (
        await client.post(_url(sid, parent=True), headers=stranger_parent["headers"])
    ).status_code == 404
    assert (
        await client.get(
            _url(sid, export["id"], parent=True, file=True), headers=stranger_parent["headers"]
        )
    ).status_code == 404
    assert (await client.post(_url(sid), headers=stranger_parent["headers"])).status_code == 403

    # The student cannot ask for their own data through either route.
    assert (await client.post(_url(sid), headers=student["headers"])).status_code == 403
    assert (
        await client.post(_url(sid, parent=True), headers=student["headers"])
    ).status_code == 403

    # No token.
    assert (await client.post(_url(sid))).status_code == 401
    assert (await client.get(_url(sid, export["id"], file=True))).status_code == 401


async def test_an_export_id_of_another_student_or_another_asker_is_a_404(
    client, tutor, student, world
):
    sid, oid = student["user"]["id"], world["omar"]["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    # Sara's export under Omar's path.
    assert (await client.get(_url(oid, export["id"]), headers=tutor["headers"])).status_code == 404
    assert (
        await client.get(_url(oid, export["id"], file=True), headers=tutor["headers"])
    ).status_code == 404
    # A linked parent cannot read the copy the tutor asked for.
    parent = await register_parent(client, tutor, student)
    assert (
        await client.get(_url(sid, export["id"], parent=True), headers=parent["headers"])
    ).status_code == 404
    assert (
        await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    ).status_code == 200


async def test_a_file_that_is_not_ready_is_a_404(client, tutor, student, world):
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    resp = await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    assert resp.status_code == 404


async def test_running_the_job_again_changes_nothing(client, tutor, student, world, monkeypatch):
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        row = await session.get(DataExport, export["id"])
        key, expires = row.storage_key, row.expires_at
        assert row.status == DataExportStatus.ready

        uploads = []
        real = storage.get_storage().upload_path

        async def spy(*args, **kwargs):
            uploads.append(args)
            return await real(*args, **kwargs)

        monkeypatch.setattr(storage.get_storage(), "upload_path", spy)
        # A finished export is a no-op.
        await data_export.export_student_data(session, {"export_id": export["id"]})
        assert uploads == []
        await session.refresh(row)
        assert (row.storage_key, row.expires_at) == (key, expires)

        # A run that died part-way (left `running`, key already chosen) is
        # picked up again and rewrites the same key.
        row.status = DataExportStatus.running
        await session.commit()
        await data_export.export_student_data(session, {"export_id": export["id"]})
        await session.refresh(row)
        assert row.status == DataExportStatus.ready and row.storage_key == key
        assert [u[0] for u in uploads] == [key]
    assert await storage.get_storage().exists(key)


async def test_a_failed_build_says_so_and_is_never_left_running(
    client, tutor, student, world, monkeypatch
):
    sid = student["user"]["id"]

    async def boom(*args, **kwargs):
        raise RuntimeError("disk exploded at /secret/path")

    monkeypatch.setattr(storage.get_storage(), "upload_path", boom)
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    body = (await client.get(_url(sid, export["id"]), headers=tutor["headers"])).json()
    assert body["status"] == "failed"
    assert body["error"] == data_export.FAILED_MESSAGE
    assert "secret" not in body["error"]
    # Asking again starts a fresh one.
    monkeypatch.undo()
    again = await _export(client, tutor["headers"], sid)
    assert again["id"] != export["id"]


async def test_a_page_missing_from_storage_does_not_fail_the_export(client, tutor, student, world):
    sid = student["user"]["id"]
    await storage.delete_file(world["sara_key"])
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    resp = await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    data = json.loads(_zip(resp.content).read("data.json"))
    assert data["files"] == [] and len(data["files_missing"]) == 1


async def test_expiry_deletes_the_file_and_the_link_says_gone(client, tutor, student, world):
    sid = student["user"]["id"]
    export = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        row = await session.get(DataExport, export["id"])
        key = row.storage_key
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await session.commit()
    assert await storage.get_storage().exists(key)

    # Past its time but not yet swept: already gone to the person asking.
    resp = await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    assert resp.status_code == 410

    async with async_session() as session:
        assert await data_export.expire_data_exports(session, datetime.now(timezone.utc)) == 1
        assert await data_export.expire_data_exports(session, datetime.now(timezone.utc)) == 0
        row = await session.get(DataExport, export["id"])
        assert row.status == DataExportStatus.expired and row.storage_key is None
    assert not await storage.get_storage().exists(key)
    resp = await client.get(_url(sid, export["id"], file=True), headers=tutor["headers"])
    assert resp.status_code == 410
    assert (await client.get(_url(sid, export["id"]), headers=tutor["headers"])).json()[
        "status"
    ] == "expired"


async def test_the_daily_retention_sweep_expires_exports_and_leaves_live_ones(
    client, tutor, student, world
):
    sid = student["user"]["id"]
    old = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        row = await session.get(DataExport, old["id"])
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await session.commit()
    live = await _export(client, tutor["headers"], sid)
    await _drain()
    async with async_session() as session:
        await retention.sweep_retention(session, {})
        statuses = {r.id: r.status for r in (await session.scalars(select(DataExport))).all()}
    assert statuses == {old["id"]: DataExportStatus.expired, live["id"]: DataExportStatus.ready}


def test_every_table_that_holds_a_student_key_is_exported_or_excluded_on_purpose():
    """A new table keyed to a student must be decided, not forgotten."""
    keyed = set()
    for table in Base.metadata.tables.values():
        names = {c.name for c in table.columns}
        if names & {"student_id", "recipient_user_id", "matched_student_id"}:
            keyed.add(table.name)
        if "user_id" in names and table.name != "organization_members":
            keyed.add(table.name)
    undecided = keyed - data_export.EXPORTED - set(data_export.NOT_EXPORTED)
    # Erasure's own bookkeeping and the export row itself describe the request,
    # not the child's record.
    undecided -= {"erasure_requests", "data_exports"}
    assert not undecided, f"decide whether these belong in a child's export: {sorted(undecided)}"
