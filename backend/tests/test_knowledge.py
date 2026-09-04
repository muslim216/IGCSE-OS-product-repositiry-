"""Tutor Knowledge Base: CRUD + injection into AI surfaces, and the AI usage
metering view.

0.5 (AV-58) unmounted knowledge.router from the production app — the surface
is hidden, not deleted, so its code, service and tables stay live and this
file keeps exercising them. The `client` fixture below shadows conftest's: it
mounts knowledge.router onto a fresh app instance so these tests reach it even
though a real deployment can't. `test_knowledge_route_is_hidden_in_production`
proves the other half — that the real app genuinely can't."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import knowledge
from app.db import async_session
from app.main import app as production_app
from app.main import create_app
from app.models import AiFeature, AiUsageEvent, User
from app.services.knowledge import build_tutor_context
from tests.factories import subject_defaults


@pytest.fixture
async def client():
    """Overrides conftest's `client`: a fresh app with knowledge.router mounted
    on top of everything production mounts, so `tutor`/`student` and every
    other conftest fixture that depends on `client` still work unchanged —
    this app is a superset of production, not a different one."""
    app = create_app()
    app.include_router(knowledge.router, prefix="/api/v1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_knowledge_route_is_hidden_in_production():
    """The other half of 0.5: not just that knowledge works when mounted
    (every other test in this file), but that the real app genuinely does not
    mount it. A route that is merely untested is not the same as one that is
    unreachable."""
    transport = ASGITransport(app=production_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/knowledge")
    assert resp.status_code == 404


async def test_create_list_update_delete_entry(client, tutor):
    create = await client.post(
        "/api/v1/knowledge",
        json={
            "kind": "teaching_method",
            "title": "Always start with a worked example",
            "body": "Before assigning practice, walk through one fully worked example.",
        },
        headers=tutor["headers"],
    )
    assert create.status_code == 201, create.text
    entry = create.json()
    assert entry["kind"] == "teaching_method"

    listing = await client.get("/api/v1/knowledge", headers=tutor["headers"])
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    updated = await client.patch(
        f"/api/v1/knowledge/{entry['id']}",
        json={
            "kind": "marking_preference",
            "title": "Be strict on units",
            "body": "Always deduct a mark for missing SI units.",
        },
        headers=tutor["headers"],
    )
    assert updated.status_code == 200
    assert updated.json()["kind"] == "marking_preference"
    assert updated.json()["title"] == "Be strict on units"

    deleted = await client.delete(f"/api/v1/knowledge/{entry['id']}", headers=tutor["headers"])
    assert deleted.status_code == 204
    listing2 = await client.get("/api/v1/knowledge", headers=tutor["headers"])
    assert listing2.json() == []


async def test_entry_access_control(client, tutor):
    create = await client.post(
        "/api/v1/knowledge",
        json={"kind": "note", "title": "Private note", "body": "Some tutor-only note."},
        headers=tutor["headers"],
    )
    entry_id = create.json()["id"]

    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-kb@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    # Another tutor can't see or edit this entry, and their own list is empty.
    listing = await client.get("/api/v1/knowledge", headers=other_headers)
    assert listing.json() == []
    edit = await client.patch(
        f"/api/v1/knowledge/{entry_id}",
        json={"kind": "note", "title": "x", "body": "y"},
        headers=other_headers,
    )
    assert edit.status_code == 404


async def test_subject_scoped_filtering(client, tutor):
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    await client.post(
        "/api/v1/knowledge",
        json={"kind": "note", "title": "General note", "body": "Applies everywhere."},
        headers=tutor["headers"],
    )
    await client.post(
        "/api/v1/knowledge",
        json={
            "kind": "solving_approach",
            "title": "Chemistry-specific approach",
            "body": "Always balance equations before answering.",
            "subject_id": subject_id,
        },
        headers=tutor["headers"],
    )

    filtered = await client.get(
        f"/api/v1/knowledge?subject_id={subject_id}", headers=tutor["headers"]
    )
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["title"] == "Chemistry-specific approach"

    unfiltered = await client.get("/api/v1/knowledge", headers=tutor["headers"])
    assert len(unfiltered.json()) == 2


async def test_build_tutor_context_compiles_entries(client, tutor):
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    await client.post(
        "/api/v1/knowledge",
        json={
            "kind": "ai_instruction",
            "title": "Tone",
            "body": "Always be encouraging, never sarcastic.",
        },
        headers=tutor["headers"],
    )
    await client.post(
        "/api/v1/knowledge",
        json={
            "kind": "solving_approach",
            "title": "Chem method",
            "body": "Balance equations before answering.",
            "subject_id": subject_id,
        },
        headers=tutor["headers"],
    )

    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        context = await build_tutor_context(session, tutor_user.id, subject_id)
        no_subject_context = await build_tutor_context(session, tutor_user.id, None)

    assert "Always be encouraging" in context
    assert "Balance equations" in context
    # Without a subject_id, only subject-agnostic entries are included.
    assert "Always be encouraging" in no_subject_context
    assert "Balance equations" not in no_subject_context


async def test_ai_usage_summary(client, tutor):
    async with async_session() as session:
        tutor_user = await session.scalar(select(User).where(User.email == "tutor@example.com"))
        session.add(
            AiUsageEvent(
                organization_id=tutor_user.organization_id,
                tutor_id=tutor_user.id,
                student_id=None,
                feature=AiFeature.marking,
                model="claude-opus-4-8",
                input_tokens=100,
                output_tokens=50,
            )
        )
        session.add(
            AiUsageEvent(
                organization_id=tutor_user.organization_id,
                tutor_id=tutor_user.id,
                student_id=None,
                feature=AiFeature.marking,
                model="claude-opus-4-8",
                input_tokens=200,
                output_tokens=80,
            )
        )
        session.add(
            AiUsageEvent(
                organization_id=tutor_user.organization_id,
                tutor_id=tutor_user.id,
                student_id=None,
                feature=AiFeature.chat,
                model="claude-opus-4-8",
                input_tokens=30,
                output_tokens=60,
            )
        )
        await session.commit()

    resp = await client.get("/api/v1/ai-usage/summary", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_input_tokens"] == 330
    assert body["total_output_tokens"] == 190
    by_feature = {f["feature"]: f for f in body["by_feature"]}
    assert by_feature["marking"]["call_count"] == 2
    assert by_feature["marking"]["input_tokens"] == 300
    assert by_feature["chat"]["call_count"] == 1


async def test_ai_usage_forbidden_for_students(client, tutor):
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
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
            "/api/v1/groups", json={"name": "G", "subject_id": subject_id}, headers=tutor["headers"]
        )
    ).json()
    await client.post(
        f"/api/v1/groups/{group['id']}/students",
        json={"name": "Sara", "username": "sara-kb", "password": "password123"},
        headers=tutor["headers"],
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara-kb", "password": "password123"}
    )
    student_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}

    resp = await client.get("/api/v1/ai-usage/summary", headers=student_headers)
    assert resp.status_code == 403

    entry = await client.post(
        "/api/v1/knowledge",
        json={"kind": "note", "title": "x", "body": "y"},
        headers=student_headers,
    )
    assert entry.status_code == 403
