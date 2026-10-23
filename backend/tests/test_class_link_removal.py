"""A class join link can be switched off, and a removal sticks (audit GH-1)."""

from sqlalchemy import select

from app.db import async_session
from app.models import User, UserRole

G = "/api/v1/groups"


async def _link(client, tutor, group):
    r = await client.post(f"{G}/{group['id']}/invites", headers=tutor["headers"])
    assert r.status_code == 201, r.text
    return r.json()["code"]


async def _register(client, code, email="sara@example.com"):
    return await client.post(
        "/api/v1/auth/register/student",
        json={"invite_code": code, "name": "Sara", "email": email, "password": "password123"},
    )


async def _other_tutor(client):
    r = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other@example.com", "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}


async def test_revoked_link_refuses_registration_and_join(client, tutor, group, student):
    code = await _link(client, tutor, group)
    revoke = await client.delete(f"{G}/{group['id']}/invites", headers=tutor["headers"])
    assert revoke.status_code == 204
    live = await client.get(f"{G}/{group['id']}/invites", headers=tutor["headers"])
    assert live.json() == []

    assert (await _register(client, code, "new@example.com")).status_code == 410
    join = await client.post(
        "/api/v1/auth/join", json={"invite_code": code}, headers=student["headers"]
    )
    assert join.status_code == 410


async def test_new_link_switches_the_old_one_off(client, tutor, group):
    old = await _link(client, tutor, group)
    new = await _link(client, tutor, group)
    live = await client.get(f"{G}/{group['id']}/invites", headers=tutor["headers"])
    assert [i["code"] for i in live.json()] == [new]
    assert (await _register(client, old)).status_code == 410
    assert (await _register(client, new)).status_code == 201


async def test_removed_student_cannot_rejoin_and_tutor_can_add_back(client, tutor, group, student):
    sid = student["user"]["id"]
    removed = await client.delete(f"{G}/{group['id']}/members/{sid}", headers=tutor["headers"])
    assert removed.status_code == 204

    for _ in range(2):  # a link, then a regenerated one
        code = await _link(client, tutor, group)
        join = await client.post(
            "/api/v1/auth/join", json={"invite_code": code}, headers=student["headers"]
        )
        assert join.status_code == 403
    detail = await client.get(f"{G}/{group['id']}", headers=tutor["headers"])
    assert detail.json()["members"] == []
    listed = await client.get(f"{G}/{group['id']}/removals", headers=tutor["headers"])
    assert [r["id"] for r in listed.json()] == [sid]
    assert listed.json()[0]["removed_at"]

    back = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": sid}, headers=tutor["headers"]
    )
    assert back.status_code == 204
    detail = await client.get(f"{G}/{group['id']}", headers=tutor["headers"])
    assert [m["id"] for m in detail.json()["members"]] == [sid]

    cleared = await client.get(f"{G}/{group['id']}/removals", headers=tutor["headers"])
    assert cleared.json() == []

    # Adding twice is harmless.
    again = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": sid}, headers=tutor["headers"]
    )
    assert again.status_code == 204


async def test_other_organization_gets_404(client, tutor, group, student):
    other = await _other_tutor(client)
    assert (await client.delete(f"{G}/{group['id']}/invites", headers=other)).status_code == 404
    assert (await client.get(f"{G}/{group['id']}/invites", headers=other)).status_code == 404
    assert (await client.get(f"{G}/{group['id']}/removals", headers=other)).status_code == 404
    add = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": student["user"]["id"]}, headers=other
    )
    assert add.status_code == 404


async def test_student_cannot_manage_links_or_members(client, tutor, group, student):
    h = student["headers"]
    assert (await client.delete(f"{G}/{group['id']}/invites", headers=h)).status_code == 403
    assert (await client.get(f"{G}/{group['id']}/invites", headers=h)).status_code == 403
    assert (await client.get(f"{G}/{group['id']}/removals", headers=h)).status_code == 403
    add = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": student["user"]["id"]}, headers=h
    )
    assert add.status_code == 403


