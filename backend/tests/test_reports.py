import pytest

from app.db import async_session
from app.workers.jobs import process_one_job
from tests.factories import subject_defaults, subject_for_tutor, write_v2_snapshot


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
    # One scored run, so there is something to report: a student with no score,
    # no marked work and no homework is refused before the model is asked.
    async with async_session() as session:
        await write_v2_snapshot(
            session, student_id=student["id"], subject_id=subject_id, score=72.0
        )
        await session.commit()
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

    names = {1: "Chemistry", 2: "Physics"}
    one = criteria_section(rows, 1, names)
    assert "- Confidence: Not scored" in one
    # Zero is a score, not an absence.
    assert "- Practicals (Chemistry): 0 / 100 (tutor-entered)" in one
    assert "Graphs" not in one
    assert "- Graphs (Physics): 40 / 100 (tutor-entered)" in criteria_section(rows, None, names)
    assert criteria_section([], None, names) == ""
    assert criteria_section([(physics, None)], 1, names) == ""


def test_a_subject_criterion_names_its_subject():
    # Two subject-specific "Effort" criteria are otherwise the same line twice.
    from app.models import CustomCriterion, CustomCriterionScore
    from app.services.reports import criteria_section

    rows = [
        (CustomCriterion(name="Effort", subject_id=1), CustomCriterionScore(score=70)),
        (CustomCriterion(name="Effort", subject_id=2), None),
        (CustomCriterion(name="Confidence", subject_id=None), None),
    ]
    # A subject name is tutor-typed text landing in Markdown: one line only.
    section = criteria_section(rows, None, {1: "Chemistry", 2: "Physics\n## Forged heading"})

    assert "- Effort (Chemistry): 70 / 100 (tutor-entered)" in section
    assert "- Effort (Physics ## Forged heading): Not scored" in section
    assert "\n## Forged heading" not in section
    # An account-wide criterion stays unlabelled.
    assert "- Confidence: Not scored" in section


async def test_report_labels_a_subject_criterion_with_its_subject(
    client, tutor, world, monkeypatch
):
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete([]))
    enrolled = await client.post(
        f"/api/v1/students/{world['student_id']}/subjects",
        json={"subject_id": world["subject_id"]},
        headers=tutor["headers"],
    )
    assert enrolled.status_code in (200, 201), enrolled.text
    created = await client.post(
        "/api/v1/custom-criteria",
        json={"name": "Effort", "subject_id": world["subject_id"]},
        headers=tutor["headers"],
    )
    assert created.status_code == 201, created.text

    content = (await _generate(client, tutor, world))["content"]
    assert "- Effort (Chemistry): Not scored" in content


# ---- Nothing to report (phase 5 sweep, F6a) ----
#
# Report subjects come from class membership. A subject the student is only
# CRM-enrolled in has no facts, and the model used to be asked to write a
# report from "Student: Sara" alone.


def _refusing_text_complete():
    async def _call(**kwargs):
        raise AssertionError("the model must not be asked to write a report from nothing")

    return _call


async def _physics_without_a_class(student_id: int) -> int:
    from app.models import StudentSubject, Subject

    async with async_session() as session:
        physics = Subject(
            **await subject_defaults(session),
            exam_board="Edexcel IGCSE",
            code="4PH1",
            name="Physics",
            grade_scale="9-1",
        )
        session.add(physics)
        await session.flush()
        session.add(StudentSubject(student_id=student_id, subject_id=physics.id))
        await session.commit()
        return physics.id


async def test_a_subject_with_no_class_is_refused_before_anything_is_queued(
    client, tutor, world, monkeypatch
):
    monkeypatch.setattr("app.services.reports.text_complete", _refusing_text_complete())
    physics_id = await _physics_without_a_class(world["student_id"])

    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent", "subject_id": physics_id},
        headers=tutor["headers"],
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == (
        "This student isn't in a class for that subject yet, so there is nothing to report."
    )
    # No report row and no job: nothing sits in "generating".
    assert await process_one_job() is False
    listing = await client.get(
        f"/api/v1/reports?student_id={world['student_id']}", headers=tutor["headers"]
    )
    assert listing.json() == []


