"""Lessons core entity: dated lesson events, topics covered, per-student
observations, and the assignments.lesson_id link."""

from app.workers.jobs import process_one_job
from tests.test_readiness_api import world  # noqa: F401 - shared fixture


async def test_create_list_update_delete_lesson(client, tutor, world):
    create = await client.post(
        "/api/v1/lessons",
        json={
            "group_id": world["group"]["id"],
            "date": "2026-07-14",
            "duration_min": 90,
            "notes": "Covered atomic structure basics.",
        },
        headers=tutor["headers"],
    )
    assert create.status_code == 201, create.text
    lesson = create.json()
    assert lesson["notes"] == "Covered atomic structure basics."
    assert lesson["topics"] == []

    listing = await client.get(
        f"/api/v1/lessons/group/{world['group']['id']}", headers=tutor["headers"]
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    updated = await client.patch(
        f"/api/v1/lessons/{lesson['id']}",
        json={"notes": "Updated notes."},
        headers=tutor["headers"],
    )
    assert updated.status_code == 200
    assert updated.json()["notes"] == "Updated notes."

    deleted = await client.delete(f"/api/v1/lessons/{lesson['id']}", headers=tutor["headers"])
    assert deleted.status_code == 204


async def test_set_lesson_topics(client, tutor, world):
    create = await client.post(
        "/api/v1/lessons",
        json={"group_id": world["group"]["id"], "date": "2026-07-14"},
        headers=tutor["headers"],
    )
    lesson_id = create.json()["id"]

    topics_resp = await client.put(
        f"/api/v1/lessons/{lesson_id}/topics",
        json={"topic_ids": [world["topic1"], world["topic2"]]},
        headers=tutor["headers"],
    )
    assert topics_resp.status_code == 200
    topic_ids = {t["id"] for t in topics_resp.json()["topics"]}
    assert topic_ids == {world["topic1"], world["topic2"]}

    # Replacing with a smaller set drops the removed topic.
    replaced = await client.put(
        f"/api/v1/lessons/{lesson_id}/topics",
        json={"topic_ids": [world["topic1"]]},
        headers=tutor["headers"],
    )
    assert {t["id"] for t in replaced.json()["topics"]} == {world["topic1"]}


async def test_lesson_observation_feeds_readiness(client, tutor, world):
    create = await client.post(
        "/api/v1/lessons",
        json={"group_id": world["group"]["id"], "date": "2026-07-14"},
        headers=tutor["headers"],
    )
    lesson_id = create.json()["id"]

    obs = await client.post(
        f"/api/v1/lessons/{lesson_id}/observations",
        json={
            "student_id": world["student_id"],
            "topic_id": world["topic1"],
            "body": "Answered confidently in class.",
            "rating": 85,
        },
        headers=tutor["headers"],
    )
    assert obs.status_code == 201, obs.text

    assert await process_one_job() is True  # recompute_readiness

    ev = await client.get(
        f"/api/v1/readiness/students/{world['student_id']}/topics/{world['topic1']}/evidence",
        headers=tutor["headers"],
    )
    assert ev.status_code == 200
    assert ev.json()["evidence"][0]["source_type"] == "observation"
    assert ev.json()["evidence"][0]["score_pct"] == 85.0

    listing = await client.get(
        f"/api/v1/lessons/{lesson_id}/observations", headers=tutor["headers"]
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


async def test_lesson_observation_without_rating_no_evidence(client, tutor, world):
    create = await client.post(
        "/api/v1/lessons",
        json={"group_id": world["group"]["id"], "date": "2026-07-14"},
        headers=tutor["headers"],
    )
    lesson_id = create.json()["id"]

    obs = await client.post(
        f"/api/v1/lessons/{lesson_id}/observations",
        json={"student_id": world["student_id"], "body": "Seemed a bit distracted today."},
        headers=tutor["headers"],
    )
    assert obs.status_code == 201
    # No rating/topic means no evidence job was enqueued.
    assert await process_one_job() is False


async def test_lesson_access_control(client, tutor, world):
    other = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Other", "email": "other-lesson@example.com", "password": "password123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    create = await client.post(
        "/api/v1/lessons",
        json={"group_id": world["group"]["id"], "date": "2026-07-14"},
        headers=other_headers,
    )
    assert create.status_code == 404

    own_create = await client.post(
        "/api/v1/lessons",
        json={"group_id": world["group"]["id"], "date": "2026-07-14"},
        headers=tutor["headers"],
    )
    lesson_id = own_create.json()["id"]
    view = await client.get(f"/api/v1/lessons/{lesson_id}", headers=other_headers)
    assert view.status_code == 404


async def test_assignment_links_to_lesson(client, tutor, world):
    create = await client.post(
        "/api/v1/lessons",
        json={"group_id": world["group"]["id"], "date": "2026-07-14"},
        headers=tutor["headers"],
    )
    lesson_id = create.json()["id"]

    assignment = await client.post(
        "/api/v1/assignments",
        json={"group_id": world["group"]["id"], "lesson_id": lesson_id, "title": "HW from lesson"},
        headers=tutor["headers"],
    )
    assert assignment.status_code == 201, assignment.text
    assert assignment.json()["lesson_id"] == lesson_id
