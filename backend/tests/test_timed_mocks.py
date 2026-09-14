"""Task 3.6 (AV-115, AV-116): a mock is timed from when the student first opens
it, the clock is the server's, and a late submission is accepted and flagged
rather than blocked.

The distinction that runs through all of this: a past-paper attempt's `timed`
and `time_taken_minutes` are **self-declared** and must be labelled as such
(`PROD-8`, `UX-20`); a mock's `measured_minutes` is measured by the server and
must not be.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Mock, MockOpening, Submission, SubmissionFile
from app.models.base import utcnow
from app.services import mock_clock
from tests.conftest import PDF_BYTES, PNG_BYTES
from tests.test_mocks import mock_paper  # noqa: F401 — fixture


async def _open(client, student, mock_id):
    return await client.post(f"/api/v1/mocks/{mock_id}/open", headers=student["headers"])


async def _sit(client, student, mock_id, text="my answers"):
    return await client.post(
        f"/api/v1/mocks/{mock_id}/submissions",
        data={"typed_answer": text},
        headers=student["headers"],
    )


async def _rewind(mock_id: int, student_id: int, minutes: int) -> None:
    """Move this student's start time back, which is how these tests make time
    pass without sleeping through a 90-minute mock."""
    async with async_session() as session:
        opening = await session.scalar(
            select(MockOpening).where(
                MockOpening.mock_id == mock_id, MockOpening.student_id == student_id
            )
        )
        opening.opened_at = utcnow() - timedelta(minutes=minutes)
        await session.commit()


# --- the clock --------------------------------------------------------------


async def test_opening_a_mock_starts_its_clock(client, student, mock_paper):  # noqa: F811
    resp = await _open(client, student, mock_paper["id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overdue"] is False
    # 90 minutes, from the fixture. Not asserted to the second — the point is
    # that the server answers with the mock's real duration, not that the test
    # and the server tick together.
    assert 89 * 60 <= body["seconds_remaining"] <= 90 * 60
    assert body["due_at"] > body["opened_at"]


async def test_coming_back_does_not_buy_more_time(client, student, mock_paper):  # noqa: F811
    """The clock starts once. Closing the tab and reopening is the obvious way
    to try for a second hour, and the reason `opened_at` is written server-side
    and never rewritten."""
    first = (await _open(client, student, mock_paper["id"])).json()
    await _rewind(mock_paper["id"], _student_id(student), 30)
    second = (await _open(client, student, mock_paper["id"])).json()

    assert second["opened_at"] < first["opened_at"]  # the rewound one, not a new one
    assert second["seconds_remaining"] < 61 * 60
    async with async_session() as session:
        assert len((await session.scalars(select(MockOpening))).all()) == 1


def _student_id(student) -> int:
    return student["user"]["id"]


async def test_an_untimed_mock_shows_no_countdown_rather_than_zero(
    client,
    tutor,
    student,
    mock_paper,  # noqa: F811
):
    """A tutor may set no duration. Absent is shown as absent (`PROD-2`,
    `UX-19`) — a zero countdown would read as "your time is up"."""
    async with async_session() as session:
        mock = await session.get(Mock, mock_paper["id"])
        mock.duration_minutes = None
        await session.commit()

    body = (await _open(client, student, mock_paper["id"])).json()
    assert body["seconds_remaining"] is None
    assert body["due_at"] is None
    assert body["overdue"] is False


async def test_the_clock_runs_out_on_the_server_whatever_the_browser_thinks(
    client,
    student,
    mock_paper,  # noqa: F811
):
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 91)

    body = (await _open(client, student, mock_paper["id"])).json()
    assert body["overdue"] is True
    # Clamped rather than negative: no screen should have to decide what a
    # countdown below zero means.
    assert body["seconds_remaining"] == 0


# --- late is flagged, never blocked -----------------------------------------


async def test_a_late_submission_is_accepted_and_flagged(client, student, mock_paper):  # noqa: F811
    """`AV-116`. Refusing it would lose a student's work to punish something the
    tutor is better placed to judge."""
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 120)

    resp = await _sit(client, student, mock_paper["id"])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["submitted_late"] is True
    assert body["measured_minutes"] == 120

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.submitted_late is True
        # And the work itself is all there — flagged, not trimmed.
        assert submission.typed_answer == "my answers"


async def test_a_submission_inside_the_time_is_not_flagged(client, student, mock_paper):  # noqa: F811
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 45)

    body = (await _sit(client, student, mock_paper["id"])).json()
    assert body["submitted_late"] is False
    assert body["measured_minutes"] == 45


async def test_a_sitting_nobody_timed_reports_no_time_rather_than_zero(
    client,
    student,
    mock_paper,  # noqa: F811
):
    """A student who never called `/open` has no start time. Nothing is invented
    to stand in for one (`PROD-2`) — zero minutes would read as an instant
    sitting, which is a lie about a real student."""
    body = (await _sit(client, student, mock_paper["id"])).json()
    assert body["measured_minutes"] is None
    # Null, not false: there is no deadline this could have missed.
    assert body["submitted_late"] is None


# --- measured is not self-declared ------------------------------------------


async def test_a_measured_mock_never_carries_the_self_declared_fields(
    client,
    student,
    mock_paper,  # noqa: F811
):
    """`PROD-8`/`UX-20`: a past paper's `timed` and `time_taken_minutes` are the
    student's own word for it and are labelled as such wherever shown. A mock's
    time is measured, and putting it in those fields would make every screen
    that reads them label the truth as a claim."""
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 50)
    await _sit(client, student, mock_paper["id"])

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        assert submission.measured_minutes == 50
        # The self-declared pair stays untouched and at its defaults.
        assert submission.timed is False
        assert submission.time_taken_minutes is None


# --- the arithmetic ---------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, 0), (1, 1), (59, 1), (60, 1), (61, 2), (5400, 90), (5401, 91)],
)
def test_elapsed_minutes_rounds_up(seconds, expected):
    """Up, not down: a student who hands in at 90 minutes and 40 seconds took 91
    minutes, and rounding to 90 would report a sitting inside its limit that was
    not."""
    started = utcnow()
    assert mock_clock.elapsed_minutes(started, started + timedelta(seconds=seconds)) == expected


def test_the_clock_is_read_from_values_not_from_a_session():
    """`BE-4` — the arithmetic is plain values in, values out, so it can be
    tested without a database and cannot quietly grow a query."""
    started = utcnow()
    clock = mock_clock.read(started, 90, now=started + timedelta(minutes=89))
    assert clock.overdue is False
    assert 0 < clock.seconds_remaining <= 60
    assert mock_clock.read(started, 90, now=started + timedelta(minutes=90)).overdue is True


async def test_the_tutor_sees_that_a_mock_came_in_late(client, tutor, student, mock_paper):  # noqa: F811
    """`AV-116` has two halves: late is never blocked, **and** it is shown to
    the tutor. Recording it without surfacing it would be the same as not
    recording it."""
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 150)
    submission_id = (await _sit(client, student, mock_paper["id"])).json()["submission_id"]

    detail = await client.get(f"/api/v1/submissions/{submission_id}", headers=tutor["headers"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["submitted_late"] is True
    assert detail.json()["measured_minutes"] == 150


async def test_homework_carries_no_measured_time(client, tutor, student, published_assignment):  # noqa: F811
    """The fields are a mock's. On homework they stay absent rather than
    reporting a sitting nobody measured (`PROD-2`)."""
    resp = await client.post(
        f"/api/v1/assignments/{published_assignment['id']}/submissions",
        data={"typed_answer": "done"},
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text
    detail = await client.get(
        f"/api/v1/submissions/{resp.json()['submission_id']}", headers=tutor["headers"]
    )
    assert detail.json()["measured_minutes"] is None
    # Null, not false: nothing timed this, so "on time" would be an assertion
    # about a sitting that was never measured.
    assert detail.json()["submitted_late"] is None


async def test_the_student_list_says_which_mocks_they_have_already_sat(
    client,
    student,
    mock_paper,  # noqa: F811
):
    """`sat_on` is the tutor's sitting date and says nothing about whether this
    student handed in. Carried on the list so the screen does not ask once per
    row — that is the same N+1, one layer out."""
    before = await client.get("/api/v1/mocks/mine", headers=student["headers"])
    assert [m["my_submission_status"] for m in before.json()] == [None]

    await _open(client, student, mock_paper["id"])
    await _sit(client, student, mock_paper["id"])

    after = await client.get("/api/v1/mocks/mine", headers=student["headers"])
    assert after.json()[0]["my_submission_status"] == "submitted"


async def test_one_students_sitting_is_invisible_to_another(client, tutor, group, mock_paper):  # noqa: F811
    """It is *their* submission status, not the class's (`SEC-7`)."""
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Omar",
            "email": "omar@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    other = {"headers": {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}}

    await _open(client, other, mock_paper["id"])
    await _sit(client, other, mock_paper["id"])
    assert (await client.get("/api/v1/mocks/mine", headers=other["headers"])).json()[0][
        "my_submission_status"
    ] == "submitted"

    # A classmate who has not sat it still sees nothing.
    invite2 = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    resp2 = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite2.json()["code"],
            "name": "Lina",
            "email": "lina@example.com",
            "password": "password123",
        },
    )
    assert resp2.status_code == 201, resp2.text
    classmate = {"headers": {"Authorization": f"Bearer {resp2.json()['tokens']['access_token']}"}}
    assert (await client.get("/api/v1/mocks/mine", headers=classmate["headers"])).json()[0][
        "my_submission_status"
    ] is None


