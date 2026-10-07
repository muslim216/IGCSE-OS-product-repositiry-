"""Who may ask for a redo, and when it is refused (`QA-12`): the wrong role, another
organization, a colleague who does not teach the student, an attempt that is not
locked or is being marked, and a student who could not hand in again."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from app.db import async_session
from app.models import (
    AttemptRedo,
    Group,
    GroupMember,
    Job,
    JobStatus,
    MarkOverrideAudit,
    Organization,
    Submission,
    User,
    UserRole,
)
from app.models.base import utcnow
from tests.factories import org_id, register_other_tutor, register_parent
from tests.redo_world import (  # noqa: F401 — fixtures and helpers shared by the redo tests
    API,
    KINDS,
    Attempt,
    Carried,
    _assert_untouched,
    _carry_rows,
    _clear_readiness_jobs,
    _colleague_headers,
    _confident_result,
    _count,
    _drain_due,
    _enforce_foreign_keys,
    _extra_class,
    _factor_scores,
    _finalized,
    _headers_for,
    _homework_hand_in,
    _mock_hand_in,
    _no_real_ai,
    _only_redo,
    _only_submission_id,
    _past_paper_hand_in,
    _readiness_jobs,
    _redo,
    assignment_all_scheme,
    attempt,
    homework_attempt,
    mock_attempt,
    mock_paper,
    past_paper,
    past_paper_attempt,
)

# ---- what is refused -----------------------------------------------------------------


async def test_an_attempt_with_no_final_mark_is_refused_and_unchanged(
    client, tutor, student, published_assignment
):
    hand_in = _homework_hand_in(client, student, published_assignment["id"])
    assert (await hand_in()).status_code == 201  # handed in, not marked
    sid = await _only_submission_id()

    response = await client.post(f"{API}/submissions/{sid}/redo", headers=tutor["headers"])

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This attempt has no final mark yet, so the student can already replace it."
    )
    assert await _count(Submission, Submission.id == sid) == 1
    assert await _count(AttemptRedo) == 0


async def test_a_second_redo_of_the_same_attempt_is_a_404(attempt):
    assert (await _redo(attempt)).status_code == 201
    assert (await _redo(attempt)).status_code == 404
    assert await _count(AttemptRedo) == 1


async def test_a_redo_of_something_that_never_existed_is_a_404(attempt):
    assert (await _redo(attempt, submission_id=999999)).status_code == 404


# ---- who may ask (QA-12) ----------------------------------------------------------------


async def test_a_student_and_a_parent_cannot_redo_and_nothing_changes(attempt):
    parent = await register_parent(attempt.client, attempt.tutor, attempt.student)

    await _carry_rows(attempt)
    async with _assert_untouched(attempt):
        assert (await _redo(attempt, headers=attempt.student["headers"])).status_code == 403
        assert (await _redo(attempt, headers=parent["headers"])).status_code == 403


async def test_no_token_is_a_401(attempt):
    await _carry_rows(attempt)
    async with _assert_untouched(attempt):
        response = await attempt.client.post(f"{API}/submissions/{attempt.submission_id}/redo")
    assert response.status_code == 401


async def test_a_tutor_in_another_organization_gets_a_404(attempt):
    other = await register_other_tutor(attempt.client)
    await _carry_rows(attempt)
    async with _assert_untouched(attempt):
        assert (await _redo(attempt, headers=other["headers"])).status_code == 404


async def test_a_colleague_who_does_not_teach_the_class_gets_a_404(
    client,
    tutor,
    student,
    assignment_all_scheme,
    monkeypatch,
    fake_ai,
    subject,
    group,  # noqa: F811
):
    """Homework belongs to whoever teaches the class (`_tutor_owns`), so a second
    tutor in the same organization is refused like a stranger. (A past paper
    belongs to the organization there, and the redo follows that rule rather than
    adding its own.)"""
    monkeypatch.setattr("app.services.marking.structured_complete", fake_ai(_confident_result()))
    assert (await _homework_hand_in(client, student, assignment_all_scheme)()).status_code == 201
    await _drain_due()
    sid = await _only_submission_id()

    response = await client.post(
        f"{API}/submissions/{sid}/redo", headers=await _colleague_headers()
    )

    assert response.status_code == 404
    assert await _count(Submission, Submission.id == sid) == 1
    assert await _count(AttemptRedo) == 0


# ---- narrowed to the tutor who teaches the student ------------------------------------


async def test_a_colleague_cannot_redo_a_past_paper_attempt_they_do_not_teach(
    past_paper_attempt,
):
    """Marking a past paper is organization-wide (`_tutor_owns`); setting an
    attempt aside is destructive and needs the tutor to teach the student."""
    attempt = past_paper_attempt
    headers = await _colleague_headers()
    await _carry_rows(attempt)

    async with _assert_untouched(attempt):
        response = await _redo(attempt, headers=headers)

    assert response.status_code == 404


async def _colleague_id() -> int:
    async with async_session() as session:
        return (
            await session.scalars(select(User.id).where(User.email == "colleague@example.com"))
        ).one()


async def test_a_colleague_who_teaches_the_student_only_in_another_subject_gets_a_404(
    past_paper_attempt,
):
    """The student is in this tutor's chemistry class and a colleague's physics
    class. The colleague teaches them, so the wide rule passes, and the paper is
    open to the student through the first class — but the colleague does not teach
    the paper's subject, so it is not theirs to set aside. `can_redo` follows."""
    attempt = past_paper_attempt
    headers = await _colleague_headers()
    await _extra_class(attempt, other_subject=True, tutor_id=await _colleague_id())
    await _carry_rows(attempt)

    detail = await attempt.client.get(f"{API}/submissions/{attempt.submission_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["can_redo"] is False
    async with _assert_untouched(attempt):
        response = await _redo(attempt, headers=headers)

    assert response.status_code == 404


async def test_a_colleague_who_teaches_the_papers_subject_to_the_student_may_redo(
    past_paper_attempt,
):
    """The other half: teaching the student in a live class of the paper's own
    subject is exactly what the narrowing asks for."""
    attempt = past_paper_attempt
    headers = await _colleague_headers()
    await _extra_class(attempt, tutor_id=await _colleague_id())

    detail = await attempt.client.get(f"{API}/submissions/{attempt.submission_id}", headers=headers)
    assert detail.json()["can_redo"] is True
    assert (await _redo(attempt, headers=headers)).status_code == 201


# ---- admins and a second organization (QA-12) ---------------------------------------------


async def test_an_admin_of_another_organization_gets_a_404(attempt):
    async with async_session() as session:
        other_org = Organization(name="Another Organization")
        session.add(other_org)
        await session.flush()
        other_org_id = other_org.id
        await session.commit()
    headers = await _headers_for(UserRole.admin, "outside-admin@example.com", other_org_id)
    await _carry_rows(attempt)

    async with _assert_untouched(attempt):
        response = await _redo(attempt, headers=headers)

    assert response.status_code == 404


async def test_an_admin_of_the_same_organization_may_redo(attempt):
    headers = await _headers_for(UserRole.admin, "inside-admin@example.com")
    await _carry_rows(attempt)

    detail = await attempt.client.get(f"{API}/submissions/{attempt.submission_id}", headers=headers)
    assert detail.json()["can_redo"] is True
    response = await _redo(attempt, headers=headers)

    assert response.status_code == 201, response.text
    assert await _count(Submission, Submission.id == attempt.submission_id) == 0
    assert (await _only_redo()).allowed_by_id != attempt.tutor["user"]["id"]


async def test_a_tutor_who_teaches_the_student_in_another_organization_gets_a_404(attempt):
    """A student can sit in a second organization's class. That tutor teaches
    them, but the work belongs to the first organization."""
    other = await register_other_tutor(attempt.client)
    async with async_session() as session:
        other_org_id = (await session.get(User, other["user"]["id"])).organization_id
        assert other_org_id != await org_id(session)
        group = Group(
            organization_id=other_org_id,
            tutor_id=other["user"]["id"],
            subject_id=attempt.subject["id"],
            name="Their class",
        )
        session.add(group)
        await session.flush()
        session.add(GroupMember(group_id=group.id, student_id=attempt.student["user"]["id"]))
        await session.commit()
    await _carry_rows(attempt)

    async with _assert_untouched(attempt):
        response = await _redo(attempt, headers=other["headers"])

    assert response.status_code == 404


# ---- nothing may be marking it -----------------------------------------------------------


@pytest.mark.parametrize("job_type", ["mark_submission", "tag_mistakes"])
@pytest.mark.parametrize("job_status", [JobStatus.pending, JobStatus.running])
async def test_an_attempt_with_marking_work_in_flight_is_refused_and_unchanged(
    homework_attempt, job_type, job_status
):
    attempt = homework_attempt
    await _carry_rows(attempt)
    async with async_session() as session:
        session.add(
            Job(type=job_type, status=job_status, payload={"submission_id": attempt.submission_id})
        )
        await session.commit()

    async with _assert_untouched(attempt):
        response = await _redo(attempt)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This attempt is being marked right now. Try again in a moment."
    )