async def test_a_report_whose_class_vanished_fails_with_the_reason_and_no_model_call(
    client, tutor, world, monkeypatch
):
    # Queued while the student was in the class, run after they left it: the
    # handler re-reads current state (BE-9) and must not write from nothing.
    from sqlalchemy import delete, select

    from app.models import GroupMember, Job, Report

    monkeypatch.setattr("app.services.reports.text_complete", _refusing_text_complete())
    resp = await client.post(
        "/api/v1/reports/generate",
        json={
            "student_id": world["student_id"],
            "audience": "parent",
            "subject_id": world["subject_id"],
        },
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    async with async_session() as session:
        await session.execute(
            delete(GroupMember).where(GroupMember.student_id == world["student_id"])
        )
        await session.commit()

    assert await process_one_job() is True

    async with async_session() as session:
        # Permanent, not transient: the job is finished, not held for a retry
        # that would ask the same question again in a minute.
        assert [job.status.value for job in (await session.scalars(select(Job))).all()] == ["done"]
        report = await session.get(Report, resp.json()["id"])
        assert report.status.value == "failed"
        assert report.content is None
        assert report.error == (
            "This student isn't in a class for that subject yet, so there is nothing to report."
        )


# ---- Not enough data yet (phase 5 sweep) ----
#
# In a class, but with no readiness score, no marked work and no homework: the
# facts block was "No readiness data yet" and the model wrote a report from it.

NOT_ENOUGH = (
    "Not enough data yet: this student has no readiness score, marked work or "
    "homework to report on."
)


async def test_a_student_with_no_data_is_refused_before_anything_is_queued(
    client, tutor, world, monkeypatch
):
    monkeypatch.setattr("app.services.reports.text_complete", _refusing_text_complete())
    blank = await client.post(
        f"/api/v1/groups/{world['group']['id']}/students",
        json={"name": "Lina", "username": "lina01", "password": "password123"},
        headers=tutor["headers"],
    )
    assert blank.status_code == 201, blank.text

    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": blank.json()["id"], "audience": "parent"},
        headers=tutor["headers"],
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == NOT_ENOUGH
    assert await process_one_job() is False


async def test_a_report_whose_data_vanished_fails_with_the_reason_and_no_model_call(
    client, tutor, world, monkeypatch
):
    from sqlalchemy import delete, select

    from app.models import Job, ReadinessSnapshot, Report

    monkeypatch.setattr("app.services.reports.text_complete", _refusing_text_complete())
    resp = await client.post(
        "/api/v1/reports/generate",
        json={"student_id": world["student_id"], "audience": "parent"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    async with async_session() as session:
        await session.execute(
            delete(ReadinessSnapshot).where(ReadinessSnapshot.student_id == world["student_id"])
        )
        await session.commit()

    assert await process_one_job() is True

    async with async_session() as session:
        assert [job.status.value for job in (await session.scalars(select(Job))).all()] == ["done"]
        report = await session.get(Report, resp.json()["id"])
        assert report.status.value == "failed"
        assert report.content is None
        assert report.error == NOT_ENOUGH


# ---- Re-running a finished report (BE-6) ----


async def test_rerunning_a_ready_report_does_not_call_the_model_again(
    client, tutor, world, monkeypatch
):
    from app.models import Report
    from app.services.reports import generate_report

    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete([]))
    first = await _generate(client, tutor, world)

    monkeypatch.setattr("app.services.reports.text_complete", _refusing_text_complete())
    async with async_session() as session:
        await generate_report(session, {"report_id": first["id"]})
        await session.commit()
        report = await session.get(Report, first["id"])
        assert report.status.value == "ready"
        assert report.content == first["content"]


# ---- A student who also sits in a second organization's class ----
#
# Subjects and criteria are each one organization's. A report is written for
# the tutor who asked for it, so it covers their classes and their criteria.


async def _rival_physics_class(client, student_id: int) -> dict:
    """A second tenant teaching this student Physics, with a scored run."""
    from app.models import GroupMember

    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Rival", "email": "rival@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}
    async with async_session() as session:
        physics = await subject_for_tutor(session, "rival@example.com", code="4PH1", name="Physics")
        await session.commit()
        physics_id = physics.id
    group = await client.post(
        "/api/v1/groups", json={"name": "Phys", "subject_id": physics_id}, headers=headers
    )
    assert group.status_code == 201, group.text
    async with async_session() as session:
        session.add(GroupMember(group_id=group.json()["id"], student_id=student_id))
        await write_v2_snapshot(session, student_id=student_id, subject_id=physics_id, score=55.0)
        await session.commit()
    return {"headers": headers, "subject_id": physics_id}


async def test_an_all_subjects_report_keeps_to_the_generating_tutors_classes(
    client, tutor, world, monkeypatch
):
    calls: list[dict] = []
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete(calls))
    rival = await _rival_physics_class(client, world["student_id"])

    await _generate(client, tutor, world)
    [call] = calls
    assert "## Chemistry" in call["prompt"]
    assert "Physics" not in call["prompt"]

    calls.clear()
    await _generate(client, rival, world)
    [call] = calls
    assert "## Physics" in call["prompt"]
    assert "Chemistry" not in call["prompt"]


async def test_another_organizations_subject_cannot_be_named_for_a_shared_student(
    client, tutor, world, monkeypatch
):
    """QA-12: the student really is in that Physics class — it is just not ours."""
    monkeypatch.setattr("app.services.reports.text_complete", _refusing_text_complete())
    rival = await _rival_physics_class(client, world["student_id"])

    resp = await client.post(
        "/api/v1/reports/generate",
        json={
            "student_id": world["student_id"],
            "audience": "parent",
            "subject_id": rival["subject_id"],
        },
        headers=tutor["headers"],
    )

    assert resp.status_code == 404, resp.text
    assert await process_one_job() is False


