"""Task 8.2/8.3: when a week closes, what is stored for each reader, what the
outbox is handed, and who may read a stored send.

Same pinned world as the facts tests: the week is Sun 4 Oct 18:00 to Sun 11 Oct
18:00 2026 UTC, and the organization sends on Sunday at 18:00.
"""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.api.weekly_sends import weekly_send as read_weekly_send
from app.config import get_settings
from app.db import async_session
from app.models import (
    Job,
    JobStatus,
    Narrative,
    NarrativeAudience,
    Notification,
    NotificationKind,
    Organization,
    UserRole,
    WeeklySend,
    WeeklySendAudience,
)
from app.services import weekly_send
from app.services.weekly_send import (
    BUILD_JOB,
    SWEEP_JOB,
    build_weekly_sends,
    due_organizations,
    load_facts,
    message_params,
    sweep_weekly_sends,
)
from tests.factories import make_user, org_id, register_other_tutor, register_parent
from tests.test_weekly_send_facts import SEND_NOW, WINDOW, _world

WEEK_END = WINDOW[1]
URL = "/api/v1/weekly-sends"


@pytest.fixture
async def world(client, tutor, group, student, subject):
    """The week's evidence, a linked parent, and the send moment set to match."""
    await _world(client, tutor, group, student, subject)
    parent = await register_parent(client, tutor, student)
    async with async_session() as s:
        await s.execute(update(Organization).values(weekly_send_weekday=6, weekly_send_hour=18))
        await s.commit()
        organization_id = await org_id(s)
    return {"org": organization_id, "parent": parent}


async def _build(organization_id: int, week_end=WEEK_END) -> None:
    async with async_session() as s:
        await build_weekly_sends(
            s, {"organization_id": organization_id, "week_end": week_end.isoformat()}
        )
        await s.commit()


async def _sends() -> dict[WeeklySendAudience, WeeklySend]:
    async with async_session() as s:
        return {row.audience: row for row in await s.scalars(select(WeeklySend))}


async def _narrative(organization_id, *, group_id=None, student_id=None, at, text="A good week."):
    async with async_session() as s:
        s.add(
            Narrative(
                organization_id=organization_id,
                audience=(
                    NarrativeAudience.tutor_class if group_id else NarrativeAudience.parent_student
                ),
                group_id=group_id,
                student_id=student_id,
                text=text,
                prompt_version="1",
                model="test",
                generated_at=at,
            )
        )
        await s.commit()


# ----------------------------------------------------------------------- build


async def test_a_closed_week_is_stored_once_for_each_reader(world, tutor, student):
    await _build(world["org"])
    sends = await _sends()
    assert set(sends) == set(WeeklySendAudience)
    assert sends[WeeklySendAudience.tutor].recipient_user_id == tutor["user"]["id"]
    assert sends[WeeklySendAudience.student].recipient_user_id == student["user"]["id"]
    assert sends[WeeklySendAudience.parent].recipient_user_id == world["parent"]["user"]["id"]
    for send in sends.values():
        facts = load_facts(send.audience, send.facts)
        assert (facts.window_start, facts.window_end) == WINDOW
    # Building the same week again changes nothing (BE-6).
    await _build(world["org"])
    async with async_session() as s:
        assert await s.scalar(select(func.count()).select_from(WeeklySend)) == 3
        assert await s.scalar(select(func.count()).select_from(Notification)) == 3


async def test_each_send_is_handed_to_the_outbox_with_counts_only(world):
    await _build(world["org"])
    sends = await _sends()
    async with async_session() as s:
        notes = {n.recipient_user_id: n for n in await s.scalars(select(Notification))}
    for send in sends.values():
        note = notes[send.recipient_user_id]
        assert note.kind == NotificationKind.weekly_send
        assert note.link_path == f"/weekly/{send.id}"
        assert set(note.params) == {"whose", "lessons_count", "homework_done"}
        assert note.params["lessons_count"].isdigit()
        assert note.params["homework_done"].isdigit()
    parent_note = notes[world["parent"]["user"]["id"]]
    assert parent_note.params["whose"].endswith("'s")


async def test_the_paragraphs_are_this_weeks_stored_narratives(world, group, student):
    sid, gid = student["user"]["id"], group["id"]
    await _narrative(world["org"], group_id=gid, at=WEEK_END - timedelta(days=1), text="Class text")
    await _narrative(world["org"], student_id=sid, at=WEEK_END - timedelta(days=30), text="Stale")
    await _build(world["org"])
    sends = await _sends()
    tutor_paragraphs = sends[WeeklySendAudience.tutor].paragraphs
    assert [(p["about"], p["text"]) for p in tutor_paragraphs] == [("Chem Y10", "Class text")]
    # Last month's paragraph is not passed off as being about this week.
    assert sends[WeeklySendAudience.parent].paragraphs == []
    # A learner is never shown the paragraph written to their parent.
    assert sends[WeeklySendAudience.student].paragraphs == []


