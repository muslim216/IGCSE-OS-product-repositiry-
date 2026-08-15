import pytest

from app.workers.jobs import process_one_job

PDF_BYTES = b"%PDF-1.4 fake test syllabus pdf"


async def fake_extraction(session, upload):
    upload.draft = {
        "exam_board": "Edexcel IGCSE",
        "code": "4XX1",
        "name": "Test Subject",
        "grade_scale": "9-1",
        "grade_boundaries": [{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        "topics": [
            {
                "code": "1",
                "title": "Section one",
                "weight": 1.0,
                "children": [
                    {"code": "1.1", "title": "Sub-topic A", "weight": 1.0, "children": []},
                    {"code": "1.2", "title": "Sub-topic B", "weight": 2.0, "children": []},
                ],
            }
        ],
    }


@pytest.fixture
async def uploaded(client, tutor, monkeypatch):
    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", fake_extraction)
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "Test syllabus"},
        files={"file": ("syllabus.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "extracting"
    assert await process_one_job() is True
    return resp.json()["id"]


async def test_upload_and_extract_flow(client, tutor, uploaded):
    detail = await client.get(f"/api/v1/syllabus-uploads/{uploaded}", headers=tutor["headers"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "review"
    assert body["draft"]["code"] == "4XX1"
    assert body["draft"]["topics"][0]["children"][1]["title"] == "Sub-topic B"


async def test_apply_creates_subject_and_topic_tree(client, tutor, uploaded):
    resp = await client.post(f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "applied"
    assert body["subject_id"] is not None

    subjects = await client.get("/api/v1/subjects", headers=tutor["headers"])
    match = next(s for s in subjects.json() if s["code"] == "4XX1")
    assert match["name"] == "Test Subject"
    assert match["exam_board"] == "Edexcel IGCSE"

    topics = await client.get(f"/api/v1/subjects/{match['id']}/topics", headers=tutor["headers"])
    codes = {t["code"] for t in topics.json()}
    assert codes == {"1", "1.1", "1.2"}
    child = next(t for t in topics.json() if t["code"] == "1.2")
    assert child["title"] == "Sub-topic B"

    # Applying twice is rejected — not silently re-applied.
    again = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    assert again.status_code == 409


async def test_apply_upserts_existing_subject_by_exam_board_and_code(
    client, tutor, uploaded, monkeypatch
):
    """Uploading a second, corrected syllabus for the same exam_board+code
    should update the existing subject's topics rather than creating a
    duplicate — matching the idempotent seed-loader behaviour."""
    first_apply = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = first_apply.json()["subject_id"]

    async def fake_extraction_v2(session, upload):
        upload.draft = {
            "exam_board": "Edexcel IGCSE",
            "code": "4XX1",
            "name": "Test Subject",
            "grade_scale": "9-1",
            "grade_boundaries": [{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
            "topics": [
                {"code": "1", "title": "Section one (revised)", "weight": 1.0, "children": []},
            ],
        }

    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", fake_extraction_v2)
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "Test syllabus v2"},
        files={"file": ("syllabus2.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    second_id = resp.json()["id"]
    assert await process_one_job() is True

    apply2 = await client.post(
        f"/api/v1/syllabus-uploads/{second_id}/apply", headers=tutor["headers"]
    )
    assert apply2.status_code == 200
    assert apply2.json()["subject_id"] == subject_id

    # Upsert-by-code updates the matching topic in place; like the seed loader,
    # it never deletes topics omitted from a later draft.
    topics = await client.get(f"/api/v1/subjects/{subject_id}/topics", headers=tutor["headers"])
    updated = next(t for t in topics.json() if t["code"] == "1")
    assert updated["title"] == "Section one (revised)"


async def test_reapply_with_no_boundaries_keeps_the_existing_global_ones(
    client, tutor, uploaded, monkeypatch
):
    """A re-upload whose extraction found no boundaries must not overwrite the
    subject's existing boundaries.

    Subjects are global and keyed on (exam_board, code), so a second upload —
    including one from another organization — reuses the same row. Blanking it,
    or replacing it with generic defaults, would change fallback predicted grades
    for every tenant that relies on it (Qodo, SEC-8).
    """
    from app.db import async_session
    from app.models import Subject

    first = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = first.json()["subject_id"]

    async def fake_no_boundaries(session, upload):
        upload.draft = {
            "exam_board": "Edexcel IGCSE",
            "code": "4XX1",
            "name": "Test Subject",
            "grade_scale": "9-1",
            "grade_boundaries": [],  # the document did not state them
            "topics": [{"code": "1", "title": "Section one", "weight": 1.0, "children": []}],
        }

    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", fake_no_boundaries)
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "Same syllabus, no boundaries"},
        files={"file": ("syllabus3.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    second_id = resp.json()["id"]
    assert await process_one_job() is True
    apply2 = await client.post(
        f"/api/v1/syllabus-uploads/{second_id}/apply", headers=tutor["headers"]
    )
    assert apply2.status_code == 200
    assert apply2.json()["subject_id"] == subject_id

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
    # Untouched — still the first apply's boundaries, neither blanked nor
    # replaced with the scale's generic defaults.
    assert subject.grade_boundaries == [{"grade": "9", "min": 90}, {"grade": "U", "min": 0}]


async def test_apply_seeds_default_boundaries_when_a_new_subject_has_none(
    client, tutor, monkeypatch
):
    """A brand-new subject whose document stated no boundaries still gets working
    predicted grades from the scale's standard split — the cold-start value the
    fallback exists for (spec §7.1)."""
    from app.db import async_session
    from app.models import Subject
    from app.services.grade_boundaries import defaults_for_scale

    async def fake_new_no_boundaries(session, upload):
        upload.draft = {
            "exam_board": "Cambridge",
            "code": "0620",
            "name": "IGCSE Chemistry",
            "grade_scale": "9-1",
            "grade_boundaries": [],
            "topics": [{"code": "1", "title": "States of matter", "weight": 1.0, "children": []}],
        }

    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", fake_new_no_boundaries)
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "New subject, no boundaries"},
        files={"file": ("new.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    upload_id = resp.json()["id"]
    assert await process_one_job() is True
    applied = await client.post(
        f"/api/v1/syllabus-uploads/{upload_id}/apply", headers=tutor["headers"]
    )
    subject_id = applied.json()["subject_id"]

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
    assert subject.grade_boundaries == defaults_for_scale("9-1")
    assert subject.grade_boundaries  # not empty


async def test_edit_draft_before_apply(client, tutor, uploaded):
    detail = await client.get(f"/api/v1/syllabus-uploads/{uploaded}", headers=tutor["headers"])
    draft = detail.json()["draft"]
    draft["topics"][0]["title"] = "Section one (tutor corrected)"

    resp = await client.put(
        f"/api/v1/syllabus-uploads/{uploaded}/draft", json=draft, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"]["topics"][0]["title"] == "Section one (tutor corrected)"

    apply_resp = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = apply_resp.json()["subject_id"]
    topics = await client.get(f"/api/v1/subjects/{subject_id}/topics", headers=tutor["headers"])
    assert any(t["title"] == "Section one (tutor corrected)" for t in topics.json())


async def test_extraction_fails_gracefully_without_api_key(client, tutor):
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "No AI configured"},
        files={"file": ("syllabus.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    upload_id = resp.json()["id"]
    await process_one_job()
    await process_one_job()

    detail = await client.get(f"/api/v1/syllabus-uploads/{upload_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "extraction_failed"
    assert "GEMINI_API_KEY" in detail.json()["error"]

    retry = await client.post(
        f"/api/v1/syllabus-uploads/{upload_id}/retry", headers=tutor["headers"]
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "extracting"


async def test_student_cannot_upload_syllabus(client, tutor):
    from app.db import async_session
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            exam_board="Edexcel IGCSE",
            code="4ZZ1",
            name="Placeholder",
            grade_scale="9-1",
            grade_boundaries=[{"grade": "9", "min": 90}, {"grade": "U", "min": 0}],
        )
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Group", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara-syllabus@example.com",
            "password": "password123",
        },
    )
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "Nope"},
        files={"file": ("syllabus.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_other_tutor_cannot_see_upload(client, uploaded):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-syllabus@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    resp = await client.get(f"/api/v1/syllabus-uploads/{uploaded}", headers=headers)
    assert resp.status_code == 404
