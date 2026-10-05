"""Handling what WhatsApp posts to us: delivery statuses and inbound messages.

There is no in-app messaging and no human inbox (owner decision, task 8.1): a
person who writes back gets an automatic reply, and STOP/START are the only
words that do anything.

`process_webhook` changes rows and returns the replies it wants sent; it sends
nothing itself. The route sends them only after its commit succeeds, so nobody
is told "you are unsubscribed" about an opt-out that then failed to save.
"""

import logging
import re
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ContactPoint,
    Notification,
    NotificationChannel,
    NotificationStatus,
    SuppressionReason,
    User,
)
from app.services.notifications.contacts import (
    clear_opt_out,
    record_opt_out,
    suppress_contact,
    whatsapp_contacts_for_number,
)
from app.services.notifications.whatsapp import WhatsAppChannel, is_permanent_code
from app.workers.jobs import enqueue

log = logging.getLogger("notifications")

#: (number, text) pairs for the route to send once its commit has succeeded.
Replies = list[tuple[str, str]]

STOP_WORDS = frozenset({"stop", "unsubscribe", "إيقاف"})
START_WORDS = frozenset({"start"})

STOPPED_REPLY = (
    "You will no longer get Avora messages, on WhatsApp or by email. "
    "Reply START to turn them back on."
)
STARTED_REPLY = "Avora messages are back on."
AUTO_REPLY = (
    "This number only sends Avora updates and isn't monitored. Please contact your tutor directly."
)

#: One auto-reply per number per hour. Without it two auto-responders (ours and
#: a business number's, or a person's away message) answer each other for as
#: long as both are up. In process memory because the API runs as one instance
#: (`RISK-1`); a second instance would at worst double the allowance. STOP and
#: START replies are never throttled — they confirm something the person did.
AUTO_REPLY_INTERVAL_SECONDS = 3600.0
_last_auto_reply: dict[str, float] = {}


def _first_word(text: str) -> str:
    """The message's first word, lowercased, without punctuation — so "Stop.",
    "STOP please" and " stop!" are all the opt-out they were meant as."""
    words = re.findall(r"[^\W\d_]+", text.casefold())
    return words[0] if words else ""


def _auto_reply_due(sender: str, now: float) -> bool:
    if len(_last_auto_reply) > 10_000:
        cutoff = now - AUTO_REPLY_INTERVAL_SECONDS
        for key in [k for k, at in _last_auto_reply.items() if at < cutoff]:
            del _last_auto_reply[key]
    last = _last_auto_reply.get(sender)
    if last is not None and now - last < AUTO_REPLY_INTERVAL_SECONDS:
        return False
    _last_auto_reply[sender] = now
    return True


async def send_reply(address: str, body: str) -> None:
    """Send one reply. Never raises: the webhook is already handled and
    committed by the time this runs, so a failure here must not make Meta
    redeliver it. A reply that confirms an opt-out and did not go out is logged
    as an error — the person was not told their STOP worked."""
    channel = WhatsAppChannel()
    if not channel.available():
        return
    try:
        await channel.send_text(address, body)
    except Exception:  # noqa: BLE001 — see docstring
        level = logging.ERROR if body == STOPPED_REPLY else logging.WARNING
        log.log(level, "could not send a WhatsApp reply", exc_info=True)


async def _has_email_fallback(session: AsyncSession, note: Notification) -> bool:
    # Imported here: service imports this package's contacts, and the route
    # imports both — a module-level import would be circular.
    from app.services.notifications.service import select_channels

    recipient = await session.get(User, note.recipient_user_id)
    if recipient is None:
        return False
    return bool((await select_channels(session, recipient, note.kind)).candidates)


async def _status(session: AsyncSession, status: dict) -> None:
    message_id = status.get("id")
    if not message_id or status.get("status") != "failed":
        return
    note = await session.scalar(
        select(Notification).where(Notification.provider_message_id == message_id)
    )
    if note is None:
        # A send whose commit failed after the provider accepted it has no id
        # stored, so its failure report lands here. Say so rather than drop it.
        log.warning("WhatsApp reported a failure for a message id we do not hold")
        return
    # Meta redelivers; only a row still showing the WhatsApp send is acted on.
    if note.status != NotificationStatus.sent or note.channel != NotificationChannel.whatsapp:
        return
    errors = status.get("errors") or [{}]
    code = errors[0].get("code") if isinstance(errors[0], dict) else None
    reason = f"WhatsApp delivery failed (code {code})"[:300]
    log.warning("notification %s: %s", note.id, reason)
    note.status = NotificationStatus.failed
    note.error = reason
    if not is_permanent_code(code):
        return
    contact = await session.scalar(
        select(ContactPoint).where(
            ContactPoint.user_id == note.recipient_user_id,
            ContactPoint.channel == NotificationChannel.whatsapp,
        )
    )
    # Changing an address clears its confirmation, so a contact confirmed after
    # this message went out is a different number from the one that failed.
    if (
        contact is not None
        and contact.confirmed_at is not None
        and note.sent_at is not None
        and contact.confirmed_at <= note.sent_at
    ):
        suppress_contact(contact, SuppressionReason.provider_rejected)
        await session.flush()
    # WhatsApp reports most undeliverable numbers here, after accepting the
    # send. The message has not reached anyone, so give the fallback its turn.
    if await _has_email_fallback(session, note):
        from app.services.notifications.service import SEND_JOB

        note.status = NotificationStatus.queued
        note.channel = None
        note.provider_message_id = None
        await enqueue(session, SEND_JOB, {"notification_id": note.id})


async def _message(session: AsyncSession, message: dict, replies: Replies) -> None:
    sender = message.get("from")
    if not sender:
        return
    body = message.get("text") if message.get("type") == "text" else None
    text = body.get("body", "") if isinstance(body, dict) else ""
    word = _first_word(text if isinstance(text, str) else "")
    contacts = await whatsapp_contacts_for_number(session, sender)
    if word in STOP_WORDS:
        # Recorded against the number whether or not we hold a contact for it:
        # the opt-out has to be there when a tutor enters this number later.
        await record_opt_out(session, sender)
        for contact in contacts:
            suppress_contact(contact, SuppressionReason.opted_out)
        log.info("a WhatsApp number opted out (%d contact rows)", len(contacts))
        replies.append((sender, STOPPED_REPLY))
    elif word in START_WORDS:
        await clear_opt_out(session, sender)
        for contact in contacts:
            # Only an opt-out is the person's to undo; a number WhatsApp
            # rejected stays suppressed whatever they type.
            if contact.suppressed_reason == SuppressionReason.opted_out:
                contact.suppressed_at = None
                contact.suppressed_reason = None
        log.info("a WhatsApp number opted back in (%d contact rows)", len(contacts))
        replies.append((sender, STARTED_REPLY))
    elif _auto_reply_due(sender, time.monotonic()):
        replies.append((sender, AUTO_REPLY))


async def process_webhook(session: AsyncSession, payload: dict) -> Replies:
    """Apply one webhook delivery and return the replies to send after the
    caller commits. Safe to run twice on the same payload — a failed delivery
    is answered with a 5xx precisely so that Meta sends it again."""
    replies: Replies = []
    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            value = (change.get("value") if isinstance(change, dict) else None) or {}
            if not isinstance(value, dict):
                continue
            for status in value.get("statuses") or []:
                if isinstance(status, dict):
                    await _status(session, status)
            for message in value.get("messages") or []:
                if isinstance(message, dict):
                    await _message(session, message, replies)
    return replies
