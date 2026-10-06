"""Task 8.2/8.3: when a week closes, what is stored for each reader, what the
outbox is handed, and who may read a stored send.

Same pinned world as the facts tests: the week is Sun 4 Oct 18:00 to Sun 11 Oct
18:00 2026 UTC, and the organization sends on Sunday at 18:00.
"""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app.api.weekly_sends import weekly_send as read_weekly_send
from app.config import get_settings
from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    Job,
    JobStatus,
    Narrative,
    NarrativeAudience,
    Notification,
    NotificationKind,
    Organization,
    ParentLink,
    UserRole,
    WeeklySend,
    WeeklySendAudience,
)
from app.models.base import utcnow
from app.security import create_access_token
from app.services import weekly_send
from app.services.weekly_send import (
    BUILD_JOB,
    SWEEP_JOB,
    build_weekly_sends,
    due_organizations,
    dump_facts,
    load_facts,
    message_params,
    sweep_weekly_sends,
)
from app.services.weekly_send_facts import ParentChildFacts, ParentFacts
from tests.factories import (
    link_parent,
    make_user,
    org_id,
    register_other_tutor,
    register_parent,
)
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


async def _set_send_moment(organization_id: int, weekday: int, hour: int) -> None:
    async with async_session() as s:
        await s.execute(
            update(Organization)
            .where(Organization.id == organization_id)
            .values(weekly_send_weekday=weekday, weekly_send_hour=hour)
        )
        await s.commit()


async def test_moving_the_hour_earlier_after_sending_does_not_send_again(world):
    await _build(world["org"])  # Sunday 18:00 went out
    await _set_send_moment(world["org"], 6, 12)
    async with async_session() as s:
        # Sunday 12:00 is inside the late grace and has no stored row of its own.
        assert await due_organizations(s, SEND_NOW + timedelta(hours=2)) == []


async def test_moving_the_hour_later_the_same_day_after_sending_does_not_send_again(world):
    await _build(world["org"])
    await _set_send_moment(world["org"], 6, 20)
    async with async_session() as s:
        # The new end is the Sunday 20:00 that has just passed; Sunday 18:00 already went.
        assert await due_organizations(s, WEEK_END + timedelta(hours=2, minutes=30)) == []


async def test_a_day_moved_to_saturday_still_sends_on_the_following_saturday(world):
    # Six days after Sunday's end: further apart than half a week, so it sends.
    await _build(world["org"])  # Sunday 11 Oct
    await _set_send_moment(world["org"], 5, 18)
    saturday = WEEK_END + timedelta(days=6, minutes=30)  # Saturday 17 Oct 18:30
    async with async_session() as s:
        assert await due_organizations(s, saturday) == [
            (world["org"], WEEK_END + timedelta(days=6))
        ]


async def test_a_day_moved_to_wednesday_skips_that_wednesday_and_sends_the_next(world):
    await _build(world["org"])  # Sunday 11 Oct
    await _set_send_moment(world["org"], 2, 18)
    wednesday = WEEK_END + timedelta(days=3, minutes=30)  # would repeat four days
    async with async_session() as s:
        assert await due_organizations(s, wednesday) == []
        assert await due_organizations(s, wednesday + timedelta(days=7)) == [
            (world["org"], WEEK_END + timedelta(days=10))
        ]


async def test_a_day_moved_to_thursday_sends_that_thursday(world):
    await _build(world["org"])
    await _set_send_moment(world["org"], 3, 18)
    thursday = WEEK_END + timedelta(days=4, minutes=30)  # repeats three days: under half
    async with async_session() as s:
        assert await due_organizations(s, thursday) == [
            (world["org"], WEEK_END + timedelta(days=4))
        ]


async def test_the_next_weeks_send_is_still_due_week_after_week(world):
    await _build(world["org"])
    async with async_session() as s:
        assert await due_organizations(s, SEND_NOW + timedelta(days=7)) == [
            (world["org"], WEEK_END + timedelta(days=7))
        ]


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


# ------------------------------------------------- what a reader may still see