async def _second_group(client, tutor, subject, name="Chem Y11"):
    r = await client.post(
        G, json={"name": name, "subject_id": subject["id"]}, headers=tutor["headers"]
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _members(client, tutor, group):
    detail = await client.get(f"{G}/{group['id']}", headers=tutor["headers"])
    return [m["id"] for m in detail.json()["members"]]


async def _join(client, student, code):
    return await client.post(
        "/api/v1/auth/join", json={"invite_code": code}, headers=student["headers"]
    )


async def _add_back(client, tutor, group, sid):
    return await client.post(
        f"{G}/{group['id']}/members", json={"student_id": sid}, headers=tutor["headers"]
    )


async def test_add_member_refuses_foreign_tutor_and_missing_ids_and_creates_nothing(
    client, tutor, group, student
):
    await _other_tutor(client)
    # A student of organization B, made straight in the database.
    async with async_session() as db:
        org_b = await db.scalar(
            select(User.organization_id).where(User.email == "other@example.com")
        )
        foreign = User(
            email="bee@example.com",
            password_hash="x",
            role=UserRole.student,
            name="Bee",
            organization_id=org_b,
        )
        db.add(foreign)
        await db.commit()
        foreign_id = foreign.id
    for sid in (foreign_id, tutor["user"]["id"], 999999):
        r = await _add_back(client, tutor, group, sid)
        assert r.status_code == 404, (sid, r.text)
    assert await _members(client, tutor, group) == [student["user"]["id"]]


async def test_remove_add_back_remove_again_never_errors(client, tutor, group, student):
    sid = student["user"]["id"]
    for _ in range(3):
        removed = await client.delete(f"{G}/{group['id']}/members/{sid}", headers=tutor["headers"])
        assert removed.status_code == 204
        # A second delete finds nobody to remove: a 404, not a 500.
        again = await client.delete(f"{G}/{group['id']}/members/{sid}", headers=tutor["headers"])
        assert again.status_code == 404
        assert (await _add_back(client, tutor, group, sid)).status_code == 204
    assert await _members(client, tutor, group) == [sid]


async def test_added_back_student_can_join_through_a_link_again(client, tutor, group, student):
    sid = student["user"]["id"]
    await client.delete(f"{G}/{group['id']}/members/{sid}", headers=tutor["headers"])
    await _add_back(client, tutor, group, sid)
    # In the class again, so the link's join is a harmless 204, not a refusal.
    code = await _link(client, tutor, group)
    assert (await _join(client, student, code)).status_code == 204
    assert await _members(client, tutor, group) == [sid]


async def test_removal_in_one_class_does_not_block_another(client, tutor, group, subject, student):
    other_class = await _second_group(client, tutor, subject)
    await client.delete(
        f"{G}/{group['id']}/members/{student['user']['id']}", headers=tutor["headers"]
    )
    code = await _link(client, tutor, other_class)
    assert (await _join(client, student, code)).status_code == 204
    assert await _members(client, tutor, other_class) == [student["user"]["id"]]


async def test_revoking_one_class_leaves_other_links_and_parent_links(
    client, tutor, group, subject, student
):
    other_class = await _second_group(client, tutor, subject)
    other_code = await _link(client, tutor, other_class)
    await _link(client, tutor, group)
    parent = await client.post(
        f"/api/v1/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
    )
    assert parent.status_code in (200, 201), parent.text

    for _ in range(2):  # twice is fine
        r = await client.delete(f"{G}/{group['id']}/invites", headers=tutor["headers"])
        assert r.status_code == 204
    live = await client.get(f"{G}/{other_class['id']}/invites", headers=tutor["headers"])
    assert [i["code"] for i in live.json()] == [other_code]
    preview = await client.get(f"/api/v1/auth/invites/{parent.json()['code']}")
    assert preview.status_code == 200


async def test_removals_are_listed_newest_first(client, tutor, group):
    ids = []
    for n in range(2):
        made = await client.post(
            f"{G}/{group['id']}/students",
            json={"name": f"S{n}", "username": f"s{n}_2010", "password": "password123"},
            headers=tutor["headers"],
        )
        ids.append(made.json()["id"])
    for sid in ids:
        await client.delete(f"{G}/{group['id']}/members/{sid}", headers=tutor["headers"])
    listed = await client.get(f"{G}/{group['id']}/removals", headers=tutor["headers"])
    assert [r["id"] for r in listed.json()] == ids[::-1]