async def test_a_job_for_another_submission_does_not_block_a_redo(homework_attempt):
    async with async_session() as session:
        session.add(Job(type="mark_submission", payload={"submission_id": 987654}))
        await session.commit()

    assert (await _redo(homework_attempt)).status_code == 201


def _clash(kind: str):
    """The errors a clash with another writer raises out of the redo."""
    if kind == "integrity":
        return IntegrityError("DELETE", {}, Exception("foreign key"))
    if kind == "operational":
        return OperationalError("DELETE", {}, Exception("lock timeout"))
    deadlock = Exception("deadlock detected")
    deadlock.sqlstate = "40P01"  # type: ignore[attr-defined]
    return DBAPIError("DELETE", {}, deadlock)


@pytest.mark.parametrize("kind", ["integrity", "operational", "deadlock"])
async def test_a_clash_with_another_writer_is_a_retry_message_not_a_500(
    homework_attempt, monkeypatch, kind
):
    async def collide(*_args):
        raise _clash(kind)

    monkeypatch.setattr("app.api.submissions.redo_attempt", collide)
    await _carry_rows(homework_attempt)

    async with _assert_untouched(homework_attempt):
        response = await _redo(homework_attempt)

    assert response.status_code == 409
    assert "Try again in a moment" in response.json()["detail"]