async def _two_child_parent_send(world, subject):
    """The parent's stored send covers Sara and a second child, Omar, who is
    taught by a second tutor in the same organization."""
    async with async_session() as s:
        other = await make_user(
            s, organization_id=world["org"], role=UserRole.tutor, name="T2", email="t2@example.com"
        )
        omar = await make_user(
            s,
            organization_id=world["org"],
            role=UserRole.student,
            name="Omar",
            email="o@example.com",
        )
        g2 = Group(
            organization_id=world["org"], tutor_id=other.id, subject_id=subject["id"], name="Other"
        )
        s.add(g2)
        await s.flush()
        s.add(GroupMember(group_id=g2.id, student_id=omar.id))
        await link_parent(s, world["parent"]["user"]["id"], omar.id)
        facts = ParentFacts(
            WINDOW[0],
            WINDOW[1],
            (ParentChildFacts("Omar", ()), ParentChildFacts("Sara", ())),
            0,
        )
        row = WeeklySend(
            organization_id=world["org"],
            recipient_user_id=world["parent"]["user"]["id"],
            audience=WeeklySendAudience.parent,
            week_start=WINDOW[0],
            week_end=WINDOW[1],
            facts=dump_facts(WeeklySendAudience.parent, facts),
            paragraphs=[
                {"about": "Omar", "text": "Omar paragraph", "narrative_id": 1},
                {"about": "Sara", "text": "Sara paragraph", "narrative_id": 2},
            ],
        )
        s.add(row)
        await s.flush()
        ids = {"send": row.id, "omar": omar.id, "other": other.id}
        await s.commit()
    ids["other_headers"] = {"Authorization": f"Bearer {create_access_token(ids['other'], 0)}"}
    return ids


def _names(body):
    return [c["child_name"] for c in body["parent"]["children"]]


async def test_a_parent_loses_a_child_they_are_no_longer_linked_to(client, world, subject):
    ids = await _two_child_parent_send(world, subject)
    headers = world["parent"]["headers"]
    both = (await client.get(f"{URL}/{ids['send']}", headers=headers)).json()
    assert _names(both) == ["Omar", "Sara"]
    assert len(both["paragraphs"]) == 2
    async with async_session() as s:
        await s.execute(delete(ParentLink).where(ParentLink.student_id == ids["omar"]))
        await s.commit()
    for body in (
        (await client.get(f"{URL}/{ids['send']}", headers=headers)).json(),
        (await client.get(f"{URL}/latest", headers=headers)).json(),
    ):
        assert _names(body) == ["Sara"]
        assert [p["about"] for p in body["paragraphs"]] == ["Sara"]
        assert "Omar" not in str(body)
    assert [r["id"] for r in (await client.get(URL, headers=headers)).json()] == [ids["send"]]


async def test_a_send_with_no_linked_child_left_is_hidden_from_the_parent(client, world, subject):
    ids = await _two_child_parent_send(world, subject)
    headers = world["parent"]["headers"]
    async with async_session() as s:
        await s.execute(delete(ParentLink))
        await s.commit()
    assert (await client.get(f"{URL}/{ids['send']}", headers=headers)).status_code == 404
    assert (await client.get(f"{URL}/latest", headers=headers)).json() is None
    assert (await client.get(URL, headers=headers)).json() == []


async def test_a_tutor_reads_only_the_children_they_teach_in_a_parents_send(
    client, world, student, subject, tutor
):
    ids = await _two_child_parent_send(world, subject)
    url = f"{URL}/{ids['send']}"
    mine = (await client.get(url, headers=tutor["headers"])).json()
    assert _names(mine) == ["Sara"]
    assert "Omar" not in str(mine)
    assert [p["about"] for p in mine["paragraphs"]] == ["Sara"]
    theirs = (await client.get(url, headers=ids["other_headers"])).json()
    assert _names(theirs) == ["Omar"]
    assert "Sara" not in str(theirs)
    listed = await client.get(
        f"/api/v1/students/{student['user']['id']}/weekly-sends", headers=tutor["headers"]
    )
    assert ids["send"] in [row["id"] for row in listed.json()]


async def test_a_duplicate_child_name_is_dropped_rather_than_guessed(client, world, subject):
    """Two stored children called Sara, one now linked: the stored send holds no
    id, so it cannot say which is which and both go."""
    ids = await _two_child_parent_send(world, subject)
    async with async_session() as s:
        row = await s.get(WeeklySend, ids["send"])
        facts = ParentFacts(
            WINDOW[0],
            WINDOW[1],
            (ParentChildFacts("Sara", ()), ParentChildFacts("Sara", ())),
            0,
        )
        row.facts = dump_facts(WeeklySendAudience.parent, facts)
        await s.commit()
    resp = await client.get(f"{URL}/{ids['send']}", headers=world["parent"]["headers"])
    assert resp.status_code == 404


async def test_an_admin_keeps_the_organization_wide_view(client, world, subject):
    ids = await _two_child_parent_send(world, subject)
    async with async_session() as s:
        admin = await make_user(
            s, organization_id=world["org"], role=UserRole.admin, name="A", email="a@example.com"
        )
        await s.commit()
    headers = {"Authorization": f"Bearer {create_access_token(admin.id, 0)}"}
    body = (await client.get(f"{URL}/{ids['send']}", headers=headers)).json()
    assert _names(body) == ["Omar", "Sara"]


