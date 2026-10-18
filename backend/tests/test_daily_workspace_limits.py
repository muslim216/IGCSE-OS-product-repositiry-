"""What one workspace may do in a day (`SA-01`).

Tutor sign-up is open (owner, 18 Oct 2026), so a stranger's workspace could
otherwise spend the AI bill, the disk and the messaging number without limit.
Every AI call, every stored file and every message going out spends from that
workspace's daily allowance. The allowances are lowered in these tests so they
prove the check without making hundreds of calls.
"""

import pytest

from app.db import async_session
from app.models import (
    Job,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    User,
)
from app.services import ai, storage
from app.services.notifications import notify
from app.services.notifications.service import DAILY_MESSAGE_LIMIT_REASON
from app.services.rate_limit import (
    ALL_LIMITERS,
    RateLimiter,
    ai_daily_limiter,
    message_daily_limiter,
    upload_daily_limiter,
)
from app.workers.jobs import is_permanent
from tests.conftest import PNG_BYTES
from tests.factories import add_contact, patch_channels

API = "/api/v1"


def _allow(monkeypatch, limiter: RateLimiter, n: int) -> None:
    """`n` more uses from here: what a fixture already spent is forgotten."""
    limiter.local._hits.clear()
    monkeypatch.setattr(limiter, "limit", n)
    monkeypatch.setattr(limiter.local, "limit", n)


async def _org(user: dict) -> int:
    async with async_session() as session:
        return (await session.get(User, user["user"]["id"])).organization_id


# --- AI --------------------------------------------------------------------


@pytest.mark.usefixtures("no_ai_key")
async def test_ai_calls_past_the_allowance_are_refused_for_that_workspace_only(
    monkeypatch, tutor, client
):
    _allow(monkeypatch, ai_daily_limiter, 2)
    org = await _org(tutor)
    other = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "B", "email": "b@example.com", "password": "password123"},
    )
    other_org = await _org(other.json())

    async def call(organization_id: int):
        await ai.text_complete(
            organization_id=organization_id, surface="narrative", prompt="x", max_tokens=10
        )

    # Within the allowance the call goes on, here to the missing key.
    for _ in range(2):
        with pytest.raises(ai.AIKeyMissingError):
            await call(org)
    with pytest.raises(ai.AIDailyLimitError, match="today's limit for AI work"):
        await call(org)
    with pytest.raises(ai.AIKeyMissingError):
        await call(other_org)


def test_a_spent_allowance_is_not_retried_and_degrades_like_a_missing_key():
    exc = ai.AIDailyLimitError("x")
    assert is_permanent(exc)
    # The surfaces that degrade for a missing key catch its parent.
    assert isinstance(exc, ai.AIUnavailableError)


@pytest.mark.usefixtures("no_ai_key")
async def test_structured_calls_spend_the_same_allowance(monkeypatch, tutor):
    _allow(monkeypatch, ai_daily_limiter, 1)
    org = await _org(tutor)
    with pytest.raises(ai.AIKeyMissingError):
        await ai.text_complete(organization_id=org, surface="narrative", prompt="x", max_tokens=10)
    with pytest.raises(ai.AIDailyLimitError):
        await ai.structured_complete(
            organization_id=org,
            surface="readiness",
            content=[{"type": "text", "text": "x"}],
            output_format=ai.BaseModel,
            max_tokens=10,
        )


# --- Uploads ---------------------------------------------------------------


async def test_uploads_past_the_allowance_are_a_429(
    monkeypatch, client, student, published_assignment
):
    _allow(monkeypatch, upload_daily_limiter, 1)
    path = f"{API}/assignments/{published_assignment['id']}/submissions"
    files = [("files", ("p.png", PNG_BYTES, "image/png"))]

    first = await client.post(path, files=files, headers=student["headers"])
    assert first.status_code == 201, first.text
    second = await client.post(path, files=files, headers=student["headers"])
    assert second.status_code == 429, second.text
    assert second.json()["detail"] == storage.DAILY_UPLOAD_LIMIT_MESSAGE


async def test_a_job_saving_past_the_allowance_gets_a_value_error(monkeypatch):
    _allow(monkeypatch, upload_daily_limiter, 0)
    with pytest.raises(ValueError, match="today's upload limit"):
        await storage.save_bytes(PNG_BYTES, "image/png", "a.png", organization_id=1)


# --- Messages --------------------------------------------------------------


async def test_messages_past_the_allowance_end_without_being_sent(monkeypatch, tutor):
    _allow(monkeypatch, message_daily_limiter, 1)
    patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        await add_contact(
            session, user.id, channel=NotificationChannel.whatsapp, address="+201001234567"
        )
        notes = [
            await notify(
                session,
                recipient=user,
                kind=NotificationKind.review_queue,
                params={"pending_count": 3},
                link_path="/review",
                idempotency_key=key,
            )
            for key in ("first", "second")
        ]
        await session.commit()
        jobs = (await session.scalars(Job.__table__.select())).all()

    assert notes[0].status == NotificationStatus.queued
    assert notes[1].status == NotificationStatus.failed
    assert notes[1].error == DAILY_MESSAGE_LIMIT_REASON
    # Only the first is queued for delivery.
    assert len(jobs) == 1


# --- Health ----------------------------------------------------------------


def test_the_daily_allowances_are_reported_with_the_other_limiters():
    purposes = {limiter.purpose for limiter in ALL_LIMITERS}
    assert {"ai_daily", "upload_daily", "message_daily"} <= purposes


async def test_a_notification_row_counts_for_its_workspace(monkeypatch, tutor):
    """Keyed by the recipient's organization, which is the sending workspace."""
    _allow(monkeypatch, message_daily_limiter, 1)
    patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        await add_contact(
            session, user.id, channel=NotificationChannel.whatsapp, address="+201001234567"
        )
        note = await notify(
            session,
            recipient=user,
            kind=NotificationKind.review_queue,
            params={"pending_count": 3},
            link_path="/review",
            idempotency_key="only",
        )
        await session.commit()
        stored = await session.get(Notification, note.id)
        assert stored.organization_id == user.organization_id
        assert stored.status == NotificationStatus.queued