async def test_a_report_lists_the_generating_tutors_criteria_not_the_home_organizations(
    client, tutor, world, monkeypatch
):
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete([]))
    home = await client.post(
        "/api/v1/custom-criteria", json={"name": "Home effort"}, headers=tutor["headers"]
    )
    assert home.status_code == 201, home.text
    scored = await client.put(
        f"/api/v1/students/{world['student_id']}/custom-criteria/{home.json()['id']}",
        json={"score": 70},
        headers=tutor["headers"],
    )
    assert scored.status_code == 200, scored.text
    rival = await _rival_physics_class(client, world["student_id"])
    theirs = await client.post(
        "/api/v1/custom-criteria", json={"name": "Rival effort"}, headers=rival["headers"]
    )
    assert theirs.status_code == 201, theirs.text

    content = (await _generate(client, rival, world))["content"]

    assert "- Rival effort: Not scored" in content
    assert "Home effort" not in content
    assert "70 / 100" not in content
    # And the home tutor's report is unchanged by the rival's criteria.
    content = (await _generate(client, tutor, world))["content"]
    assert "- Home effort: 70 / 100 (tutor-entered)" in content
    assert "Rival effort" not in content
    # Each report's AI cost is metered to the organization that asked for it.
    from sqlalchemy import select

    from app.models import AiUsageEvent, User

    async with async_session() as session:
        events = (await session.scalars(select(AiUsageEvent))).all()
        assert len(events) == 2
        for event in events:
            asker = await session.get(User, event.tutor_id)
            assert event.organization_id == asker.organization_id


# ---- Reading a report another organization generated (SEC-7, API-7) ----
#
# A report is written from the generating tutor's classes and criteria, so
# sharing the student is not enough to read it: the reader must be staff of the
# organization that asked for it.


async def test_a_tutor_cannot_read_a_report_another_organization_generated(
    client, tutor, world, monkeypatch
):
    """QA-12: the rival really does teach this student — the report is not theirs."""
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete([]))
    rival = await _rival_physics_class(client, world["student_id"])
    ours = await _generate(client, tutor, world)
    theirs = await _generate(client, rival, world)
    listing_url = f"/api/v1/reports?student_id={world['student_id']}"

    listing = await client.get(listing_url, headers=rival["headers"])
    assert listing.status_code == 200, listing.text
    assert [r["id"] for r in listing.json()] == [theirs["id"]]
    detail = await client.get(f"/api/v1/reports/{ours['id']}", headers=rival["headers"])
    assert detail.status_code == 404, detail.text

    # The organization that generated it still reads it, and only its own.
    listing = await client.get(listing_url, headers=tutor["headers"])
    assert [r["id"] for r in listing.json()] == [ours["id"]]
    detail = await client.get(f"/api/v1/reports/{ours['id']}", headers=tutor["headers"])
    assert detail.status_code == 200, detail.text
    assert (
        await client.get(f"/api/v1/reports/{theirs['id']}", headers=tutor["headers"])
    ).status_code == 404


async def test_an_admin_cannot_read_a_report_another_organization_generated(
    client, tutor, world, monkeypatch
):
    from sqlalchemy import select

    from app.models import User, UserRole

    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete([]))
    rival = await _rival_physics_class(client, world["student_id"])
    ours = await _generate(client, tutor, world)
    # The rival tutor's token, with the account promoted: role is read per request.
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.email == "rival@example.com"))
        user.role = UserRole.admin
        await session.commit()

    listing = await client.get(
        f"/api/v1/reports?student_id={world['student_id']}", headers=rival["headers"]
    )
    assert listing.status_code == 200, listing.text
    assert listing.json() == []
    detail = await client.get(f"/api/v1/reports/{ours['id']}", headers=rival["headers"])
    assert detail.status_code == 404, detail.text


async def test_students_and_parents_read_their_reports_whichever_organization_wrote_them(
    client, tutor, world, monkeypatch
):
    monkeypatch.setattr("app.services.reports.text_complete", _capturing_text_complete([]))
    rival = await _rival_physics_class(client, world["student_id"])
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": "sara", "password": "password123"}
    )
    student = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    listing_url = f"/api/v1/reports?student_id={world['student_id']}"

    for_student = [
        (await _generate(client, author, world, audience="student"))["id"]
        for author in (tutor, rival)
    ]
    for_parent = [(await _generate(client, author, world))["id"] for author in (tutor, rival)]

    listing = await client.get(listing_url, headers=student)
    assert sorted(r["id"] for r in listing.json()) == for_student
    listing = await client.get(listing_url, headers=world["parent_headers"])
    assert sorted(r["id"] for r in listing.json()) == for_parent
    for report_id, headers in [
        *((i, student) for i in for_student),
        *((i, world["parent_headers"]) for i in for_parent),
    ]:
        detail = await client.get(f"/api/v1/reports/{report_id}", headers=headers)
        assert detail.status_code == 200, detail.text
