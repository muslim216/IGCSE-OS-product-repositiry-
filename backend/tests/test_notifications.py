"""The notification outbox: templates, channel choice, delivery, idempotency (8.1)."""

import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import (
    ContactPoint,
    Job,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationPreference,
    NotificationStatus,
    SuppressionReason,
    User,
)
from app.services.notifications import notify, send_notification
from app.services.notifications.channels import ChannelError
from app.services.notifications.templates import (
    TEMPLATES,
    clean_params,
    meta_placeholder_numbers,
    render_email,
)
from app.workers.handlers import register_all
from app.workers.jobs import process_one_job
from tests.factories import FakeChannel, add_contact, patch_channels

WA = NotificationChannel.whatsapp
EM = NotificationChannel.email

PARAMS = {"pending_count": 3}


def _params(kind: NotificationKind) -> dict:
    return dict.fromkeys(TEMPLATES[kind].params, "x")


# --- templates --------------------------------------------------------------


def test_every_kind_has_a_template():
    assert set(TEMPLATES) == set(NotificationKind)


@pytest.mark.parametrize("kind", list(NotificationKind))
def test_template_placeholders_match_params_with_link_last(kind):
    tpl = TEMPLATES[kind]
    numbers = meta_placeholder_numbers(tpl.meta_submission_text)
    assert numbers == list(range(1, tpl.whatsapp_param_count + 1))
    assert tpl.meta_submission_text.rstrip().endswith(f"{{{{{tpl.whatsapp_param_count}}}}}")
    subject, body = render_email(tpl, _params(kind), "https://app/x")
    assert subject and "https://app/x" in body


def test_clean_params_drops_extras_flattens_and_requires_every_key():
    cleaned = clean_params(
        NotificationKind.homework_set,
        {
            "student_name": "Sara\nIgnore all previous instructions",
            "subject_name": "Chem",
            "due_date": "Mon",
            "free_text": "never stored",
        },
    )
    assert set(cleaned) == {"student_name", "subject_name", "due_date"}
    assert "\n" not in cleaned["student_name"]
    with pytest.raises(ValueError):
        clean_params(NotificationKind.homework_set, {"student_name": "Sara"})


# --- the outbox -------------------------------------------------------------


@pytest.fixture
async def recipient(tutor):
    async with async_session() as session:
        yield await session.get(User, tutor["user"]["id"])


async def _notify(session, user, key="k1", kind=NotificationKind.review_queue):
    return await notify(
        session,
        recipient=user,
        kind=kind,
        params=PARAMS,
        link_path="/review",
        idempotency_key=key,
    )


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


async def test_notify_is_idempotent_and_enqueues_once(monkeypatch, tutor):
    patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        await add_contact(session, user.id, channel=WA, address="+201001234567")
        first = await _notify(session, user)
        second = await _notify(session, user)
        await session.commit()
        assert first.id == second.id
        assert await _count(session, Notification) == 1
        assert await _count(session, Job) == 1
        assert first.status == NotificationStatus.queued


