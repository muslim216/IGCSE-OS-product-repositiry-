"""The inbound WhatsApp webhook: signature, STOP/START, auto-reply, statuses (8.1)."""

import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session
from app.models import (
    ContactPoint,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    SuppressionReason,
)
from app.services.notifications import inbound
from tests.factories import add_contact

URL = "/api/v1/webhooks/whatsapp"
SECRET = "app-secret"
NUMBER = "+201001234567"


@pytest.fixture(autouse=True)
def _wa_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", SECRET)
    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", "verify-me")


@pytest.fixture
def replies(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def fake_reply(address, body):
        sent.append((address, body))

    monkeypatch.setattr(inbound, "send_reply", fake_reply)
    return sent


def _sign(body: bytes, secret: str = SECRET) -> dict:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


def _inbound(text: str, sender: str = "201001234567") -> bytes:
    return json.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": sender, "type": "text", "text": {"body": text}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
    ).encode()


async def _post(client, body: bytes, headers=None):
    return await client.post(URL, content=body, headers=_sign(body) if headers is None else headers)


@pytest.fixture
async def contact(tutor):
    async with async_session() as session:
        c = await add_contact(
            session, tutor["user"]["id"], channel=NotificationChannel.whatsapp, address=NUMBER
        )
        await session.commit()
        return c.id


async def _contact(contact_id) -> ContactPoint:
    async with async_session() as session:
        return await session.get(ContactPoint, contact_id)


# --- verification -----------------------------------------------------------


async def test_handshake_echoes_the_challenge(client):
    resp = await client.get(
        URL,
        params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1234"},
    )
    assert (resp.status_code, resp.text) == (200, "1234")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"},
        {"hub.mode": "subscribe", "hub.challenge": "1"},
    ],
)
async def test_handshake_rejects_a_mismatch(client, params):
    assert (await client.get(URL, params=params)).status_code == 403


async def test_handshake_is_closed_when_no_verify_token_is_set(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_verify_token", None)
    resp = await client.get(
        URL, params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"}
    )
    assert resp.status_code == 403


# --- signature --------------------------------------------------------------


async def test_a_valid_signature_is_accepted(client, replies):
    assert (await _post(client, _inbound("hello"))).status_code == 200


async def test_an_invalid_signature_is_rejected(client, replies, contact):
    body = _inbound("STOP")
    resp = await _post(client, body, _sign(body, secret="someone-else"))
    assert resp.status_code == 401
    assert (await _contact(contact)).suppressed_at is None
    assert replies == []


async def test_a_missing_signature_is_rejected(client, replies):
    assert (await _post(client, _inbound("hello"), {})).status_code == 401


async def test_a_tampered_body_is_rejected(client, replies):
    headers = _sign(_inbound("hello"))
    assert (await _post(client, _inbound("STOP"), headers)).status_code == 401


async def test_every_post_is_rejected_when_the_secret_is_unset(client, monkeypatch, replies):
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", None)
    body = _inbound("hello")
    assert (await _post(client, body, _sign(body, secret=""))).status_code == 401
    assert (await _post(client, body)).status_code == 401


async def test_signed_garbage_is_acknowledged_not_retried(client):
    assert (await _post(client, b"not json")).status_code == 200


# --- inbound messages -------------------------------------------------------


@pytest.mark.parametrize("word", ["STOP", "  stop ", "Unsubscribe", "إيقاف"])
async def test_stop_opts_the_number_out_and_confirms(client, replies, contact, word):
    assert (await _post(client, _inbound(word))).status_code == 200
    row = await _contact(contact)
    assert row.suppressed_reason == SuppressionReason.opted_out
    assert row.suppressed_at is not None
    assert replies == [("201001234567", inbound.STOPPED_REPLY)]


async def test_start_clears_an_opt_out_only(client, replies, contact):
    await _post(client, _inbound("STOP"))
    await _post(client, _inbound("start"))
    assert (await _contact(contact)).suppressed_at is None
    assert replies[-1][1] == inbound.STARTED_REPLY


async def test_start_does_not_undo_a_provider_rejection(client, replies, contact):
    async with async_session() as session:
        row = await session.get(ContactPoint, contact)
        row.suppressed_reason = SuppressionReason.provider_rejected
        row.suppressed_at = row.created_at
        await session.commit()
    await _post(client, _inbound("START"))
    assert (await _contact(contact)).suppressed_reason == SuppressionReason.provider_rejected


async def test_anything_else_gets_the_auto_reply_and_changes_nothing(client, replies, contact):
    await _post(client, _inbound("can I ask about my homework?"))
    assert replies == [("201001234567", inbound.AUTO_REPLY)]
    assert (await _contact(contact)).suppressed_at is None


async def test_an_unknown_sender_still_gets_the_auto_reply(client, replies):
    await _post(client, _inbound("hi", sender="447700900123"))
    assert replies == [("447700900123", inbound.AUTO_REPLY)]


# --- status callbacks -------------------------------------------------------


def _status(message_id: str, status: str, code: int | None = None) -> bytes:
    entry: dict = {"id": message_id, "status": status}
    if code is not None:
        entry["errors"] = [{"code": code}]
    return json.dumps({"entry": [{"changes": [{"value": {"statuses": [entry]}}]}]}).encode()


@pytest.fixture
async def sent_note(tutor, contact):
    async with async_session() as session:
        organization_id = (await session.get(ContactPoint, contact)).organization_id
        note = Notification(
            organization_id=organization_id,
            recipient_user_id=tutor["user"]["id"],
            kind=NotificationKind.review_queue,
            template="avora_review_queue",
            params={"pending_count": "1"},
            link_path="/",
            idempotency_key="status-1",
            status=NotificationStatus.sent,
            channel=NotificationChannel.whatsapp,
            provider_message_id="wamid.1",
        )
        session.add(note)
        await session.commit()
        return note.id


async def test_a_permanent_failure_callback_fails_the_row_and_suppresses(
    client, sent_note, contact
):
    await _post(client, _status("wamid.1", "failed", code=131026))
    async with async_session() as session:
        note = await session.get(Notification, sent_note)
        assert note.status == NotificationStatus.failed
        assert "131026" in note.error
    assert (await _contact(contact)).suppressed_reason == SuppressionReason.provider_rejected


async def test_a_transient_failure_callback_fails_the_row_but_keeps_the_contact(
    client, sent_note, contact
):
    await _post(client, _status("wamid.1", "failed", code=131047))
    async with async_session() as session:
        assert (await session.get(Notification, sent_note)).status == NotificationStatus.failed
    assert (await _contact(contact)).suppressed_at is None


async def test_delivered_and_unknown_ids_change_nothing(client, sent_note):
    await _post(client, _status("wamid.1", "delivered"))
    await _post(client, _status("wamid.unknown", "failed", code=131026))
    async with async_session() as session:
        assert (await session.get(Notification, sent_note)).status == NotificationStatus.sent
        assert await session.scalar(select(ContactPoint.suppressed_at)) is None