async def test_a_clock_that_collides_does_not_discard_the_caller_s_other_work(
    client,
    student,
    mock_paper,
    monkeypatch,  # noqa: F811
):
    """The recovery from a simultaneous open is a SAVEPOINT rollback, not a
    transaction one.

    A full rollback would be correct for this row and wrong for everything else
    in the session — it would silently take any work the caller had already
    staged with it, and the caller would get no exception saying so. Today's
    only caller stages nothing; this is what stops the next one being surprised.

    The race is forced rather than waited for: the first lookup is made to miss
    once, which is exactly the window between another request's insert and this
    one's flush.
    """
    from app.models import Mock
    from app.services import mock_clock

    student_id = _student_id(student)
    async with async_session() as session:
        mock = await session.get(Mock, mock_paper["id"])
        # The other request's row, already committed — what this one collides
        # with.
        session.add(MockOpening(mock_id=mock.id, student_id=student_id))
        await session.commit()

        # Work the caller staged before asking for the clock.
        mock.title = "Renamed while the clock was being read"
        await session.flush()

        real_scalar = session.scalar
        missed = False

        async def _miss_once(*args, **kwargs):
            nonlocal missed
            if not missed:
                missed = True
                return None
            return await real_scalar(*args, **kwargs)

        monkeypatch.setattr(session, "scalar", _miss_once)
        opening = await mock_clock.start(session, mock, student_id)
        monkeypatch.undo()

        assert missed, "the collision path was never entered"
        assert opening is not None
        await session.commit()

    async with async_session() as session:
        # The staged rename survived the collision, and no second clock started.
        assert (await session.get(Mock, mock_paper["id"])).title == (
            "Renamed while the clock was being read"
        )
        assert len((await session.scalars(select(MockOpening))).all()) == 1


