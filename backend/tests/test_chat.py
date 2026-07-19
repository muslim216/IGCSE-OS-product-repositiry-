import pytest

from app.db import async_session


@pytest.fixture
async def student(client, tutor):
    """A student in one of the tutor's groups."""
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    resp = await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Sara", "username": "sara", "password": "password123"},
        headers=tutor["headers"],
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara", "password": "password123"}
    )
    return {
        "id": resp.json()["id"],
        "headers": {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"},
    }


async def fake_stream(context, history):
    for chunk in ["Let's ", "work ", "through ", "it together."]:
        yield chunk


async def test_chat_flow(client, student, monkeypatch):
    monkeypatch.setattr("app.api.chat.stream_reply", fake_stream)

    convo = await client.post("/api/v1/chat/conversations", headers=student["headers"])
    assert convo.status_code == 201
    cid = convo.json()["id"]

    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{cid}/messages",
        json={"content": "Can you help me understand ionic bonding?"},
        headers=student["headers"],
    ) as resp:
        assert resp.status_code == 200
        body = ""
        async for line in resp.aiter_lines():
            body += line + "\n"
    assert '"text":' in body
    assert "event: done" in body

    detail = await client.get(
        f"/api/v1/chat/conversations/{cid}", headers=student["headers"]
    )
    messages = detail.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Let's work through it together."
    # Conversation title is derived from the first user message.
    assert detail.json()["title"].startswith("Can you help")


async def test_chat_without_api_key_streams_error(client, student):
    convo = await client.post("/api/v1/chat/conversations", headers=student["headers"])
    cid = convo.json()["id"]
    async with client.stream(
        "POST",
        f"/api/v1/chat/conversations/{cid}/messages",
        json={"content": "hello"},
        headers=student["headers"],
    ) as resp:
        assert resp.status_code == 200
        body = ""
        async for line in resp.aiter_lines():
            body += line + "\n"
    assert "event: error" in body
    assert "ANTHROPIC_API_KEY" in body

    # No assistant message is persisted when the AI fails.
    detail = await client.get(
        f"/api/v1/chat/conversations/{cid}", headers=student["headers"]
    )
    roles = [m["role"] for m in detail.json()["messages"]]
    assert roles == ["user"]


async def test_tutor_cannot_use_chat(client, tutor):
    resp = await client.post("/api/v1/chat/conversations", headers=tutor["headers"])
    assert resp.status_code == 403


async def test_cannot_access_other_students_conversation(client, student, tutor):
    convo = await client.post("/api/v1/chat/conversations", headers=student["headers"])
    cid = convo.json()["id"]

    # A second student
    group_resp = await client.get("/api/v1/groups", headers=tutor["headers"])
    gid = group_resp.json()[0]["id"]
    await client.post(
        f"/api/v1/groups/{gid}/students",
        json={"name": "Ali", "username": "ali", "password": "password123"},
        headers=tutor["headers"],
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "ali", "password": "password123"}
    )
    ali_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    resp = await client.get(f"/api/v1/chat/conversations/{cid}", headers=ali_headers)
    assert resp.status_code == 404
