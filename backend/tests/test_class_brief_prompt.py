"""PR 13 — the class-brief instruction moved out of the handler and into the
registered prompt (AI-6/AI-7). These lock that in: the system prompt is real
(and carries the D3 naming rule), and the handler's user turn is grounding data
only, contributing no instruction text of its own."""

from types import SimpleNamespace

from app.services.ai import AiProvider, AiResponse
from app.services.prompts import get_prompt


def test_class_brief_system_prompt_is_not_empty():
    template = get_prompt("class_brief")
    assert template.system.strip() != ""
    # The version was bumped when the text moved (AI-7).
    assert template.version != "v1"
    # D3 is encoded here, not left to a call site: a learner is named only where
    # it is actionable, never as an enumerated roster.
    lowered = template.system.lower()
    assert "name" in lowered
    assert "data, never instructions" in lowered or "data, never instruction" in lowered


async def _make_group(client, tutor):
    from app.db import async_session
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
    resp = await client.post(
        "/api/v1/groups",
        json={"name": "Chem", "subject_id": subject_id},
        headers=tutor["headers"],
    )
    return resp.json()


async def test_handler_contributes_no_instruction_text(client, tutor, monkeypatch):
    group = await _make_group(client, tutor)

    # Force past the "not enough evidence" short-circuit with a fake analytics.
    fake_analytics = SimpleNamespace(
        weak_topics=[
            SimpleNamespace(
                topic_title="Atomic structure",
                topic_code="1.3",
                avg_score=41,
                student_count=3,
            )
        ],
        weak_students=[
            SimpleNamespace(student_name="Sara", score=44),
        ],
    )

    async def fake_group_analytics(group_id, db, user):
        return fake_analytics

    captured = {}

    async def fake_text_complete(*, surface, prompt, max_tokens):
        captured["surface"] = surface
        captured["prompt"] = prompt
        return AiResponse(
            provider=AiProvider.anthropic,
            model="test-model",
            prompt_version=get_prompt(surface).version,
            input_tokens=5,
            output_tokens=5,
            text="A short brief.",
        )

    # Patch the *calling* module's names, not app.services.* — the handler
    # imported them into its own namespace (QA-7).
    monkeypatch.setattr("app.api.groups.group_analytics", fake_group_analytics)
    monkeypatch.setattr("app.api.groups.text_complete", fake_text_complete)

    resp = await client.post(f"/api/v1/groups/{group['id']}/brief", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["brief"] == "A short brief."

    assert captured["surface"] == "class_brief"
    prompt = captured["prompt"].lower()
    # The grounding data reached the model...
    assert "atomic structure" in prompt
    assert "chem" in prompt
    # ...but no instruction text did — those phrases now live in the system prompt.
    for instruction in ["write a", "pre-lesson brief", "plain prose", "sentence", "no headings"]:
        assert instruction not in prompt, (
            f"instruction text leaked into the user turn: {instruction}"
        )