async def test_a_late_upload_is_accepted_like_a_late_typed_answer(
    client,
    student,
    mock_paper,  # noqa: F811
):
    """The promise is "late is accepted and flagged" for **every** way a student
    can hand in, not just the typed one. Photographed pages are how most of them
    actually do it."""
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 130)

    resp = await client.post(
        f"/api/v1/mocks/{mock_paper['id']}/submissions",
        files=[("files", ("page1.png", PNG_BYTES, "image/png"))],
        headers=student["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["submitted_late"] is True
    assert resp.json()["measured_minutes"] == 130

    async with async_session() as session:
        submission = await session.scalar(select(Submission))
        # The pages arrived with it — flagged, not trimmed.
        assert len((await session.scalars(select(SubmissionFile))).all()) == 1
        assert submission.submitted_late is True


async def test_a_student_outside_the_class_cannot_start_its_clock(
    client,
    tutor,
    subject,
    mock_paper,  # noqa: F811
):
    """`QA-12`. `/open` writes a row, so it is the one route in this task that
    must refuse a stranger by itself rather than by association."""
    other_group = await client.post(
        "/api/v1/groups",
        json={"name": "Someone else's class", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    invite = await client.post(
        f"/api/v1/groups/{other_group.json()['id']}/invites", headers=tutor["headers"]
    )
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Outsider",
            "email": "outsider@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    outsider = {"headers": {"Authorization": f"Bearer {resp.json()['tokens']['access_token']}"}}

    # 404, not 403 — an id is enumerable and must not confirm the mock exists.
    assert (await _open(client, outsider, mock_paper["id"])).status_code == 404
    async with async_session() as session:
        assert (await session.scalars(select(MockOpening))).all() == []


async def test_a_resit_is_still_timed_from_the_first_opening(client, student, mock_paper):  # noqa: F811
    """The clock starts once, and that holds across a resubmission too: a
    student who hands in, reopens and hands in again is still measured from when
    they first saw the paper. Anything else would hand out a fresh hour for the
    price of a second click."""
    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 40)
    first = (await _sit(client, student, mock_paper["id"], "first go")).json()
    assert first["measured_minutes"] == 40
    assert first["submitted_late"] is False

    await _open(client, student, mock_paper["id"])
    await _rewind(mock_paper["id"], _student_id(student), 200)
    second = (await _sit(client, student, mock_paper["id"], "second go")).json()

    # Measured from the original opening, so the resit is over its time.
    assert second["measured_minutes"] == 200
    assert second["submitted_late"] is True
    async with async_session() as session:
        assert len((await session.scalars(select(MockOpening))).all()) == 1


async def test_a_class_cannot_be_swapped_under_a_student_mid_sitting(
    client,
    tutor,
    subject,
    student,
    mock_paper,  # noqa: F811
):
    """Reassigning was already refused once anyone had handed in. A student
    with the paper open is the same situation one step earlier: moving the mock
    takes it away from them mid-sitting and the work they have done is lost."""
    assert (await _open(client, student, mock_paper["id"])).status_code == 200

    other = await client.post(
        "/api/v1/groups",
        json={"name": "A different class", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    resp = await client.patch(
        f"/api/v1/mocks/{mock_paper['id']}",
        json={"group_id": other.json()["id"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 409
    assert "sitting this mock" in resp.text


async def test_a_mock_cannot_be_set_with_a_duration_of_zero_or_less(
    client,
    tutor,
    subject,
    group,  # noqa: F811
):
    """A zero or negative duration puts the deadline at or before the moment
    the student opens the paper — every submission late before they have read a
    question."""
    for bad in ("0", "-30"):
        resp = await client.post(
            "/api/v1/mocks",
            data={
                "subject_id": str(subject["id"]),
                "title": "Impossible mock",
                "group_id": str(group["id"]),
                "duration_minutes": bad,
            },
            files={"paper": ("mock.pdf", PDF_BYTES, "application/pdf")},
            headers=tutor["headers"],
        )
        assert resp.status_code == 422, f"{bad}: {resp.status_code}"


def test_the_last_second_is_shown_as_a_second_not_as_zero():
    """Truncating would show 0 while `overdue` was still false — a screen
    saying "time is up" over a server that disagrees, which is the confusion a
    server-side clock exists to end."""
    from datetime import timedelta

    started = utcnow()
    # Six tenths of a second left.
    clock = mock_clock.read(started, 1, now=started + timedelta(seconds=59.4))
    assert clock.overdue is False
    assert clock.seconds_remaining == 1

    done = mock_clock.read(started, 1, now=started + timedelta(seconds=60))
    assert done.overdue is True
    assert done.seconds_remaining == 0
