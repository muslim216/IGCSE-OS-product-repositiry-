"""Inbound WhatsApp webhooks (task 8.1).

These two routes are unauthenticated on purpose — Meta cannot hold a bearer
token. The control is the shared secret: the GET handshake checks the verify
token, and every POST must carry an `X-Hub-Signature-256` HMAC of the raw body
under the app secret. An unset secret rejects everything rather than trusting
anything (the channel is dormant until the owner registers with Meta).
"""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.api.deps import DbSession
from app.config import get_settings
from app.services.notifications import inbound

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger("api")


def _valid_signature(secret: str | None, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.get("/whatsapp")
async def verify_whatsapp(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    expected = get_settings().whatsapp_verify_token
    if (
        mode != "subscribe"
        or not expected
        or token is None
        or not hmac.compare_digest(token.encode(), expected.encode())
        or challenge is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification failed")
    return Response(content=challenge, media_type="text/plain")


@router.post("/whatsapp")
async def receive_whatsapp(request: Request, db: DbSession) -> dict[str, str]:
    body = await request.body()
    if not _valid_signature(
        get_settings().whatsapp_app_secret, body, request.headers.get("X-Hub-Signature-256")
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    try:
        payload = json.loads(body)
    except ValueError:
        # Signed but malformed: acknowledge, or Meta retries it forever.
        return {"status": "ignored"}
    if isinstance(payload, dict):
        try:
            await inbound.process_webhook(db, payload)
            await db.commit()
        except Exception:  # noqa: BLE001 — a 5xx would make Meta redeliver
            log.exception("could not process a WhatsApp webhook")
            await db.rollback()
    return {"status": "ok"}
