"""'Where are you up to?' (task 9.1b): the taught-before marker, its endpoints, and
the coverage readers and plan drafting that consume it.

The marker is a second coverage source beside `lesson_topics` (PROD-14, amended by
the owner), so each reader gets a test proving a marked topic counts and an
unmarked one does not."""

from datetime import date

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Chapter,
    Group,
    JobStatus,
    Lesson,
    LessonTopic,
    Subject,
    TaughtBeforeTopic,
    TeachingPlan,
    Topic,
    User,
    UserRole,
)
from app.security import create_access_token
from app.services.class_report import build_class_report
from app.services.plan_drafting import draft_plan_slots
from app.services.readiness_v2 import _topic_coverage
from app.services.taught_before import answered_group_ids, taught_before_topic_ids
from tests.factories import make_user, register_other_tutor, subject_defaults
from tests.plan_world import make_chapters
from tests.test_plan_drafting import advice, fixed_today, run_job, slots, world  # noqa: F401
from tests.test_today_overview import NOW


def _url(group) -> str:
    return f"/api/v1/groups/{group['id']}/taught-before"


# --- endpoints -----------------------------------------------------------------------


async def test_get_before_any_answer_is_not_answered(client, tutor, group):
    resp = await client.get(_url(group), headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"answered": False, "answered_at": None, "topic_ids": []}


async def test_put_replaces_and_is_idempotent_and_get_reflects_it(client, tutor, group, subject):
    t1, t2 = subject["topic1"], subject["topic2"]
    first = await client.put(_url(group), json={"topic_ids": [t2, t1]}, headers=tutor["headers"])
    assert first.status_code == 200, first.text
    assert first.json()["answered"] is True
    assert first.json()["topic_ids"] == sorted([t1, t2])
    # The same body again (with a duplicate id) changes nothing and adds no rows.
    again = await client.put(
        _url(group), json={"topic_ids": [t1, t2, t1]}, headers=tutor["headers"]
    )
    assert again.json()["topic_ids"] == sorted([t1, t2])
    # A shorter list replaces rather than appends.
    shorter = await client.put(_url(group), json={"topic_ids": [t1]}, headers=tutor["headers"])
    assert shorter.json()["topic_ids"] == [t1]
    got = await client.get(_url(group), headers=tutor["headers"])
    assert got.json()["topic_ids"] == [t1]
    assert got.json()["answered"] is True
    async with async_session() as s:
        rows = (await s.scalars(select(TaughtBeforeTopic))).all()
        assert [(r.group_id, r.topic_id) for r in rows] == [(group["id"], t1)]
        assert rows[0].created_by_id == tutor["user"]["id"]


