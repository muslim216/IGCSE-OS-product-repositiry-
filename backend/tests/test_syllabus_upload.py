import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import AiFeature, AiUsageEvent, Chapter, Topic
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults

PDF_BYTES = b"%PDF-1.4 fake test syllabus pdf"


def draft_of(*, chapters, level="igcse", code="4XX1", exam_board="Edexcel IGCSE"):
    return {
        "exam_board": exam_board,
        "code": code,
        "name": "Test Subject",
        "grade_scale": "9-1",
        "level": level,
        "chapters": chapters,
    }


CHAPTERS = [
    {
        "code": "1",
        "title": "Section one",
        "topics": [
            {"code": "1.1", "title": "Sub-topic A", "weight": 1.0, "children": []},
            {
                "code": "1.2",
                "title": "Sub-topic B",
                "weight": 2.0,
                "children": [
                    {"code": "1.2.1", "title": "Detail", "weight": 1.0, "children": []},
                ],
            },
        ],
    },
    {
        "code": "2",
        "title": "Section two",
        "topics": [{"code": "2.1", "title": "Sub-topic C", "weight": 1.0, "children": []}],
    },
]


async def fake_extraction(session, upload):
    upload.draft = draft_of(chapters=CHAPTERS)


def extraction_returning(draft):
    async def _run(session, upload):
        upload.draft = draft

    return _run


