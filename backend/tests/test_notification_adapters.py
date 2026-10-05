"""The WhatsApp and SMTP adapters, against fake transports (no network, QA-8)."""

import json

import httpx
import pytest

from app.config import get_settings
from app.services.notifications import email as email_module
from app.services.notifications.channels import ChannelError
from app.services.notifications.email import EmailChannel
from app.services.notifications.whatsapp import WhatsAppChannel

PARAMS = {"student_name": "Sara", "subject_name": "Chemistry", "due_date": "Mon"}


@pytest.fixture
def configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_access_token", "tok")
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "555")


def _channel(handler) -> WhatsAppChannel:
    return WhatsAppChannel(transport=httpx.MockTransport(handler))


def test_unset_settings_make_both_channels_unavailable():
    assert WhatsAppChannel().available() is False
    assert EmailChannel().available() is False


async def test_sending_while_unconfigured_is_a_permanent_error_not_a_crash():
    with pytest.raises(ChannelError) as err:
        await WhatsAppChannel().send("+201001234567", "avora_homework_set", PARAMS, "https://x")
    assert err.value.permanent


async def test_template_message_shape(configured):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.9"}]})

    mid = await _channel(handler).send(
        "+201001234567", "avora_homework_set", PARAMS, "https://app/h", language="ar"
    )
    assert mid == "wamid.9"
    assert seen["url"] == "https://graph.facebook.com/v21.0/555/messages"
    assert seen["auth"] == "Bearer tok"
    body = seen["body"]
    assert body["to"] == "201001234567"
    assert body["type"] == "template"
    assert body["template"]["name"] == "avora_homework_set"
    assert body["template"]["language"] == {"code": "ar"}
    texts = [p["text"] for p in body["template"]["components"][0]["parameters"]]
    assert texts == ["Sara", "Chemistry", "Mon", "https://app/h"]


async def test_free_text_for_the_auto_reply(configured):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    await _channel(handler).send_text("+201001234567", "hello")
    assert seen["type"] == "text"
    assert seen["text"] == {"body": "hello"}


@pytest.mark.parametrize(
    ("status", "code", "permanent", "suppress"),
    [
        (400, 131026, True, True),
        (400, 100, True, False),
        (429, 130429, False, False),
        (500, None, False, False),
    ],
)
async def test_error_mapping(configured, status, code, permanent, suppress):
    def handler(request):
        body = {"error": {"code": code, "message": "no"}} if code else {}
        return httpx.Response(status, json=body)

    with pytest.raises(ChannelError) as err:
        await _channel(handler).send("+201001234567", "avora_homework_set", PARAMS, "https://x")
    assert (err.value.permanent, err.value.suppress) == (permanent, suppress)


async def test_a_network_failure_is_transient(configured):
    def handler(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ChannelError) as err:
        await _channel(handler).send("+201001234567", "avora_homework_set", PARAMS, "https://x")
    assert err.value.permanent is False


async def test_email_renders_and_sends_through_smtp(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "avora@example.com")
    sent = {}

    async def fake_send(msg, **kwargs):
        sent["msg"], sent["kwargs"] = msg, kwargs

    monkeypatch.setattr(email_module.aiosmtplib, "send", fake_send)
    mid = await EmailChannel().send("a@b.co", "avora_homework_set", PARAMS, "https://app/h")
    assert sent["msg"]["To"] == "a@b.co"
    assert "Sara" in sent["msg"]["Subject"]
    assert "https://app/h" in sent["msg"].get_content()
    assert sent["kwargs"]["hostname"] == "smtp.example.com"
    assert mid == sent["msg"]["Message-ID"]


async def test_email_refusal_is_permanent_and_suppresses(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "avora@example.com")

    async def refuse(msg, **kwargs):
        raise email_module.aiosmtplib.SMTPRecipientsRefused([])

    monkeypatch.setattr(email_module.aiosmtplib, "send", refuse)
    with pytest.raises(ChannelError) as err:
        await EmailChannel().send("a@b.co", "avora_homework_set", PARAMS, "https://x")
    assert (err.value.permanent, err.value.suppress) == (True, True)


@pytest.mark.parametrize("status", [401, 403])
async def test_refused_credentials_are_an_alarm_not_a_bad_number(configured, status, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": 190, "message": "token expired"}})

    with caplog.at_level("ERROR", logger="notifications"), pytest.raises(ChannelError) as err:
        await _channel(handler).send("+201001234567", "avora_homework_set", PARAMS, "https://x")
    assert (err.value.permanent, err.value.suppress) == (True, False)
    assert "credentials" in caplog.text
    assert "Bearer" not in caplog.text and "201001234567" not in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>gateway</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"messages": ["wamid.1"]}),
        httpx.Response(400, json={"error": "a string, not an object"}),
        httpx.Response(400, json=["nope"]),
    ],
)
async def test_an_unexpected_reply_shape_is_a_channel_error_not_a_crash(configured, response):
    with pytest.raises(ChannelError):
        await _channel(lambda request: response).send(
            "+201001234567", "avora_homework_set", PARAMS, "https://x"
        )


async def test_smtp_credentials_are_never_sent_without_tls(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "avora@example.com")
    monkeypatch.setattr(s, "smtp_username", "user")
    monkeypatch.setattr(s, "smtp_password", "secret")
    monkeypatch.setattr(s, "smtp_starttls", False)

    async def must_not_send(msg, **kwargs):
        raise AssertionError("sent credentials in clear text")

    monkeypatch.setattr(email_module.aiosmtplib, "send", must_not_send)
    with pytest.raises(ChannelError) as err:
        await EmailChannel().send("a@b.co", "avora_homework_set", PARAMS, "https://x")
    assert err.value.permanent


async def test_implicit_tls_replaces_starttls(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "avora@example.com")
    monkeypatch.setattr(s, "smtp_use_tls", True)
    seen = {}

    async def fake_send(msg, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(email_module.aiosmtplib, "send", fake_send)
    await EmailChannel().send("a@b.co", "avora_homework_set", PARAMS, "https://x")
    assert (seen["use_tls"], seen["start_tls"]) == (True, False)
