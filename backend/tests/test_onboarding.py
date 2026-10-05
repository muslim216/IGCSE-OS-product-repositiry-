"""Task 9.1a — onboarding state derived from data, and default acknowledgements."""

from datetime import date, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import async_session
from app.models import (
    Chapter,
    Group,
    Organization,
    ReadinessWeights,
    ScheduleSlot,
    SetupAcknowledgement,
    SetupItem,
    Subject,
    TeachingPlan,
    TeachingPlanStatus,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.security import create_access_token
from app.services.grade_boundaries import defaults_for_scale, set_org_boundaries
from app.services.mistake_categories import ensure_categories
from app.services.onboarding import acknowledge
from tests.factories import make_subject, make_user, register_other_tutor, register_parent

API = "/api/v1/onboarding"
ACK = f"{API}/acknowledgements"


async def _user(email="tutor@example.com") -> User:
    async with async_session() as session:
        return await session.scalar(select(User).where(User.email == email))


async def _subject(tutor, *, code="4CH1", name="Chemistry", chapters=0):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.id == tutor["user"]["id"]))
        s = await make_subject(
            session,
            organization_id=user.organization_id,
            code=code,
            name=name,
            grade_boundaries=[],
        )
        for i in range(chapters):
            session.add(Chapter(subject_id=s.id, code=str(i + 1), title=f"Ch {i}", position=i))
        await session.commit()
        return s.id


async def _group(tutor, subject_id, name="Y10"):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.id == tutor["user"]["id"]))
        g = Group(
            organization_id=user.organization_id,
            tutor_id=user.id,
            subject_id=subject_id,
            name=name,
        )
        session.add(g)
        await session.commit()
        return g.id


async def _slot(group_id):
    async with async_session() as session:
        session.add(
            ScheduleSlot(group_id=group_id, weekday=1, start_time=time(17), duration_min=60)
        )
        await session.commit()


async def _plan(group_id, status, acceptor_id=None):
    async with async_session() as session:
        org_id = await session.scalar(select(Group.organization_id).where(Group.id == group_id))
        session.add(
            TeachingPlan(
                organization_id=org_id,
                group_id=group_id,
                status=status,
                exam_date=date(2027, 5, 1),
                lessons_per_week=2,
                lesson_minutes=60,
                **(
                    {"accepted_at": utcnow(), "accepted_by_id": acceptor_id}
                    if status is TeachingPlanStatus.accepted
                    else {}
                ),
            )
        )
        await session.commit()


