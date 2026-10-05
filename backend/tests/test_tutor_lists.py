"""GET /assignments and GET /students (task 9.3c): the cross-class Homework and
Students lists. Plain counts and names only, bounded, scoped to the caller's
classes."""

from datetime import datetime, timezone

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
from tests.factories import make_user, publish_assignment, register_other_tutor, submit_work

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
    rows = resp.json()
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
    assert resp.json() == []


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
    rows = (await client.get(HOMEWORK, headers=tutor["headers"])).json()
    assert [r["title"] for r in rows] == ["HW 3", "HW 2"]


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
    assert resp.json() == []


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
    assert (await client.get(HOMEWORK, headers=colleague)).json() == []
    rows = (await client.get(HOMEWORK, headers=admin)).json()
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
    rows = resp.json()
    assert [r["name"] for r in rows] == ["Ann", "zed"]
    assert rows[0]["id"] == ann and rows[1]["id"] == zed
    assert [(c["group_name"], c["subject_name"]) for c in rows[0]["classes"]] == [
        ("Chem A", "Chemistry"),
        ("Chem B", "Chemistry"),
    ]
    assert [c["group_id"] for c in rows[1]["classes"]] == [a["id"]]
    assert set(rows[0]) == {"id", "name", "classes"}


async def test_students_is_empty_without_classes_or_members(client, tutor, subject):
    assert (await client.get(STUDENTS, headers=tutor["headers"])).json() == []
    await _group(client, tutor, subject, "Empty")
    assert (await client.get(STUDENTS, headers=tutor["headers"])).json() == []


async def test_students_cap_counts_students_not_memberships(client, tutor, subject, monkeypatch):
    monkeypatch.setattr(tutor_lists, "STUDENT_LIST_LIMIT", 2)
    org = await _org_id(tutor)
    a = await _group(client, tutor, subject, "Chem A")
    b = await _group(client, tutor, subject, "Chem B")
    ann = await _enrol(a["id"], org, "Ann", "ann@example.com")
    await _join(b["id"], ann)
    await _enrol(a["id"], org, "Ben", "ben@example.com")
    await _enrol(a["id"], org, "Cy", "cy@example.com")
    rows = (await client.get(STUDENTS, headers=tutor["headers"])).json()
    assert [r["name"] for r in rows] == ["Ann", "Ben"]
    assert len(rows[0]["classes"]) == 2


async def test_students_only_shows_the_callers_classes_of_a_shared_student(client, tutor, subject):
    org = await _org_id(tutor)
    mine = await _group(client, tutor, subject, "Mine")
    ann = await _enrol(mine["id"], org, "Ann", "ann@example.com")
    colleague_id = None
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
        colleague_id = col.id
    rows = (await client.get(STUDENTS, headers=tutor["headers"])).json()
    assert [c["group_name"] for c in rows[0]["classes"]] == ["Mine"]
    assert colleague_id is not None


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
    assert (await client.get(STUDENTS, headers=other["headers"])).json() == []
    assert (await client.get(STUDENTS, headers=colleague)).json() == []
    assert [r["name"] for r in (await client.get(STUDENTS, headers=admin)).json()] == ["Ann"]


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
