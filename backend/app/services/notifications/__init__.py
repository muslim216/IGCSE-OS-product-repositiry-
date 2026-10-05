"""Notifications (task 8.1): WhatsApp first, email as the fallback."""

from app.services.notifications.service import SEND_JOB, notify, send_notification

__all__ = ["SEND_JOB", "notify", "send_notification"]
