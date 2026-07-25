"""Invite lifetime and single-use policy.

Invite codes are the one credential that travels outside the app — they get
pasted into WhatsApp groups, printed on handouts, forwarded to a parent. So
they are bounded in two ways, and both rules live here rather than in the
routers that mint them:

- **Everything expires.** An unbounded code is a permanent, unauthenticated
  path into a tutor's organization for anyone who ever saw it.
- **Parent links are single-use.** A parent-link code grants a stranger the
  complete academic record of one named child, and it is meant for exactly one
  parent. A group-join code is deliberately still multi-use — a tutor shares
  one link with a whole class — so an expiry is all that bounds it.
"""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.models import Invite, InviteKind

#: How long a freshly minted code stays usable.
STUDENT_JOIN_TTL = timedelta(days=14)
PARENT_LINK_TTL = timedelta(days=14)

#: Kinds that are consumed by the first account that redeems them.
SINGLE_USE_KINDS = frozenset({InviteKind.parent_link})

_TTLS = {
    InviteKind.student_join: STUDENT_JOIN_TTL,
    InviteKind.parent_link: PARENT_LINK_TTL,
}


def build_invite(
    kind: InviteKind,
    *,
    created_by_id: int,
    group_id: int | None = None,
    student_id: int | None = None,
) -> Invite:
    """A new invite with its expiry already set. 64 bits of entropy, which is
    not guessable, but the code is shared by hand so it is treated as public
    the moment it is issued — the expiry is what actually bounds it."""
    return Invite(
        code=secrets.token_urlsafe(8),
        kind=kind,
        group_id=group_id,
        student_id=student_id,
        created_by_id=created_by_id,
        expires_at=datetime.now(timezone.utc) + _TTLS[kind],
    )


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone=True columns.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def is_expired(invite: Invite) -> bool:
    return invite.expires_at is not None and _aware(invite.expires_at) < datetime.now(timezone.utc)


def is_used(invite: Invite) -> bool:
    return invite.kind in SINGLE_USE_KINDS and invite.used_at is not None


def check_usable(invite: Invite) -> None:
    """Raise if this code can no longer be redeemed. Expiry and exhaustion are
    reported apart from 'no such code' so a tutor can tell a confused parent
    which one it is and reissue."""
    if is_used(invite):
        raise HTTPException(
            status.HTTP_410_GONE,
            "This invite link has already been used — ask for a new one",
        )
    if is_expired(invite):
        raise HTTPException(status.HTTP_410_GONE, "This invite link has expired")


def consume(invite: Invite) -> None:
    """Mark a single-use code redeemed. A no-op for multi-use kinds, so callers
    can call it unconditionally after a successful redemption."""
    if invite.kind in SINGLE_USE_KINDS:
        invite.used_at = datetime.now(timezone.utc)
