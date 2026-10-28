"""GH-6: the tutor's side of AI-marked mocks — what the AI read (with topics),
Try again, the class results table, and upload cleanup."""

import pytest
from sqlalchemy import event, select, update

from app.db import async_session, engine
from app.models import (
    GroupMember,
    Mock,
    MockOpening,
    MockQuestion,
    MockStatus,
    QuestionMark,
    Submission,
    SubmissionStatus,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.workers.jobs import process_one_job
from tests.conftest import PDF_BYTES
from tests.factories import make_user, register_other_tutor
from tests.test_mocks import _create, _extraction_double, mock_paper  # noqa: F401 — fixture


def _url(mock, tail=""):
    return f"/api/v1/mocks/{mock['id']}{tail}"


# --- topics -----------------------------------------------------------------


async def test_the_tutors_mock_detail_carries_each_questions_topics(client, tutor, mock_paper):  # noqa: F811
    detail = (await client.get(_url(mock_paper), headers=tutor["headers"])).json()
    first, second = detail["questions"]
    assert [t["code"] for t in first["topics"]] == ["1.3"]
    assert [t["code"] for t in second["topics"]] == ["1.6"]
    assert set(first["topics"][0]) >= {"id", "code", "title"}


async def test_a_student_gets_no_topics(client, student, mock_paper):  # noqa: F811
    detail = (await client.get(_url(mock_paper), headers=student["headers"])).json()
    assert [q["topics"] for q in detail["questions"]] == [[], []]


async def test_detail_topics_cost_a_fixed_number_of_queries(client, tutor, mock_paper):  # noqa: F811
    n = 0

    def bump(*_):
        nonlocal n
        n += 1

    event.listen(engine.sync_engine, "before_cursor_execute", bump)
    try:
        two = await client.get(_url(mock_paper), headers=tutor["headers"])
        before = n
        async with async_session() as s:
            mock = await s.get(Mock, mock_paper["id"])
            for i in range(3, 9):
                s.add(
                    MockQuestion(
                        mock_id=mock.id, position=i, number=str(i), text_summary="q", max_marks=1
                    )
                )
            await s.commit()
        n = 0
        eight = await client.get(_url(mock_paper), headers=tutor["headers"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", bump)
    assert two.status_code == eight.status_code == 200
    assert len(eight.json()["questions"]) == 8
    assert n == before


# --- retry ------------------------------------------------------------------


async def _failed_mock(client, tutor, subject, group, monkeypatch, fake_ai):
    from app.services.extraction import ExtractionResult

    monkeypatch.setattr(
        "app.services.extraction.structured_complete", fake_ai(ExtractionResult(questions=[]))
    )
    created = (await _create(client, tutor, subject, group)).json()
    await process_one_job()
    return created


async def test_retry_requeues_a_failed_read(client, tutor, subject, group, monkeypatch, fake_ai):
    mock = await _failed_mock(client, tutor, subject, group, monkeypatch, fake_ai)
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    resp = await client.post(_url(mock, "/retry-extraction"), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "extracting"
    assert resp.json()["extraction_error"] is None
    assert await process_one_job() is True
    detail = (await client.get(_url(mock), headers=tutor["headers"])).json()
    assert detail["status"] == "published"
    assert len(detail["questions"]) == 2


@pytest.mark.parametrize("state", [MockStatus.extracting, MockStatus.published])
async def test_retry_is_refused_unless_the_read_failed(client, tutor, mock_paper, state):  # noqa: F811
    async with async_session() as s:
        await s.execute(update(Mock).where(Mock.id == mock_paper["id"]).values(status=state))
        await s.commit()
    resp = await client.post(_url(mock_paper, "/retry-extraction"), headers=tutor["headers"])
    assert resp.status_code == 409
    assert "failed" in resp.json()["detail"]


async def test_retry_by_another_tutor_or_a_student_is_refused(client, student, mock_paper):  # noqa: F811
    other = await register_other_tutor(client)
    async with async_session() as s:
        await s.execute(
            update(Mock)
            .where(Mock.id == mock_paper["id"])
            .values(status=MockStatus.extraction_failed)
        )
        await s.commit()
    url = _url(mock_paper, "/retry-extraction")
    assert (await client.post(url, headers=other["headers"])).status_code == 404
    assert (await client.post(url, headers=student["headers"])).status_code == 403
    async with async_session() as s:
        assert (await s.get(Mock, mock_paper["id"])).status == MockStatus.extraction_failed


# --- results ----------------------------------------------------------------


async def _classmate(
    group,
    name,
    status=None,
    *,
    opened=False,
    final=None,
    minutes=None,
    late=False,
    marks=True,
    **user_fields,
):
    """A student in the class, optionally opened, optionally with a submission."""
    async with async_session() as s:
        mock = await s.scalar(select(Mock).where(Mock.group_id == group["id"]))
        tutor_org = mock.organization_id
        user = await make_user(
            s,
            organization_id=tutor_org,
            role=UserRole.student,
            name=name,
            email=f"{name.lower()}@example.com",
            **user_fields,
        )
        s.add(GroupMember(group_id=group["id"], student_id=user.id))
        if opened:
            s.add(MockOpening(mock_id=mock.id, student_id=user.id, opened_at=utcnow()))
        if status is not None:
            sub = Submission(
                work_id=mock.work_id,
                student_id=user.id,
                status=status,
                submitted_at=utcnow(),
                measured_minutes=minutes,
                submitted_late=late,
            )
            s.add(sub)
            await s.flush()
            questions = (
                await s.scalars(select(MockQuestion).where(MockQuestion.mock_id == mock.id))
            ).all()
            for q, fin in zip(questions if marks else [], final or [None, None], strict=False):
                s.add(
                    QuestionMark(
                        submission_id=sub.id,
                        mock_question_id=q.id,
                        ai_marks=q.max_marks,  # a draft that must never be counted
                        final_marks=fin,
                    )
                )
        await s.commit()
        return user.id


async def _results(client, tutor, mock):
    resp = await client.get(_url(mock, "/results"), headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    return {r["student_name"]: r for r in resp.json()}


async def test_results_map_every_status_and_count_final_marks_only(
    client,
    tutor,
    group,
    mock_paper,  # noqa: F811
):
    S = SubmissionStatus
    await _classmate(group, "Ann")  # not started
    await _classmate(group, "Ben", opened=True)  # in progress
    await _classmate(group, "Cal", S.submitted, minutes=50)
    await _classmate(group, "Dee", S.marking)
    await _classmate(group, "Eve", S.ai_failed)
    await _classmate(group, "Fay", S.needs_review, final=[2, None])
    await _classmate(group, "Gus", S.ai_marked)
    await _classmate(group, "Hal", S.auto_finalized, final=[2, 3], minutes=95, late=True)
    await _classmate(group, "Ivy", S.finalized, final=[0, 4], minutes=40)
    rows = await _results(client, tutor, mock_paper)

    states = {n: r["status"] for n, r in rows.items()}
    assert states == {
        "Ann": "not_started",
        "Ben": "in_progress",
        "Cal": "handed_in",
        "Dee": "handed_in",
        "Eve": "handed_in",
        "Fay": "marked",
        "Gus": "marked",
        "Hal": "final",
        "Ivy": "final",
    }
    # Nothing but a final submission has a score, and a 0 is a real 0 only there.
    for name in ("Ann", "Ben", "Cal", "Dee", "Eve", "Fay", "Gus"):
        assert rows[name]["marks_awarded"] is None
        assert rows[name]["marks_available"] is None
    assert (rows["Hal"]["marks_awarded"], rows["Hal"]["marks_available"]) == (5, 6)
    assert (rows["Ivy"]["marks_awarded"], rows["Ivy"]["marks_available"]) == (4, 6)
    assert rows["Ann"]["submission_id"] is None
    assert rows["Ann"]["submitted_at"] is None
    assert rows["Cal"]["submission_id"] is not None
    assert rows["Cal"]["submitted_at"]


async def test_results_report_late_and_measured_minutes(client, tutor, group, mock_paper):  # noqa: F811
    await _classmate(group, "Hal", SubmissionStatus.submitted, minutes=95, late=True)
    await _classmate(group, "Ivy", SubmissionStatus.submitted, minutes=40)
    await _classmate(group, "Jo", SubmissionStatus.submitted)  # never opened: untimed
    rows = await _results(client, tutor, mock_paper)
    assert (rows["Hal"]["submitted_late"], rows["Hal"]["measured_minutes"]) == (True, 95)
    assert (rows["Ivy"]["submitted_late"], rows["Ivy"]["measured_minutes"]) == (False, 40)
    assert (rows["Jo"]["submitted_late"], rows["Jo"]["measured_minutes"]) == (False, None)


async def test_results_are_ordered_by_name_and_skip_removed_and_erased_students(
    client,
    tutor,
    group,
    mock_paper,  # noqa: F811
):
    await _classmate(group, "Zed")
    await _classmate(group, "Amy")
    gone = await _classmate(group, "Bob", SubmissionStatus.submitted)
    erased = await _classmate(group, "Cat")
    async with async_session() as s:
        member = await s.scalar(select(GroupMember).where(GroupMember.student_id == gone))
        await s.delete(member)
        await s.execute(update(User).where(User.id == erased).values(deleted_at=utcnow()))
        await s.commit()
    resp = await client.get(_url(mock_paper, "/results"), headers=tutor["headers"])
    assert [r["student_name"] for r in resp.json()] == ["Amy", "Zed"]


async def test_a_mock_with_no_class_has_no_results(
    client, tutor, subject, group, monkeypatch, fake_ai
):
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    resp = await client.post(
        "/api/v1/mocks",
        data={"subject_id": str(subject["id"]), "title": "Unassigned"},
        files={"paper": ("p.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    resp = await client.get(_url(resp.json(), "/results"), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == []


async def test_results_are_the_owning_tutors_alone(client, student, mock_paper):  # noqa: F811
    other = await register_other_tutor(client)
    url = _url(mock_paper, "/results")
    assert (await client.get(url, headers=other["headers"])).status_code == 404
    assert (await client.get(url, headers=student["headers"])).status_code == 403
    assert (await client.get(url)).status_code == 401


async def test_results_cost_the_same_queries_for_any_class_size(client, tutor, group, mock_paper):  # noqa: F811
    async def count():
        n = 0

        def bump(*_):
            nonlocal n
            n += 1

        event.listen(engine.sync_engine, "before_cursor_execute", bump)
        try:
            await _results(client, tutor, mock_paper)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", bump)
        return n

    await _classmate(group, "Amy", SubmissionStatus.finalized, final=[1, 1])
    small = await count()
    for i, name in enumerate(["Bea", "Cy", "Di", "Ed", "Flo"]):
        await _classmate(group, name, SubmissionStatus.finalized, final=[1, 1], opened=i % 2 == 0)
    assert await count() == small


# --- create cleanup ---------------------------------------------------------


async def test_a_failed_create_leaves_no_saved_file_behind(client, tutor, subject, monkeypatch):
    deleted: list[str] = []
    kept: list[str] = []
    from app.services import storage

    real = storage.save_upload

    async def save(upload, **kw):
        if upload.filename == "ms.pdf":
            raise RuntimeError("disk full")
        result = await real(upload, **kw)
        kept.append(result[0])
        return result

    async def record(key: str) -> None:
        deleted.append(key)

    monkeypatch.setattr("app.api.mocks.storage.save_upload", save)
    monkeypatch.setattr("app.services.storage.delete_file", record)
    with pytest.raises(RuntimeError):
        await client.post(
            "/api/v1/mocks",
            data={"subject_id": str(subject["id"]), "title": "T"},
            files={
                "paper": ("p.pdf", PDF_BYTES, "application/pdf"),
                "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
            },
            headers=tutor["headers"],
        )
    assert len(kept) == 1
    assert deleted == kept
    async with async_session() as s:
        assert (await s.scalar(select(Mock.id))) is None


async def test_a_failed_insert_also_removes_both_files(client, tutor, subject, monkeypatch):
    deleted: list[str] = []

    async def record(key: str) -> None:
        deleted.append(key)

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.api.mocks.create_work", boom)
    monkeypatch.setattr("app.services.storage.delete_file", record)
    with pytest.raises(RuntimeError):
        await client.post(
            "/api/v1/mocks",
            data={"subject_id": str(subject["id"]), "title": "T"},
            files={
                "paper": ("p.pdf", PDF_BYTES, "application/pdf"),
                "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
            },
            headers=tutor["headers"],
        )
    assert len(deleted) == 2


async def test_a_mock_created_with_a_class_is_still_hidden_until_extracted(
    client, tutor, student, subject, group, monkeypatch, fake_ai
):
    monkeypatch.setattr("app.services.extraction.structured_complete", _extraction_double(fake_ai))
    created = (await _create(client, tutor, subject, group)).json()
    assert created["status"] == "extracting"
    assert (await client.get(_url(created), headers=student["headers"])).status_code == 404
    assert (await client.get("/api/v1/mocks/mine", headers=student["headers"])).json() == []
    await process_one_job()
    assert (await client.get(_url(created), headers=student["headers"])).status_code == 200


async def test_an_admin_in_the_same_organization_is_not_the_owner(client, tutor, mock_paper):  # noqa: F811
    """`_visible_mock` lets an organization admin read a mock; Try again and the
    results table are the owning tutor's alone, so for an admin they are a 404."""
    from app.security import create_access_token

    async with async_session() as s:
        mock = await s.get(Mock, mock_paper["id"])
        mock.status = MockStatus.extraction_failed
        admin = await make_user(
            s,
            organization_id=mock.organization_id,
            role=UserRole.admin,
            name="Boss",
            email="boss@example.com",
        )
        await s.commit()
        headers = {"Authorization": f"Bearer {create_access_token(admin.id, admin.token_version)}"}
    retry = await client.post(_url(mock_paper, "/retry-extraction"), headers=headers)
    assert retry.status_code == 404
    assert (await client.get(_url(mock_paper, "/results"), headers=headers)).status_code == 404


def test_every_submission_status_has_a_result_state():
    from app.api.mocks import _RESULT_STATUS

    assert set(SubmissionStatus) <= set(_RESULT_STATUS)


async def test_a_same_org_tutor_who_does_not_own_the_mock_gets_404(client, mock_paper):  # noqa: F811
    from app.security import create_access_token

    async with async_session() as s:
        mock = await s.get(Mock, mock_paper["id"])
        mock.status = MockStatus.extraction_failed
        mate = await make_user(
            s,
            organization_id=mock.organization_id,
            role=UserRole.tutor,
            name="Colleague",
            email="colleague@example.com",
        )
        await s.commit()
        headers = {"Authorization": f"Bearer {create_access_token(mate.id, mate.token_version)}"}
    for tail, method in (("/retry-extraction", client.post), ("/results", client.get)):
        assert (await method(_url(mock_paper, tail), headers=headers)).status_code == 404


async def test_late_without_a_measured_time_is_not_reported_late(client, tutor, group, mock_paper):  # noqa: F811
    await _classmate(group, "Kit", SubmissionStatus.submitted, late=True)
    rows = await _results(client, tutor, mock_paper)
    assert rows["Kit"]["submitted_late"] is False


async def test_a_student_with_an_erasure_request_is_not_listed(client, tutor, group, mock_paper):  # noqa: F811
    await _classmate(group, "Lee", erasure_requested_at=utcnow())
    await _classmate(group, "Max")
    assert list(await _results(client, tutor, mock_paper)) == ["Max"]


async def test_results_are_scoped_to_this_mock(client, tutor, subject, group, mock_paper):  # noqa: F811
    from app.models import WorkKind
    from app.services.work import create_work

    await _classmate(group, "Nia")
    await _classmate(group, "Oz", SubmissionStatus.finalized, final=[1, 1])
    before = await _results(client, tutor, mock_paper)
    async with async_session() as s:
        first = await s.get(Mock, mock_paper["id"])
        work = await create_work(
            s,
            kind=WorkKind.mock,
            organization_id=first.organization_id,
            subject_id=first.subject_id,
            title="Other",
        )
        other = Mock(
            work_id=work.id,
            organization_id=first.organization_id,
            tutor_id=first.tutor_id,
            subject_id=first.subject_id,
            group_id=first.group_id,
            title="Other",
            paper_path="x",
            paper_name="x.pdf",
            paper_mime="application/pdf",
        )
        s.add(other)
        await s.flush()
        for uid in await s.scalars(select(GroupMember.student_id)):
            s.add(MockOpening(mock_id=other.id, student_id=uid, opened_at=utcnow()))
            s.add(
                Submission(
                    work_id=work.id,
                    student_id=uid,
                    status=SubmissionStatus.finalized,
                    submitted_at=utcnow(),
                )
            )
        await s.commit()
    assert await _results(client, tutor, mock_paper) == before


async def test_marks_available_is_the_whole_paper_even_with_an_unmarked_question(
    client,
    tutor,
    group,
    mock_paper,  # noqa: F811
):
    await _classmate(group, "Pam", SubmissionStatus.finalized, final=[2, None])
    await _classmate(group, "Quin", SubmissionStatus.finalized, marks=False)
    rows = await _results(client, tutor, mock_paper)
    assert (rows["Pam"]["marks_awarded"], rows["Pam"]["marks_available"]) == (2, 6)
    assert rows["Quin"]["status"] == "final"
    assert rows["Quin"]["marks_awarded"] is None
    assert rows["Quin"]["marks_available"] is None


_TWO_FILES = {
    "paper": ("p.pdf", PDF_BYTES, "application/pdf"),
    "mark_scheme": ("ms.pdf", PDF_BYTES, "application/pdf"),
}


async def test_a_successful_create_keeps_both_files(client, tutor, subject, monkeypatch):
    deleted: list[str] = []

    async def record(key: str) -> None:
        deleted.append(key)

    monkeypatch.setattr("app.services.storage.delete_file", record)
    resp = await client.post(
        "/api/v1/mocks",
        data={"subject_id": str(subject["id"]), "title": "T"},
        files=_TWO_FILES,
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert deleted == []


async def test_a_failed_enqueue_removes_both_files(client, tutor, subject, monkeypatch):
    deleted: list[str] = []

    async def record(key: str) -> None:
        deleted.append(key)

    async def boom(*a, **k):
        raise RuntimeError("queue down")

    monkeypatch.setattr("app.api.mocks.enqueue", boom)
    monkeypatch.setattr("app.services.storage.delete_file", record)
    with pytest.raises(RuntimeError):
        await client.post(
            "/api/v1/mocks",
            data={"subject_id": str(subject["id"]), "title": "T"},
            files=_TWO_FILES,
            headers=tutor["headers"],
        )
    assert len(deleted) == 2
