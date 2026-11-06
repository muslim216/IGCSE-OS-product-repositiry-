"""One syllabus read at a time per workspace (T-028).

A read can now run for up to 45 minutes on the model's full answer length, so a
workspace may not start a second one while the first is still going: upload and
retry answer 409 until it finishes.

The check has to hold when two requests arrive together, so the route locks the
workspace's organization row (`SELECT ... FOR UPDATE`) before it looks.

What each test here can prove depends on the database:

- On SQLite (the default suite) `FOR UPDATE` is silently dropped, so nothing
  here can show the lock *serialising* two requests. What SQLite does prove is
  the behaviour one request at a time, the tenancy boundary, and that the route
  asks for the lock on the organization row before it reads the uploads
  (`test_the_workspace_is_locked_before_the_check`), which is the part a later
  edit could quietly break.
- Only Postgres proves the race itself:
  `test_two_uploads_at_the_same_moment_start_one_read` sends two at once and
  needs one 201 and one 409. It skips on SQLite rather than passing, because
  there it would race with no lock at all. CI's "Backend tests (Postgres)" job
  runs it.
"""

import asyncio
import os

import pytest
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.api import syllabus_uploads
from app.api.syllabus_uploads import SYLLABUS_BEING_READ_MESSAGE
from app.services import storage
from app.workers.jobs import process_one_job

API = "/api/v1/syllabus-uploads"
PDF_BYTES = b"%PDF-1.4 fake test syllabus pdf"


async def _post(client, who, title="Chemistry"):
    return await client.post(
        API,
        data={"title": title},
        files={"file": ("syllabus.pdf", PDF_BYTES, "application/pdf")},
        headers=who["headers"],
    )


async def _register(client, email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


@pytest.fixture
def reads_do_nothing(monkeypatch):
    async def _fake(session, upload):
        upload.draft = None

    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", _fake)


@pytest.fixture
def reads_fail(monkeypatch):
    async def _fail(session, upload):
        raise ValueError("unreadable")

    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", _fail)


async def test_a_second_upload_while_one_is_being_read_is_refused(client, tutor):
    first = await _post(client, tutor)
    assert first.status_code == 201, first.text

    second = await _post(client, tutor, title="Physics")
    assert second.status_code == 409, second.text
    assert second.json()["detail"] == SYLLABUS_BEING_READ_MESSAGE


async def test_a_refused_upload_stores_nothing_and_queues_nothing(client, tutor):
    from sqlalchemy import func, select

    from app.db import async_session
    from app.models import Job, SyllabusUpload

    assert (await _post(client, tutor)).status_code == 201
    assert (await _post(client, tutor)).status_code == 409
    async with async_session() as session:
        assert await session.scalar(select(func.count(SyllabusUpload.id))) == 1
        assert await session.scalar(select(func.count(Job.id))) == 1


async def test_once_the_read_finishes_the_next_upload_goes_ahead(client, tutor, reads_do_nothing):
    assert (await _post(client, tutor)).status_code == 201
    assert await process_one_job() is True
    assert (await _post(client, tutor, title="Physics")).status_code == 201


async def test_a_retry_while_another_upload_is_being_read_is_refused(
    client, tutor, monkeypatch, reads_fail
):
    failed = await _post(client, tutor)
    assert failed.status_code == 201
    await process_one_job()
    await process_one_job()
    detail = await client.get(f"{API}/{failed.json()['id']}", headers=tutor["headers"])
    assert detail.json()["status"] == "extraction_failed"

    assert (await _post(client, tutor, title="Physics")).status_code == 201
    retry = await client.post(f"{API}/{failed.json()['id']}/retry", headers=tutor["headers"])
    assert retry.status_code == 409, retry.text
    assert retry.json()["detail"] == SYLLABUS_BEING_READ_MESSAGE
    # Refused means untouched: still failed, and still retryable later.
    detail = await client.get(f"{API}/{failed.json()['id']}", headers=tutor["headers"])
    assert detail.json()["status"] == "extraction_failed"


async def test_a_retry_with_nothing_else_being_read_goes_ahead(client, tutor, reads_fail):
    failed = await _post(client, tutor)
    await process_one_job()
    await process_one_job()
    retry = await client.post(f"{API}/{failed.json()['id']}/retry", headers=tutor["headers"])
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "extracting"


async def test_another_workspace_s_read_does_not_block_this_one(client, tutor):
    """Negative tenancy case: the lock and the check are per organization."""
    other = await _register(client, "other@example.com")
    assert (await _post(client, other)).status_code == 201

    mine = await _post(client, tutor)
    assert mine.status_code == 201, mine.text


async def test_another_workspace_s_read_does_not_block_a_retry_here(client, tutor, reads_fail):
    failed = await _post(client, tutor)
    await process_one_job()
    await process_one_job()
    other = await _register(client, "other@example.com")
    assert (await _post(client, other)).status_code == 201

    retry = await client.post(f"{API}/{failed.json()['id']}/retry", headers=tutor["headers"])
    assert retry.status_code == 200, retry.text


@pytest.mark.parametrize("route", ["upload", "retry"])
async def test_the_workspace_is_locked_before_the_check(client, tutor, reads_fail, route):
    """What SQLite can prove about the race: the route asks for a row lock on the
    organization, and asks before it reads the uploads. Without that order two
    requests on Postgres would both see nothing in progress."""
    if route == "retry":
        failed = await _post(client, tutor)
        await process_one_job()
        await process_one_job()

    seen: list = []

    def _record(state):
        seen.append(state.statement)

    event.listen(Session, "do_orm_execute", _record)
    try:
        if route == "upload":
            resp = await _post(client, tutor)
            assert resp.status_code == 201, resp.text
        else:
            resp = await client.post(f"{API}/{failed.json()['id']}/retry", headers=tutor["headers"])
            assert resp.status_code == 200, resp.text
    finally:
        event.remove(Session, "do_orm_execute", _record)

    compiled = [str(s.compile(dialect=postgresql.dialect())) for s in seen]
    lock_at = next(
        (
            i
            for i, sql in enumerate(compiled)
            if "FROM organizations" in sql and "FOR UPDATE" in sql
        ),
        None,
    )
    check_at = next(
        (
            i
            for i, sql in enumerate(compiled)
            if "FROM syllabus_uploads" in sql and "syllabus_uploads.status = " in sql
        ),
        None,
    )
    assert lock_at is not None, "the organization row must be locked FOR UPDATE"
    assert check_at is not None, "the route must look for a read in progress"
    assert lock_at < check_at


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason=(
        "needs real Postgres: SQLite drops FOR UPDATE, so two requests at once would "
        "race with no lock and this would prove nothing"
    ),
)
async def test_two_uploads_at_the_same_moment_start_one_read(client, tutor, monkeypatch):
    # Slow the file save, which comes after the check, so that without the lock
    # both requests would pass the check before either wrote its row.
    real_save = storage.save_upload

    async def slow_save(*args, **kwargs):
        await asyncio.sleep(0.5)
        return await real_save(*args, **kwargs)

    monkeypatch.setattr(syllabus_uploads.storage, "save_upload", slow_save)

    first, second = await asyncio.gather(_post(client, tutor), _post(client, tutor, "Physics"))

    assert sorted([first.status_code, second.status_code]) == [201, 409], (
        first.text,
        second.text,
    )
