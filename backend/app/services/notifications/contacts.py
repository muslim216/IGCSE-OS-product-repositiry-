"""Contact points: validation, confirmation and suppression."""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ContactPoint,
    NotificationChannel,
    SuppressionReason,
    User,
    WhatsAppOptOut,
)

log = logging.getLogger("notifications")

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def _looks_like_email(value: str) -> bool:
    """One `@`, something before it, a dotted domain after it, no whitespace.
    Plain string checks, not a regex: the obvious pattern backtracks
    polynomially on input a caller controls (CodeQL py/polynomial-redos)."""
    if len(value) > 254 or any(ch.isspace() for ch in value):
        return False
    local, at, domain = value.partition("@")
    if not local or not at or "@" in domain:
        return False
    return all(domain.split(".")) and "." in domain


def normalize_address(channel: NotificationChannel, address: str) -> str:
    """The stored form of an address, or ValueError.

    WhatsApp numbers are stored as E.164 with the leading `+` — spaces, dashes
    and brackets a person types are stripped, but a number without a country
    code is refused rather than guessed at (a wrong guess messages a stranger).
    """
    raw = address.strip()
    if channel == NotificationChannel.whatsapp:
        cleaned = re.sub(r"[\s\-().]", "", raw)
        if not _E164.match(cleaned):
            raise ValueError("Enter the number in international format, e.g. +201001234567")
        return cleaned
    lowered = raw.lower()
    if not _looks_like_email(lowered):
        raise ValueError("Enter a valid email address")
    return lowered


async def contacts_for(session: AsyncSession, user_id: int) -> list[ContactPoint]:
    return list(
        await session.scalars(
            select(ContactPoint)
            .where(ContactPoint.user_id == user_id)
            .order_by(ContactPoint.channel)
        )
    )


async def _contact_row(
    session: AsyncSession, user_id: int, channel: NotificationChannel
) -> ContactPoint | None:
    return await session.scalar(
        select(ContactPoint).where(ContactPoint.user_id == user_id, ContactPoint.channel == channel)
    )


async def set_contact(
    session: AsyncSession,
    *,
    user: User,
    channel: NotificationChannel,
    address: str,
) -> ContactPoint:
    """Create or replace one person's address on a channel.

    A changed address clears the confirmation and any suppression: the tutor
    must see the new address and confirm it again (threat review F5), and a
    bounce belonged to the old address. Re-submitting the same address changes
    nothing, so a form that saves everything does not un-confirm a contact.

    An opt-out is the exception to "cleared": it is held against the *number*
    (`WhatsAppOptOut`), so a number that texted STOP arrives suppressed however
    many times a tutor re-enters it. Only that person's own START lifts it.
    """
    normalized = normalize_address(channel, address)
    contact = await _contact_row(session, user.id, channel)
    if contact is None:
        contact = ContactPoint(
            organization_id=user.organization_id,
            user_id=user.id,
            channel=channel,
            address=normalized,
        )
        try:
            async with session.begin_nested():
                session.add(contact)
                await session.flush()
        except IntegrityError:
            # Lost a race on (user, channel): take the row the other request
            # made and apply this address to it like any later edit.
            winner = await _contact_row(session, user.id, channel)
            if winner is None:
                raise
            contact = winner
    if contact.address != normalized:
        contact.address = normalized
        contact.confirmed_at = None
        contact.confirmed_by_id = None
        contact.suppressed_at = None
        contact.suppressed_reason = None
    if (
        channel == NotificationChannel.whatsapp
        and contact.suppressed_at is None
        and await number_opted_out(session, normalized)
    ):
        suppress_contact(contact, SuppressionReason.opted_out)
    await session.flush()
    return contact


def confirm_contact(contact: ContactPoint, confirmed_by: User) -> None:
    contact.confirmed_at = datetime.now(timezone.utc)
    contact.confirmed_by_id = confirmed_by.id


def suppress_contact(contact: ContactPoint, reason: SuppressionReason) -> None:
    if contact.suppressed_at is None:
        contact.suppressed_at = datetime.now(timezone.utc)
        contact.suppressed_reason = reason
        # The id, never the address: logs are not a place for a parent's number.
        log.info("contact %s suppressed: %s", contact.id, reason.value)


def e164(number: str) -> str:
    """Meta sends numbers without the `+` that ContactPoint.address stores."""
    return number if number.startswith("+") else f"+{number}"


async def number_opted_out(session: AsyncSession, number: str) -> bool:
    return (
        await session.scalar(
            select(WhatsAppOptOut.id).where(WhatsAppOptOut.address == e164(number))
        )
    ) is not None


async def record_opt_out(session: AsyncSession, number: str) -> None:
    """Remember that this number texted STOP. Idempotent — Meta redelivers."""
    if await number_opted_out(session, number):
        return
    try:
        async with session.begin_nested():
            session.add(WhatsAppOptOut(address=e164(number)))
            await session.flush()
    except IntegrityError:
        pass  # a concurrent delivery of the same STOP recorded it first


async def clear_opt_out(session: AsyncSession, number: str) -> None:
    await session.execute(delete(WhatsAppOptOut).where(WhatsAppOptOut.address == e164(number)))


async def whatsapp_contacts_for_number(session: AsyncSession, number: str) -> list[ContactPoint]:
    """Every WhatsApp contact holding this number. An opt-out is the *number's*,
    so it applies across organizations and people sharing it."""
    return list(
        await session.scalars(
            select(ContactPoint).where(
                ContactPoint.channel == NotificationChannel.whatsapp,
                ContactPoint.address == e164(number),
            )
        )
    )
