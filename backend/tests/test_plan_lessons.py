"""Task 6.5 (AV-17, E15): the plan suggests the next lesson, and creating one
confirms its slot. Lessons are never auto-created."""

from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.db import async_session
from app.models import (
    Chapter,
    Lesson,
    LessonTopic,
    Organization,
    PlanSlot,
    PlanSlotProvenance,
    ScheduleSlot,
    TeachingPlan,
    TeachingPlanStatus,
    Topic,
    User,
)
from app.services import plan_lessons
from tests.factories import make_subject, org_id

EXAM = date.today() + timedelta(days=120)


@pytest.fixture
async def chapters(subject):
    """Two chapters; the first holds the fixture's two topics, the second one of its own."""
    async with async_session() as s:
        c1 = Chapter(subject_id=subject["id"], code="C1", title="Atoms", position=1)
        c2 = Chapter(subject_id=subject["id"], code="C2", title="Bonding", position=2)
        s.add_all([c1, c2])
        await s.flush()
        for topic_id in (subject["topic1"], subject["topic2"]):
            (await s.get(Topic, topic_id)).chapter_id = c1.id
        extra = Topic(subject_id=subject["id"], code="2.1", title="Covalent", chapter_id=c2.id)
        s.add(extra)
        await s.commit()
        return {"c1": c1.id, "c2": c2.id, "t_c2": extra.id}


async def _plan(group, tutor, chapter_ids, *, status=TeachingPlanStatus.accepted, start=10):
    async with async_session() as s:
        plan = TeachingPlan(
            organization_id=await org_id(s),
            group_id=group["id"],
            status=status,
            exam_date=EXAM,
            lessons_per_week=2,
            lesson_minutes=60,
            accepted_at=datetime.now(timezone.utc) if status.value == "accepted" else None,
            accepted_by_id=tutor["user"]["id"] if status.value == "accepted" else None,
        )
        s.add(plan)
        await s.flush()
        rows = [
            PlanSlot(
                plan_id=plan.id,
                chapter_id=cid,
                scheduled_date=date.today() + timedelta(days=start + i),
                sequence=i + 1,
            )
            for i, cid in enumerate(chapter_ids)
        ]
        s.add_all(rows)
        await s.commit()
        return [r.id for r in rows]


def _next(group):
    return f"/api/v1/groups/{group['id']}/plan/next-lesson"


async def _post_lesson(client, tutor, group, **over):
    body = {"group_id": group["id"], "date": date.today().isoformat(), **over}
    return await client.post("/api/v1/lessons", json=body, headers=tutor["headers"])


async def _slot(slot_id):
    async with async_session() as s:
        row = await s.get(PlanSlot, slot_id)
        return row.lesson_id, row.provenance


async def _lesson_count():
    async with async_session() as s:
        return await s.scalar(select(func.count()).select_from(Lesson))


# --- The suggestion ------------------------------------------------------------


