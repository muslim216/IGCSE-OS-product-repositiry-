"""P-8: a parent link can be removed, by the tutor, the parent or the student,
access ends at once, and every removal is recorded (PROD-7)."""

from sqlalchemy import select

from app.db import async_session
from app.models import (
    Invite,
    Notification,
    NotificationKind,
    NotificationStatus,
    ParentLink,
    ParentLinkRemoval,
    User,
    UserRole,
)
from app.services.notifications import notify, send_notification
from tests.factories import (
    add_contact,
    make_user,
    patch_channels,
    register_other_tutor,
    register_parent,
)

API = "/api/v1"


async def _setup(client, tutor, student, email="parent@example.com"):
    parent = await register_parent(client, tutor, student, email)
    sid = student["user"]["id"]
    listed = await client.get(f"{API}/students/{sid}/parents", headers=tutor["headers"])
    assert listed.status_code == 200
    link = next(p for p in listed.json() if p["parent_id"] == parent["user"]["id"])
    return parent, sid, link["id"]


async def _parent_reads(client, parent, sid) -> dict:
    h = parent["headers"]
    return {
        "readiness": (await client.get(f"{API}/readiness/students/{sid}", headers=h)).status_code,
        "reports": (await client.get(f"{API}/reports?student_id={sid}", headers=h)).status_code,
        "narrative": (await client.get(f"{API}/students/{sid}/narrative", headers=h)).status_code,
    }


async def _link_exists(link_id) -> bool:
    async with async_session() as s:
        return await s.get(ParentLink, link_id) is not None


async def test_tutor_unlink_revokes_access_and_writes_audit(client, tutor, student):
    parent, sid, link_id = await _setup(client, tutor, student)
    assert (await _parent_reads(client, parent, sid))["readiness"] == 200

    resp = await client.delete(f"{API}/students/{sid}/parents/{link_id}", headers=tutor["headers"])
    assert resp.status_code == 204

    assert await _parent_reads(client, parent, sid) == {
        "readiness": 404,
        "reports": 404,
        "narrative": 404,
    }
    async with async_session() as s:
        row = (await s.scalars(select(ParentLinkRemoval))).one()
        assert (row.link_id, row.parent_id, row.student_id) == (link_id, parent["user"]["id"], sid)
        assert row.removed_by_id == tutor["user"]["id"]
        assert row.removed_by_role == "tutor"
        assert row.created_at is not None
    assert not await _link_exists(link_id)


async def test_other_organizations_tutor_gets_404(client, tutor, student):
    _, sid, link_id = await _setup(client, tutor, student)
    other = await register_other_tutor(client)
    listed = await client.get(f"{API}/students/{sid}/parents", headers=other["headers"])
    assert listed.status_code == 404
    resp = await client.delete(f"{API}/students/{sid}/parents/{link_id}", headers=other["headers"])
    assert resp.status_code == 404
    assert await _link_exists(link_id)


async def test_link_id_under_the_wrong_student_is_404(client, tutor, student):
    _, sid, link_id = await _setup(client, tutor, student)
    resp = await client.delete(
        f"{API}/students/{sid + 999}/parents/{link_id}", headers=tutor["headers"]
    )
    assert resp.status_code == 404
    assert await _link_exists(link_id)


