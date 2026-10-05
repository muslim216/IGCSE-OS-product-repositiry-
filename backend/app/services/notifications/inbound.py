"""Handling what WhatsApp posts to us: delivery statuses and inbound messages.

There is no in-app messaging and no human inbox (owner decision, task 8.1): a
person who writes back gets an automatic reply, and STOP/START are the only
words that do anything.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ContactPoint,
    Notification,
    NotificationChannel,
    NotificationStatus,
    SuppressionReason,
)
from app.services.notifications.contacts import suppress_contact, whatsapp_contacts_for_number
from app.services.notifications.whatsapp import WhatsAppChannel, is_permanent_code

log = logging.getLogger("notifications")

Reply = Callable[[str, str], Awaitable[None]]

STOP_WORDS = frozenset({"stop", "unsubscribe", "إيقاف"})
START_WORDS = frozenset({"start"})

STOPPED_REPLY = (
    "You will no longer get Avora messages on WhatsApp. Reply START to turn them back on."
)
STARTED_REPLY = "Avora messages are back on."
AUTO_REPLY = (
    "This number only sends Avora updates and isn't monitored. Please contact your tutor directly."
)


def _word(text: str) -> str:
    return " ".join(text.split()).casefold()


async def send_reply(address: str, body: str) -> None:
    """The default reply path. Never raises: a failed courtesy reply must not
    make Meta retry a webhook we have already handled."""
    channel = WhatsAppChannel()
    if not channel.available():
        return
    try:
        await channel.send_text(address, body)
    except Exception:  # noqa: BLE001 — see docstring
        log.warning("could not send a WhatsApp auto-reply", exc_info=True)


async def _status(session: AsyncSession, status: dict) -> None:
    message_id = status.get("id")
    if not message_id:
        return
    note = await session.scalar(
        select(Notification).where(Notification.provider_message_id == message_id)
    )
    if note is None or status.get("status") != "failed":
        return
    errors = status.get("errors") or [{}]
    code = errors[0].get("code")
    note.status = NotificationStatus.failed
    note.error = f"WhatsApp delivery failed (code {code})"[:300]
    if is_permanent_code(code):
        contact = await session.scalar(
            select(ContactPoint).where(
                ContactPoint.user_id == note.recipient_user_id,
                ContactPoint.channel == NotificationChannel.whatsapp,
            )
        )
        if contact is not None:
            suppress_contact(contact, SuppressionReason.provider_rejected)


async def _message(session: AsyncSession, message: dict, reply: Reply) -> None:
    sender = message.get("from")
    if not sender:
        return
    text = message.get("text", {}).get("body", "") if message.get("type") == "text" else ""
    word = _word(text)
    contacts = await whatsapp_contacts_for_number(session, sender)
    if word in STOP_WORDS:
        for contact in contacts:
            suppress_contact(contact, SuppressionReason.opted_out)
        await reply(sender, STOPPED_REPLY)
    elif word in START_WORDS:
        for contact in contacts:
            # Only an opt-out is the person's to undo; a number WhatsApp
            # rejected stays suppressed whatever they type.
            if contact.suppressed_reason == SuppressionReason.opted_out:
                contact.suppressed_at = None
                contact.suppressed_reason = None
        await reply(sender, STARTED_REPLY)
    else:
        await reply(sender, AUTO_REPLY)


async def process_webhook(session: AsyncSession, payload: dict, reply: Reply | None = None) -> None:
    # Resolved at call time so a test can substitute `send_reply`.
    reply = reply or send_reply
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for status in value.get("statuses") or []:
                await _status(session, status)
            for message in value.get("messages") or []:
                await _message(session, message, reply)