async def test_a_database_fault_that_is_not_a_clash_is_not_swallowed(homework_attempt, monkeypatch):
    fault = Exception("syntax error")
    fault.sqlstate = "42601"  # type: ignore[attr-defined]

    async def broken(*_args):
        raise DBAPIError("DELETE", {}, fault)

    monkeypatch.setattr("app.api.submissions.redo_attempt", broken)

    with pytest.raises(DBAPIError):
        await _redo(homework_attempt)


async def test_a_write_that_lands_between_the_snapshot_and_the_delete_fails_closed(
    homework_attempt, monkeypatch
):
    """An audit row the snapshot does not hold must stop the delete, not be
    deleted unrecorded (`PROD-7`)."""
    from app.services import attempt_redo

    real = attempt_redo.build_snapshot

    async def snapshot_then_write(session, kind, submission, marks, parent):
        snapshot = await real(session, kind, submission, marks, parent)
        session.add(
            MarkOverrideAudit(
                question_mark_id=marks[0].id, old_marks=1, new_marks=2, changed_by_id=1
            )
        )
        await session.flush()
        return snapshot

    monkeypatch.setattr(attempt_redo, "build_snapshot", snapshot_then_write)

    # The attempt carries every kind of row, so the deletes that ran before the
    # mismatch was noticed (topic links, mistakes, remark requests) are real and
    # their rollback is what the counts prove.
    await _carry_rows(homework_attempt)

    async with _assert_untouched(homework_attempt):
        response = await _redo(homework_attempt)

    assert response.status_code == 409
    assert "changed while it was being set aside" in response.json()["detail"]


