"""GET /assignments and GET /students (task 9.3c): the cross-class Homework and
Students lists. Plain counts and names only, bounded, scoped to the caller's
classes."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    SubmissionStatus,
    User,
    UserRole,
)
from app.security import create_access_token
from app.services import tutor_lists
from tests.factories import (
    make_user,
    publish_assignment,
    register_other_tutor,
    settled_submission,
    submit_work,
)

HOMEWORK = "/api/v1/assignments"
STUDENTS = "/api/v1/students"


def _at(day: int) -> datetime:
    return datetime(2026, 9, day, 10, 0, tzinfo=timezone.utc)


async def _group(client, tutor, subject, name) -> dict:
    resp = await client.post(
        "/api/v1/groups",
        json={"name": name, "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _org_id(tutor) -> int:
    async with async_session() as s:
        return (await s.get(User, tutor["user"]["id"])).organization_id


async def _headers_for(**kw) -> dict:
    async with async_session() as s:
        user = await make_user(s, **kw)
        await s.commit()
        token = create_access_token(user.id, user.token_version)
    return {"Authorization": f"Bearer {token}"}


async def _enrol(group_id: int, organization_id: int, name: str, email: str) -> int:
    async with async_session() as s:
        user = await make_user(
            s, organization_id=organization_id, role=UserRole.student, name=name, email=email
        )
        s.add(GroupMember(group_id=group_id, student_id=user.id))
        await s.commit()
        return user.id


async def _join(group_id: int, student_id: int) -> None:
    async with async_session() as s:
        s.add(GroupMember(group_id=group_id, student_id=student_id))
        await s.commit()


async def _homework(group, subject, org, title, day, **kw):
    async with async_session() as s:
        a = await publish_assignment(
            s,
            group_id=group["id"],
            subject_id=subject["id"],
            organization_id=org,
            title=title,
            created_at=_at(day),
            **kw,
        )
        await s.commit()
        return a


async def _submit(assignment, student_id, status):
    async with async_session() as s:
        await submit_work(
            s,
            assignment=assignment,
            student_id=student_id,
            status=status,
            submitted_at=_at(20),
        )
        await s.commit()


# --- Homework ----------------------------------------------------------------


async def test_homework_lists_newest_first_with_real_counts(client, tutor, subject):
    org = await _org_id(tutor)
    a = await _group(client, tutor, subject, "Chem A")
    b = await _group(client, tutor, subject, "Chem B")
    s1 = await _enrol(a["id"], org, "Ann", "ann@example.com")
    s2 = await _enrol(a["id"], org, "Ben", "ben@example.com")
    s3 = await _enrol(a["id"], org, "Cy", "cy@example.com")
    old = await _homework(a, subject, org, "Older", 1)
    new = await _homework(b, subject, org, "Newer", 3)

    await _submit(old, s1, SubmissionStatus.finalized)
    await _submit(old, s2, SubmissionStatus.auto_finalized)
    await _submit(old, s3, SubmissionStatus.needs_review)

    resp = await client.get(HOMEWORK, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert [r["title"] for r in rows] == ["Newer", "Older"]
    assert rows[0]["id"] == new.id
    assert rows[0]["group_name"] == "Chem B" and rows[0]["subject_name"] == "Chemistry"
    # A class with nobody in it reports 0 enrolled; the page words that, not 0 of 0.
    assert (rows[0]["enrolled_count"], rows[0]["submitted_count"], rows[0]["marked_count"]) == (
        0,
        0,
        0,
    )
    assert rows[1]["status"] == "published"
    assert (rows[1]["enrolled_count"], rows[1]["submitted_count"], rows[1]["marked_count"]) == (
        3,
        3,
        2,
    )


async def test_homework_is_empty_for_a_tutor_without_classes(client, tutor):
    resp = await client.get(HOMEWORK, headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "truncated": False, "limit": 200}


async def test_homework_query_count_does_not_grow_with_rows(client, tutor, subject):
    from sqlalchemy import event

    from app.db import engine

    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    sid = await _enrol(g["id"], org, "Ann", "ann@example.com")

    async def count_queries() -> int:
        n = 0

        def bump(*_):
            nonlocal n
            n += 1

        event.listen(engine.sync_engine, "before_cursor_execute", bump)
        try:
            resp = await client.get(HOMEWORK, headers=tutor["headers"])
            assert resp.status_code == 200
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", bump)
        return n

    one = await _homework(g, subject, org, "One", 1)
    await _submit(one, sid, SubmissionStatus.finalized)
    before = await count_queries()
    for day in range(2, 6):
        hw = await _homework(g, subject, org, f"HW {day}", day)
        await _submit(hw, sid, SubmissionStatus.finalized)
    assert await count_queries() == before


async def test_homework_is_capped_at_the_most_recent(client, tutor, subject, monkeypatch):
    monkeypatch.setattr(tutor_lists, "HOMEWORK_LIST_LIMIT", 2)
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    for day in (1, 2, 3):
        await _homework(g, subject, org, f"HW {day}", day)
    body = (await client.get(HOMEWORK, headers=tutor["headers"])).json()
    assert [r["title"] for r in body["items"]] == ["HW 3", "HW 2"]
    assert body["truncated"] is True and body["limit"] == 2


async def test_homework_limit_matches_what_the_page_assumes():
    assert tutor_lists.HOMEWORK_LIST_LIMIT == 200
    assert tutor_lists.STUDENT_LIST_LIMIT == 500


async def test_homework_hides_another_organizations_rows(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    await _homework(g, subject, org, "Mine", 1)
    other = await register_other_tutor(client)
    resp = await client.get(HOMEWORK, headers=other["headers"])
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_homework_hides_a_colleagues_classes_but_an_admin_sees_them(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    await _homework(g, subject, org, "Mine", 1)
    colleague = await _headers_for(
        organization_id=org, role=UserRole.tutor, name="Col", email="col@example.com"
    )
    admin = await _headers_for(
        organization_id=org, role=UserRole.admin, name="Adm", email="adm@example.com"
    )
    assert (await client.get(HOMEWORK, headers=colleague)).json()["items"] == []
    rows = (await client.get(HOMEWORK, headers=admin)).json()["items"]
    assert [r["title"] for r in rows] == ["Mine"]


async def test_homework_refuses_a_student_and_the_anonymous(client, student):
    resp = await client.get(HOMEWORK, headers=student["headers"])
    assert resp.status_code == 403
    assert (await client.get(HOMEWORK)).status_code == 401


async def test_homework_route_does_not_swallow_the_static_siblings(client, tutor):
    # `/attention` and `/group/{id}` must still resolve beside the new root route.
    assert (await client.get(f"{HOMEWORK}/attention", headers=tutor["headers"])).status_code == 200
    assert (await client.get(f"{HOMEWORK}/group/999", headers=tutor["headers"])).status_code == 404


# --- Students ----------------------------------------------------------------


async def test_students_lists_each_once_by_name_with_their_classes(client, tutor, subject):
    org = await _org_id(tutor)
    a = await _group(client, tutor, subject, "Chem A")
    b = await _group(client, tutor, subject, "Chem B")
    zed = await _enrol(a["id"], org, "zed", "zed@example.com")
    ann = await _enrol(a["id"], org, "Ann", "ann@example.com")
    await _join(b["id"], ann)

    resp = await client.get(STUDENTS, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert [r["name"] for r in rows] == ["Ann", "zed"]
    assert rows[0]["id"] == ann and rows[1]["id"] == zed
    assert [(c["group_name"], c["subject_name"]) for c in rows[0]["classes"]] == [
        ("Chem A", "Chemistry"),
        ("Chem B", "Chemistry"),
    ]
    assert [c["group_id"] for c in rows[1]["classes"]] == [a["id"]]
    assert set(rows[0]) == {"id", "name", "classes"}


async def test_students_is_empty_without_classes_or_members(client, tutor, subject):
    empty = {"items": [], "truncated": False, "limit": 500}
    assert (await client.get(STUDENTS, headers=tutor["headers"])).json() == empty
    await _group(client, tutor, subject, "Empty")
    assert (await client.get(STUDENTS, headers=tutor["headers"])).json() == empty


async def test_students_cap_counts_students_not_memberships(client, tutor, subject, monkeypatch):
    monkeypatch.setattr(tutor_lists, "STUDENT_LIST_LIMIT", 2)
    org = await _org_id(tutor)
    a = await _group(client, tutor, subject, "Chem A")
    b = await _group(client, tutor, subject, "Chem B")
    ann = await _enrol(a["id"], org, "Ann", "ann@example.com")
    await _join(b["id"], ann)
    await _enrol(a["id"], org, "Ben", "ben@example.com")
    await _enrol(a["id"], org, "Cy", "cy@example.com")
    body = (await client.get(STUDENTS, headers=tutor["headers"])).json()
    rows = body["items"]
    assert [r["name"] for r in rows] == ["Ann", "Ben"]
    assert len(rows[0]["classes"]) == 2
    assert body["truncated"] is True and body["limit"] == 2


async def test_students_only_shows_the_callers_classes_of_a_shared_student(client, tutor, subject):
    org = await _org_id(tutor)
    mine = await _group(client, tutor, subject, "Mine")
    ann = await _enrol(mine["id"], org, "Ann", "ann@example.com")
    async with async_session() as s:
        col = await make_user(
            s, organization_id=org, role=UserRole.tutor, name="Col", email="col@example.com"
        )
        theirs = Group(
            organization_id=org, tutor_id=col.id, subject_id=subject["id"], name="Theirs"
        )
        s.add(theirs)
        await s.flush()
        s.add(GroupMember(group_id=theirs.id, student_id=ann))
        await s.commit()
    resp = await client.get(STUDENTS, headers=tutor["headers"])
    rows = resp.json()["items"]
    assert [c["group_name"] for c in rows[0]["classes"]] == ["Mine"]
    # Nowhere in the payload, not just on the first row.
    assert "Theirs" not in resp.text


async def test_students_hides_other_tenants_and_colleagues_but_admin_sees_the_org(
    client, tutor, subject
):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    await _enrol(g["id"], org, "Ann", "ann@example.com")
    other = await register_other_tutor(client)
    colleague = await _headers_for(
        organization_id=org, role=UserRole.tutor, name="Col", email="col@example.com"
    )
    admin = await _headers_for(
        organization_id=org, role=UserRole.admin, name="Adm", email="adm@example.com"
    )
    assert (await client.get(STUDENTS, headers=other["headers"])).json()["items"] == []
    assert (await client.get(STUDENTS, headers=colleague)).json()["items"] == []
    assert [r["name"] for r in (await client.get(STUDENTS, headers=admin)).json()["items"]] == [
        "Ann"
    ]


async def test_students_refuses_a_student_and_the_anonymous(client, student):
    assert (await client.get(STUDENTS, headers=student["headers"])).status_code == 403
    assert (await client.get(STUDENTS)).status_code == 401


async def test_students_refuses_a_parent(client, tutor, student):
    from tests.factories import register_parent

    parent = await register_parent(client, tutor, student)
    assert (await client.get(STUDENTS, headers=parent["headers"])).status_code == 403
    assert (await client.get(HOMEWORK, headers=parent["headers"])).status_code == 403


async def test_students_route_does_not_swallow_the_id_routes(client, tutor, student):
    resp = await client.get(f"{STUDENTS}/{student['user']['id']}/crm", headers=tutor["headers"])
    assert resp.status_code == 200


# --- Review fixes ------------------------------------------------------------


async def test_counts_only_cover_students_still_in_the_class(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    stayer = await _enrol(g["id"], org, "Ann", "ann@example.com")
    leaver = await _enrol(g["id"], org, "Ben", "ben@example.com")
    hw = await _homework(g, subject, org, "HW", 1)
    await _submit(hw, stayer, SubmissionStatus.finalized)
    await _submit(hw, leaver, SubmissionStatus.finalized)

    row = (await client.get(HOMEWORK, headers=tutor["headers"])).json()["items"][0]
    assert (row["enrolled_count"], row["submitted_count"], row["marked_count"]) == (2, 2, 2)

    async with async_session() as s:
        member = await s.scalar(
            select(GroupMember).where(
                GroupMember.group_id == g["id"], GroupMember.student_id == leaver
            )
        )
        await s.delete(member)
        await s.commit()

    row = (await client.get(HOMEWORK, headers=tutor["headers"])).json()["items"][0]
    assert (row["enrolled_count"], row["submitted_count"], row["marked_count"]) == (1, 1, 1)
    assert row["submitted_count"] <= row["enrolled_count"]


async def test_membership_is_per_assignments_own_class(client, tutor, subject):
    org = await _org_id(tutor)
    a = await _group(client, tutor, subject, "Chem A")
    b = await _group(client, tutor, subject, "Chem B")
    ann = await _enrol(a["id"], org, "Ann", "ann@example.com")
    hw_a = await _homework(a, subject, org, "For A", 1)
    hw_b = await _homework(b, subject, org, "For B", 2)
    await _submit(hw_a, ann, SubmissionStatus.finalized)
    # Ann is not in B: a submission against B's work does not count there.
    await _submit(hw_b, ann, SubmissionStatus.finalized)
    items = (await client.get(HOMEWORK, headers=tutor["headers"])).json()["items"]
    rows = {r["title"]: r for r in items}
    assert rows["For A"]["submitted_count"] == 1
    assert rows["For B"]["submitted_count"] == 0 and rows["For B"]["enrolled_count"] == 0


async def test_a_past_paper_submission_changes_no_homework_count(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    ann = await _enrol(g["id"], org, "Ann", "ann@example.com")
    await _homework(g, subject, org, "HW", 1)
    async with async_session() as s:
        await settled_submission(
            s,
            subject_id=subject["id"],
            organization_id=org,
            student_id=ann,
            analysed=False,
            marks=1,
        )
        await s.commit()
    row = (await client.get(HOMEWORK, headers=tutor["headers"])).json()["items"][0]
    assert (row["submitted_count"], row["marked_count"]) == (0, 0)


async def test_truncated_is_false_at_the_limit_and_true_one_past_it(
    client, tutor, subject, monkeypatch
):
    monkeypatch.setattr(tutor_lists, "HOMEWORK_LIST_LIMIT", 2)
    monkeypatch.setattr(tutor_lists, "STUDENT_LIST_LIMIT", 2)
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    for day in (1, 2):
        await _homework(g, subject, org, f"HW {day}", day)
    await _enrol(g["id"], org, "Ann", "ann@example.com")
    await _enrol(g["id"], org, "Ben", "ben@example.com")
    for url in (HOMEWORK, STUDENTS):
        body = (await client.get(url, headers=tutor["headers"])).json()
        assert len(body["items"]) == 2 and body["truncated"] is False, url

    await _homework(g, subject, org, "HW 3", 3)
    await _enrol(g["id"], org, "Cy", "cy@example.com")
    for url in (HOMEWORK, STUDENTS):
        body = (await client.get(url, headers=tutor["headers"])).json()
        assert len(body["items"]) == 2 and body["truncated"] is True, url


async def test_another_tenant_with_their_own_data_sees_only_their_own(client, tutor, subject):
    org = await _org_id(tutor)
    mine = await _group(client, tutor, subject, "Mine")
    await _enrol(mine["id"], org, "Ann", "ann@example.com")
    await _homework(mine, subject, org, "My homework", 1)

    other = await register_other_tutor(client)
    other_org = await _org_id(other)
    # Inserted directly: the API only lets a tutor pick their own organization's
    # subjects, and the subject fixture belongs to the first tutor's.
    async with async_session() as s:
        group = Group(
            organization_id=other_org,
            tutor_id=other["user"]["id"],
            subject_id=subject["id"],
            name="Theirs",
        )
        s.add(group)
        await s.commit()
        theirs = {"id": group.id}
    await _enrol(theirs["id"], other_org, "Zoe", "zoe@example.com")
    await _homework(theirs, subject, other_org, "Their homework", 2)

    mine_hw = (await client.get(HOMEWORK, headers=tutor["headers"])).json()["items"]
    their_hw = (await client.get(HOMEWORK, headers=other["headers"])).json()["items"]
    assert [r["title"] for r in mine_hw] == ["My homework"]
    assert [r["title"] for r in their_hw] == ["Their homework"]
    mine_st = (await client.get(STUDENTS, headers=tutor["headers"])).json()["items"]
    their_st = (await client.get(STUDENTS, headers=other["headers"])).json()["items"]
    assert [r["name"] for r in mine_st] == ["Ann"]
    assert [r["name"] for r in their_st] == ["Zoe"]


async def test_homework_ties_on_created_at_break_by_id_descending(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    first = await _homework(g, subject, org, "First", 1)
    second = await _homework(g, subject, org, "Second", 1)
    rows = (await client.get(HOMEWORK, headers=tutor["headers"])).json()["items"]
    assert [r["id"] for r in rows] == [second.id, first.id]


async def test_students_with_the_same_name_are_separate_rows_ordered_by_id(client, tutor, subject):
    org = await _org_id(tutor)
    g = await _group(client, tutor, subject, "Chem A")
    one = await _enrol(g["id"], org, "Sam", "sam1@example.com")
    two = await _enrol(g["id"], org, "Sam", "sam2@example.com")
    rows = (await client.get(STUDENTS, headers=tutor["headers"])).json()["items"]
    assert [r["id"] for r in rows] == [one, two]
