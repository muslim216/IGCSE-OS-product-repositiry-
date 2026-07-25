import secrets
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


def _create_token(user_id: int, token_version: int, token_type: str, expires_delta: timedelta) -> str:
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


def create_refresh_token(user_id: int, token_version: int) -> str:
    settings = get_settings()
    return _create_token(
        user_id, token_version, "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


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
    """Return (user id, token version) if the token is valid and of the expected type."""
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
