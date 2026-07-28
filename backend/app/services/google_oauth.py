"""Google OAuth for the Classroom import.

Uses the REST endpoints through httpx directly. google-api-python-client is
sync-only, which would block the async worker, and this integration makes only
a handful of distinct calls.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GoogleAccount, GoogleAccountStatus

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# classroom.coursework.students.readonly covers both listing coursework and
# reading student submissions as the teacher. drive.readonly is unavoidable:
# Classroom returns attachment metadata only, never bytes, and drive.file is
# limited to files this app created.
SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly",
    "https://www.googleapis.com/auth/classroom.profile.emails",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Without these the import cannot work at all; Google's consent screen lets the
# user untick individual scopes, so what was granted has to be checked.
REQUIRED_SCOPES = {
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
}

STATE_TYPE = "google_oauth_state"


class GoogleReauthRequired(Exception):
    """The stored grant is gone — the tutor has to reconnect."""


def _require_enabled() -> None:
    if not get_settings().google_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Classroom is not configured on this server",
        )


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(get_settings().google_token_key.encode())


def encrypt_token(value: str | None) -> str | None:
    return None if value is None else _fernet().encrypt(value.encode()).decode()


def decrypt_token(value: str | None) -> str | None:
    if value is None:
        return None
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        # A rotated GOOGLE_TOKEN_KEY makes stored tokens unreadable; treat it
        # as a revoked grant rather than a crash.
        raise GoogleReauthRequired("Stored Google credentials could not be read") from None


def make_state(tutor_id: int) -> str:
    """Carry the tutor's identity through the redirect.

    The callback is a plain browser GET with no Authorization header, so who
    started the flow has to travel in `state` — signed, so it can't be forged.
    """
    settings = get_settings()
    return jwt.encode(
        {
            "sub": str(tutor_id),
            "type": STATE_TYPE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def read_state(state: str) -> int:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired state") from None
    if payload.get("type") != STATE_TYPE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid state")
    return int(payload["sub"])


def authorize_url(tutor_id: int) -> str:
    _require_enabled()
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        # Both are needed to actually receive a refresh token.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": make_state(tutor_id),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def missing_scopes(granted: str | None) -> list[str]:
    have = set((granted or "").split())
    return sorted(REQUIRED_SCOPES - have)


async def exchange_code(code: str) -> dict:
    _require_enabled()
    settings = get_settings()
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Google rejected the sign-in")
    return resp.json()


def id_token_claims(id_token: str) -> dict:
    """Read sub/email from the id_token.

    It came straight from Google's token endpoint over TLS, so the signature
    adds nothing here and verifying it would mean fetching and caching JWKS.
    """
    return jwt.decode(id_token, options={"verify_signature": False})


async def _refresh(account: GoogleAccount) -> dict:
    settings = get_settings()
    refresh_token = decrypt_token(account.refresh_token)
    if not refresh_token:
        raise GoogleReauthRequired("No refresh token stored")
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
    if resp.status_code != 200:
        # invalid_grant: revoked, password changed, or the 7-day expiry that
        # applies while the OAuth app is still in Testing.
        raise GoogleReauthRequired("Google access was revoked or expired")
    return resp.json()


async def ensure_access_token(session: AsyncSession, account: GoogleAccount) -> str:
    """Return a usable access token, refreshing shortly before it expires."""
    now = datetime.now(timezone.utc)
    expires = account.token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if account.access_token and expires and expires - timedelta(seconds=60) > now:
        token = decrypt_token(account.access_token)
        if token:
            return token

    try:
        data = await _refresh(account)
    except GoogleReauthRequired as exc:
        account.status = GoogleAccountStatus.needs_reauth
        account.last_error = str(exc)
        account.access_token = None
        await session.commit()
        raise

    account.access_token = encrypt_token(data["access_token"])
    account.token_expires_at = now + timedelta(seconds=int(data.get("expires_in", 3600)))
    account.status = GoogleAccountStatus.connected
    account.last_error = None
    if data.get("refresh_token"):
        account.refresh_token = encrypt_token(data["refresh_token"])
    await session.commit()
    return data["access_token"]


async def revoke(account: GoogleAccount) -> None:
    """Best effort — a failure here shouldn't block disconnecting locally."""
    token = None
    try:
        token = decrypt_token(account.refresh_token) or decrypt_token(account.access_token)
    except GoogleReauthRequired:
        return
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            await http.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        pass
