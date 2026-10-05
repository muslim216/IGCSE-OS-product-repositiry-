"""WhatsApp Cloud API adapter (Meta).

Dormant until the owner registers with Meta: with any of the token or phone
number id unset, `available()` is False and nothing here is called.
"""

import httpx

from app.config import get_settings
from app.services.notifications.channels import ChannelError
from app.services.notifications.templates import (
    WHATSAPP_LANGUAGES,
    ordered_values,
    template_by_name,
)

_TIMEOUT = httpx.Timeout(10.0)

#: Graph error codes that mean the number itself cannot be messaged — retrying
#: or sending again later will not help, and the contact should stop receiving.
#: 131026: not a WhatsApp user / undeliverable; 131047: re-engagement window
#: closed is transient-ish and deliberately not listed; 131021: sender and
#: recipient are the same; 130429/131056: rate limits are transient.
PERMANENT_CODES = frozenset({131026, 131021, 131030, 131051, 131052, 131053, 132000, 132001})


def is_permanent_code(code: int | None) -> bool:
    return code in PERMANENT_CODES


def _endpoint() -> str:
    s = get_settings()
    return f"https://graph.facebook.com/{s.whatsapp_graph_version}/{s.whatsapp_phone_number_id}/messages"


class WhatsAppChannel:
    name = "whatsapp"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def available(self) -> bool:
        s = get_settings()
        return bool(s.whatsapp_access_token and s.whatsapp_phone_number_id)

    async def _post(self, payload: dict) -> str:
        if not self.available():
            raise ChannelError("WhatsApp is not configured", permanent=True)
        headers = {"Authorization": f"Bearer {get_settings().whatsapp_access_token}"}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
                resp = await client.post(_endpoint(), json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise ChannelError(
                f"WhatsApp request failed: {exc.__class__.__name__}", permanent=False
            ) from exc
        if resp.status_code >= 400:
            code = None
            message = f"WhatsApp rejected the message ({resp.status_code})"
            try:
                err = resp.json().get("error", {})
                code = err.get("code")
                message = f"{message}: {err.get('message', '')}"[:300]
            except ValueError:
                pass
            # 4xx other than throttling is the request or number being wrong;
            # 5xx and 429 are the provider's to recover from.
            permanent = is_permanent_code(code) or (
                resp.status_code < 500 and resp.status_code not in (408, 429)
            )
            raise ChannelError(message, permanent=permanent, suppress=is_permanent_code(code))
        messages = resp.json().get("messages") or []
        if not messages or not messages[0].get("id"):
            raise ChannelError("WhatsApp accepted the request but returned no id", permanent=False)
        return str(messages[0]["id"])

    async def send(
        self, address: str, template: str, params: dict, link_url: str, *, language: str = "en"
    ) -> str:
        tpl = template_by_name(template)
        if tpl is None:
            raise ChannelError(f"Unknown WhatsApp template {template}", permanent=True)
        values = ordered_values(tpl, params, link_url)
        payload = {
            "messaging_product": "whatsapp",
            "to": address.lstrip("+"),
            "type": "template",
            "template": {
                "name": template,
                "language": {"code": WHATSAPP_LANGUAGES.get(language, "en")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": v} for v in values],
                    }
                ],
            },
        }
        return await self._post(payload)

    async def send_text(self, address: str, body: str) -> str:
        """Free-form text, allowed only inside the 24h window after an inbound
        message — which is the only place the auto-reply uses it."""
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": address.lstrip("+"),
                "type": "text",
                "text": {"body": body},
            }
        )