async def _get(client, tutor):
    resp = await client.get(API, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _ack(client, tutor, item, subject_id=None):
    return await client.post(
        ACK, json={"item": item, "subject_id": subject_id}, headers=tutor["headers"]
    )


async def _answer_taught_before(group_id):
    async with async_session() as session:
        (await session.get(Group, group_id)).taught_before_answered_at = utcnow()
        await session.commit()


def _item(subject_state, key):
    return next(i for i in subject_state["items"] if i["key"] == key)


def _steps(cls):
    return {s["key"]: s["done"] for s in cls["steps"]}


# --- brand new / Required steps ---------------------------------------------


async def test_brand_new_tutor(client, tutor):
    body = await _get(client, tutor)
    assert body["subjects"] == []
    assert body["complete"] is False
    assert body["in_flow"] is True
    assert body["next_step"] == {"key": "syllabus", "subject_id": None, "group_id": None}
    assert body["account"] == {"key": "account_basics", "kind": "defaulted", "state": "default"}


async def test_required_steps_flip_in_order_and_complete(client, tutor):
    sid = await _subject(tutor)
    body = await _get(client, tutor)
    assert body["subjects"][0]["required"] == [{"key": "syllabus", "done": False}]
    assert body["next_step"] == {"key": "syllabus", "subject_id": sid, "group_id": None}

    async with async_session() as session:
        session.add(Chapter(subject_id=sid, code="1", title="Atoms", position=0))
        await session.commit()
    body = await _get(client, tutor)
    assert body["subjects"][0]["required"] == [{"key": "syllabus", "done": True}]
    # Syllabus is in but no class exists: the class (with its timetable) is next.
    assert body["next_step"] == {"key": "timetable", "subject_id": sid, "group_id": None}

    gid = await _group(tutor, sid)
    body = await _get(client, tutor)
    assert _steps(body["subjects"][0]["classes"][0]) == {
        "timetable": False,
        "taught_before": False,
        "plan_inputs": False,
        "plan_accepted": False,
    }
    assert body["next_step"] == {"key": "timetable", "subject_id": sid, "group_id": gid}

    await _slot(gid)
    body = await _get(client, tutor)
    assert body["next_step"] == {"key": "taught_before", "subject_id": sid, "group_id": gid}

    # "Starting fresh" is an answer: no topics, but the question is closed.
    await _answer_taught_before(gid)
    body = await _get(client, tutor)
    assert body["next_step"] == {"key": "plan_inputs", "subject_id": sid, "group_id": gid}

    await _plan(gid, TeachingPlanStatus.draft)
    body = await _get(client, tutor)
    assert _steps(body["subjects"][0]["classes"][0])["plan_inputs"] is True
    assert body["next_step"] == {"key": "plan_accepted", "subject_id": sid, "group_id": gid}
    assert body["complete"] is False

    async with async_session() as session:
        plan = await session.scalar(select(TeachingPlan).where(TeachingPlan.group_id == gid))
        plan.status = TeachingPlanStatus.accepted
        plan.accepted_at = utcnow()
        plan.accepted_by_id = tutor["user"]["id"]
        await session.commit()
    body = await _get(client, tutor)
    assert body["complete"] is True
    assert body["next_step"] is None
    assert body["subjects"][0]["classes"][0]["complete"] is True


async def test_complete_needs_the_syllabus_of_that_class_subject(client, tutor):
    """A finished class under a subject with no chapters is not onboarding done."""
    sid = await _subject(tutor)
    gid = await _group(tutor, sid)
    await _slot(gid)
    await _answer_taught_before(gid)
    await _plan(gid, TeachingPlanStatus.accepted, tutor["user"]["id"])
    body = await _get(client, tutor)
    assert body["subjects"][0]["classes"][0]["complete"] is True
    assert body["complete"] is False
    assert body["next_step"] == {"key": "syllabus", "subject_id": sid, "group_id": None}


async def test_next_step_points_at_the_class_closest_to_done(client, tutor):
    sid = await _subject(tutor, chapters=1)
    behind = await _group(tutor, sid, "Behind")
    ahead = await _group(tutor, sid, "Ahead")
    await _slot(ahead)
    body = await _get(client, tutor)
    assert body["next_step"] == {"key": "taught_before", "subject_id": sid, "group_id": ahead}
    assert behind != ahead


async def test_an_accepted_plan_without_the_taught_before_answer_is_not_complete(client, tutor):
    """A class set up before the question existed still owes its answer."""
    sid = await _subject(tutor, chapters=1)
    gid = await _group(tutor, sid)
    await _slot(gid)
    await _plan(gid, TeachingPlanStatus.accepted, tutor["user"]["id"])
    body = await _get(client, tutor)
    assert body["complete"] is False
    assert body["next_step"] == {"key": "taught_before", "subject_id": sid, "group_id": gid}
    # Not complete, yet past the finish line: the missing answer is owed on the
    # checklist, the tutor is not sent back into the flow.
    assert body["in_flow"] is False


async def test_in_flow_until_a_plan_is_accepted_at_every_stage(client, tutor):
    assert (await _get(client, tutor))["in_flow"] is True
    sid = await _subject(tutor)
    assert (await _get(client, tutor))["in_flow"] is True  # no syllabus
    async with async_session() as session:
        session.add(Chapter(subject_id=sid, code="1", title="Ch", position=0))
        await session.commit()
    assert (await _get(client, tutor))["in_flow"] is True  # no class
    gid = await _group(tutor, sid)
    assert (await _get(client, tutor))["in_flow"] is True  # no timetable
    await _slot(gid)
    await _answer_taught_before(gid)
    assert (await _get(client, tutor))["in_flow"] is True  # no plan
    await _plan(gid, TeachingPlanStatus.draft)
    assert (await _get(client, tutor))["in_flow"] is True  # draft only
    async with async_session() as session:
        plan = await session.scalar(select(TeachingPlan).where(TeachingPlan.group_id == gid))
        plan.status = TeachingPlanStatus.accepted
        plan.accepted_at = utcnow()
        plan.accepted_by_id = tutor["user"]["id"]
        await session.commit()
    body = await _get(client, tutor)
    assert body["in_flow"] is False
    assert body["complete"] is True


async def test_another_tutors_accepted_plan_does_not_end_this_tutors_flow(client, tutor):
    sid = await _subject(tutor, chapters=1)
    async with async_session() as session:
        org_id = (await _user()).organization_id
        colleague = await make_user(
            session, organization_id=org_id, role=UserRole.tutor, name="C", email="c@example.com"
        )
        group = Group(organization_id=org_id, tutor_id=colleague.id, subject_id=sid, name="Theirs")
        session.add(group)
        await session.commit()
        colleague_group = group.id
        colleague_id = colleague.id
    await _plan(colleague_group, TeachingPlanStatus.accepted, colleague_id)
    assert (await _get(client, tutor))["in_flow"] is True

    other = await register_other_tutor(client)
    other_sid = await _subject(other, code="4MA1", name="Maths", chapters=1)
    other_gid = await _group(other, other_sid, name="Other")
    await _plan(other_gid, TeachingPlanStatus.accepted, other["user"]["id"])
    assert (await _get(client, other))["in_flow"] is False
    assert (await _get(client, tutor))["in_flow"] is True


# --- Defaulted items ---------------------------------------------------------


async def test_account_basics_default_reviewed_and_set_by_you(client, tutor):
    assert (await _get(client, tutor))["account"]["state"] == "default"
    body = (await _ack(client, tutor, "account_basics")).json()
    assert body["account"]["state"] == "reviewed"

    async with async_session() as session:
        org = await session.get(Organization, (await _user()).organization_id)
        org.weekly_send_weekday = 2
        await session.commit()
    assert (await _get(client, tutor))["account"]["state"] == "set_by_you"


async def test_account_basics_unacknowledged_change_is_set_by_you(client, tutor):
    async with async_session() as session:
        org = await session.get(Organization, (await _user()).organization_id)
        org.ai_language = "ar"
        await session.commit()
    assert (await _get(client, tutor))["account"]["state"] == "set_by_you"


async def test_boundaries_states(client, tutor):
    sid = await _subject(tutor)
    subject = (await _get(client, tutor))["subjects"][0]
    # No rows is no predicted grade, not a default in force, and acknowledging
    # nothing does not make it something (PROD-2).
    assert _item(subject, "boundaries")["state"] == "not_set"
    body = (await _ack(client, tutor, "boundaries", sid)).json()
    assert _item(body["subjects"][0], "boundaries")["state"] == "not_set"
    assert body["subjects"][0]["reviewed_count"] == 0

    sid2 = await _subject(tutor, code="4MA1", name="Maths")
    async with async_session() as session:
        await set_org_boundaries(
            session, (await _user()).organization_id, sid2, defaults_for_scale("9-1")
        )
        await session.commit()
    maths = next(s for s in (await _get(client, tutor))["subjects"] if s["subject_id"] == sid2)
    assert _item(maths, "boundaries")["state"] == "set_by_you"


async def test_marking_rules_states(client, tutor):
    sid = await _subject(tutor)
    assert _item((await _get(client, tutor))["subjects"][0], "marking_rules")["state"] == "default"
    resp = await client.put(
        f"/api/v1/subjects/{sid}/marking-rules",
        json={"rules": "Award method marks."},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert _item((await _get(client, tutor))["subjects"][0], "marking_rules")["state"] == (
        "set_by_you"
    )
    # Clearing stores NULL, the same as never set, so it reads as default again.
    await client.put(
        f"/api/v1/subjects/{sid}/marking-rules", json={"rules": ""}, headers=tutor["headers"]
    )
    assert _item((await _get(client, tutor))["subjects"][0], "marking_rules")["state"] == "default"


async def test_mistake_categories_states(client, tutor):
    sid = await _subject(tutor)
    org_id = (await _user()).organization_id
    # Auto-written defaults are ordinary rows but not a tutor decision.
    async with async_session() as session:
        await ensure_categories(session, org_id, sid)
        await session.commit()
    subject = (await _get(client, tutor))["subjects"][0]
    assert _item(subject, "mistake_categories")["state"] == "default"
    body = (await _ack(client, tutor, "mistake_categories", sid)).json()
    assert _item(body["subjects"][0], "mistake_categories")["state"] == "reviewed"

    async with async_session() as session:
        rows = await ensure_categories(session, org_id, sid)
        rows[0].name = "Slip"
        await session.commit()
    subject = (await _get(client, tutor))["subjects"][0]
    assert _item(subject, "mistake_categories")["state"] == "set_by_you"


async def test_weak_threshold_states(client, tutor):
    sid = await _subject(tutor)
    assert _item((await _get(client, tutor))["subjects"][0], "weak_threshold")["state"] == "default"
    user = await _user()
    async with async_session() as session:
        # The editor writes the whole row: saving a factor weight stores the
        # threshold it inherited, which is not the tutor choosing one.
        row = ReadinessWeights(
            organization_id=user.organization_id,
            subject_id=sid,
            tutor_id=user.id,
            weak_threshold=60.0,
        )
        session.add(row)
        await session.commit()
        assert (
            _item((await _get(client, tutor))["subjects"][0], "weak_threshold")["state"]
            == "default"
        )
        row.weak_threshold = 55.0
        await session.commit()
    assert _item((await _get(client, tutor))["subjects"][0], "weak_threshold")["state"] == (
        "set_by_you"
    )


async def test_teaching_guidance_is_optional_and_never_counts(client, tutor):
    sid = await _subject(tutor)
    subject = (await _get(client, tutor))["subjects"][0]
    assert _item(subject, "teaching_guidance") == {
        "key": "teaching_guidance",
        "kind": "optional",
        "state": "not_set",
    }
    assert subject["review_total"] == 4
    async with async_session() as session:
        s = await session.get(Subject, sid)
        s.guidance_path = "guidance/x.pdf"
        await session.commit()
    subject = (await _get(client, tutor))["subjects"][0]
    assert _item(subject, "teaching_guidance")["state"] == "set_by_you"
    assert subject["reviewed_count"] == 0
    assert subject["review_total"] == 4


async def test_reviewed_count_counts_reviewed_and_set_by_you(client, tutor):
    sid = await _subject(tutor)
    await _ack(client, tutor, "weak_threshold", sid)
    await client.put(
        f"/api/v1/subjects/{sid}/marking-rules", json={"rules": "x"}, headers=tutor["headers"]
    )
    subject = (await _get(client, tutor))["subjects"][0]
    assert (subject["reviewed_count"], subject["review_total"]) == (2, 4)


# --- acknowledgements --------------------------------------------------------


async def test_acknowledgement_is_idempotent(client, tutor):
    sid = await _subject(tutor)
    for _ in range(2):
        assert (await _ack(client, tutor, "boundaries", sid)).status_code == 200
        assert (await _ack(client, tutor, "account_basics")).status_code == 200
    async with async_session() as session:
        assert await session.scalar(select(func.count()).select_from(SetupAcknowledgement)) == 2


async def test_unique_indexes_hold_for_null_subject_and_subject(client, tutor):
    """The row-level guarantee behind the race-safety, on the real schema."""
    sid = await _subject(tutor)
    user = await _user()

    def row(subject_id, item):
        return SetupAcknowledgement(
            organization_id=user.organization_id,
            subject_id=subject_id,
            item=item,
            acknowledged_by_id=user.id,
            acknowledged_at=utcnow(),
        )

    for subject_id, item in (
        (None, SetupItem.account_basics),
        (sid, SetupItem.boundaries),
    ):
        async with async_session() as session:
            session.add(row(subject_id, item))
            await session.commit()
        async with async_session() as session:
            session.add(row(subject_id, item))
            with pytest.raises(IntegrityError):
                await session.commit()


async def test_losing_a_race_is_a_no_op(client, tutor):
    """Two submits both pass the existence check; the unique index refuses the
    second insert, and that must read as success, not an error. (The HTTP-level
    race cannot be driven here: the test engine shares one SQLite connection.)"""
    sid = await _subject(tutor)
    user = await _user()
    async with async_session() as session:
        await acknowledge(session, user, SetupItem.weak_threshold, sid)
        await session.commit()
    async with async_session() as session:
        real_scalar = session.scalar

        async def blind_once(*args, **kwargs):
            session.scalar = real_scalar
            return None

        session.scalar = blind_once
        await acknowledge(session, user, SetupItem.weak_threshold, sid)
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(SetupAcknowledgement)) == 1


async def test_acknowledgement_validation(client, tutor):
    sid = await _subject(tutor)
    # Unknown, Required and Optional keys are not acknowledgeable.
    for key in ("nope", "syllabus", "timetable", "plan_accepted", "teaching_guidance"):
        assert (await _ack(client, tutor, key, sid)).status_code == 422, key
    # A subject-level item needs a subject; the account item takes none.
    assert (await _ack(client, tutor, "boundaries")).status_code == 422
    assert (await _ack(client, tutor, "account_basics", sid)).status_code == 422
    # A subject that does not exist.
    assert (await _ack(client, tutor, "boundaries", 99999)).status_code == 404
    async with async_session() as session:
        assert await session.scalar(select(func.count()).select_from(SetupAcknowledgement)) == 0


# --- auth and tenancy (QA-12) ------------------------------------------------


async def test_student_and_parent_are_refused(client, tutor, student):
    parent = await register_parent(client, tutor, student)
    sid = await _subject(tutor, code="4MA1", name="Maths")
    for who in (student, parent):
        assert (await client.get(API, headers=who["headers"])).status_code == 403
        resp = await client.post(
            ACK, json={"item": "boundaries", "subject_id": sid}, headers=who["headers"]
        )
        assert resp.status_code == 403
    async with async_session() as session:
        assert await session.scalar(select(func.count()).select_from(SetupAcknowledgement)) == 0


async def test_unauthenticated_is_refused(client):
    assert (await client.get(API)).status_code == 401
    assert (await client.post(ACK, json={"item": "account_basics"})).status_code == 401


async def test_other_organization_sees_and_touches_nothing(client, tutor):
    sid = await _subject(tutor, chapters=1)
    gid = await _group(tutor, sid)
    await _slot(gid)
    await _ack(client, tutor, "boundaries", sid)
    await _ack(client, tutor, "account_basics")

    other = await register_other_tutor(client)
    body = await _get(client, other)
    assert body["subjects"] == []
    assert body["account"]["state"] == "default"
    assert body["next_step"] == {"key": "syllabus", "subject_id": None, "group_id": None}

    # Cannot acknowledge for a subject only the first organization has, and the
    # refusal is indistinguishable from a subject that does not exist.
    resp = await _ack(client, other, "boundaries", sid)
    assert resp.status_code == 404
    assert resp.json() == (await _ack(client, other, "boundaries", 99999)).json()
    async with async_session() as session:
        assert await session.scalar(select(func.count()).select_from(SetupAcknowledgement)) == 2

    # The other org's acknowledgement of the account item is its own.
    await _ack(client, other, "account_basics")
    assert (await _get(client, tutor))["account"]["state"] == "reviewed"
    async with async_session() as session:
        assert await session.scalar(select(func.count()).select_from(SetupAcknowledgement)) == 3


async def test_classes_are_the_callers_own(client, tutor):
    """A colleague in the same organization shares its subjects and their
    acknowledgements, and sees none of this tutor's classes."""
    sid = await _subject(tutor, chapters=1)
    await _group(tutor, sid)
    await _ack(client, tutor, "weak_threshold", sid)
    async with async_session() as session:
        org_id = (await _user()).organization_id
        colleague = await make_user(
            session, organization_id=org_id, role=UserRole.tutor, name="C", email="c@example.com"
        )
        await session.commit()
        token = create_access_token(colleague.id, colleague.token_version)
    theirs = await _get(client, {"headers": {"Authorization": f"Bearer {token}"}})
    assert [s["subject_id"] for s in theirs["subjects"]] == [sid]
    assert theirs["subjects"][0]["classes"] == []
    # Settings are the organization's, so a colleague's review of one counts.
    assert _item(theirs["subjects"][0], "weak_threshold")["state"] == "reviewed"
    assert len((await _get(client, tutor))["subjects"][0]["classes"]) == 1

    other = await register_other_tutor(client)
    assert (await _get(client, other))["subjects"] == []


async def test_a_subject_id_past_int32_is_refused_before_the_database(client, tutor):
    assert (await _ack(client, tutor, "boundaries", 10**20)).status_code == 422
    assert (await _ack(client, tutor, "boundaries", 0)).status_code == 422
