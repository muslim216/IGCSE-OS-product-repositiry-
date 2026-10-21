"""A class join link can be switched off, and a removal sticks (audit GH-1)."""

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

    back = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": sid}, headers=tutor["headers"]
    )
    assert back.status_code == 204
    detail = await client.get(f"{G}/{group['id']}", headers=tutor["headers"])
    assert [m["id"] for m in detail.json()["members"]] == [sid]

    # Adding twice is harmless.
    again = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": sid}, headers=tutor["headers"]
    )
    assert again.status_code == 204


async def test_other_organization_gets_404(client, tutor, group, student):
    other = await _other_tutor(client)
    assert (await client.delete(f"{G}/{group['id']}/invites", headers=other)).status_code == 404
    assert (await client.get(f"{G}/{group['id']}/invites", headers=other)).status_code == 404
    add = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": student["user"]["id"]}, headers=other
    )
    assert add.status_code == 404


async def test_student_cannot_manage_links_or_members(client, tutor, group, student):
    h = student["headers"]
    assert (await client.delete(f"{G}/{group['id']}/invites", headers=h)).status_code == 403
    assert (await client.get(f"{G}/{group['id']}/invites", headers=h)).status_code == 403
    add = await client.post(
        f"{G}/{group['id']}/members", json={"student_id": student["user"]["id"]}, headers=h
    )
    assert add.status_code == 403