async def upload_pdf(client, tutor, title="Test syllabus", name="syllabus.pdf"):
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": title},
        files={"file": (name, PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True
    return resp.json()["id"]


@pytest.fixture
async def uploaded(client, tutor, monkeypatch):
    monkeypatch.setattr("app.services.syllabus_extraction._run_extraction", fake_extraction)
    return await upload_pdf(client, tutor)


async def test_upload_and_extract_flow(client, tutor, uploaded):
    detail = await client.get(f"/api/v1/syllabus-uploads/{uploaded}", headers=tutor["headers"])
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "review"
    assert body["draft"]["code"] == "4XX1"
    assert [c["code"] for c in body["draft"]["chapters"]] == ["1", "2"]
    assert body["draft"]["chapters"][0]["topics"][1]["title"] == "Sub-topic B"
    assert body["draft"]["chapters"][0]["topics"][1]["children"][0]["code"] == "1.2.1"


async def test_extraction_records_ai_usage(client, tutor, monkeypatch, fake_ai):
    """A cost-analytics gap found on review: extract_syllabus called
    structured_complete but never record_usage, so every syllabus extraction
    call was silently missing from ai_usage_events (undercounting spend, not
    even reporting as unpriced_call_count — AI-17 needs the row to exist)."""
    from app.services.syllabus_extraction import SyllabusExtractionResult

    result = SyllabusExtractionResult(
        exam_board="Edexcel IGCSE",
        code="4XX1",
        name="Test Subject",
        grade_scale="9-1",
        level="igcse",
        chapters=[
            {
                "code": "1",
                "title": "Section one",
                "topics": [{"code": "1.1", "title": "A", "weight": 1.0, "children": []}],
            }
        ],
    )
    monkeypatch.setattr("app.services.syllabus_extraction.structured_complete", fake_ai(result))
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "Test syllabus"},
        files={"file": ("syllabus.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert await process_one_job() is True

    async with async_session() as session:
        events = (
            await session.scalars(
                select(AiUsageEvent).where(AiUsageEvent.feature == AiFeature.extraction)
            )
        ).all()
    assert len(events) == 1
    assert events[0].tutor_id == tutor["user"]["id"]


async def test_apply_creates_chapters_with_their_topics(client, tutor, uploaded):
    resp = await client.post(f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "applied"
    subject_id = body["subject_id"]
    assert subject_id is not None

    subjects = await client.get("/api/v1/subjects", headers=tutor["headers"])
    match = next(s for s in subjects.json() if s["code"] == "4XX1")
    assert match["name"] == "Test Subject"

    async with async_session() as session:
        chapters = (
            await session.scalars(
                select(Chapter).where(Chapter.subject_id == subject_id).order_by(Chapter.position)
            )
        ).all()
        topics = (await session.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()

    assert [(c.code, c.title, c.position) for c in chapters] == [
        ("1", "Section one", 1),
        ("2", "Section two", 2),
    ]
    by_code = {t.code: t for t in topics}
    assert set(by_code) == {"1.1", "1.2", "1.2.1", "2.1"}
    # Every topic hangs off a chapter — the whole point of 2.3. A sub-topic
    # belongs to its parent's chapter, not to a chapter of its own.
    assert by_code["1.1"].chapter_id == chapters[0].id
    assert by_code["1.2.1"].chapter_id == chapters[0].id
    assert by_code["1.2.1"].parent_id == by_code["1.2"].id
    assert by_code["2.1"].chapter_id == chapters[1].id
    assert by_code["1.1"].parent_id is None

    # Applying twice is rejected — not silently re-applied.
    again = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    assert again.status_code == 409


async def test_apply_refuses_a_draft_with_no_level(client, tutor, monkeypatch):
    """AV-7: no screen may assume IGCSE, and PROD-2 forbids inventing the value.
    A document that never stated its qualification leaves `level` null, and the
    tutor states it during review."""
    from app.models import Subject, SubjectLevel

    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(draft_of(chapters=CHAPTERS, level=None)),
    )
    upload_id = await upload_pdf(client, tutor, title="No level stated")

    refused = await client.post(
        f"/api/v1/syllabus-uploads/{upload_id}/apply", headers=tutor["headers"]
    )
    assert refused.status_code == 422

    detail = await client.get(f"/api/v1/syllabus-uploads/{upload_id}", headers=tutor["headers"])
    draft = detail.json()["draft"]
    draft["level"] = "a_level"
    saved = await client.put(
        f"/api/v1/syllabus-uploads/{upload_id}/draft", json=draft, headers=tutor["headers"]
    )
    assert saved.status_code == 200

    applied = await client.post(
        f"/api/v1/syllabus-uploads/{upload_id}/apply", headers=tutor["headers"]
    )
    assert applied.status_code == 200
    async with async_session() as session:
        subject = await session.get(Subject, applied.json()["subject_id"])
    assert subject.level is SubjectLevel.a_level


async def test_apply_upserts_existing_subject_by_exam_board_and_code(
    client, tutor, uploaded, monkeypatch
):
    """Uploading a second, corrected syllabus for the same exam_board+code
    should update the existing subject's chapters and topics rather than
    creating a duplicate."""
    first_apply = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = first_apply.json()["subject_id"]

    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(
            draft_of(
                chapters=[
                    {
                        "code": "1",
                        "title": "Section one (revised)",
                        "topics": [
                            {"code": "1.1", "title": "Sub-topic A (revised)", "children": []}
                        ],
                    }
                ]
            )
        ),
    )
    second_id = await upload_pdf(client, tutor, title="Test syllabus v2", name="syllabus2.pdf")

    apply2 = await client.post(
        f"/api/v1/syllabus-uploads/{second_id}/apply", headers=tutor["headers"]
    )
    assert apply2.status_code == 200
    assert apply2.json()["subject_id"] == subject_id

    async with async_session() as session:
        chapters = (
            await session.scalars(select(Chapter).where(Chapter.subject_id == subject_id))
        ).all()
        topics = (await session.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()

    # Upsert by code, in place: one chapter row, retitled — not a second "1".
    assert {c.code for c in chapters} == {"1", "2"}  # chapter 2 is left alone
    assert next(c for c in chapters if c.code == "1").title == "Section one (revised)"
    assert next(t for t in topics if t.code == "1.1").title == "Sub-topic A (revised)"

    # The whole topology, not just the rows the draft mentioned. A topic the
    # corrected draft dropped ("1.2" and its child) is **kept**, deliberately:
    # marks, mistakes and evidence attach to a topic id, so deleting one because
    # a re-uploaded PDF stopped listing it would silently discard a student's
    # record of work against it. A tutor removing a concept for real is a
    # deletion they ask for, not a side effect of re-uploading a document
    # (cubic asked which behaviour this is — this is the answer, pinned).
    assert {t.code for t in topics} == {"1.1", "1.2", "1.2.1", "2.1"}


async def test_apply_sets_no_grade_boundaries(client, tutor, uploaded):
    """Applying a syllabus creates no boundaries and no predicted grade.

    The org-scoped table is the only source since task 2.4 (AV-11), and nothing
    writes it on a tutor's behalf: a published split seeded here would be
    indistinguishable from figures they entered (PROD-2, PROD-8). The editor
    offers it pre-filled, labelled unconfirmed, and it counts once they save.
    """
    from app.models import GradeBoundary
    from app.services.grade_boundaries import defaults_for_scale

    applied = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = applied.json()["subject_id"]

    async with async_session() as session:
        rows = (
            await session.scalars(
                select(GradeBoundary).where(GradeBoundary.subject_id == subject_id)
            )
        ).all()
    assert rows == []

    read = await client.get(
        f"/api/v1/subjects/{subject_id}/grade-boundaries", headers=tutor["headers"]
    )
    body = read.json()
    assert body["source"] == "none"
    # Offered, not stored — the published starting point for the scale.
    assert body["boundaries"] == [
        {"grade": b["grade"], "min": b["min"]} for b in defaults_for_scale("9-1")
    ]


async def test_edit_draft_before_apply(client, tutor, uploaded):
    detail = await client.get(f"/api/v1/syllabus-uploads/{uploaded}", headers=tutor["headers"])
    draft = detail.json()["draft"]
    draft["chapters"][0]["title"] = "Section one (tutor corrected)"
    draft["chapters"][0]["topics"][0]["title"] = "Sub-topic A (tutor corrected)"

    resp = await client.put(
        f"/api/v1/syllabus-uploads/{uploaded}/draft", json=draft, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"]["chapters"][0]["title"] == "Section one (tutor corrected)"

    apply_resp = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = apply_resp.json()["subject_id"]
    async with async_session() as session:
        chapter = await session.scalar(
            select(Chapter).where(Chapter.subject_id == subject_id, Chapter.code == "1")
        )
    assert chapter.title == "Section one (tutor corrected)"
    topics = await client.get(f"/api/v1/subjects/{subject_id}/topics", headers=tutor["headers"])
    assert any(t["title"] == "Sub-topic A (tutor corrected)" for t in topics.json())


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
    # Anthropic, not Gemini, since task 2.3 flipped `ai_syllabus_provider`.
    assert "ANTHROPIC_API_KEY" in detail.json()["error"]

    retry = await client.post(
        f"/api/v1/syllabus-uploads/{upload_id}/retry", headers=tutor["headers"]
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "extracting"


async def test_student_cannot_upload_syllabus(client, tutor):
    from app.models import Subject

    async with async_session() as session:
        subject = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4ZZ1",
            name="Placeholder",
            grade_scale="9-1",
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


async def test_a_repeated_code_in_the_draft_merges_instead_of_failing(client, tutor, monkeypatch):
    """Chapter and topic codes are tutor-editable free text, so a draft can
    arrive with the same code twice. `(subject_id, code)` is unique on both
    tables, so a second INSERT would surface as a 500 — the second occurrence
    updates the first row instead."""
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(
            draft_of(
                chapters=[
                    {
                        "code": "1",
                        "title": "First",
                        "topics": [{"code": "1.1", "title": "A", "children": []}],
                    },
                    {
                        "code": "1",
                        "title": "Also chapter one",
                        "topics": [{"code": "1.1", "title": "A again", "children": []}],
                    },
                ]
            )
        ),
    )
    upload_id = await upload_pdf(client, tutor, title="Duplicate codes", name="dupes.pdf")
    applied = await client.post(
        f"/api/v1/syllabus-uploads/{upload_id}/apply", headers=tutor["headers"]
    )
    assert applied.status_code == 200, applied.text
    subject_id = applied.json()["subject_id"]

    async with async_session() as session:
        chapters = (
            await session.scalars(select(Chapter).where(Chapter.subject_id == subject_id))
        ).all()
        topics = (await session.scalars(select(Topic).where(Topic.subject_id == subject_id))).all()
    assert [(c.code, c.title) for c in chapters] == [("1", "Also chapter one")]
    assert [(t.code, t.title) for t in topics] == [("1.1", "A again")]


async def test_a_chapter_dropped_by_a_later_draft_sorts_after_the_new_ones(
    client, tutor, uploaded, monkeypatch
):
    """Nothing deletes a chapter a later draft omits, so it must not keep a
    position the new draft just handed to a different chapter — two rows sharing
    one makes `order_by(position)` arbitrary (Gitar)."""
    first = await client.post(
        f"/api/v1/syllabus-uploads/{uploaded}/apply", headers=tutor["headers"]
    )
    subject_id = first.json()["subject_id"]

    # The second draft keeps chapter 2 and drops chapter 1, so 2 takes position 1.
    monkeypatch.setattr(
        "app.services.syllabus_extraction._run_extraction",
        extraction_returning(
            draft_of(
                chapters=[
                    {
                        "code": "2",
                        "title": "Section two",
                        "topics": [{"code": "2.1", "title": "Sub-topic C", "children": []}],
                    }
                ]
            )
        ),
    )
    second_id = await upload_pdf(client, tutor, title="Chapter 1 dropped", name="dropped.pdf")
    apply2 = await client.post(
        f"/api/v1/syllabus-uploads/{second_id}/apply", headers=tutor["headers"]
    )
    assert apply2.status_code == 200

    async with async_session() as session:
        chapters = (
            await session.scalars(
                select(Chapter).where(Chapter.subject_id == subject_id).order_by(Chapter.position)
            )
        ).all()
    assert [(c.code, c.position) for c in chapters] == [("2", 1), ("1", 2)]


async def test_a_draft_with_chapters_but_no_topics_is_rejected(client, tutor, monkeypatch, fake_ai):
    """Chapters alone are not a syllabus — marks, mistakes and readiness attach
    at topic level, so a chapter-only draft would apply into a subject nothing
    can be tracked against (cubic)."""
    from app.services.syllabus_extraction import SyllabusExtractionResult

    monkeypatch.setattr(
        "app.services.syllabus_extraction.structured_complete",
        fake_ai(
            SyllabusExtractionResult(
                exam_board="Edexcel IGCSE",
                code="4XX1",
                name="Test Subject",
                grade_scale="9-1",
                level="igcse",
                chapters=[{"code": "1", "title": "Section one", "topics": []}],
            )
        ),
    )
    resp = await client.post(
        "/api/v1/syllabus-uploads",
        data={"title": "Chapters only"},
        files={"file": ("empty.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    upload_id = resp.json()["id"]
    await process_one_job()
    await process_one_job()

    detail = await client.get(f"/api/v1/syllabus-uploads/{upload_id}", headers=tutor["headers"])
    assert detail.json()["status"] == "extraction_failed"
    assert "No topics" in detail.json()["error"]
