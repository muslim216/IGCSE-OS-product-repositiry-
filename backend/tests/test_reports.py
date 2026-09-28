import pytest

from app.db import async_session
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults


@pytest.fixture
async def world(client, tutor):
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4CH1",
            name="Chemistry",
            grade_scale="9-1",
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
    student = (
        await client.post(
            f"/api/v1/groups/{group['id']}/students",
            json={"name": "Sara", "username": "sara", "password": "password123"},
            headers=tutor["headers"],
        )
    ).json()
    # Link a parent.
    code = (
        await client.post(f"/api/v1/students/{student['id']}/parent-code", headers=tutor["headers"])
    ).json()["code"]
    parent = await client.post(
        "/api/v1/auth/register/parent",
        json={
            "link_code": code,
            "name": "Parent",
            "email": "parent@example.com",
            "password": "password123",
        },
    )
    return {
        "subject_id": subject_id,
        "group": group,
        "student_id": student["id"],
        "parent_headers": {"Authorization": f"Bearer {parent.json()['tokens']['access_token']}"},
    }


async def fake_write(audience, facts, *args, **kwargs):
    return "# Progress report\n\nYour child is making steady progress."


async def test_tutor_generates_parent_report(client, tutor, world, monkeypatch):
    monkeypatch.setattr("app.services.reports._write_report", fake_write)
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "generating"
    report_id = resp.json()["id"]

    assert await process_one_job() is True

    detail = await client.get(f"/api/v1/reports/{report_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "ready"
    assert "progress" in detail.json()["content"].lower()


async def test_parent_sees_only_parent_reports(client, tutor, world, monkeypatch):
    monkeypatch.setattr("app.services.reports._write_report", fake_write)
    # Tutor generates a parent report and a tutor report.
    await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "tutor"},
        headers=tutor["headers"],
    )
    await process_one_job()
    await process_one_job()

    listing = await client.get(
        f"/api/v1/reports?student_id={world['student_id']}", headers=world["parent_headers"]
    )
    assert listing.status_code == 200
    audiences = {r["audience"] for r in listing.json()}
    assert audiences == {"parent"}


async def test_parent_cannot_generate_reports(client, world):
    # Only tutors generate reports now — parents (and students) are view-only.
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=world["parent_headers"],
    )
    assert resp.status_code == 403


async def test_parent_cannot_generate_tutor_report(client, world):
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "tutor"},
        headers=world["parent_headers"],
    )
    assert resp.status_code == 403


async def test_student_cannot_generate_reports(client, tutor, world, monkeypatch):
    monkeypatch.setattr("app.services.reports._write_report", fake_write)
    student_login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "sara", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {student_login.json()['tokens']['access_token']}"}
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "student"},
        headers=headers,
    )
    assert resp.status_code == 403

    # But they can still view a tutor-generated report.
    generated = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "student"},
        headers=tutor["headers"],
    )
    await process_one_job()
    listing = await client.get(f"/api/v1/reports?student_id={world['student_id']}", headers=headers)
    assert listing.status_code == 200
    assert any(r["id"] == generated.json()["id"] for r in listing.json())


async def test_report_generation_fails_gracefully(client, tutor, world):
    # No API key configured -> the real generator should fail the report.
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    report_id = resp.json()["id"]
    await process_one_job()
    await process_one_job()  # retry
    detail = await client.get(f"/api/v1/reports/{report_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "failed"
    assert "ANTHROPIC_API_KEY" in detail.json()["error"]


async def test_unrelated_parent_cannot_generate(client, tutor, world):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=headers,
    )
    # A tutor who doesn't teach this student cannot see them.
    assert resp.status_code in (403, 404)


# ---- Tutor-entered criteria (task 5.4c, owner decision 19) ----
#
# Appended after the AI writes, as a fixed list: the model never reads them, so
# it cannot fold a tutor's hand score into prose that sounds measured.


def _capturing_text_complete(calls: list[dict]):
    from app.services.ai import AiProvider, AiResponse

    async def _call(**kwargs) -> AiResponse:
        calls.append(kwargs)
        return AiResponse(
            provider=AiProvider.anthropic, model="test", prompt_version="test", text="# Report"
        )

    return _call


async def _generate(client, tutor, world, **body) -> dict:
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent", **body},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True
    detail = await client.get(f"/api/v1/reports/{resp.json()['id']}", headers=tutor["headers"])
    assert detail.json()["status"] == "ready", detail.text
    return detail.json()


async def test_report_lists_tutor_entered_criteria_the_ai_never_saw(
    client, tutor, world, monkeypatch
):
    calls: list[dict] = []
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete(calls))
    for name in ("Exam technique", "Confidence"):
        resp = await client.post(
            "/api/v1/custom-criteria", json={"name": name}, headers=tutor["headers"]
        )
        assert resp.status_code == 201, resp.text
        if name == "Exam technique":
            scored = await client.put(
                f"/api/v1/students/{world['student_id']}/custom-criteria/{resp.json()['id']}",
                json={"score": 70},
                headers=tutor["headers"],
            )
            assert scored.status_code == 200, scored.text

    content = (await _generate(client, tutor, world))["content"]

    assert content.startswith("# Report")
    assert "## Tutor-entered criteria" in content
    assert "- Exam technique: 70 / 100 (tutor-entered)" in content
    assert "- Confidence: Not scored" in content
    [call] = calls
    assert "Exam technique" not in repr(call)
    assert "Confidence" not in repr(call)


async def test_report_has_no_criteria_section_without_criteria(client, tutor, world, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete(calls))
    content = (await _generate(client, tutor, world))["content"]
    assert content == "# Report"


def test_criteria_section_keeps_to_the_reports_subject():
    from app.models import CustomCriterion, CustomCriterionScore
    from app.services.reports import criteria_section

    everywhere = CustomCriterion(name="Confidence", subject_id=None)
    chemistry = CustomCriterion(name="Practicals", subject_id=1)
    physics = CustomCriterion(name="Graphs", subject_id=2)
    rows = [
        (everywhere, None),
        (chemistry, CustomCriterionScore(score=0)),
        (physics, CustomCriterionScore(score=40)),
    ]

    one = criteria_section(rows, subject_id=1)
    assert "- Confidence: Not scored" in one
    # Zero is a score, not an absence.
    assert "- Practicals: 0 / 100 (tutor-entered)" in one
    assert "Graphs" not in one
    assert "- Graphs: 40 / 100 (tutor-entered)" in criteria_section(rows, subject_id=None)
    assert criteria_section([], subject_id=None) == ""
    assert criteria_section([(physics, None)], subject_id=1) == ""
