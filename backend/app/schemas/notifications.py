from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import NotificationChannel, NotificationKind, SuppressionReason


class ContactOut(BaseModel):
    id: int
    channel: NotificationChannel
    address: str
    confirmed_at: datetime | None
    confirmed_by_id: int | None
    suppressed_at: datetime | None
    suppressed_reason: SuppressionReason | None


class PersonContactsOut(BaseModel):
    user_id: int
    name: str
    role: str
    contacts: list[ContactOut]


class ContactSet(BaseModel):
    # The student themself when omitted; otherwise one of the student's parents.
    user_id: int | None = None
    channel: NotificationChannel
    address: str = Field(min_length=3, max_length=255)


class SelfContactSet(BaseModel):
    channel: NotificationChannel
    address: str = Field(min_length=3, max_length=255)


class PreferenceItem(BaseModel):
    kind: NotificationKind
    channel: NotificationChannel
    enabled: bool


class PreferencesUpdate(BaseModel):
    preferences: list[PreferenceItem] = Field(max_length=64)


class ChannelStatusOut(BaseModel):
    # Booleans only — never a secret or any part of one.
    whatsapp_configured: bool
    email_configured: bool


AiLanguage = Literal["en", "ar"]


class OrganizationSettingsUpdate(BaseModel):
    """Only the fields sent are changed."""

    weekly_send_weekday: int | None = Field(default=None, ge=0, le=6)
    weekly_send_hour: int | None = Field(default=None, ge=0, le=23)
    ai_language: AiLanguage | None = None
