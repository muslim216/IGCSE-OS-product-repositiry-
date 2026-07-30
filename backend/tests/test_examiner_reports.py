"""The shared examiner-report library.

Deliberately global where the rest of the past-paper world is scoped to
(organization, subject): an examiner report is a public board document and the
collection is meant to be built up once for everybody. These tests pin both
halves of that — the sharing works, and the guards on who may change a shared
row hold.
"""

import pytest

from app.workers.jobs import process_one_job

from tests.test_homework import PDF_BYTES, PNG_BYTES, group, student, subject  # noqa: F401
from tests.test_past_papers import past_paper  # noqa: F401


async def _second_tutor(client):
    """A tutor in a different organization — one is created per tutor at
    signup, so registering is enough to be somewhere else."""
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other Tutor", "email": "other-tutor@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}


async def _upload_report(client, headers, subject_id, **overrides):
    payload = {
        "subject_id": str(subject_id),
        "paper_number": "Paper 1",
        "session_label": "November 2026",
    }
    payload.update({k: str(v) for k, v in overrides.items()})
    return await client.post(
        "/api/v1/examiner-reports",
        data=payload,
        files={"file": ("report.pdf", PDF_BYTES, "application/pdf")},
        headers=headers,
    )


async def test_upload_and_list(client, tutor, subject):  # noqa: F811
    resp = await _upload_report(client, tutor["headers"], subject["id"])
    assert resp.status_code == 201, resp.text
    assert resp.json()["can_manage"] is True

    listing = await client.get("/api/v1/examiner-reports", headers=tutor["headers"])
    assert [r["paper_number"] for r in listing.json()] == ["Paper 1"]


async def test_the_library_is_shared_across_organizations(client, tutor, subject):  # noqa: F811
    """The whole point of the shared library: one upload covers everyone."""
    created = await _upload_report(client, tutor["headers"], subject["id"])
    assert created.status_code == 201

    other = await _second_tutor(client)
    listing = await client.get("/api/v1/examiner-reports", headers=other)
    assert listing.status_code == 200
    reports = listing.json()
    assert len(reports) == 1
    # Visible and downloadable, but not theirs to change.
    assert reports[0]["can_manage"] is False
    download = await client.get(
        f"/api/v1/examiner-reports/{reports[0]['id']}/file", headers=other
    )
    assert download.status_code == 200


async def test_only_the_uploader_can_replace_or_delete(client, tutor, subject):  # noqa: F811
    """A shared row changes marking for every organization, so a second tutor
    must not be able to overwrite it out from under the first."""
    created = await _upload_report(client, tutor["headers"], subject["id"])
    report_id = created.json()["id"]
    other = await _second_tutor(client)

    clash = await _upload_report(client, other, subject["id"])
    assert clash.status_code == 409

    denied = await client.delete(f"/api/v1/examiner-reports/{report_id}", headers=other)
    assert denied.status_code == 403

    replaced = await _upload_report(client, tutor["headers"], subject["id"])
    assert replaced.status_code == 201
    assert replaced.json()["id"] == report_id, "replacing updates the row, not a duplicate"

    removed = await client.delete(f"/api/v1/examiner-reports/{report_id}", headers=tutor["headers"])
    assert removed.status_code == 204
    listing = await client.get("/api/v1/examiner-reports", headers=tutor["headers"])
    assert listing.json() == []


async def test_students_cannot_reach_examiner_reports(client, tutor, student, subject):  # noqa: F811
    """Tutor-only for the same reason a mark scheme is: the report discusses
    the answers the board expected."""
    created = await _upload_report(client, tutor["headers"], subject["id"])
    report_id = created.json()["id"]

    assert (
        await client.get("/api/v1/examiner-reports", headers=student["headers"])
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/examiner-reports/{report_id}/file", headers=student["headers"]
        )
    ).status_code == 403
    assert (await _upload_report(client, student["headers"], subject["id"])).status_code == 403


async def test_unknown_subject_is_rejected(client, tutor):  # noqa: F811
    assert (await _upload_report(client, tutor["headers"], 9999)).status_code == 404


def _capturing_ai(parsed):
    from app.services.ai import AiProvider, AiResponse

    calls: dict = {}

    async def _call(**kwargs):
        calls.update(kwargs)
        return AiResponse(
            provider=AiProvider.anthropic,
            model="test-model",
            prompt_version="test",
            input_tokens=10,
            output_tokens=10,
            parsed=parsed,
        )

    return calls, _call