async def test_tutor_who_does_not_teach_the_student_gets_404(client, tutor, student):
    _, sid, link_id = await _setup(client, tutor, student)
    async with async_session() as s:
        org = (await s.get(User, tutor["user"]["id"])).organization_id
        await make_user(
            s, organization_id=org, role=UserRole.tutor, name="Col", email="col@example.com"
        )
        await s.commit()
    login = await client.post(
        f"{API}/auth/login", json={"identifier": "col@example.com", "password": "password123"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    assert (await client.get(f"{API}/students/{sid}/parents", headers=headers)).status_code == 404
    resp = await client.delete(f"{API}/students/{sid}/parents/{link_id}", headers=headers)
    assert resp.status_code == 404
    assert await _link_exists(link_id)


async def test_parent_removes_own_link_only(client, tutor, student):
    p1, sid, l1 = await _setup(client, tutor, student, "p1@example.com")
    p2, _, l2 = await _setup(client, tutor, student, "p2@example.com")

    resp = await client.delete(f"{API}/me/children/{sid}", headers=p2["headers"])
    assert resp.status_code == 204
    assert (await _parent_reads(client, p2, sid))["readiness"] == 404
    assert (await _parent_reads(client, p1, sid))["readiness"] == 200
    # Nothing of p2's is left to remove, and p1's link is untouched.
    resp = await client.delete(f"{API}/me/children/{sid}", headers=p2["headers"])
    assert resp.status_code == 404

    async with async_session() as s:
        row = (await s.scalars(select(ParentLinkRemoval))).one()
        assert row.link_id == l2
        assert row.removed_by_id == p2["user"]["id"]
        assert row.removed_by_role == "parent"
    assert await _link_exists(l1)


async def test_wrong_role_is_refused(client, tutor, student):
    parent, sid, link_id = await _setup(client, tutor, student)
    h = parent["headers"]
    assert (await client.get(f"{API}/students/{sid}/parents", headers=h)).status_code == 403
    resp = await client.delete(f"{API}/students/{sid}/parents/{link_id}", headers=h)
    assert resp.status_code == 403
    assert (await client.delete(f"{API}/me/parent-links/{link_id}", headers=h)).status_code == 403
    resp = await client.delete(f"{API}/me/children/{sid}", headers=tutor["headers"])
    assert resp.status_code == 403
    assert await _link_exists(link_id)


async def test_student_sees_and_removes_a_link(client, tutor, student):
    parent, sid, link_id = await _setup(client, tutor, student)
    h = student["headers"]
    listed = await client.get(f"{API}/me/parent-links", headers=h)
    assert [p["id"] for p in listed.json()] == [link_id]

    assert (await client.delete(f"{API}/me/parent-links/{link_id}", headers=h)).status_code == 204
    assert (await _parent_reads(client, parent, sid))["readiness"] == 404
    assert (await client.get(f"{API}/me/parent-links", headers=h)).json() == []
    async with async_session() as s:
        assert (await s.scalars(select(ParentLinkRemoval))).one().removed_by_role == "student"


async def test_student_cannot_remove_another_students_link(client, tutor, student, group):
    invite = await client.post(f"{API}/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        f"{API}/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Omar",
            "email": "omar@example.com",
            "password": "password123",
        },
    )
    omar = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}
    _, _, link_id = await _setup(client, tutor, student)
    resp = await client.delete(f"{API}/me/parent-links/{link_id}", headers=omar)
    assert resp.status_code == 404
    assert await _link_exists(link_id)


async def test_the_code_that_made_a_removed_link_is_already_spent(client, tutor, student):
    """Parent-link codes are single-use, so unlinking leaves nothing to reuse."""
    _, sid, link_id = await _setup(client, tutor, student)
    await client.delete(f"{API}/students/{sid}/parents/{link_id}", headers=tutor["headers"])
    async with async_session() as s:
        used = (await s.scalars(select(Invite).where(Invite.student_id == sid))).all()
    assert used
    assert all(i.used_at is not None for i in used)


async def test_a_parent_in_another_organization_is_not_listed(client, tutor, student):
    """SEC-7: the list is also scoped by organization, whatever a link row says."""
    _, sid, _ = await _setup(client, tutor, student)
    async with async_session() as s:
        other = await register_other_tutor(client)
        outsider = await make_user(
            s,
            organization_id=(await s.get(User, other["user"]["id"])).organization_id,
            role=UserRole.parent,
            name="Outsider",
            email="outsider@example.com",
        )
        s.add(ParentLink(parent_id=outsider.id, student_id=sid))
        await s.commit()
    listed = await client.get(f"{API}/students/{sid}/parents", headers=tutor["headers"])
    assert "Outsider" not in [p["name"] for p in listed.json()]
    assert "Outsider" not in [
        p["name"]
        for p in (await client.get(f"{API}/me/parent-links", headers=student["headers"])).json()
    ]


async def test_a_queued_message_is_not_sent_after_the_parent_is_unlinked(
    monkeypatch, client, tutor, student
):
    fakes = patch_channels(monkeypatch)
    parent, sid, link_id = await _setup(client, tutor, student)
    async with async_session() as s:
        user = await s.get(User, parent["user"]["id"])
        await add_contact(s, user.id, channel="email", address="p@example.com")
        note = await notify(
            s,
            recipient=user,
            kind=NotificationKind.review_queue,
            params={"pending_count": 1},
            link_path="/x",
            idempotency_key="unlink-1",
        )
        await s.commit()
        note_id = note.id
    await client.delete(f"{API}/students/{sid}/parents/{link_id}", headers=tutor["headers"])
    async with async_session() as s:
        await send_notification(s, {"notification_id": note_id})
        await s.commit()
        note = await s.get(Notification, note_id)
        assert note.status == NotificationStatus.suppressed
    assert all(not f.sent for f in fakes.values())