async def test_a_parent_reads_the_paragraph_about_their_child(world, student):
    sid = student["user"]["id"]
    await _narrative(world["org"], student_id=sid, at=WEEK_END - timedelta(hours=1), text="Steady")
    await _build(world["org"])
    paragraphs = (await _sends())[WeeklySendAudience.parent].paragraphs
    assert [p["text"] for p in paragraphs] == ["Steady"]
    assert paragraphs[0]["about"] == student["user"]["name"]


async def test_one_reader_failing_does_not_cost_the_others_their_week(world, monkeypatch):
    async def boom(session, student, window):
        raise RuntimeError("bad row")

    monkeypatch.setattr(weekly_send, "build_student_facts", boom)
    await _build(world["org"])
    assert set(await _sends()) == {WeeklySendAudience.tutor, WeeklySendAudience.parent}


async def test_a_send_day_changed_since_the_job_was_queued_is_a_no_op(world):
    async with async_session() as s:
        await s.execute(update(Organization).values(weekly_send_weekday=2))
        await s.commit()
    await _build(world["org"])
    assert await _sends() == {}


async def test_nothing_is_built_while_the_kill_switch_is_off(world, monkeypatch):
    monkeypatch.setattr(get_settings(), "weekly_send_enabled", False)
    await _build(world["org"])
    assert await _sends() == {}


async def test_an_account_with_no_classes_is_sent_nothing(client, tutor):
    async with async_session() as s:
        await s.execute(update(Organization).values(weekly_send_weekday=6, weekly_send_hour=18))
        await s.commit()
        organization_id = await org_id(s)
    await _build(organization_id)
    assert await _sends() == {}


# ----------------------------------------------------------------------- sweep


async def test_an_organization_is_due_for_a_day_after_its_week_closes(world):
    async with async_session() as s:
        assert await due_organizations(s, SEND_NOW) == [(world["org"], WEEK_END)]
        # A week that closed more than a day ago is not sent late.
        assert await due_organizations(s, WEEK_END + timedelta(hours=25)) == []
    await _build(world["org"])
    async with async_session() as s:
        assert await due_organizations(s, SEND_NOW) == []


async def test_the_sweep_queues_one_build_and_the_narrative_refresh(world, monkeypatch, group):
    class Clock(weekly_send.datetime):
        @classmethod
        def now(cls, tz=None):
            return SEND_NOW

    monkeypatch.setattr(weekly_send, "datetime", Clock)
    for _ in range(2):  # the second sweep finds the build already waiting
        async with async_session() as s:
            await sweep_weekly_sends(s, {})
            await s.commit()
    async with async_session() as s:
        jobs = (await s.scalars(select(Job))).all()
    builds = [j for j in jobs if j.type == BUILD_JOB]
    assert [j.payload for j in builds] == [
        {"organization_id": world["org"], "week_end": WEEK_END.isoformat()}
    ]
    # Held back so the narrative writer runs first.
    assert builds[0].run_after is not None
    narratives = [j.payload for j in jobs if j.type == "generate_narrative"]
    assert {"audience": "tutor_class", "group_id": group["id"]} in narratives
    assert len(narratives) == 2  # the class and its one learner, once each
    # The schedule re-armed itself exactly once.
    assert len([j for j in jobs if j.type == SWEEP_JOB]) == 1


async def test_a_build_that_stored_nothing_is_not_queued_again(client, tutor, monkeypatch):
    """An account with no classes has no rows to show for its week. The finished
    job is what says the week was handled."""

    class Clock(weekly_send.datetime):
        @classmethod
        def now(cls, tz=None):
            return SEND_NOW

    monkeypatch.setattr(weekly_send, "datetime", Clock)
    async with async_session() as s:
        await s.execute(update(Organization).values(weekly_send_weekday=6, weekly_send_hour=18))
        await s.commit()

    async def sweep() -> list[Job]:
        async with async_session() as s:
            await sweep_weekly_sends(s, {})
            await s.commit()
        async with async_session() as s:
            return list(await s.scalars(select(Job).where(Job.type == BUILD_JOB)))

    (build,) = await sweep()
    async with async_session() as s:
        job = await s.get(Job, build.id)
        job.status = JobStatus.done  # it ran and stored nothing
        await s.commit()
    assert len(await sweep()) == 1
    # A build that failed is tried again by the next sweep.
    async with async_session() as s:
        job = await s.get(Job, build.id)
        job.status = JobStatus.failed
        await s.commit()
    assert len(await sweep()) == 2


