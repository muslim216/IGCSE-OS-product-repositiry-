"""SMTP email adapter — the fallback channel. Provider-agnostic: any SMTP host."""

from email.message import EmailMessage
from email.utils import make_msgid

import aiosmtplib

from app.config import get_settings
from app.services.notifications.channels import ChannelError
from app.services.notifications.templates import render_email, template_by_name

_TIMEOUT_SECONDS = 15.0


class EmailChannel:
    name = "email"

    def available(self) -> bool:
        s = get_settings()
        return bool(s.smtp_host and s.smtp_from)

    async def send(
        self, address: str, template: str, params: dict, link_url: str, *, language: str = "en"
    ) -> str:
        # `language` is accepted for the Channel protocol; email copy is English
        # only for now.
        s = get_settings()
        if not self.available():
            raise ChannelError("Email is not configured", permanent=True)
        tpl = template_by_name(template)
        if tpl is None:
            raise ChannelError(f"Unknown template {template}", permanent=True)
        subject, body = render_email(tpl, params, link_url)
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = address
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()
        msg.set_content(body)
        try:
            await aiosmtplib.send(
                msg,
                hostname=s.smtp_host,
                port=s.smtp_port,
                username=s.smtp_username or None,
                password=s.smtp_password or None,
                start_tls=s.smtp_starttls,
                timeout=_TIMEOUT_SECONDS,
            )
        except aiosmtplib.SMTPRecipientsRefused as exc:
            raise ChannelError("Recipient refused", permanent=True, suppress=True) from exc
        except aiosmtplib.SMTPResponseException as exc:
            # 5xx is the server saying no for good; 4xx asks us to try later.
            raise ChannelError(
                f"SMTP {exc.code}", permanent=exc.code >= 500, suppress=exc.code in (550, 551, 553)
            ) from exc
        except (aiosmtplib.SMTPException, OSError) as exc:
            raise ChannelError(f"SMTP failed: {exc.__class__.__name__}", permanent=False) from exc
        # SMTP gives no message id back that we can correlate to; the Message-ID
        # header is ours to set if bounce tracking is ever wired.
        return str(msg["Message-ID"] or "smtp")