async def test_suggestion_is_the_earliest_unstarted_slot_with_its_chapters_topics(
    client, tutor, group, chapters, subject
):
    slots = await _plan(group, tutor, [chapters["c2"], chapters["c1"]])
    resp = await client.get(_next(group), headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["slot_id"] == slots[0]
    assert body["chapter"]["code"] == "C2"
    assert [t["id"] for t in body["topics"]] == [chapters["t_c2"]]
    assert await _lesson_count() == 0  # nothing is created by asking


async def test_suggestion_skips_linked_confirmed_and_completed_slots(
    client, tutor, group, chapters
):
    slots = await _plan(group, tutor, [chapters["c1"], chapters["c1"], chapters["c2"]])
    async with async_session() as s:
        (await s.get(PlanSlot, slots[0])).provenance = PlanSlotProvenance.completed
        (await s.get(PlanSlot, slots[1])).provenance = PlanSlotProvenance.confirmed
        await s.commit()
    body = (await client.get(_next(group), headers=tutor["headers"])).json()
    assert body["slot_id"] == slots[2]


async def test_suggestion_skips_a_slot_a_lesson_is_linked_to(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"], chapters["c2"]])
    resp = await _post_lesson(client, tutor, group, plan_slot_id=slots[0])
    assert resp.status_code == 201, resp.text
    body = (await client.get(_next(group), headers=tutor["headers"])).json()
    assert body["slot_id"] == slots[1]


async def test_suggestion_is_null_once_every_slot_is_started(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"]])
    assert (await _post_lesson(client, tutor, group, plan_slot_id=slots[0])).status_code == 201
    resp = await client.get(_next(group), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() is None


async def test_suggestion_never_reads_a_draft_plan(client, tutor, group, chapters):
    await _plan(group, tutor, [chapters["c1"]], status=TeachingPlanStatus.draft)
    resp = await client.get(_next(group), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() is None


async def test_suggestion_uses_the_accepted_plan_when_a_draft_sits_beside_it(
    client, tutor, group, chapters
):
    # The draft's slot is earlier; it must still be ignored.
    await _plan(group, tutor, [chapters["c1"]], status=TeachingPlanStatus.draft, start=1)
    accepted = await _plan(group, tutor, [chapters["c2"]], start=20)
    body = (await client.get(_next(group), headers=tutor["headers"])).json()
    assert body["slot_id"] == accepted[0]


async def test_suggestion_is_null_with_no_plan(client, tutor, group):
    resp = await client.get(_next(group), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() is None


# --- Confirming on create ------------------------------------------------------


async def test_create_with_a_slot_links_it_confirms_it_and_keeps_the_tutors_topics(
    client, tutor, group, chapters, subject
):
    slots = await _plan(group, tutor, [chapters["c1"]])
    # The suggestion is chapter 1's two topics; the tutor keeps only one.
    resp = await _post_lesson(
        client, tutor, group, plan_slot_id=slots[0], topic_ids=[subject["topic2"]]
    )
    assert resp.status_code == 201, resp.text
    assert [t["id"] for t in resp.json()["topics"]] == [subject["topic2"]]
    lesson_id, provenance = await _slot(slots[0])
    assert lesson_id == resp.json()["id"]
    assert provenance is PlanSlotProvenance.confirmed
    async with async_session() as s:
        rows = (await s.scalars(select(LessonTopic.topic_id))).all()
    assert rows == [subject["topic2"]]


async def test_create_without_a_slot_touches_no_slot(client, tutor, group, chapters, subject):
    slots = await _plan(group, tutor, [chapters["c1"]])
    resp = await _post_lesson(client, tutor, group, topic_ids=[subject["topic1"]])
    assert resp.status_code == 201
    assert await _slot(slots[0]) == (None, PlanSlotProvenance.generated)


async def test_a_slot_of_another_class_is_404_and_creates_no_lesson(
    client, tutor, group, chapters, subject
):
    slots = await _plan(group, tutor, [chapters["c1"]])
    other = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y11", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    resp = await _post_lesson(client, tutor, other.json(), plan_slot_id=slots[0])
    assert resp.status_code == 404
    assert await _lesson_count() == 0
    assert (await _slot(slots[0]))[0] is None


async def test_a_slot_in_another_organization_is_404(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"]])
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-lessons@example.com", "password": "password123"},
    )
    assert reg.status_code == 201, reg.text
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    async with async_session() as s:
        other_org = await s.scalar(
            select(User.organization_id).where(User.id == reg.json()["user"]["id"])
        )
        other_subject = await make_subject(s, organization_id=other_org, code="OTH1")
        await s.commit()
        other_subject_id = other_subject.id
    other_group = await client.post(
        "/api/v1/groups", json={"name": "Theirs", "subject_id": other_subject_id}, headers=headers
    )
    assert other_group.status_code == 201, other_group.text
    resp = await client.post(
        "/api/v1/lessons",
        json={
            "group_id": other_group.json()["id"],
            "date": date.today().isoformat(),
            "plan_slot_id": slots[0],
        },
        headers=headers,
    )
    assert resp.status_code == 404
    assert (await _slot(slots[0]))[0] is None


async def test_an_already_linked_slot_is_409(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"]])
    assert (await _post_lesson(client, tutor, group, plan_slot_id=slots[0])).status_code == 201
    resp = await _post_lesson(client, tutor, group, plan_slot_id=slots[0])
    assert resp.status_code == 409
    assert await _lesson_count() == 1


async def test_a_completed_slot_is_409(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"]])
    async with async_session() as s:
        (await s.get(PlanSlot, slots[0])).provenance = PlanSlotProvenance.completed
        await s.commit()
    assert (await _post_lesson(client, tutor, group, plan_slot_id=slots[0])).status_code == 409
    assert await _lesson_count() == 0


async def test_a_draft_plans_slot_cannot_be_confirmed(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"]], status=TeachingPlanStatus.draft)
    resp = await _post_lesson(client, tutor, group, plan_slot_id=slots[0])
    assert resp.status_code == 404
    assert await _lesson_count() == 0
    assert await _slot(slots[0]) == (None, PlanSlotProvenance.generated)


async def test_a_topic_from_another_subject_is_422_and_creates_nothing(
    client, tutor, group, chapters
):
    slots = await _plan(group, tutor, [chapters["c1"]])
    async with async_session() as s:
        foreign = await make_subject(s, code="OTH2")
        topic = Topic(subject_id=foreign.id, code="9.9", title="Elsewhere")
        s.add(topic)
        await s.commit()
        topic_id = topic.id
    resp = await _post_lesson(client, tutor, group, plan_slot_id=slots[0], topic_ids=[topic_id])
    assert resp.status_code == 422
    assert await _lesson_count() == 0
    assert (await _slot(slots[0]))[0] is None


# --- Never auto-created --------------------------------------------------------


async def test_nothing_creates_a_lesson_on_its_own(client, tutor, group, chapters):
    await _plan(group, tutor, [chapters["c1"], chapters["c2"]])
    for url in (_next(group), f"/api/v1/groups/{group['id']}/plan"):
        assert (await client.get(url, headers=tutor["headers"])).status_code == 200
    assert await _lesson_count() == 0


# --- Deleting ------------------------------------------------------------------


async def test_deleting_a_linked_lesson_frees_the_slot_as_manually_modified(
    client, tutor, group, chapters
):
    slots = await _plan(group, tutor, [chapters["c1"]])
    lesson_id = (await _post_lesson(client, tutor, group, plan_slot_id=slots[0])).json()["id"]
    resp = await client.delete(f"/api/v1/lessons/{lesson_id}", headers=tutor["headers"])
    assert resp.status_code == 204
    assert await _slot(slots[0]) == (None, PlanSlotProvenance.manually_modified)
    # ...and it is suggested again.
    assert (await client.get(_next(group), headers=tutor["headers"])).json()["slot_id"] == slots[0]


async def test_deleting_an_unlinked_lesson_changes_no_slot(client, tutor, group, chapters):
    slots = await _plan(group, tutor, [chapters["c1"]])
    lesson_id = (await _post_lesson(client, tutor, group)).json()["id"]
    assert (
        await client.delete(f"/api/v1/lessons/{lesson_id}", headers=tutor["headers"])
    ).status_code == 204
    assert await _slot(slots[0]) == (None, PlanSlotProvenance.generated)


# --- Authorization (QA-12) -----------------------------------------------------


async def test_student_cannot_read_the_suggestion(client, tutor, group, student, chapters):
    await _plan(group, tutor, [chapters["c1"]])
    resp = await client.get(_next(group), headers=student["headers"])
    assert resp.status_code == 403


async def test_no_token_is_401(client, tutor, group):
    assert (await client.get(_next(group))).status_code == 401


async def test_another_tutor_gets_404_for_the_suggestion(client, tutor, group, chapters):
    await _plan(group, tutor, [chapters["c1"]])
    reg = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-next@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    assert (await client.get(_next(group), headers=headers)).status_code == 404


# --- Review fixes: topic and timetable-slot ownership ---------------------------


async def _foreign_topic(*, other_org: bool) -> int:
    async with async_session() as s:
        kwargs: dict = {"code": "OTH3"}
        if other_org:
            org = Organization(name="Elsewhere")
            s.add(org)
            await s.flush()
            kwargs["organization_id"] = org.id
        foreign = await make_subject(s, **kwargs)
        topic = Topic(subject_id=foreign.id, code="9.8", title="Elsewhere")
        s.add(topic)
        await s.commit()
        return topic.id


@pytest.mark.parametrize("other_org", [False, True])
async def test_put_topics_rejects_a_topic_of_another_subject_and_writes_nothing(
    client, tutor, group, subject, other_org
):
    lesson_id = (await _post_lesson(client, tutor, group, topic_ids=[subject["topic1"]])).json()[
        "id"
    ]
    foreign = await _foreign_topic(other_org=other_org)
    resp = await client.put(
        f"/api/v1/lessons/{lesson_id}/topics",
        json={"topic_ids": [subject["topic2"], foreign]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422
    async with async_session() as s:
        rows = (await s.scalars(select(LessonTopic.topic_id))).all()
    assert rows == [subject["topic1"]]  # nothing was written


async def test_put_topics_still_replaces_with_valid_topics(client, tutor, group, subject):
    lesson_id = (await _post_lesson(client, tutor, group, topic_ids=[subject["topic1"]])).json()[
        "id"
    ]
    resp = await client.put(
        f"/api/v1/lessons/{lesson_id}/topics",
        json={"topic_ids": [subject["topic2"]]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200
    assert [t["id"] for t in resp.json()["topics"]] == [subject["topic2"]]


async def _timetable_slot(group_id: int) -> int:
    async with async_session() as s:
        slot = ScheduleSlot(group_id=group_id, weekday=1, start_time=time(17, 0), duration_min=60)
        s.add(slot)
        await s.commit()
        return slot.id


async def test_a_timetable_slot_of_another_class_is_404(client, tutor, group, subject):
    other = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem Y11", "subject_id": subject["id"]},
            headers=tutor["headers"],
        )
    ).json()
    foreign_slot = await _timetable_slot(other["id"])
    resp = await _post_lesson(client, tutor, group, schedule_slot_id=foreign_slot)
    assert resp.status_code == 404
    assert await _lesson_count() == 0


async def test_a_timetable_slot_of_this_class_is_accepted(client, tutor, group):
    slot = await _timetable_slot(group["id"])
    resp = await _post_lesson(client, tutor, group, schedule_slot_id=slot)
    assert resp.status_code == 201
    assert resp.json()["schedule_slot_id"] == slot


async def test_deleting_a_lesson_whose_slot_is_completed_sets_it_manually_modified(
    client, tutor, group, chapters
):
    slots = await _plan(group, tutor, [chapters["c1"]])
    lesson_id = (await _post_lesson(client, tutor, group, plan_slot_id=slots[0])).json()["id"]
    async with async_session() as s:
        (await s.get(PlanSlot, slots[0])).provenance = PlanSlotProvenance.completed
        await s.commit()
    await client.delete(f"/api/v1/lessons/{lesson_id}", headers=tutor["headers"])
    # Intended: the lesson is gone, so nothing was taught against this slot.
    assert await _slot(slots[0]) == (None, PlanSlotProvenance.manually_modified)


async def test_a_slot_taken_between_the_read_and_the_claim_is_409_and_creates_no_lesson(
    client, tutor, group, chapters, monkeypatch
):
    slots = await _plan(group, tutor, [chapters["c1"]])
    real = plan_lessons._accepted_slot

    async def read_then_lose_the_race(session, grp, slot_id):
        slot = await real(session, grp, slot_id)  # the read sees it free...
        async with async_session() as other:  # ...then another request takes it
            rival = Lesson(organization_id=grp.organization_id, group_id=grp.id, date=date.today())
            other.add(rival)
            await other.flush()
            (await other.get(PlanSlot, slot_id)).lesson_id = rival.id
            await other.commit()
        return slot

    monkeypatch.setattr(plan_lessons, "_accepted_slot", read_then_lose_the_race)
    resp = await _post_lesson(client, tutor, group, plan_slot_id=slots[0])
    assert resp.status_code == 409
    assert await _lesson_count() == 1  # only the rival's; ours was rolled back


@pytest.mark.parametrize("body", [{"plan_slot_id": 0}, {"topic_ids": [0]}, {"topic_ids": [-3]}])
async def test_non_positive_ids_are_422(client, tutor, group, body):
    assert (await _post_lesson(client, tutor, group, **body)).status_code == 422
