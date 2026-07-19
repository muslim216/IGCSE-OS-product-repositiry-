import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.db import async_session
from app.models import (
    ChatConversation,
    ChatMessage,
    ChatRole,
    User,
    UserRole,
)
from app.schemas.chat import (
    ConversationDetail,
    ConversationOut,
    MessageOut,
    SendMessage,
)
from app.services.ai import AIUnavailableError
from app.services.student_context import build_student_context
from app.services.tutor_chat import stream_reply

router = APIRouter(prefix="/chat", tags=["chat"])

# Simple abuse guard: cap AI messages per student per rolling 24h.
DAILY_MESSAGE_LIMIT = 50


def _require_student(user: User) -> None:
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")


async def _owned_conversation(db, user: User, conversation_id: int) -> ChatConversation:
    convo = await db.get(ChatConversation, conversation_id)
    if convo is None or convo.student_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return convo


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(db: DbSession, user: CurrentUser) -> list[ConversationOut]:
    _require_student(user)
    rows = (
        await db.scalars(
            select(ChatConversation)
            .where(ChatConversation.student_id == user.id)
            .order_by(ChatConversation.updated_at.desc())
        )
    ).all()
    return [
        ConversationOut(id=c.id, title=c.title, updated_at=c.updated_at) for c in rows
    ]


@router.post("/conversations", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
async def create_conversation(db: DbSession, user: CurrentUser) -> ConversationDetail:
    _require_student(user)
    convo = ChatConversation(student_id=user.id, title="New chat")
    db.add(convo)
    await db.commit()
    return ConversationDetail(id=convo.id, title=convo.title, messages=[])


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int, db: DbSession, user: CurrentUser
) -> ConversationDetail:
    _require_student(user)
    convo = await _owned_conversation(db, user, conversation_id)
    messages = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == convo.id)
            .order_by(ChatMessage.id)
        )
    ).all()
    return ConversationDetail(
        id=convo.id,
        title=convo.title,
        messages=[
            MessageOut(id=m.id, role=m.role.value, content=m.content, created_at=m.created_at)
            for m in messages
        ],
    )


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int, body: SendMessage, db: DbSession, user: CurrentUser
) -> StreamingResponse:
    _require_student(user)
    convo = await _owned_conversation(db, user, conversation_id)

    since = datetime.now(timezone.utc) - timedelta(days=1)
    sent_today = await db.scalar(
        select(func.count(ChatMessage.id))
        .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
        .where(
            ChatConversation.student_id == user.id,
            ChatMessage.role == ChatRole.user,
            ChatMessage.created_at >= since,
        )
    )
    if (sent_today or 0) >= DAILY_MESSAGE_LIMIT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You've reached today's chat limit — take a break and try again tomorrow.",
        )

    # Persist the user's message and build history before streaming.
    db.add(ChatMessage(conversation_id=convo.id, role=ChatRole.user, content=body.content))
    if convo.title == "New chat":
        convo.title = body.content[:60]
    convo.updated_at = datetime.now(timezone.utc)
    await db.commit()

    history_rows = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == convo.id)
            .order_by(ChatMessage.id)
        )
    ).all()
    history = [{"role": m.role.value, "content": m.content} for m in history_rows]

    student = await db.get(User, user.id)
    context = await build_student_context(db, student)
    convo_id = convo.id

    async def event_stream() -> AsyncIterator[str]:
        collected: list[str] = []
        try:
            async for chunk in stream_reply(context, history):
                collected.append(chunk)
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except AIUnavailableError as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"
            return
        except Exception as exc:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'message': 'The tutor is unavailable right now. Please try again.'})}\n\n"
            return

        reply = "".join(collected).strip()
        if reply:
            async with async_session() as save_session:
                save_session.add(
                    ChatMessage(
                        conversation_id=convo_id, role=ChatRole.assistant, content=reply
                    )
                )
                saved_convo = await save_session.get(ChatConversation, convo_id)
                if saved_convo is not None:
                    saved_convo.updated_at = datetime.now(timezone.utc)
                await save_session.commit()
        yield f"event: done\ndata: {json.dumps({'ok': True})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: int, db: DbSession, user: CurrentUser
) -> None:
    _require_student(user)
    convo = await _owned_conversation(db, user, conversation_id)
    await db.delete(convo)
    await db.commit()