async def test_the_service_says_gone_for_a_submission_that_does_not_exist(homework_attempt):
    from app.models import User
    from app.services.attempt_redo import AttemptGone, redo_attempt

    async with async_session() as session:
        tutor = await session.get(User, homework_attempt.tutor["user"]["id"])
        with pytest.raises(AttemptGone):
            await redo_attempt(session, 999999, tutor)


# ---- the student must still be able to hand in again ----------------------------------------
#
# A redo that leaves the student no way to replace what it deleted destroys marks
# for nothing. Each state below is one the student's own hand-in route refuses
# (404), and the redo must refuse in exactly that state — and only that state.


async def _close_assignment(attempt: Attempt) -> None:
    from app.models import Assignment, AssignmentStatus

    async with async_session() as session:
        row = await session.get(Assignment, attempt.parent_id)
        row.status = AssignmentStatus.closed
        await session.commit()


async def _close_mock(attempt: Attempt) -> None:
    from app.models import Mock, MockStatus

    async with async_session() as session:
        row = await session.get(Mock, attempt.parent_id)
        row.status = MockStatus.closed
        await session.commit()


async def _delete_class(attempt: Attempt) -> None:
    from app.models import Group

    await _extra_class(attempt)
    async with async_session() as session:
        row = await session.get(Group, attempt.group["id"])
        row.deleted_at = utcnow()
        await session.commit()


async def _remove_from_class(attempt: Attempt) -> None:
    from sqlalchemy import delete

    from app.models import GroupMember

    await _extra_class(attempt)
    async with async_session() as session:
        await session.execute(
            delete(GroupMember).where(
                GroupMember.group_id == attempt.group["id"],
                GroupMember.student_id == attempt.student["user"]["id"],
            )
        )
        await session.commit()


async def _leave_the_subject(attempt: Attempt) -> None:
    """The class that gave access to this paper's subject is deleted; the only
    class left is in another subject, so the tutor still teaches the student but
    the paper is no longer theirs to log."""
    from app.models import Group

    await _extra_class(attempt, other_subject=True)
    async with async_session() as session:
        row = await session.get(Group, attempt.group["id"])
        row.deleted_at = utcnow()
        await session.commit()


async def _keep_the_subject(attempt: Attempt) -> None:
    from app.models import Group

    await _extra_class(attempt)
    async with async_session() as session:
        row = await session.get(Group, attempt.group["id"])
        row.deleted_at = utcnow()
        await session.commit()


async def _hide_the_paper(attempt: Attempt) -> None:
    from app.models import PastPaper

    async with async_session() as session:
        row = await session.get(PastPaper, attempt.parent_id)
        row.hidden_at = utcnow()
        await session.commit()


CLOSED_TO_THE_STUDENT = [
    ("homework", _close_assignment),
    ("homework", _delete_class),
    ("homework", _remove_from_class),
    ("mock", _close_mock),
    ("mock", _delete_class),
    ("mock", _remove_from_class),
]

STILL_OPEN_TO_THE_STUDENT = [
    ("past_paper", _keep_the_subject),
    ("past_paper", _hide_the_paper),
]


async def test_a_tutor_who_no_longer_teaches_the_papers_subject_gets_a_404(past_paper_attempt):
    """Only a live class of the paper's own (organization, subject) lets a tutor set
    a past-paper attempt aside. Once the student has only a class in another
    subject, the paper is closed to the student and the tutor has lost it too."""
    attempt = past_paper_attempt
    await _carry_rows(attempt)
    await _leave_the_subject(attempt)

    assert (await attempt.hand_in()).status_code == 404
    async with _assert_untouched(attempt):
        response = await _redo(attempt)

    assert response.status_code == 404


