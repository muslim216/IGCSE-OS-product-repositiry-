import asyncio
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# bcrypt takes about a quarter of a second by design, and the API and the job
# worker share one event loop: run on it, twenty concurrent sign-ins stalled
# every other request for five seconds (`SA-02`, `BE-13`). bcrypt releases the
# GIL while it hashes, so a thread really does run it alongside the loop.
#
# Its own two threads rather than the loop's shared pool: that pool is a
# handful of threads on a small instance and also carries every file read,
# write and photo conversion, so a burst of sign-ins (which need no account)
# would queue uploads behind it. Here a burst queues only other sign-ins.
_BCRYPT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bcrypt")


async def run_bcrypt(fn, *args):
    """Run a bcrypt-bound call off the event loop, in its own pool."""
    return await asyncio.get_running_loop().run_in_executor(_BCRYPT_POOL, fn, *args)


# Request handlers use these; the sync pair above stays for seeds and tests.
async def hash_password_async(password: str) -> str:
    return await run_bcrypt(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await run_bcrypt(verify_password, password, password_hash)


def _create_token(
    user_id: int, token_version: int, token_type: str, expires_delta: timedelta
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        user_id, token_version, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(
    user_id: int, token_version: int, session_id: int, generation: int, expires_at: datetime
) -> str:
    """A single-use refresh token: `sid`/`gen` name the session and which of its
    tokens this is (`services/refresh_sessions.py`, `SA-11`)."""
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "type": "refresh",
        "sid": session_id,
        "gen": generation,
        "iat": datetime.now(timezone.utc),
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_refresh_token(token: str) -> tuple[int, int, int, int] | None:
    """(user id, token version, session id, generation), or None. A refresh token
    from before sessions existed names none and is refused: its holder signs in
    again, once."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "refresh":
        return None
    try:
        return int(payload["sub"]), int(payload["tv"]), int(payload["sid"]), int(payload["gen"])
    except (KeyError, TypeError, ValueError):
        return None


def create_device_token(user_id: int) -> str:
    """Marks a browser that has signed in to this account, so its owner keeps a
    failed-sign-in allowance of their own that a stranger cannot spend (`SA-06`).
    Bound to the account, not to what was typed, so it holds whether the owner
    signs in by email or by username. It grants no access by itself."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "type": "device",
        "uid": user_id,
        "nonce": secrets.token_urlsafe(12),
        "iat": now,
        "exp": now + timedelta(days=settings.known_device_days),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def known_device(token: str | None, user_id: int) -> str | None:
    """This browser's id if `token` is a device token issued for `user_id`."""
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "device" or payload.get("uid") != user_id:
        return None
    nonce = payload.get("nonce")
    return nonce if isinstance(nonce, str) and nonce else None


#: OAuth round-trips leave the app and come back through Google. Ten minutes is
#: long enough for a consent screen and short enough that a captured state is
#: worthless by the time it is replayed.
STATE_TOKEN_TTL = timedelta(minutes=10)


def create_state_token(user_id: int, purpose: str) -> str:
    """A signed, expiring OAuth `state`, bound to the user who started the flow.

    The client also compares this against the copy it stashed before redirecting,
    which catches a callback that started in a different browser. That check
    alone is not enough — it lives in script the server cannot vouch for — so the
    server signs the value too and re-checks it on the way back. Without that,
    an attacker can hand a tutor a callback URL carrying the attacker's own
    authorization code and silently connect the attacker's Google account to
    the tutor's organization.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "oauth_state",
        "purpose": purpose,
        "nonce": secrets.token_urlsafe(8),
        "iat": now,
        "exp": now + STATE_TOKEN_TTL,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_state_token(token: str, user_id: int, purpose: str) -> bool:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return False
    if payload.get("type") != "oauth_state" or payload.get("purpose") != purpose:
        return False
    return payload.get("sub") == str(user_id)


def decode_token(token: str, expected_type: str) -> tuple[int, int] | None:
    """Return (user id, token version) if the token is valid and of the expected type.

    Never for a refresh token: those go through `decode_refresh_token`, because
    accepting one here would skip the single-use check in `rotate()` (`SA-11`).
    """
    if expected_type == "refresh":
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    try:
        return int(payload["sub"]), int(payload.get("tv", 0))
    except (KeyError, ValueError):
        return None
