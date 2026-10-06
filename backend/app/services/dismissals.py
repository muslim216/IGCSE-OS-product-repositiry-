"""A tutor's "Not now" on what their home page asks of them.

A dismissal is a display choice and nothing else. The `key` is an opaque label
the frontend chose for the thing it hid (`chapter_prompt:12:340`); it is never
resolved to a row, so storing one grants no access to anything and a made-up key
reads back as exactly what it is, a label. That is why the key is validated for
shape and prefix only, and why the work-waiting list ("Needs you") has no prefix
here: hiding a student's unmarked work would let it silently never be marked.

Rows are scoped to the authenticated user and their organization, never to an
id from the path or body (`SEC-7`). The table cannot be filled: past
`MAX_DISMISSALS_PER_USER` a new hide is refused.
"""

import re

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DismissedPrompt, User

MAX_DISMISSALS_PER_USER = 500
MAX_KEY_LENGTH = 120

_KEY_PATTERN = re.compile(r"^[a-z0-9_:-]{1,120}$")

#: A key must be one of these exactly, or begin with one of the prefixes below it
#: followed by something. Adding a hideable thing means adding it here.
EXACT_KEYS = frozenset({"setup_guide"})
KEY_PREFIXES = (
    "setup_step:",
    "setup_checklist:",
    "chapter_prompt:",
    "lesson_reminder:",
)


class InvalidKey(ValueError):
    pass


class TooManyDismissals(Exception):
    pass


def validate_key(key: str) -> str:
    if not _KEY_PATTERN.fullmatch(key):
        raise InvalidKey("Key must be lowercase letters, digits, '_', ':' or '-', up to 120 long")
    if key in EXACT_KEYS:
        return key
    for prefix in KEY_PREFIXES:
        if key.startswith(prefix) and len(key) > len(prefix):
            return key
    raise InvalidKey("Unknown kind of prompt")


async def list_keys(db: AsyncSession, user: User) -> list[str]:
    rows = await db.scalars(
        select(DismissedPrompt.key)
        .where(
            DismissedPrompt.user_id == user.id,
            DismissedPrompt.organization_id == user.organization_id,
        )
        .order_by(DismissedPrompt.id)
    )
    return list(rows)


async def dismiss(db: AsyncSession, user: User, key: str) -> None:
    """Idempotent: hiding what is already hidden changes nothing."""
    key = validate_key(key)
    exists = await db.scalar(
        select(DismissedPrompt.id).where(
            DismissedPrompt.user_id == user.id, DismissedPrompt.key == key
        )
    )
    if exists is not None:
        return
    count = await db.scalar(
        select(func.count()).select_from(DismissedPrompt).where(DismissedPrompt.user_id == user.id)
    )
    if (count or 0) >= MAX_DISMISSALS_PER_USER:
        raise TooManyDismissals
    try:
        # A savepoint, so a lost race with a second tab (unique violation) is
        # swallowed without poisoning the request's transaction.
        async with db.begin_nested():
            db.add(DismissedPrompt(organization_id=user.organization_id, user_id=user.id, key=key))
    except IntegrityError:
        return
    await db.commit()


async def restore(db: AsyncSession, user: User, key: str) -> None:
    """Idempotent. An unknown or malformed key simply matches nothing."""
    await db.execute(
        delete(DismissedPrompt).where(
            DismissedPrompt.user_id == user.id, DismissedPrompt.key == key
        )
    )
    await db.commit()


async def restore_all(db: AsyncSession, user: User) -> None:
    await db.execute(delete(DismissedPrompt).where(DismissedPrompt.user_id == user.id))
    await db.commit()