async def _send_with_ids(world, children, paragraphs):
    async with async_session() as s:
        facts = ParentFacts(
            WINDOW[0],
            WINDOW[1],
            tuple(ParentChildFacts(name, (), cid) for name, cid in children),
            2,
        )
        row = WeeklySend(
            organization_id=world["org"],
            recipient_user_id=world["parent"]["user"]["id"],
            audience=WeeklySendAudience.parent,
            week_start=WINDOW[0],
            week_end=WINDOW[1],
            facts=dump_facts(WeeklySendAudience.parent, facts),
            paragraphs=paragraphs,
        )
        s.add(row)
        await s.flush()
        send_id = row.id
        await s.commit()
    return send_id


async def test_a_new_child_with_an_old_childs_name_does_not_inherit_the_send(
    client, world, student, subject
):
    """Sam-A was unlinked; Sam-B, taught by Tutor2, was linked later. Same name,
    different child: neither the parent nor Tutor2 reads Sam-A's facts."""
    parent_id = world["parent"]["user"]["id"]
    sam_a = 987654
    send_id = await _send_with_ids(
        world,
        [("Sam", sam_a), ("Sara", student["user"]["id"])],
        [
            {"about": "Sam", "text": "Sam-A paragraph", "narrative_id": 1, "child_id": sam_a},
            {
                "about": "Sara",
                "text": "Sara paragraph",
                "narrative_id": 2,
                "child_id": student["user"]["id"],
            },
        ],
    )
    async with async_session() as s:
        tutor2 = await make_user(
            s, organization_id=world["org"], role=UserRole.tutor, name="T2", email="t2@example.com"
        )
        sam_b = await make_user(
            s,
            organization_id=world["org"],
            role=UserRole.student,
            name="Sam",
            email="sb@example.com",
        )
        g2 = Group(
            organization_id=world["org"], tutor_id=tutor2.id, subject_id=subject["id"], name="G2"
        )
        s.add(g2)
        await s.flush()
        s.add(GroupMember(group_id=g2.id, student_id=sam_b.id))
        await link_parent(s, parent_id, sam_b.id)
        await s.commit()
        t2_id = tutor2.id
    url = f"{URL}/{send_id}"
    body = (await client.get(url, headers=world["parent"]["headers"])).json()
    assert _names(body) == ["Sara"]
    assert "Sam-A" not in str(body)
    t2 = {"Authorization": f"Bearer {create_access_token(t2_id, 0)}"}
    assert (await client.get(url, headers=t2)).status_code == 404


async def test_a_send_stored_before_ids_still_filters_by_name_but_not_a_later_link(
    client, world, student, subject, tutor
):
    ids = await _two_child_parent_send(world, subject)
    headers = world["parent"]["headers"]
    url = f"{URL}/{ids['send']}"
    assert _names((await client.get(url, headers=headers)).json()) == ["Omar", "Sara"]
    async with async_session() as s:
        # A link made after the send was stored cannot inherit a name-matched child.
        await s.execute(
            update(ParentLink)
            .where(ParentLink.student_id == ids["omar"])
            .values(created_at=utcnow() + timedelta(days=1))
        )
        await s.commit()
    assert _names((await client.get(url, headers=headers)).json()) == ["Sara"]


async def test_a_renamed_child_with_an_id_is_still_visible_to_their_parent(client, world, student):
    send_id = await _send_with_ids(
        world,
        [("Old Name", student["user"]["id"])],
        [
            {
                "about": "Old Name",
                "text": "Para",
                "narrative_id": 1,
                "child_id": student["user"]["id"],
            }
        ],
    )
    body = (await client.get(f"{URL}/{send_id}", headers=world["parent"]["headers"])).json()
    assert _names(body) == ["Old Name"]
    assert len(body["paragraphs"]) == 1


async def test_a_tutor_does_not_learn_of_unresolved_links_through_the_filtered_send(
    client, world, student, tutor
):
    send_id = await _send_with_ids(world, [("Sara", student["user"]["id"])], [])
    mine = (await client.get(f"{URL}/{send_id}", headers=tutor["headers"])).json()
    assert mine["parent"]["dropped_links"] == 0
    own = (await client.get(f"{URL}/{send_id}", headers=world["parent"]["headers"])).json()
    assert own["parent"]["dropped_links"] == 2


async def test_the_latest_send_skips_one_with_nothing_left(client, world, subject):
    ids = await _two_child_parent_send(world, subject)
    async with async_session() as s:
        await s.execute(delete(ParentLink))
        await s.commit()
    assert (await client.get(f"{URL}/latest", headers=world["parent"]["headers"])).json() is None
    assert ids
