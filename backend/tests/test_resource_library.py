"""GET /resources (task 9.3b): everything a tutor has shared, across their own
classes, for the Library. A record: files and recordings in one list, newest first,
each with its class."""

from datetime import datetime, timezone

from sqlalchemy import event

from app.db import async_session, engine
from app.models import Group, GroupResource, ResourceKind, User, UserRole
from app.security import create_access_token
from tests.factories import make_user, register_other_tutor

URL = "/api/v1/resources"


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


async def _share(group_id, tutor_id, kind, title, day):
    async with async_session() as s:
        s.add(
            GroupResource(
                group_id=group_id,
                tutor_id=tutor_id,
                kind=ResourceKind(kind),
                title=title,
                url="https://example.com/r" if kind == "recording" else None,
                file_path="x/y.pdf" if kind == "file" else None,
                file_name="y.pdf" if kind == "file" else None,
                file_mime="application/pdf" if kind == "file" else None,
                created_at=_at(day),
            )
        )
        await s.commit()


async def _headers_for(**kw) -> dict:
    async with async_session() as s:
        user = await make_user(s, **kw)
        await s.commit()
        token = create_access_token(user.id, user.token_version)
    return {"Authorization": f"Bearer {token}"}


async def _org_id(tutor) -> int:
    async with async_session() as s:
        return (await s.get(User, tutor["user"]["id"])).organization_id


async def test_lists_files_and_recordings_across_classes_newest_first(client, tutor, subject):
    a = await _group(client, tutor, subject, "Chem A")
    b = await _group(client, tutor, subject, "Chem B")
    uid = tutor["user"]["id"]
    await _share(a["id"], uid, "file", "Worksheet", 1)
    await _share(b["id"], uid, "recording", "Lesson 2", 3)
    await _share(a["id"], uid, "recording", "Lesson 1", 2)

    resp = await client.get(URL, headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["title"] for r in rows] == ["Lesson 2", "Lesson 1", "Worksheet"]
    assert [(r["group_id"], r["group_name"]) for r in rows] == [
        (b["id"], "Chem B"),
        (a["id"], "Chem A"),
        (a["id"], "Chem A"),
    ]
    assert rows[2]["kind"] == "file" and rows[2]["file_name"] == "y.pdf"
    assert rows[0]["url"] == "https://example.com/r"


async def test_kind_filter_and_an_invalid_kind(client, tutor, subject):
    a = await _group(client, tutor, subject, "Chem A")
    uid = tutor["user"]["id"]
    await _share(a["id"], uid, "file", "Worksheet", 1)
    await _share(a["id"], uid, "recording", "Lesson", 2)

    files = await client.get(URL, params={"kind": "file"}, headers=tutor["headers"])
    assert [r["title"] for r in files.json()] == ["Worksheet"]
    recs = await client.get(URL, params={"kind": "recording"}, headers=tutor["headers"])
    assert [r["title"] for r in recs.json()] == ["Lesson"]
    bad = await client.get(URL, params={"kind": "video"}, headers=tutor["headers"])
    assert bad.status_code == 422


async def test_no_material_is_an_empty_list(client, tutor):
    resp = await client.get(URL, headers=tutor["headers"])
    assert resp.status_code == 200 and resp.json() == []


async def test_a_student_and_a_parent_are_refused_and_unauthenticated_too(
    client, tutor, group, student
):
    assert (await client.get(URL, headers=student["headers"])).status_code == 403
    parent = await _headers_for(
        organization_id=await _org_id(tutor),
        role=UserRole.parent,
        name="P",
        email="p@example.com",
    )
    assert (await client.get(URL, headers=parent)).status_code == 403
    assert (await client.get(URL)).status_code == 401


async def test_another_organizations_tutor_sees_none_of_it(client, tutor, subject):
    a = await _group(client, tutor, subject, "Chem A")
    await _share(a["id"], tutor["user"]["id"], "file", "Worksheet", 1)
    other = await register_other_tutor(client)
    resp = await client.get(URL, headers=other["headers"])
    assert resp.status_code == 200 and resp.json() == []


async def test_a_colleague_and_an_admin_see_only_their_own_classes(client, tutor, subject):
    a = await _group(client, tutor, subject, "Chem A")
    await _share(a["id"], tutor["user"]["id"], "file", "Worksheet", 1)
    org_id = await _org_id(tutor)
    colleague = await _headers_for(
        organization_id=org_id, role=UserRole.tutor, name="C", email="c@example.com"
    )
    admin = await _headers_for(
        organization_id=org_id, role=UserRole.admin, name="A", email="a@example.com"
    )
    assert (await client.get(URL, headers=colleague)).json() == []
    assert (await client.get(URL, headers=admin)).json() == []


async def test_a_class_moved_to_another_organization_is_not_listed(client, tutor, subject):
    # The organization binds alongside ownership (SEC-7): a class whose
    # organization is not the caller's is not theirs even with their tutor_id.
    a = await _group(client, tutor, subject, "Chem A")
    await _share(a["id"], tutor["user"]["id"], "file", "Worksheet", 1)
    other = await register_other_tutor(client)
    async with async_session() as s:
        moved = await s.get(Group, a["id"])
        moved.organization_id = (await s.get(User, other["user"]["id"])).organization_id
        await s.commit()
    assert (await client.get(URL, headers=tutor["headers"])).json() == []


async def test_query_count_is_flat_in_the_number_of_classes(client, tutor, subject):
    uid = tutor["user"]["id"]

    async def count() -> int:
        queries: list[str] = []

        def before(conn, cursor, statement, params, context, executemany):
            queries.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", before)
        try:
            resp = await client.get(URL, headers=tutor["headers"])
            assert resp.status_code == 200
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", before)
        return len(queries)

    first = await _group(client, tutor, subject, "One")
    await _share(first["id"], uid, "file", "f", 1)
    baseline = await count()
    for i in range(5):
        g = await _group(client, tutor, subject, f"More{i}")
        await _share(g["id"], uid, "recording", f"r{i}", 2 + i)
    assert await count() == baseline
