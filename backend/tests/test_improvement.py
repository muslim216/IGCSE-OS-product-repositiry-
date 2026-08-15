"""The improvement ranking — the highest product risk in the plan.

The assertion the whole design rests on is
`test_no_classmate_value_appears_in_any_response`: the endpoint may return the
reader's own rank, the reader's own delta and a count, and nothing else. If a
later change adds a per-classmate value that test is what fails, and the
de-anonymisation vectors documented in services/improvement.py are what it is
protecting.

The ranking maths is tested against `rank_of` and `placing` directly rather than
through the API. Both are pure, the boundary rules they encode are exactly the
ones an off-by-one would break silently, and driving n=11 through HTTP would
mean eleven registered students and a month of history each per case.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.improvement import MIN_RANKED, placing, rank_of
from app.services.readiness_summary import MONTH_WINDOW_DAYS, period_delta

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def _deltas(*values: float) -> dict[int, float]:
    """Reader is always student 1, so the tests read as "me among these"."""
    return {i + 1: v for i, v in enumerate(values)}


# ---- the shape of the payload ----


def test_no_classmate_value_appears_in_any_response():
    """The design in one assertion.

    Every key the endpoint can return is enumerated here. A field carrying a
    classmate's score, grade, delta, name or identity would fail this — which is
    the point, because none of the vectors this design closes survive a
    per-classmate value existing anywhere in the body.
    """
    from app.schemas.improvement import FocusTopic, ImprovementPeriod, SubjectImprovement

    assert set(SubjectImprovement.model_fields) == {
        "subject_id",
        "subject_name",
        "window_days",
        "member_count",
        "periods",
        "focus",
    }
    assert set(ImprovementPeriod.model_fields) == {
        "label",
        "delta",
        "rank",
        "ranked_count",
        "banded",
    }
    assert set(FocusTopic.model_fields) == {"topic_code", "topic_title", "score"}


async def test_improvement_endpoint_is_student_gated(client, tutor):
    """The role gate: a tutor gets 403, an anonymous caller 401. This is the
    signature gate (QA-12); the cross-organization scope is exercised
    separately below, where it is the SEC-8 control that actually matters."""
    resp = await client.get("/api/v1/improvement/me", headers=tutor["headers"])
    assert resp.status_code == 403

    anonymous = await client.get("/api/v1/improvement/me")
    assert anonymous.status_code == 401


async def _register_tutor(client, email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": email, "email": email, "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {
        "user": data["user"],
        "headers": {"Authorization": f"Bearer {data['tokens']['access_token']}"},
    }


async def _join_student(client, tutor_headers: dict, group_id: int, name: str) -> int:
    invite = await client.post(f"/api/v1/groups/{group_id}/invites", headers=tutor_headers)
    resp = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": name,
            "email": f"{name}@example.com",
            "password": "password123",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["user"]["id"]


async def test_classmates_excludes_another_orgs_students_for_the_same_subject(client, tutor):
    """SEC-8, the control this whole feature turns on. Subjects are global, so a
    student in another organization's class for the *same* subject must never
    enter the reader's cohort — otherwise the ranking would compare children
    across tenants and leak the size of a stranger's class.

    Two organizations, each with a class in one shared subject, one student
    each. The reader's classmate set, and therefore member_count, is exactly
    their own org's roster.
    """
    from app.db import async_session
    from app.models import Subject, User
    from app.services.improvement import _classmates

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

    # Org A (the shared `tutor` fixture) teaches this subject.
    group_a = await client.post(
        "/api/v1/groups",
        json={"name": "A-Chem", "subject_id": subject_id},
        headers=tutor["headers"],
    )
    reader_id = await _join_student(client, tutor["headers"], group_a.json()["id"], "reader")

    # Org B is a different tutor (different organization) teaching the same
    # global subject to their own student.
    tutor_b = await _register_tutor(client, "tutorB@example.com")
    group_b = await client.post(
        "/api/v1/groups",
        json={"name": "B-Chem", "subject_id": subject_id},
        headers=tutor_b["headers"],
    )
    stranger_id = await _join_student(client, tutor_b["headers"], group_b.json()["id"], "stranger")

    async with async_session() as session:
        reader = await session.get(User, reader_id)
        peers = await _classmates(session, reader, subject_id)

    assert reader_id in peers
    assert stranger_id not in peers
    assert len(peers) == 1  # member_count sees only the reader's own org


# ---- the gates ----


def test_gate_counts_full_period_deltas_not_enrolment():
    """Eight enrolled including one joiner is seven data points, and must not
    pass a headcount test."""
    seven = _deltas(*[float(i) for i in range(7)])
    assert placing(1, seven, member_count=8).rank is None

    eight = _deltas(*[float(i) for i in range(8)])
    assert placing(1, eight, member_count=8).rank is not None
    assert len(eight) == MIN_RANKED


def test_coverage_below_gate_returns_no_rank_but_still_returns_own_delta():
    """Ranking the eight students with evidence out of thirty is not a ranking.
    The reader's own movement is still theirs and still renders — that is a
    complete surface, not a degraded one."""
    result = placing(1, _deltas(*[float(i) for i in range(8)]), member_count=30)
    assert result.rank is None
    assert result.delta == 0.0  # student 1's own value, unaffected by the gate


def test_a_reader_with_no_delta_gets_no_rank_and_no_fabricated_zero():
    result = placing(99, _deltas(*[float(i) for i in range(8)]), member_count=8)
    assert result.rank is None
    assert result.delta is None


# ---- the placing rules ----


@pytest.mark.parametrize(
    "n,rank,expected_banded",
    [
        (11, 5, False),  # floor(11/2) = 5 — the last exact placing
        (11, 6, True),  # one past the line
        (8, 4, False),  # floor(8/2) = 4
        (8, 5, True),
    ],
)
def test_top_half_boundary_is_floor_n_over_2(n, rank, expected_banded):
    """Distinct deltas, so the reader's rank is exactly `rank`: n descending
    integers, and the reader takes the one at that position."""
    values = [float(n - i) for i in range(n)]
    _, banded = rank_of(values[rank - 1], values)
    assert banded is expected_banded


def test_tie_shares_the_better_rank():
    """Two students on the same delta are joint 3rd; the next is 5th. Breaking
    the tie by id would invent an ordering the data does not contain."""
    values = [10.0, 9.0, 6.0, 6.0, 4.0, 3.0, 2.0, 1.0]
    assert rank_of(6.0, values)[0] == 3
    assert rank_of(4.0, values)[0] == 5


def test_tie_spanning_the_boundary_is_banded_for_everyone_in_it():
    """The off-by-one this rule exists to prevent.

    n=11, cut-off 5. Three students tie on 6, taking positions 5, 6 and 7 at a
    shared rank of 5. Showing all three "5th" renders the exact placing for two
    students who are in the second half; showing them different numbers breaks
    the tie rule. So the whole group is banded.
    """
    values = [12.0, 11.0, 10.0, 9.0, 6.0, 6.0, 6.0, 3.0, 2.0, 1.0, 0.0]
    rank, banded = rank_of(6.0, values)
    assert rank == 5
    assert banded is True
    # And the student directly above the tie, safely inside the top half, is not
    # dragged into the band with them.
    assert rank_of(9.0, values) == (4, False)


def test_a_tie_wholly_inside_the_top_half_stays_exact():
    values = [12.0, 9.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    assert rank_of(9.0, values) == (2, False)


# ---- the window ----


def test_a_student_in_their_first_weeks_has_no_delta_rather_than_zero():
    """Their score has no month behind it. Reporting the change since their
    first ever computation as "this month" would credit them with progress they
    have not had."""
    points = [(NOW - timedelta(days=3), 50.0), (NOW - timedelta(days=1), 62.0)]
    assert period_delta(points, NOW) is None


def test_the_baseline_is_where_they_stood_a_month_ago_not_their_oldest_record():
    points = [
        (NOW - timedelta(days=200), 20.0),  # ancient, and not the baseline
        (NOW - timedelta(days=MONTH_WINDOW_DAYS + 1), 60.0),
        (NOW - timedelta(days=2), 66.0),
    ]
    assert period_delta(points, NOW) == 6.0


def test_nothing_recorded_inside_the_window_is_absent_not_zero():
    """No movement to report is not the same as no movement, and it is the
    difference the "full period" gate turns on."""
    points = [
        (NOW - timedelta(days=120), 40.0),
        (NOW - timedelta(days=90), 55.0),
    ]
    assert period_delta(points, NOW) is None


def test_the_window_is_anchored_to_midnight_so_a_rank_cannot_be_correlated():
    """Two reads on the same day must give the same answer. A window anchored to
    the request moment would shift continuously, and a rank that moves minutes
    after a submission points at whose submission it was."""
    points = [
        (NOW - timedelta(days=MONTH_WINDOW_DAYS + 1), 60.0),
        (NOW - timedelta(days=1), 70.0),
    ]
    morning = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
    evening = datetime(2026, 6, 15, 22, 0, tzinfo=timezone.utc)
    assert period_delta(points, morning) == period_delta(points, evening) == 10.0


def test_a_snapshot_created_today_does_not_move_the_current_delta():
    """The teeth of the privacy control. A point written *today* — a classmate's
    fresh submission recomputed at midday — must not change the current delta
    between a morning and an evening read. The current window closes at today's
    midnight, so today's point is excluded until tomorrow. If the window ended at
    the request time instead, the evening read would jump to it and the rank
    would move minutes after the submission (Qodo, CodeRabbit)."""
    baseline = (NOW - timedelta(days=MONTH_WINDOW_DAYS + 1), 60.0)
    yesterday = (NOW - timedelta(days=1), 70.0)
    today_noon = (datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc), 95.0)

    morning = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
    evening = datetime(2026, 6, 15, 22, 0, tzinfo=timezone.utc)

    before = period_delta([baseline, yesterday], morning)
    after = period_delta([baseline, yesterday, today_noon], evening)
    assert before == after == 10.0  # today's 95 is not in the window yet


def test_window_start_treats_a_naive_now_as_utc():
    """A naive datetime is read as UTC, the same rule every point timestamp gets
    through _aware — otherwise astimezone() would read it as host-local time and
    shift the whole window by the machine's offset (CodeRabbit)."""
    from app.services.readiness_summary import window_start

    naive = datetime(2026, 6, 15, 12, 0)
    aware = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert window_start(naive) == window_start(aware)


def test_earlier_periods_read_their_own_window():
    """YOUR MONTHS is the same computation shifted back, not a different one."""
    points = [
        (NOW - timedelta(days=70), 40.0),
        (NOW - timedelta(days=45), 50.0),  # inside the previous window
        (NOW - timedelta(days=1), 58.0),
    ]
    assert period_delta(points, NOW, periods_ago=1) == 10.0
    assert period_delta(points, NOW, periods_ago=0) == 8.0