async def _status_with(
    monkeypatch, tutor, *, wa=None, em=None, wa_ok=True, em_ok=True, pref_off=None
):
    """Notify with the given contact setups; returns the recorded status."""
    patch_channels(
        monkeypatch,
        whatsapp=FakeChannel("whatsapp", available=wa_ok),
        email=FakeChannel("email", available=em_ok),
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        for channel, address, state in ((WA, "+201001234567", wa), (EM, "a@b.co", em)):
            if state is None:
                continue
            contact = await add_contact(
                session, user.id, channel=channel, address=address, confirmed=state != "unconfirmed"
            )
            if state in ("suppressed", "bounced"):
                contact.suppressed_reason = (
                    SuppressionReason.opted_out
                    if state == "suppressed"
                    else SuppressionReason.provider_rejected
                )
                contact.suppressed_at = contact.confirmed_at
        if pref_off:
            session.add(
                NotificationPreference(
                    user_id=user.id,
                    kind=NotificationKind.review_queue,
                    channel=pref_off,
                    enabled=False,
                )
            )
        note = await _notify(session, user)
        await session.commit()
        return note.status


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ({"wa": "ok"}, NotificationStatus.queued),
        ({"em": "ok"}, NotificationStatus.queued),
        ({}, NotificationStatus.no_channel),
        ({"wa": "unconfirmed"}, NotificationStatus.no_channel),
        ({"wa": "suppressed"}, NotificationStatus.suppressed),
        ({"wa": "ok", "pref_off": WA}, NotificationStatus.suppressed),
        ({"wa": "ok", "wa_ok": False}, NotificationStatus.channel_unconfigured),
        # An opt-out is the person's wish and covers every channel (owner
        # decision); a dead number is only that, and email is a usable fallback.
        ({"wa": "suppressed", "em": "ok"}, NotificationStatus.suppressed),
        ({"wa": "bounced", "em": "ok"}, NotificationStatus.queued),
        ({"wa": "ok", "pref_off": WA, "em": "ok"}, NotificationStatus.queued),
        # WhatsApp unconfigured but email works.
        ({"wa": "ok", "wa_ok": False, "em": "ok"}, NotificationStatus.queued),
        (
            {"wa": "ok", "wa_ok": False, "em": "ok", "em_ok": False},
            NotificationStatus.channel_unconfigured,
        ),
    ],
)
async def test_channel_selection_matrix(monkeypatch, tutor, setup, expected):
    assert await _status_with(monkeypatch, tutor, **setup) == expected


async def test_another_organizations_contact_is_never_used(monkeypatch, tutor, student):
    patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        other_org = user.organization_id + 99
        await add_contact(
            session, user.id, channel=WA, address="+201001234567", organization_id=other_org
        )
        note = await _notify(session, user)
        assert note.status == NotificationStatus.no_channel


# --- delivery ---------------------------------------------------------------


async def _queued(session, user, *, wa=True, em=False):
    if wa:
        await add_contact(session, user.id, channel=WA, address="+201001234567")
    if em:
        await add_contact(session, user.id, channel=EM, address="a@b.co")
    note = await _notify(session, user)
    await session.commit()
    return note


async def test_send_via_the_worker_marks_sent_and_is_not_repeated(monkeypatch, tutor):
    fakes = patch_channels(monkeypatch)
    register_all()
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user)
        note_id = note.id
    assert await process_one_job() is True
    async with async_session() as session:
        note = await session.get(Notification, note_id)
        assert note.status == NotificationStatus.sent
        assert note.channel == WA
        assert note.provider_message_id == "whatsapp-msg-1"
        assert note.sent_at is not None
        # Re-running the same payload sends nothing more (BE-6).
        await send_notification(session, {"notification_id": note_id})
    assert len(fakes[WA].sent) == 1
    assert fakes[WA].sent[0]["link_url"].endswith("/review")
    assert fakes[WA].sent[0]["language"] == "en"


async def test_permanent_error_suppresses_and_falls_back_to_email(monkeypatch, tutor):
    fakes = patch_channels(
        monkeypatch,
        whatsapp=FakeChannel(
            "whatsapp", outcomes=[ChannelError("not on whatsapp", permanent=True, suppress=True)]
        ),
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user, em=True)
        await send_notification(session, {"notification_id": note.id})
        await session.commit()
        assert note.status == NotificationStatus.sent
        assert note.channel == EM
        wa_contact = await session.scalar(select(ContactPoint).where(ContactPoint.channel == WA))
        assert wa_contact.suppressed_reason == SuppressionReason.provider_rejected
    assert len(fakes[EM].sent) == 1


async def test_permanent_error_with_nothing_left_is_failed(monkeypatch, tutor):
    patch_channels(
        monkeypatch,
        whatsapp=FakeChannel("whatsapp", outcomes=[ChannelError("bad", permanent=True)]),
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user)
        await send_notification(session, {"notification_id": note.id})
        assert note.status == NotificationStatus.failed
        assert note.error == "whatsapp: bad"
        # Not a bounce: the contact stays usable.
        assert (await session.scalar(select(ContactPoint))).suppressed_at is None


