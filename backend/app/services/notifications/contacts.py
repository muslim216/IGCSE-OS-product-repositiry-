"""Contact points: validation, confirmation and suppression."""

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContactPoint, NotificationChannel, SuppressionReason, User

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    if len(lowered) > 254 or not _EMAIL.match(lowered):
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


async def set_contact(
    session: AsyncSession,
    *,
    user: User,
    channel: NotificationChannel,
    address: str,
) -> ContactPoint:
    """Create or replace one person's address on a channel.

    A changed address clears the confirmation and any suppression: the tutor
    must see the new address and confirm it again (threat review F5), and an
    opt-out belonged to the old number. Re-submitting the same address changes
    nothing, so a form that saves everything does not un-confirm a contact.
    """
    normalized = normalize_address(channel, address)
    contact = await session.scalar(
        select(ContactPoint).where(ContactPoint.user_id == user.id, ContactPoint.channel == channel)
    )
    if contact is None:
        contact = ContactPoint(
            organization_id=user.organization_id,
            user_id=user.id,
            channel=channel,
            address=normalized,
        )
        session.add(contact)
    elif contact.address != normalized:
        contact.address = normalized
        contact.confirmed_at = None
        contact.confirmed_by_id = None
        contact.suppressed_at = None
        contact.suppressed_reason = None
    await session.flush()
    return contact


def confirm_contact(contact: ContactPoint, confirmed_by: User) -> None:
    contact.confirmed_at = datetime.now(timezone.utc)
    contact.confirmed_by_id = confirmed_by.id


def suppress_contact(contact: ContactPoint, reason: SuppressionReason) -> None:
    if contact.suppressed_at is None:
        contact.suppressed_at = datetime.now(timezone.utc)
        contact.suppressed_reason = reason


async def whatsapp_contacts_for_number(session: AsyncSession, number: str) -> list[ContactPoint]:
    """Every WhatsApp contact holding this number. An opt-out is the *number's*,
    so it applies across organizations and people sharing it."""
    e164 = number if number.startswith("+") else f"+{number}"
    return list(
        await session.scalars(
            select(ContactPoint).where(
                ContactPoint.channel == NotificationChannel.whatsapp,
                ContactPoint.address == e164,
            )
        )
    )
