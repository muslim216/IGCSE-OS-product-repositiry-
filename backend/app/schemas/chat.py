from datetime import datetime

from pydantic import BaseModel, Field


class ConversationOut(BaseModel):
    id: int
    title: str
    updated_at: datetime


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationDetail(BaseModel):
    id: int
    title: str
    messages: list[MessageOut]


class SendMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