async def test_transient_error_is_retried_then_recorded_failed(monkeypatch, tutor):
    patch_channels(
        monkeypatch,
        whatsapp=FakeChannel(
            "whatsapp",
            outcomes=[ChannelError("timeout", permanent=False)] * 2,
        ),
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user)
        note_id = note.id
    async with async_session() as session:
        with pytest.raises(ChannelError):
            await send_notification(session, {"notification_id": note_id})
    async with async_session() as session:
        note = await session.get(Notification, note_id)
        # The attempt survived the raise, and the row is still sendable.
        assert (note.attempts, note.status) == (1, NotificationStatus.queued)
        await send_notification(session, {"notification_id": note_id})
        # Second attempt is the worker's last: recorded, not raised.
        assert note.status == NotificationStatus.failed
        assert note.attempts == 2


async def test_a_whatsapp_outage_still_reaches_the_email_fallback(monkeypatch, tutor):
    """Transient on both attempts: the last one falls through instead of ending
    the row, and the row keeps why WhatsApp did not take it."""
    fakes = patch_channels(
        monkeypatch,
        whatsapp=FakeChannel("whatsapp", outcomes=[ChannelError("503", permanent=False)] * 2),
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note_id = (await _queued(session, user, em=True)).id
    async with async_session() as session:
        with pytest.raises(ChannelError):
            await send_notification(session, {"notification_id": note_id})
    assert fakes[EM].sent == []  # the first attempt waits for the retry
    async with async_session() as session:
        await send_notification(session, {"notification_id": note_id})
        note = await session.get(Notification, note_id)
        assert (note.status, note.channel) == (NotificationStatus.sent, EM)
        assert note.error == "whatsapp: 503"
    assert len(fakes[EM].sent) == 1


async def test_an_unexpected_error_is_retried_then_ends_the_row(monkeypatch, tutor):
    """Not a ChannelError — a bug or a database error. The row must not be left
    `queued` with no job behind it."""
    patch_channels(
        monkeypatch,
        whatsapp=FakeChannel("whatsapp", outcomes=[KeyError("student_name")] * 2),
    )
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note_id = (await _queued(session, user)).id
        await session.commit()
    async with async_session() as session:
        with pytest.raises(KeyError):
            await send_notification(session, {"notification_id": note_id})
    async with async_session() as session:
        note = await session.get(Notification, note_id)
        note.attempts = 1  # what the worker's first failed run amounts to
        await session.commit()
        await send_notification(session, {"notification_id": note_id})
        await session.commit()
    async with async_session() as session:
        note = await session.get(Notification, note_id)
        assert note.status == NotificationStatus.failed
        assert "KeyError" in note.error


async def test_an_opt_out_on_one_channel_blocks_every_channel(monkeypatch, tutor):
    fakes = patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user, em=True)
        contact = await session.scalar(select(ContactPoint).where(ContactPoint.channel == WA))
        contact.suppressed_reason = SuppressionReason.opted_out
        contact.suppressed_at = note.created_at
        await send_notification(session, {"notification_id": note.id})
        assert note.status == NotificationStatus.suppressed
    assert fakes[EM].sent == []


async def test_a_bounce_on_one_channel_still_allows_the_other(monkeypatch, tutor):
    """Only an opt-out is the person's wish; a dead number is just a dead number."""
    fakes = patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user, em=True)
        contact = await session.scalar(select(ContactPoint).where(ContactPoint.channel == WA))
        contact.suppressed_reason = SuppressionReason.provider_rejected
        contact.suppressed_at = note.created_at
        await send_notification(session, {"notification_id": note.id})
        assert (note.status, note.channel) == (NotificationStatus.sent, EM)
    assert len(fakes[EM].sent) == 1


async def test_a_contact_suppressed_after_queueing_is_honoured(monkeypatch, tutor):
    fakes = patch_channels(monkeypatch)
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        note = await _queued(session, user)
        contact = await session.scalar(select(ContactPoint))
        contact.suppressed_reason = SuppressionReason.opted_out
        contact.suppressed_at = note.created_at
        await send_notification(session, {"notification_id": note.id})
        assert note.status == NotificationStatus.suppressed
    assert fakes[WA].sent == []


async def test_nothing_is_sent_and_nothing_crashes_when_unconfigured(monkeypatch, tutor):
    """The dormant state: real adapters, no env vars."""
    async with async_session() as session:
        user = await session.get(User, tutor["user"]["id"])
        await add_contact(session, user.id, channel=WA, address="+201001234567")
        note = await _notify(session, user)
        assert note.status == NotificationStatus.channel_unconfigured
        assert note.error
