"""A tutor's "Not now" (owner decision 2026-10-06).

The negative cases carry the weight: one tutor must never see or clear another's
hidden prompts, in the same organization or another, and a non-tutor is refused
(`QA-12`).
"""

from app.db import async_session
from app.models import DismissedPrompt, User, UserRole
from app.security import create_access_token, hash_password
from app.services.dismissals import MAX_DISMISSALS_PER_USER
from tests.factories import register_other_tutor, register_parent

URL = "/api/v1/me/dismissals"


async def _colleague(organization_id: int) -> dict:
    """A second tutor in the SAME organization."""
    async with async_session() as session:
        user = User(
            email="colleague@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.tutor,
            name="Colleague",
            organization_id=organization_id,
        )
        session.add(user)
        await session.commit()
        token = create_access_token(user.id, user.token_version)
    return {"Authorization": f"Bearer {token}"}


async def _org_id(tutor) -> int:
    async with async_session() as session:
        return (await session.get(User, tutor["user"]["id"])).organization_id


async def _keys(client, headers) -> list[str]:
    resp = await client.get(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["keys"]


async def test_round_trip(client, tutor):
    h = tutor["headers"]
    assert await _keys(client, h) == []
    assert (await client.put(f"{URL}/chapter_prompt:3:40", headers=h)).status_code == 204
    assert (await client.put(f"{URL}/setup_guide", headers=h)).status_code == 204
    assert await _keys(client, h) == ["chapter_prompt:3:40", "setup_guide"]

    assert (await client.delete(f"{URL}/setup_guide", headers=h)).status_code == 204
    assert await _keys(client, h) == ["chapter_prompt:3:40"]

    assert (await client.delete(URL, headers=h)).status_code == 204
    assert await _keys(client, h) == []


async def test_the_timetable_step_of_a_subject_with_no_class_is_a_valid_key(client, tutor):
    h = tutor["headers"]
    assert (await client.put(f"{URL}/setup_step:timetable:subject-7", headers=h)).status_code == 204
    assert await _keys(client, h) == ["setup_step:timetable:subject-7"]


async def test_put_and_delete_are_idempotent(client, tutor):
    h = tutor["headers"]
    for _ in range(2):
        assert (await client.put(f"{URL}/lesson_reminder:9", headers=h)).status_code == 204
    assert await _keys(client, h) == ["lesson_reminder:9"]
    for _ in range(2):
        assert (await client.delete(f"{URL}/lesson_reminder:9", headers=h)).status_code == 204
    assert (await client.delete(f"{URL}/lesson_reminder:never", headers=h)).status_code == 204
    assert (await client.delete(URL, headers=h)).status_code == 204
    assert await _keys(client, h) == []


async def test_a_student_is_refused_on_every_route(client, tutor, student):
    h = student["headers"]
    assert (await client.get(URL, headers=h)).status_code == 403
    assert (await client.put(f"{URL}/setup_guide", headers=h)).status_code == 403
    assert (await client.delete(f"{URL}/setup_guide", headers=h)).status_code == 403
    assert (await client.delete(URL, headers=h)).status_code == 403
    assert await _keys(client, tutor["headers"]) == []


async def test_a_parent_is_refused_and_no_token_is_401(client, tutor, student):
    parent = await register_parent(client, tutor, student)
    assert (await client.get(URL, headers=parent["headers"])).status_code == 403
    assert (await client.put(f"{URL}/setup_guide", headers=parent["headers"])).status_code == 403
    assert (await client.get(URL)).status_code == 401
    assert (await client.put(f"{URL}/setup_guide")).status_code == 401


async def test_a_tutor_in_another_organization_sees_and_clears_nothing_of_mine(client, tutor):
    other = await register_other_tutor(client)
    await client.put(f"{URL}/setup_guide", headers=tutor["headers"])
    await client.put(f"{URL}/setup_guide", headers=other["headers"])
    await client.put(f"{URL}/chapter_prompt:1:2", headers=tutor["headers"])

    assert await _keys(client, other["headers"]) == ["setup_guide"]

    await client.delete(f"{URL}/chapter_prompt:1:2", headers=other["headers"])
    await client.delete(URL, headers=other["headers"])
    assert await _keys(client, tutor["headers"]) == ["setup_guide", "chapter_prompt:1:2"]
    assert await _keys(client, other["headers"]) == []


async def test_a_colleague_in_the_same_organization_sees_and_clears_nothing_of_mine(client, tutor):
    colleague = await _colleague(await _org_id(tutor))
    await client.put(f"{URL}/setup_guide", headers=tutor["headers"])

    assert await _keys(client, colleague) == []
    # Hiding the same thing is a separate row, not a share of mine.
    await client.put(f"{URL}/setup_guide", headers=colleague)
    await client.delete(URL, headers=colleague)
    assert await _keys(client, tutor["headers"]) == ["setup_guide"]


async def test_a_bad_key_is_422(client, tutor):
    h = tutor["headers"]
    for bad in [
        "Setup_Guide",  # upper case
        "setup guide",  # space
        "setup_guide!",
        "needs_you:1",  # not an allow-listed kind
        "setup_step:",  # prefix with nothing after it
        "chapter_prompt",  # prefix without its colon
        "chapter_prompt:" + "1" * 120,  # over 120
        "x",
    ]:
        resp = await client.put(f"{URL}/{bad}", headers=h)
        assert resp.status_code == 422, bad
    assert await _keys(client, h) == []


async def test_the_table_cannot_be_filled(client, tutor):
    h = tutor["headers"]
    org_id = await _org_id(tutor)
    async with async_session() as session:
        session.add_all(
            DismissedPrompt(
                organization_id=org_id,
                user_id=tutor["user"]["id"],
                key=f"lesson_reminder:{n}",
            )
            for n in range(MAX_DISMISSALS_PER_USER)
        )
        await session.commit()

    assert (await client.put(f"{URL}/lesson_reminder:new", headers=h)).status_code == 409
    # Hiding what is already hidden is still fine at the cap.
    assert (await client.put(f"{URL}/lesson_reminder:0", headers=h)).status_code == 204
    # Restoring frees room.
    await client.delete(f"{URL}/lesson_reminder:0", headers=h)
    assert (await client.put(f"{URL}/lesson_reminder:new", headers=h)).status_code == 204