async def test_an_admin_is_refused_a_past_paper_redo_the_student_could_not_hand_in_again(
    past_paper_attempt,
):
    """For a tutor the narrowing makes this state unreachable (teaching the paper's
    subject is what opens it to the student). An admin keeps organization-wide
    reach, so the hand-in gate is what stops a destructive redo for them."""
    attempt = past_paper_attempt
    headers = await _headers_for(UserRole.admin, "gate-admin@example.com")
    await _carry_rows(attempt)
    await _leave_the_subject(attempt)

    assert (await attempt.hand_in()).status_code == 404
    async with _assert_untouched(attempt):
        response = await _redo(attempt, headers=headers)

    assert response.status_code == 409, response.text
    assert "This past paper is no longer open to this student" in response.json()["detail"]


@pytest.fixture
def gated(request):
    return request.getfixturevalue(f"{request.param}_attempt")


def _ids(cases):
    return [f"{kind}-{change.__name__.strip('_')}" for kind, change in cases]


@pytest.mark.parametrize(
    ("gated", "change"),
    CLOSED_TO_THE_STUDENT,
    indirect=["gated"],
    ids=_ids(CLOSED_TO_THE_STUDENT),
)
async def test_a_redo_is_refused_exactly_when_the_student_could_not_hand_in_again(gated, change):
    await _carry_rows(gated)
    await change(gated)

    assert (await gated.hand_in()).status_code == 404
    async with _assert_untouched(gated):
        response = await _redo(gated)

    assert response.status_code == 409, response.text
    assert "is no longer open to this student" in response.json()["detail"]
    assert "could not hand it in again" in response.json()["detail"]


@pytest.mark.parametrize(
    ("gated", "change"),
    STILL_OPEN_TO_THE_STUDENT,
    indirect=["gated"],
    ids=_ids(STILL_OPEN_TO_THE_STUDENT),
)
async def test_a_redo_is_allowed_when_the_student_could_still_hand_in_again(gated, change):
    """The other half of the parity: the student's route is past its gate (and
    stopped only by the lock the redo removes), so the redo must not refuse."""
    await change(gated)

    assert (await gated.hand_in()).status_code == 409
    assert (await _redo(gated)).status_code == 201
    assert (await gated.hand_in()).status_code == 201


async def test_the_gate_reads_the_assignment_as_it_is_when_the_lock_is_taken(homework_attempt):
    """A copy of the assignment left in the session's identity map from an earlier
    read says "published" for one a tutor closed a moment ago. The service
    re-reads the parent after taking the lock, so it is the current row that is
    judged. (Two sessions share the test connection, so this stands in for two
    requests; the lock itself is Postgres-only.)"""
    from app.models import Assignment, AssignmentStatus
    from app.services.attempt_redo import AttemptNotOpen, redo_attempt

    attempt = homework_attempt
    async with async_session() as stale, async_session() as other:
        tutor = await stale.get(User, attempt.tutor["user"]["id"])
        before = await stale.get(Assignment, attempt.parent_id)
        assert before.status == AssignmentStatus.published
        closing = await other.get(Assignment, attempt.parent_id)
        closing.status = AssignmentStatus.closed
        await other.commit()

        with pytest.raises(AttemptNotOpen):
            await redo_attempt(stale, attempt.submission_id, tutor)
        await stale.rollback()


async def test_the_review_page_is_not_offered_a_redo_the_endpoint_would_refuse(homework_attempt):
    attempt = homework_attempt
    url = f"{API}/submissions/{attempt.submission_id}"
    before = await attempt.client.get(url, headers=attempt.tutor["headers"])
    assert before.json()["can_redo"] is True

    await _close_assignment(attempt)
    after = await attempt.client.get(url, headers=attempt.tutor["headers"])

    assert after.json()["can_redo"] is False
    assert (await _redo(attempt)).status_code == 409