async def test_a_send_survives_its_message_failing_to_queue(world, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("outbox is down")

    monkeypatch.setattr(weekly_send, "notify", boom)
    await _build(world["org"])
    assert set(await _sends()) == set(WeeklySendAudience)
    async with async_session() as s:
        assert await s.scalar(select(func.count()).select_from(Notification)) == 0


async def test_the_sweep_keeps_its_schedule_but_builds_nothing_when_switched_off(
    world, monkeypatch
):
    monkeypatch.setattr(get_settings(), "weekly_send_enabled", False)
    async with async_session() as s:
        await sweep_weekly_sends(s, {})
        await s.commit()
    async with async_session() as s:
        assert [j.type for j in await s.scalars(select(Job))] == [SWEEP_JOB]


# ------------------------------------------------------------------ the message


async def test_message_counts_are_sums_and_a_quiet_week_says_zero(world):
    await _build(world["org"])
    sends = await _sends()
    tutor_facts = load_facts(WeeklySendAudience.tutor, sends[WeeklySendAudience.tutor].facts)
    params = message_params(WeeklySendAudience.tutor, tutor_facts)
    held = sum(c.attendance.lessons_held for c in tutor_facts.classes if c.attendance)
    assert params == {
        "whose": "your classes'",
        "lessons_count": str(held),
        "homework_done": str(
            sum(c.homework.handed_in_count for c in tutor_facts.classes if c.homework)
        ),
    }
    student_facts = load_facts(WeeklySendAudience.student, sends[WeeklySendAudience.student].facts)
    assert message_params(WeeklySendAudience.student, student_facts)["whose"] == "your"


# -------------------------------------------------------------------- reading


async def test_each_reader_sees_their_own_send(client, world, tutor, student):
    assert (await client.get(f"{URL}/latest", headers=student["headers"])).json() is None
    await _build(world["org"])
    for who, key in ((tutor, "tutor"), (student, "student"), (world["parent"], "parent")):
        latest = (await client.get(f"{URL}/latest", headers=who["headers"])).json()
        assert latest["audience"] == key
        assert latest[key] is not None
        assert [latest[k] for k in ("tutor", "student", "parent") if k != key] == [None, None]
        listed = (await client.get(URL, headers=who["headers"])).json()
        assert [row["id"] for row in listed] == [latest["id"]]
        one = await client.get(f"{URL}/{latest['id']}", headers=who["headers"])
        assert one.status_code == 200 and one.json() == latest


async def test_the_parent_send_carries_no_topics_and_no_mistakes(client, world):
    await _build(world["org"])
    body = (await client.get(f"{URL}/latest", headers=world["parent"]["headers"])).text
    assert "weak_topics" not in body and "mistake" not in body


async def test_a_tutor_reads_what_went_to_their_learner_and_the_parent(
    client, world, tutor, student
):
    await _build(world["org"])
    sends = await _sends()
    listed = await client.get(
        f"/api/v1/students/{student['user']['id']}/weekly-sends", headers=tutor["headers"]
    )
    assert {row["audience"] for row in listed.json()} == {"student", "parent"}
    for audience in (WeeklySendAudience.student, WeeklySendAudience.parent):
        resp = await client.get(f"{URL}/{sends[audience].id}", headers=tutor["headers"])
        assert resp.status_code == 200


async def test_nobody_reads_a_send_that_is_not_theirs(client, world, tutor, student):
    await _build(world["org"])
    sends = await _sends()
    other = await register_other_tutor(client)
    tutor_send, student_send, parent_send = (
        sends[WeeklySendAudience.tutor].id,
        sends[WeeklySendAudience.student].id,
        sends[WeeklySendAudience.parent].id,
    )
    # Another organization's tutor: every id is a 404, and so is the list.
    for send_id in (tutor_send, student_send, parent_send):
        assert (await client.get(f"{URL}/{send_id}", headers=other["headers"])).status_code == 404
    assert (
        await client.get(
            f"/api/v1/students/{student['user']['id']}/weekly-sends", headers=other["headers"]
        )
    ).status_code == 404
    assert (await client.get(f"{URL}/latest", headers=other["headers"])).json() is None
    # A learner does not read their parent's report or the tutor's.
    for send_id in (tutor_send, parent_send):
        resp = await client.get(f"{URL}/{send_id}", headers=student["headers"])
        assert resp.status_code == 404
    # A parent does not read the tutor's, and the per-student list is tutor-only.
    parent = world["parent"]["headers"]
    assert (await client.get(f"{URL}/{tutor_send}", headers=parent)).status_code == 404
    assert (
        await client.get(f"/api/v1/students/{student['user']['id']}/weekly-sends", headers=parent)
    ).status_code == 403
    assert (await client.get(f"{URL}/latest")).status_code == 401
    assert (await client.get(f"{URL}/999999", headers=tutor["headers"])).status_code == 404


async def test_a_parent_of_another_child_cannot_read_this_childs_send(world):
    """Same organization, different family: the route is called directly because
    this parent exists only as a row, with no credentials to log in with."""
    await _build(world["org"])
    sends = await _sends()
    async with async_session() as s:
        stranger = await make_user(
            s,
            organization_id=world["org"],
            role=UserRole.parent,
            name="Other Parent",
            email="stranger@example.com",
        )
        with pytest.raises(HTTPException) as err:
            await read_weekly_send(sends[WeeklySendAudience.parent].id, s, stranger)
        assert err.value.status_code == 404