async def test_an_empty_list_is_an_answer_starting_fresh(client, tutor, group, subject):
    await client.put(_url(group), json={"topic_ids": [subject["topic1"]]}, headers=tutor["headers"])
    resp = await client.put(_url(group), json={"topic_ids": []}, headers=tutor["headers"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["answered"] is True and body["answered_at"] is not None
    assert body["topic_ids"] == []


async def test_a_topic_of_another_subject_is_rejected_and_nothing_is_written(
    client, tutor, group, subject
):
    async with async_session() as s:
        other = Subject(
            **await subject_defaults(s),
            exam_board="X",
            code="9XX1",
            name="Physics",
            grade_scale="9-1",
        )
        s.add(other)
        await s.flush()
        foreign = Topic(subject_id=other.id, code="1", title="Forces")
        s.add(foreign)
        await s.commit()
        foreign_id = foreign.id
    resp = await client.put(
        _url(group),
        json={"topic_ids": [subject["topic1"], foreign_id]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422
    assert "subject" in resp.json()["detail"]
    got = await client.get(_url(group), headers=tutor["headers"])
    assert got.json()["answered"] is False and got.json()["topic_ids"] == []


async def test_a_student_is_rejected(client, tutor, group, student, subject):
    assert (await client.get(_url(group), headers=student["headers"])).status_code == 403
    resp = await client.put(
        _url(group), json={"topic_ids": [subject["topic1"]]}, headers=student["headers"]
    )
    assert resp.status_code == 403
    assert (await client.get(_url(group))).status_code == 401
    assert (await client.put(_url(group), json={"topic_ids": []})).status_code == 401


async def test_a_list_too_long_or_with_a_non_positive_id_is_refused(client, tutor, group):
    for body in ({"topic_ids": [0]}, {"topic_ids": [-3]}, {"topic_ids": list(range(1, 2002))}):
        resp = await client.put(_url(group), json=body, headers=tutor["headers"])
        assert resp.status_code == 422, body
    got = await client.get(_url(group), headers=tutor["headers"])
    assert got.json()["answered"] is False


async def test_a_tutor_in_another_organization_gets_404(client, tutor, group, subject):
    other = await register_other_tutor(client)
    assert (await client.get(_url(group), headers=other["headers"])).status_code == 404
    resp = await client.put(
        _url(group), json={"topic_ids": [subject["topic1"]]}, headers=other["headers"]
    )
    assert resp.status_code == 404
    async with async_session() as s:
        assert (await s.scalars(select(TaughtBeforeTopic))).all() == []
        assert (await s.get(Group, group["id"])).taught_before_answered_at is None


async def test_a_colleague_who_does_not_own_the_class_gets_404_but_an_admin_does_not(
    client, tutor, group, subject
):
    async with async_session() as s:
        org_id = (await s.get(User, tutor["user"]["id"])).organization_id
        colleague = await make_user(
            s, organization_id=org_id, role=UserRole.tutor, name="C", email="c@example.com"
        )
        admin = await make_user(
            s, organization_id=org_id, role=UserRole.admin, name="A", email="a@example.com"
        )
        await s.commit()
        c_token = create_access_token(colleague.id, colleague.token_version)
        a_token = create_access_token(admin.id, admin.token_version)
    c_headers = {"Authorization": f"Bearer {c_token}"}
    a_headers = {"Authorization": f"Bearer {a_token}"}
    body = {"topic_ids": [subject["topic1"]]}
    assert (await client.get(_url(group), headers=c_headers)).status_code == 404
    assert (await client.put(_url(group), json=body, headers=c_headers)).status_code == 404
    # `_owned_group` lets an admin act inside their own organization; match it.
    assert (await client.put(_url(group), json=body, headers=a_headers)).status_code == 200


# --- service helpers -----------------------------------------------------------------


async def test_answered_group_ids_and_topic_ids_are_batched(client, tutor, group, subject):
    async with async_session() as s:
        assert await answered_group_ids(s, [group["id"]]) == set()
        assert await answered_group_ids(s, []) == set()
    await client.put(_url(group), json={"topic_ids": [subject["topic1"]]}, headers=tutor["headers"])
    async with async_session() as s:
        assert await answered_group_ids(s, [group["id"], 99999]) == {group["id"]}
        assert await taught_before_topic_ids(s, [group["id"]]) == {subject["topic1"]}
        narrowed = await taught_before_topic_ids(s, [group["id"]], topic_ids=[subject["topic2"]])
        assert narrowed == set()


# --- coverage readers ----------------------------------------------------------------


async def test_a_marked_topic_counts_as_taught_in_student_readiness_coverage(
    client, tutor, group, subject, student
):
    await client.put(_url(group), json={"topic_ids": [subject["topic1"]]}, headers=tutor["headers"])
    async with async_session() as s:
        topics = [await s.get(Topic, subject["topic1"]), await s.get(Topic, subject["topic2"])]
        cov = await _topic_coverage(s, student["user"]["id"], subject["id"], {}, topics)
    assert [c.taught for c in cov] == [True, False]


async def test_a_marked_topic_counts_as_taught_in_the_class_report(
    client, tutor, group, subject, student
):
    ch = await make_chapters(subject, topics_in_c1=2)
    await client.put(_url(group), json={"topic_ids": [ch["t1"][0]]}, headers=tutor["headers"])
    async with async_session() as s:
        report = await build_class_report(s, await s.get(Group, group["id"]), now=NOW)
    c1 = next(c for c in report.chapters if c.chapter_id == ch["c1"])
    assert (c1.topics_total, c1.topics_taught, c1.state) == (2, 1, "in_progress")
    assert [t.taught for t in c1.topics] == [True, False]
    # The marker is not a lesson.
    async with async_session() as s:
        assert (await s.scalars(select(Lesson))).all() == []


# --- plan drafting -------------------------------------------------------------------


async def _give_topics(world, counts):  # noqa: F811
    """Topics for chapters 2 and 3 (chapter 1 already has 1.1), `counts` of each.
    Returns {chapter_id: [topic ids]} for all three."""
    out = {}
    async with async_session() as s:
        c1, c2, c3 = world["chapter_ids"]
        out[c1] = list(await s.scalars(select(Topic.id).where(Topic.chapter_id == c1)))
        for cid, n in ((c2, counts[0]), (c3, counts[1])):
            rows = [
                Topic(subject_id=world["subject_id"], chapter_id=cid, code=f"{cid}.{i}", title="t")
                for i in range(n)
            ]
            s.add_all(rows)
            await s.flush()
            out[cid] = [r.id for r in rows]
        await s.commit()
    return out


async def _mark(world, topic_ids):  # noqa: F811
    async with async_session() as s:
        s.add_all(
            TaughtBeforeTopic(
                organization_id=world["org_id"],
                group_id=world["group_id"],
                topic_id=t,
                created_by_id=world["tutor_id"],
            )
            for t in topic_ids
        )
        await s.commit()


async def test_fully_covered_chapters_are_left_out_and_a_partial_one_stays(
    world,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    by_ch = await _give_topics(world, (2, 2))
    c1, c2, c3 = world["chapter_ids"]
    # c1 fully marked; c2 half marked (stays whole); c3 untouched.
    await _mark(world, by_ch[c1] + by_ch[c2][:1])
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    job = await run_job(world)
    assert job.status is JobStatus.done, job.error
    assert {r.chapter_id for r in await slots(world)} == {c2, c3}
    async with async_session() as s:
        stored = (await s.get(TeachingPlan, world["plan_id"])).draft_result
    assert [c["chapter_id"] for c in stored["chapters"]] == [c2, c3]


async def test_a_lesson_topic_also_counts_as_covered_for_drafting(
    world,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    by_ch = await _give_topics(world, (1, 1))
    c1, c2, c3 = world["chapter_ids"]
    async with async_session() as s:
        lesson = Lesson(
            organization_id=world["org_id"],
            group_id=world["group_id"],
            date=date(2027, 1, 1),
            duration_min=60,
        )
        s.add(lesson)
        await s.flush()
        s.add(LessonTopic(lesson_id=lesson.id, topic_id=by_ch[c1][0]))
        await s.commit()
    await _mark(world, by_ch[c2])  # a lesson and the marker are unioned
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    assert (await run_job(world)).status is JobStatus.done
    assert {r.chapter_id for r in await slots(world)} == {c3}


async def test_a_chapter_with_no_topics_is_never_treated_as_covered(
    world,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    # The fixture's chapters 2 and 3 have no topics: marking chapter 1 must leave them.
    c1, c2, c3 = world["chapter_ids"]
    async with async_session() as s:
        topic_id = await s.scalar(select(Topic.id).where(Topic.chapter_id == c1))
    await _mark(world, [topic_id])
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    assert (await run_job(world)).status is JobStatus.done
    assert {r.chapter_id for r in await slots(world)} == {c2, c3}


async def test_every_chapter_covered_fails_with_all_taught(world, monkeypatch):  # noqa: F811
    c1, c2, c3 = world["chapter_ids"]
    async with async_session() as s:
        for cid in (c2, c3):
            await s.delete(await s.get(Chapter, cid))
        topic_id = await s.scalar(select(Topic.id).where(Topic.chapter_id == c1))
        await s.commit()
    await _mark(world, [topic_id])

    async def boom(**kwargs):
        raise AssertionError("the model must not be called when nothing is left to plan")

    monkeypatch.setattr("app.services.plan_drafting.structured_complete", boom)
    async with async_session() as s:
        result = await draft_plan_slots(s, world["plan_id"])
        await s.commit()
    assert result.status == "failed"
    assert result.failure["code"] == "all_taught"
    assert "already marked as taught" in result.failure["message"]
    assert await slots(world) == []


async def test_nothing_marked_drafts_every_chapter_as_before(
    world,
    monkeypatch,
    fake_ai,  # noqa: F811
):
    monkeypatch.setattr(
        "app.services.plan_drafting.structured_complete", fake_ai(advice(world, [1.0, 1.0, 1.0]))
    )
    assert (await run_job(world)).status is JobStatus.done
    assert {r.chapter_id for r in await slots(world)} == set(world["chapter_ids"])


async def test_the_topic_list_says_which_chapter_each_topic_is_filed_under(client, tutor, subject):
    """The "where are you up to" editor groups by chapter, the unit the plan
    drafter leaves out, so the two must agree on which topics a chapter holds."""
    resp = await client.get(f"/api/v1/subjects/{subject['id']}/topics", headers=tutor["headers"])
    assert resp.status_code == 200
    async with async_session() as s:
        filed = dict((await s.execute(select(Topic.id, Topic.chapter_id))).tuples().all())
    assert resp.json()
    assert {t["id"]: t["chapter_id"] for t in resp.json()} == filed
