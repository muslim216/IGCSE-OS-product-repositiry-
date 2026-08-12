"""PR 15 — the narrative read endpoints, and the negative cases QA-12 requires.

The rule under test is that a paragraph about a named child reaches exactly the
people entitled to it, and that everyone else gets 404 rather than 403 — a 403
would confirm the row exists, and integer keys are enumerable (API-7 / SEC-9).
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import (
    Group,
    Narrative,
    NarrativeAudience,
    ParentLink,
    Subject,
    Topic,
    User,
    UserRole,
)


@pytest.fixture
async def world(client, tutor):
    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.flush()
        session.add(Topic(subject_id=subject.id, code="1.3", title="Atoms", weight=1.0))
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()

    # A parent linked to that student.
    parent = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "P", "email": "parent@example.com", "password": "password123"},
        )
    ).json()
    async with async_session() as session:
        parent_user = await session.get(User, parent["user"]["id"])
        # UserRole.parent, not the raw string: the column stores enum members, so
        # a literal would silently rot if a member were ever renamed.
        parent_user.role = UserRole.parent
        # Real parents inherit the organization of the child they link to
        # (api/auth.py register_parent). Registering via the tutor endpoint mints
        # a fresh organization, so without this the fixture builds a parent that
        # cannot exist — and would mask the cross-tenant check below.
        student_row = await session.get(User, student["id"])
        parent_user.organization_id = student_row.organization_id
        session.add(ParentLink(parent_id=parent_user.id, student_id=student["id"]))
        await session.commit()
    parent_login = await client.post(
        "/api/v1/auth/login", json={"identifier": "parent@example.com", "password": "password123"}
    )

    return {
        "group_id": group["id"],
        "student_id": student["id"],
        "parent_headers": {
            "Authorization": f"Bearer {parent_login.json()['tokens']['access_token']}"
        },
    }


async def _write_narrative(*, audience, group_id=None, student_id=None, text="stored text"):
    async with async_session() as session:
        if group_id is not None:
            org_id = (await session.get(Group, group_id)).organization_id
        else:
            org_id = (await session.get(User, student_id)).organization_id
        session.add(
            Narrative(
                organization_id=org_id,
                audience=audience,
                group_id=group_id,
                student_id=student_id,
                text=text,
                prompt_version="v1",
                model="test-model",
                generated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


async def test_tutor_reads_their_class_narrative(client, tutor, world):
    await _write_narrative(
        audience=NarrativeAudience.tutor_class,
        group_id=world["group_id"],
        text="The class is finding bonding hard.",
    )
    resp = await client.get(
        f"/api/v1/groups/{world['group_id']}/narrative", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "The class is finding bonding hard."
    assert resp.json()["generated_at"] is not None


async def test_absent_narrative_is_stated_not_faked(client, tutor, world):
    """Nothing generated yet is text=None — never "", which a surface would
    render as a blank panel (PROD-2, UX-19)."""
    resp = await client.get(
        f"/api/v1/groups/{world['group_id']}/narrative", headers=tutor["headers"]
    )
    assert resp.status_code == 200
    assert resp.json() == {"text": None, "generated_at": None, "prompt_version": None}


async def test_parent_reads_their_own_childs_narrative(client, world):
    await _write_narrative(
        audience=NarrativeAudience.parent_student,
        student_id=world["student_id"],
        text="Sara is on track in Chemistry.",
    )
    resp = await client.get(
        f"/api/v1/students/{world['student_id']}/narrative", headers=world["parent_headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "Sara is on track in Chemistry."


async def test_parent_cannot_read_a_non_child_narrative_returns_404(client, tutor, world):
    """A parent asking about a child who is not theirs gets 404, not 403."""
    other = (
        await client.post(
            f"/api/v1/groups/{world['group_id']}/students",
            json={"name": "Omar", "username": "omar01", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    await _write_narrative(
        audience=NarrativeAudience.parent_student,
        student_id=other["id"],
        text="About another child entirely.",
    )
    resp = await client.get(
        f"/api/v1/students/{other['id']}/narrative", headers=world["parent_headers"]
    )
    assert resp.status_code == 404
    assert "About another child" not in resp.text


async def test_parent_cannot_read_another_orgs_narrative_returns_404(client, world):
    """A second organization's tutor, class and learner are invisible — the
    organization comes from the authenticated user, never the path (SEC-7)."""
    other_tutor = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "T2", "email": "t2@example.com", "password": "password123"},
        )
    ).json()
    other_headers = {"Authorization": f"Bearer {other_tutor['tokens']['access_token']}"}
    async with async_session() as session:
        subject_id = await session.scalar(select(Subject.id))
    other_group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Other", "subject_id": subject_id},
            headers=other_headers,
        )
    ).json()
    other_student = (
        await client.post(
            f"/api/v1/groups/{other_group['id']}/students",
            json={"name": "Zed", "username": "zed01", "password": "password123"},
            headers=other_headers,
        )
    ).json()
    await _write_narrative(
        audience=NarrativeAudience.parent_student,
        student_id=other_student["id"],
        text="Another organization's child.",
    )

    resp = await client.get(
        f"/api/v1/students/{other_student['id']}/narrative", headers=world["parent_headers"]
    )
    assert resp.status_code == 404
    assert "Another organization" not in resp.text


async def test_a_tutor_cannot_read_another_orgs_class_narrative(client, world):
    other_tutor = (
        await client.post(
            "/api/v1/auth/register/tutor",
            json={"name": "T3", "email": "t3@example.com", "password": "password123"},
        )
    ).json()
    other_headers = {"Authorization": f"Bearer {other_tutor['tokens']['access_token']}"}
    await _write_narrative(
        audience=NarrativeAudience.tutor_class,
        group_id=world["group_id"],
        text="Not yours.",
    )
    resp = await client.get(f"/api/v1/groups/{world['group_id']}/narrative", headers=other_headers)
    assert resp.status_code == 404
    assert "Not yours" not in resp.text


async def test_a_student_cannot_reach_the_class_narrative(client, tutor, world):
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara01", "password": "password123"}
    )
    student_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    resp = await client.get(
        f"/api/v1/groups/{world['group_id']}/narrative", headers=student_headers
    )
    assert resp.status_code == 403  # the signature-level tutor gate


async def test_a_student_does_not_read_their_parents_paragraph(client, world):
    await _write_narrative(
        audience=NarrativeAudience.parent_student,
        student_id=world["student_id"],
        text="Written for the parent.",
    )
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara01", "password": "password123"}
    )
    student_headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    resp = await client.get(
        f"/api/v1/students/{world['student_id']}/narrative", headers=student_headers
    )
    assert resp.status_code == 404
    assert "Written for the parent" not in resp.text


async def test_no_token_is_refused_before_any_role_check(client, world):
    resp = await client.get(f"/api/v1/groups/{world['group_id']}/narrative")
    assert resp.status_code == 401


async def test_narrative_response_carries_no_review_state(client, tutor, world):
    """D2, asserted at the API boundary so a review workflow cannot accrete."""
    await _write_narrative(audience=NarrativeAudience.tutor_class, group_id=world["group_id"])
    resp = await client.get(
        f"/api/v1/groups/{world['group_id']}/narrative", headers=tutor["headers"]
    )
    body = resp.json()
    assert "reviewed_at" not in body
    assert "suppressed" not in body


async def test_prepare_again_enqueues_a_forced_refresh(client, tutor, world, monkeypatch):
    """ "Prepare again" is D2's correction: it regenerates rather than approving,
    and the parent read then takes the new row."""
    from app.models import Job
    from app.services.ai import AiProvider, AiResponse

    async def fake_group_analytics(group_id, db, user):
        from types import SimpleNamespace

        return SimpleNamespace(
            weak_topics=[
                SimpleNamespace(
                    topic_title="Atoms", topic_code="1.3", avg_score=40, student_count=1
                )
            ],
            weak_students=[SimpleNamespace(student_name="Sara", score=44)],
        )

    async def fake_text_complete(*, surface, prompt, max_tokens):
        return AiResponse(
            provider=AiProvider.anthropic,
            model="test-model",
            prompt_version="v2",
            input_tokens=1,
            output_tokens=1,
            text="Fresh brief.",
        )

    monkeypatch.setattr("app.api.groups.group_analytics", fake_group_analytics)
    monkeypatch.setattr("app.api.groups.text_complete", fake_text_complete)

    resp = await client.post(f"/api/v1/groups/{world['group_id']}/brief", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text

    async with async_session() as session:
        payloads = (
            await session.scalars(select(Job.payload).where(Job.type == "generate_narrative"))
        ).all()
    # Both audiences are refreshed, and both are forced.
    assert any(p.get("audience") == "tutor_class" and p.get("force") for p in payloads)
    assert any(
        p.get("audience") == "parent_student"
        and p.get("student_id") == world["student_id"]
        and p.get("force")
        for p in payloads
    )
