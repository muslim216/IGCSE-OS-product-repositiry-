"""The notification outbox: `notify()` records, `send_notification` delivers.

Nothing is sent from a request. `notify()` writes the outbox row and enqueues a
job carrying only its id (`BE-9`); the handler re-reads current state, so a
contact suppressed or a preference switched off between the two is honoured.

Three things this module deliberately does not do:

- **It does not resend what was skipped.** A row that ends `channel_unconfigured`
  (the server has no WhatsApp or SMTP settings yet), `no_channel` or `suppressed`
  is terminal. Configuring a channel later does not replay it: the messages are
  weekly summaries and reminders, and a stale one is worse than none.
- **It is at-least-once, not exactly-once.** A send the provider accepted but
  whose reply we never saw (a read timeout, a crash before the commit) is
  retried and can arrive twice. Neither WhatsApp nor SMTP offers an idempotency
  key to close that window; a duplicate reminder is the cheaper failure.
- **It never logs an address.** Ids, kinds and statuses only.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    ContactPoint,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationPreference,
    NotificationStatus,
    Organization,
    SuppressionReason,
    User,
)
from app.models.base import utcnow
from app.services.notifications.channels import Channel, ChannelError
from app.services.notifications.contacts import suppress_contact
from app.services.notifications.email import EmailChannel
from app.services.notifications.templates import clean_params, template_for
from app.services.notifications.whatsapp import WhatsAppChannel
from app.workers.jobs import MAX_ATTEMPTS, enqueue

log = logging.getLogger("notifications")

SEND_JOB = "send_notification"

#: WhatsApp first, email as the fallback (owner decision, task 8.1).
CHANNEL_ORDER = (NotificationChannel.whatsapp, NotificationChannel.email)


def channel_registry() -> dict[NotificationChannel, Channel]:
    """The delivery adapters. A function so tests substitute fakes by patching
    this one name rather than the network."""
    return {
        NotificationChannel.whatsapp: WhatsAppChannel(),
        NotificationChannel.email: EmailChannel(),
    }


@dataclass(frozen=True)
class Selection:
    #: Channels that can be tried now, best first.
    candidates: list[tuple[Channel, ContactPoint]]
    #: Set when `candidates` is empty.
    status: NotificationStatus | None = None
    reason: str | None = None


async def _enabled(session: AsyncSession, user_id: int, kind: NotificationKind) -> set:
    """Channels this user has *not* switched off for this kind."""
    off = set(
        await session.scalars(
            select(NotificationPreference.channel).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.kind == kind,
                NotificationPreference.enabled.is_(False),
            )
        )
    )
    return set(NotificationChannel) - off


async def select_channels(
    session: AsyncSession, recipient: User, kind: NotificationKind
) -> Selection:
    contacts = {
        c.channel: c
        for c in await session.scalars(
            select(ContactPoint).where(
                ContactPoint.user_id == recipient.id,
                # SEC-7: a contact from another tenant is never used, whatever
                # its user_id says.
                ContactPoint.organization_id == recipient.organization_id,
            )
        )
    }
    # STOP means everything (owner decision, 2026-10-05). A person who opts out
    # on one channel has said they do not want Avora messages; falling back to
    # their email would send a child's record somewhere they asked us not to
    # reach them, with nothing telling them why it kept coming.
    if any(c.suppressed_reason == SuppressionReason.opted_out for c in contacts.values()):
        return Selection([], NotificationStatus.suppressed, "This person opted out of messages")

    allowed = await _enabled(session, recipient.id, kind)
    registry = channel_registry()

    eligible: list[tuple[Channel, ContactPoint]] = []
    blocked = False
    for channel in CHANNEL_ORDER:
        contact = contacts.get(channel)
        if contact is None or contact.confirmed_at is None:
            continue
        if contact.suppressed_at is not None or channel not in allowed:
            blocked = True
            continue
        eligible.append((registry[channel], contact))

    usable = [(ch, c) for ch, c in eligible if ch.available()]
    if usable:
        return Selection(candidates=usable)
    if eligible:
        return Selection(
            [],
            NotificationStatus.channel_unconfigured,
            "The channel for this contact is not configured on the server",
        )
    if blocked:
        return Selection(
            [], NotificationStatus.suppressed, "Contact suppressed, or preference is off"
        )
    return Selection([], NotificationStatus.no_channel, "No confirmed contact for this person")


def _end(note: Notification, status: NotificationStatus, reason: str | None) -> None:
    """Put a notification in a terminal state and say so in the log: a row that
    ends anywhere but `sent` is otherwise visible only to someone reading the
    table."""
    note.status = status
    note.error = reason
    log.log(
        logging.INFO if status == NotificationStatus.sent else logging.WARNING,
        "notification %s (%s) ended %s: %s",
        note.id,
        note.kind.value,
        status.value,
        reason or "ok",
    )


async def notify(
    session: AsyncSession,
    *,
    recipient: User,
    kind: NotificationKind,
    params: dict,
    link_path: str,
    idempotency_key: str,
) -> Notification:
    """Record one notification and queue its delivery. Flushes, never commits —
    the caller's transaction owns the outbox row and the job together."""
    existing = await session.scalar(
        select(Notification).where(Notification.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing

    tpl = template_for(kind)
    if not link_path.startswith("/"):
        raise ValueError("link_path must be an absolute path on the app")
    note = Notification(
        organization_id=recipient.organization_id,
        recipient_user_id=recipient.id,
        kind=kind,
        template=tpl.whatsapp_name,
        params=clean_params(kind, params),
        link_path=link_path[:255],
        idempotency_key=idempotency_key,
        status=NotificationStatus.queued,
    )
    try:
        async with session.begin_nested():
            session.add(note)
            await session.flush()
    except IntegrityError:
        # Lost a race on the unique key: someone else queued the same send.
        winner = await session.scalar(
            select(Notification).where(Notification.idempotency_key == idempotency_key)
        )
        assert winner is not None
        return winner

    selection = await select_channels(session, recipient, kind)
    if selection.status is not None:
        _end(note, selection.status, selection.reason)
        await session.flush()
        return note
    await enqueue(session, SEND_JOB, {"notification_id": note.id})
    return note


async def _language(session: AsyncSession, organization_id: int) -> str:
    org = await session.get(Organization, organization_id)
    return org.ai_language if org is not None else "en"


def _suppress_for(channel: Channel, contact: ContactPoint) -> None:
    suppress_contact(
        contact,
        SuppressionReason.bounced
        if channel.name == NotificationChannel.email.value
        else SuppressionReason.provider_rejected,
    )


async def send_notification(session: AsyncSession, payload: dict) -> None:
    """Job handler. Safe to re-run (`BE-6`): only a `queued` row is acted on.

    Each channel is tried in order. A permanent failure ends the attempt on that
    channel and falls through to the next. A transient failure is raised for the
    worker to retry, after the attempt is committed — except on the last
    attempt, where it too falls through, so a WhatsApp outage still reaches the
    email fallback instead of ending the row. Whatever happens, the row leaves
    this function `queued` only if the job is going to run again: an unexpected
    exception on the last attempt is recorded as `failed` rather than left for a
    worker that will not come back.
    """
    note = await session.get(Notification, payload["notification_id"])
    if note is None or note.status != NotificationStatus.queued:
        return
    recipient = await session.get(User, note.recipient_user_id)
    if recipient is None:
        _end(note, NotificationStatus.failed, "Recipient no longer exists")
        return

    note.attempts += 1
    last_attempt = note.attempts >= MAX_ATTEMPTS
    selection = await select_channels(session, recipient, note.kind)
    if selection.status is not None:
        _end(note, selection.status, selection.reason)
        return

    link_url = get_settings().app_base_url.rstrip("/") + note.link_path
    language = await _language(session, note.organization_id)
    # Every channel's failure, in the order tried: the WhatsApp reason must not
    # be lost because the email fallback then failed differently.
    errors: list[str] = []
    for channel, contact in selection.candidates:
        try:
            message_id = await channel.send(
                contact.address, note.template, note.params, link_url, language=language
            )
        except ChannelError as exc:
            errors.append(f"{channel.name}: {exc}")
            log.warning(
                "notification %s: %s failed (%s): %s",
                note.id,
                channel.name,
                "permanent" if exc.permanent else "transient",
                exc,
            )
            if exc.permanent:
                if exc.suppress:
                    _suppress_for(channel, contact)
                continue
            if last_attempt:
                continue
            note.error = "; ".join(errors)[:1000]
            # The worker rolls the session back when a handler raises, so the
            # attempt count and error are committed first.
            await session.commit()
            raise
        except Exception as exc:
            # Not a delivery failure but a bug or a database error. Retry while
            # the worker still will; after that, end the row rather than leave
            # it `queued` with no job behind it.
            log.exception("notification %s: unexpected error on %s", note.id, channel.name)
            if last_attempt:
                await session.rollback()
                note = await session.get(Notification, payload["notification_id"])
                if note is not None:
                    note.attempts = MAX_ATTEMPTS
                    _end(note, NotificationStatus.failed, f"Unexpected error: {type(exc).__name__}")
                return
            raise
        note.channel = NotificationChannel(channel.name)
        note.provider_message_id = message_id
        note.sent_at = utcnow()
        # A fallback that worked is still worth seeing: keep why WhatsApp did not.
        _end(note, NotificationStatus.sent, "; ".join(errors)[:1000] or None)
        return
    _end(note, NotificationStatus.failed, "; ".join(errors)[:1000] or "No channel accepted it")