def _draft():
    from app.services.marking import MarkingResult, QuestionMarkDraft

    return MarkingResult(
        questions=[
            QuestionMarkDraft(
                number="1", transcription="a", proposed_marks=2,
                feedback="Correct.", confidence="high",
            ),
            QuestionMarkDraft(
                number="2", transcription="b", proposed_marks=3,
                feedback="Nearly.", confidence="high",
            ),
        ]
    )


async def _sit(client, headers, past_paper_id):  # noqa: F811
    resp = await client.post(
        f"/api/v1/past-papers/{past_paper_id}/attempts",
        data={"attempted_at": "2026-07-01", "timed": "true", "time_taken_minutes": "85"},
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("with_report", [True, False])
async def test_the_marker_receives_a_matching_report_and_copes_without_one(
    client, tutor, student, subject, past_paper, monkeypatch, with_report  # noqa: F811
):
    """The report is matched on (subject, paper number, session) — the same
    three fields that identify the paper — so no tutor links them by hand."""
    if with_report:
        created = await _upload_report(
            client,
            tutor["headers"],
            subject["id"],
            paper_number=past_paper["paper_number"],
            session_label=past_paper["session_label"],
        )
        assert created.status_code == 201

    calls, stub = _capturing_ai(_draft())
    monkeypatch.setattr("app.services.marking.structured_complete", stub)
    await _sit(client, student["headers"], past_paper["id"])
    assert await process_one_job() is True

    documents = [b for b in calls["content"] if b.get("type") == "document"]
    # booklet + mark scheme, plus the report when the library has one.
    assert len(documents) == (3 if with_report else 2)
    text = calls["content"][-1]["text"]
    assert ("examiner report" in text) is with_report


async def test_a_report_for_a_different_sitting_is_not_used(
    client, tutor, student, subject, past_paper, monkeypatch  # noqa: F811
):
    """Matching is exact — a report for another paper or session must not be
    handed to the marker as though it described this one."""
    created = await _upload_report(
        client,
        tutor["headers"],
        subject["id"],
        paper_number="Paper 2",
        session_label=past_paper["session_label"],
    )
    assert created.status_code == 201

    calls, stub = _capturing_ai(_draft())
    monkeypatch.setattr("app.services.marking.structured_complete", stub)
    await _sit(client, student["headers"], past_paper["id"])
    assert await process_one_job() is True

    documents = [b for b in calls["content"] if b.get("type") == "document"]
    assert len(documents) == 2, "only the booklet and mark scheme belong to this paper"


async def test_homework_marking_never_receives_an_examiner_report(
    client, tutor, student, subject, monkeypatch  # noqa: F811
):
    """Examiner reports describe a paper sitting; homework has none, and the
    paper-level guidance layer is skipped for the same reason."""
    from tests.test_homework import PNG_BYTES as PNG

    await _upload_report(client, tutor["headers"], subject["id"])

    created = await client.post(
        "/api/v1/assignments",
        json={"group_id": (await client.get("/api/v1/groups", headers=tutor["headers"])).json()[0]["id"],
              "title": "Homework"},
        headers=tutor["headers"],
    )
    aid = created.json()["id"]
    await client.put(
        f"/api/v1/assignments/{aid}/questions",
        json=[{"number": "1", "text_summary": "Define an isotope", "max_marks": 2,
               "has_mark_scheme": True, "topic_ids": []}],
        headers=tutor["headers"],
    )
    await client.post(f"/api/v1/assignments/{aid}/publish", headers=tutor["headers"])

    from app.services.marking import MarkingResult, QuestionMarkDraft

    calls, stub = _capturing_ai(
        MarkingResult(
            questions=[
                QuestionMarkDraft(
                    number="1", transcription="a", proposed_marks=2,
                    feedback="Correct.", confidence="high",
                )
            ]
        )
    )
    monkeypatch.setattr("app.services.marking.structured_complete", stub)
    await client.post(
        f"/api/v1/assignments/{aid}/submissions",
        files=[("files", ("page1.png", PNG, "image/png"))],
        headers=student["headers"],
    )
    assert await process_one_job() is True

    assert [b for b in calls["content"] if b.get("type") == "document"] == []
