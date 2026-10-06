"""Contact, preference, org-setting and status endpoints (8.1)."""

from datetime import timedelta

import pytest

from app.config import get_settings
from app.db import async_session
from app.models import (
    Group,
    GroupMember,
    Notification,
    NotificationKind,
    NotificationStatus,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.security import create_access_token
from tests.factories import (
    link_parent,
    make_user,
    register_other_tutor,
    register_parent,
)

NUMBER = "+201001234567"


def _contacts(student_id) -> str:
    return f"/api/v1/students/{student_id}/contacts"


async def _put(client, headers, student, address=NUMBER, channel="whatsapp", user_id=None):
    body = {"channel": channel, "address": address}
    if user_id is not None:
        body["user_id"] = user_id
    return await client.put(_contacts(student["user"]["id"]), json=body, headers=headers)


async def test_tutor_sets_lists_and_confirms_a_student_contact(client, tutor, student):
    put = await _put(client, tutor["headers"], student, address="+20 100 123-4567")
    assert put.status_code == 200, put.text
    contact = put.json()
    assert contact["address"] == NUMBER
    assert contact["confirmed_at"] is None

    confirm = await client.post(
        f"{_contacts(student['user']['id'])}/{contact['id']}/confirm", headers=tutor["headers"]
    )
    assert confirm.status_code == 200
    assert confirm.json()["confirmed_at"] is not None
    assert confirm.json()["confirmed_by_id"] == tutor["user"]["id"]

    listing = await client.get(_contacts(student["user"]["id"]), headers=tutor["headers"])
    people = listing.json()
    assert [p["role"] for p in people] == ["student"]
    assert people[0]["contacts"][0]["address"] == NUMBER


async def test_a_parent_contact_is_listed_and_settable(client, tutor, student):
    parent = await register_parent(client, tutor, student)
    pid = parent["user"]["id"]
    put = await _put(client, tutor["headers"], student, "Mum@Example.com", "email", user_id=pid)
    assert put.status_code == 200
    assert put.json()["address"] == "mum@example.com"
    people = (await client.get(_contacts(student["user"]["id"]), headers=tutor["headers"])).json()
    assert {p["user_id"] for p in people} == {student["user"]["id"], pid}


async def test_changing_the_address_clears_confirmation_and_resubmitting_does_not(
    client, tutor, student
):
    contact = (await _put(client, tutor["headers"], student)).json()
    url = f"{_contacts(student['user']['id'])}/{contact['id']}/confirm"
    await client.post(url, headers=tutor["headers"])

    same = (await _put(client, tutor["headers"], student)).json()
    assert same["confirmed_at"] is not None

    changed = (await _put(client, tutor["headers"], student, address="+201009999999")).json()
    assert changed["id"] == contact["id"]
    assert changed["confirmed_at"] is None
    assert changed["confirmed_by_id"] is None


@pytest.mark.parametrize(
    ("channel", "address"),
    [("whatsapp", "01001234567"), ("whatsapp", "+12"), ("whatsapp", "abc"), ("email", "nope")],
)
async def test_invalid_addresses_are_refused(client, tutor, student, channel, address):
    resp = await _put(client, tutor["headers"], student, address, channel)
    assert resp.status_code == 422


async def test_a_person_who_is_not_the_students_parent_is_404(client, tutor, student):
    resp = await _put(client, tutor["headers"], student, user_id=tutor["user"]["id"])
    assert resp.status_code == 404


# --- cross-organization negatives (QA-12) ------------------------------------


async def test_another_organizations_tutor_gets_404_everywhere(client, tutor, student):
    other = await register_other_tutor(client)
    sid = student["user"]["id"]
    contact = (await _put(client, tutor["headers"], student)).json()

    assert (await client.get(_contacts(sid), headers=other["headers"])).status_code == 404
    assert (await _put(client, other["headers"], student)).status_code == 404
    confirm = await client.post(
        f"{_contacts(sid)}/{contact['id']}/confirm", headers=other["headers"]
    )
    assert confirm.status_code == 404
    # And nothing was changed by the attempts.
    again = (await client.get(_contacts(sid), headers=tutor["headers"])).json()
    assert again[0]["contacts"][0]["confirmed_at"] is None


async def test_a_contact_id_cannot_be_confirmed_through_a_different_student(client, tutor, student):
    """Own student, someone else's contact: the contact must belong to the
    student's people, not merely exist."""
    other = await register_other_tutor(client)
    mine = (await _put(client, tutor["headers"], student)).json()
    resp = await client.post(f"/api/v1/me/contacts/{mine['id']}/confirm", headers=other["headers"])
    assert resp.status_code == 404


async def test_students_and_parents_cannot_use_the_tutor_endpoints(client, tutor, student):
    parent = await register_parent(client, tutor, student)
    sid = student["user"]["id"]
    for headers in (student["headers"], parent["headers"]):
        assert (await client.get(_contacts(sid), headers=headers)).status_code == 403
        assert (await _put(client, headers, student)).status_code == 403
        assert (await client.get("/api/v1/me/contacts", headers=headers)).status_code == 403
        assert (
            await client.get("/api/v1/notifications/status", headers=headers)
        ).status_code == 403


async def test_unauthenticated_requests_are_refused(client, student):
    assert (await client.get(_contacts(student["user"]["id"]))).status_code == 401
    assert (await client.get("/api/v1/me/notification-preferences")).status_code == 401


# --- the tutor's own contacts -------------------------------------------------


async def test_a_tutor_manages_and_confirms_their_own_contact(client, tutor):
    put = await client.put(
        "/api/v1/me/contacts",
        json={"channel": "whatsapp", "address": NUMBER},
        headers=tutor["headers"],
    )
    assert put.status_code == 200
    cid = put.json()["id"]
    confirm = await client.post(f"/api/v1/me/contacts/{cid}/confirm", headers=tutor["headers"])
    assert confirm.json()["confirmed_by_id"] == tutor["user"]["id"]
    assert len((await client.get("/api/v1/me/contacts", headers=tutor["headers"])).json()) == 1


async def test_a_tutor_cannot_confirm_somebody_elses_contact_through_me(client, tutor, student):
    contact = (await _put(client, tutor["headers"], student)).json()
    other = await register_other_tutor(client)
    resp = await client.post(
        f"/api/v1/me/contacts/{contact['id']}/confirm", headers=other["headers"]
    )
    assert resp.status_code == 404
    # Even the owning organization's tutor: it is the student's, not theirs.
    resp = await client.post(
        f"/api/v1/me/contacts/{contact['id']}/confirm", headers=tutor["headers"]
    )
    assert resp.status_code == 404


# --- preferences ----------------------------------------------------------------


async def test_preferences_list_every_kind_and_channel_and_default_enabled(client, student):
    prefs = (
        await client.get("/api/v1/me/notification-preferences", headers=student["headers"])
    ).json()
    assert len(prefs) == 8 * 2
    assert all(p["enabled"] for p in prefs)


async def test_preferences_are_per_user_and_per_channel(client, tutor, student):
    put = await client.put(
        "/api/v1/me/notification-preferences",
        json={"preferences": [{"kind": "homework_set", "channel": "whatsapp", "enabled": False}]},
        headers=student["headers"],
    )
    assert put.status_code == 200
    off = [p for p in put.json() if not p["enabled"]]
    assert off == [{"kind": "homework_set", "channel": "whatsapp", "enabled": False}]
    # Switching it back on updates the same row.
    again = await client.put(
        "/api/v1/me/notification-preferences",
        json={"preferences": [{"kind": "homework_set", "channel": "whatsapp", "enabled": True}]},
        headers=student["headers"],
    )
    assert all(p["enabled"] for p in again.json())
    # The tutor's own were never touched.
    mine = (
        await client.get("/api/v1/me/notification-preferences", headers=tutor["headers"])
    ).json()
    assert all(p["enabled"] for p in mine)


async def test_the_same_preference_twice_in_one_body_is_last_one_wins(client, student):
    item = {"kind": "homework_set", "channel": "whatsapp"}
    put = await client.put(
        "/api/v1/me/notification-preferences",
        json={"preferences": [{**item, "enabled": True}, {**item, "enabled": False}]},
        headers=student["headers"],
    )
    assert put.status_code == 200
    assert [p for p in put.json() if not p["enabled"]] == [{**item, "enabled": False}]


async def test_unknown_preference_kinds_are_422(client, student):
    resp = await client.put(
        "/api/v1/me/notification-preferences",
        json={"preferences": [{"kind": "spam", "channel": "whatsapp", "enabled": False}]},
        headers=student["headers"],
    )
    assert resp.status_code == 422


# --- organization settings ----------------------------------------------------


async def test_org_defaults_and_update(client, tutor):
    org = (await client.get("/api/v1/me/organization", headers=tutor["headers"])).json()
    assert (org["weekly_send_weekday"], org["weekly_send_hour"], org["ai_language"]) == (
        6,
        17,
        "en",
    )

    put = await client.put(
        "/api/v1/me/organization",
        json={"weekly_send_weekday": 4, "ai_language": "ar"},
        headers=tutor["headers"],
    )
    assert put.status_code == 200
    assert (put.json()["weekly_send_weekday"], put.json()["weekly_send_hour"]) == (4, 17)
    assert put.json()["ai_language"] == "ar"


@pytest.mark.parametrize(
    "body",
    [
        {"weekly_send_weekday": 7},
        {"weekly_send_weekday": -1},
        {"weekly_send_hour": 24},
        {"weekly_send_hour": -1},
        {"ai_language": "fr"},
    ],
)
async def test_org_settings_are_validated(client, tutor, body):
    resp = await client.put("/api/v1/me/organization", json=body, headers=tutor["headers"])
    assert resp.status_code == 422


async def test_only_a_tutor_changes_org_settings(client, tutor, student):
    resp = await client.put(
        "/api/v1/me/organization", json={"weekly_send_hour": 9}, headers=student["headers"]
    )
    assert resp.status_code == 403


# --- channel status ---------------------------------------------------------


async def test_status_is_booleans_and_dormant_by_default(client, tutor):
    resp = await client.get("/api/v1/notifications/status", headers=tutor["headers"])
    assert resp.json() == {"whatsapp_configured": False, "email_configured": False}


async def test_status_reflects_configuration_without_leaking_it(client, tutor, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_access_token", "secret-token")
    monkeypatch.setattr(s, "whatsapp_phone_number_id", "123")
    monkeypatch.setattr(s, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(s, "smtp_from", "hi@example.com")
    resp = await client.get("/api/v1/notifications/status", headers=tutor["headers"])
    assert resp.json() == {"whatsapp_configured": True, "email_configured": True}
    assert "secret-token" not in resp.text


# --- undelivered ----------------------------------------------------------------

UNDELIVERED = "/api/v1/notifications/undelivered"


async def _note(user_id: int, key: str, status: NotificationStatus, *, age_days: int = 0) -> None:
    async with async_session() as session:
        user = await session.get(User, user_id)
        session.add(
            Notification(
                organization_id=user.organization_id,
                recipient_user_id=user.id,
                kind=NotificationKind.weekly_send,
                template="avora_weekly_send",
                params={},
                link_path="/",
                idempotency_key=key,
                status=status,
                error="No confirmed contact for this person",
                created_at=utcnow() - timedelta(days=age_days),
            )
        )
        await session.commit()


async def test_the_tutor_sees_what_reached_nobody_and_why(client, tutor, student):
    sid = student["user"]["id"]
    await _note(sid, "u1", NotificationStatus.no_channel)
    await _note(sid, "u2", NotificationStatus.failed)
    await _note(sid, "u3", NotificationStatus.sent)  # delivered: not a problem
    await _note(sid, "u4", NotificationStatus.queued)  # in flight: not a problem
    await _note(sid, "u5", NotificationStatus.suppressed, age_days=45)  # too old
    rows = (await client.get(UNDELIVERED, headers=tutor["headers"])).json()
    assert {r["status"] for r in rows} == {"no_channel", "failed"}
    assert rows[0]["recipient_name"] == student["user"]["name"]
    assert rows[0]["reason"] == "No confirmed contact for this person"
    assert "address" not in rows[0]


async def test_undelivered_is_one_row_per_person_and_reason_not_one_per_message(
    client, tutor, student
):
    sid = student["user"]["id"]
    for i in range(5):  # five reminders missed for the same reason
        await _note(sid, f"n{i}", NotificationStatus.no_channel, age_days=i)
    await _note(sid, "f1", NotificationStatus.failed)
    rows = (await client.get(UNDELIVERED, headers=tutor["headers"])).json()
    assert sorted(r["status"] for r in rows) == ["failed", "no_channel"]


async def test_undelivered_is_tutor_only_and_never_crosses_organizations(client, tutor, student):
    await _note(student["user"]["id"], "u1", NotificationStatus.failed)
    other = await register_other_tutor(client)
    assert (await client.get(UNDELIVERED, headers=other["headers"])).json() == []
    assert (await client.get(UNDELIVERED, headers=student["headers"])).status_code == 403
    assert (await client.get(UNDELIVERED)).status_code == 401


async def test_a_tutor_sees_failures_only_for_people_in_their_own_classes(
    client, tutor, group, student, subject
):
    """A second tutor in the same organization teaches another learner and that
    learner's parent; neither the failures about them nor the unlinked parent's
    show up for the first tutor, and the second tutor does not see Sara's."""
    parent = await register_parent(client, tutor, student)
    async with async_session() as s:
        org = (await s.get(User, tutor["user"]["id"])).organization_id
        other = await make_user(
            s, organization_id=org, role=UserRole.tutor, name="T2", email="t2@example.com"
        )
        omar = await make_user(
            s, organization_id=org, role=UserRole.student, name="Omar", email="o@example.com"
        )
        omars_parent = await make_user(
            s, organization_id=org, role=UserRole.parent, name="OP", email="op@example.com"
        )
        admin = await make_user(
            s, organization_id=org, role=UserRole.admin, name="Ad", email="ad@example.com"
        )
        g2 = Group(organization_id=org, tutor_id=other.id, subject_id=subject["id"], name="G2")
        s.add(g2)
        await s.flush()
        s.add(GroupMember(group_id=g2.id, student_id=omar.id))
        await link_parent(s, omars_parent.id, omar.id)
        await s.commit()
        other_id, omar_id, op_id, admin_id = other.id, omar.id, omars_parent.id, admin.id
    for key, uid in (
        ("sara", student["user"]["id"]),
        ("sara-parent", parent["user"]["id"]),
        ("omar", omar_id),
        ("omar-parent", op_id),
    ):
        await _note(uid, key, NotificationStatus.failed)

    def headers(uid):
        return {"Authorization": f"Bearer {create_access_token(uid, 0)}"}

    async def names(h):
        return {r["recipient_name"] for r in (await client.get(UNDELIVERED, headers=h)).json()}

    assert await names(tutor["headers"]) == {"Sara", "Parent"}
    assert await names(headers(other_id)) == {"Omar", "OP"}
    # An admin keeps the organization-wide view.
    assert await names(headers(admin_id)) == {"Sara", "Parent", "Omar", "OP"}
