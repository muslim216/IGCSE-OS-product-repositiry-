"""The second per-subject setup document (task 2.5, AV-10).

Stored and served, never parsed: Phase 6 is what reads it to weight the plan
(AV-14). What matters here is that it is one document per subject, that it is
tutor material rather than student-visible (AV-95), and that another
organization's subject id is indistinguishable from one that does not exist
(API-7, SEC-9).
"""

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Subject
from tests.factories import make_subject, other_org_subject

PDF = b"%PDF-1.4 a scheme of work"
PDF2 = b"%PDF-1.4 a revised scheme of work"


@pytest.fixture
async def subject_id(tutor):  # depends on `tutor` so the organization exists first
    async with async_session() as session:
        subject = await make_subject(session, code="4CH1", name="Chemistry")
        await session.commit()
        return subject.id


def upload_files(data=PDF, name="scheme-of-work.pdf"):
    return {"file": (name, data, "application/pdf")}


async def test_a_subject_with_no_guidance_says_so_rather_than_404ing(client, tutor, subject_id):
    """Absence is a state the screen renders, not an error: the subject exists,
    and "nothing uploaded yet" is the answer (PROD-2, UX-19)."""
    resp = await client.get(
        f"/api/v1/subjects/{subject_id}/teaching-guidance", headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["uploaded"] is False
    assert body["file_name"] is None
    assert body["uploaded_at"] is None
    assert body["subject_name"] == "Chemistry"


async def test_upload_then_read_then_download(client, tutor, subject_id):
    up = await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files=upload_files(),
        headers=tutor["headers"],
    )
    assert up.status_code == 200, up.text
    assert up.json()["uploaded"] is True
    assert up.json()["file_name"] == "scheme-of-work.pdf"
    assert up.json()["uploaded_at"] is not None

    read = await client.get(
        f"/api/v1/subjects/{subject_id}/teaching-guidance", headers=tutor["headers"]
    )
    assert read.json()["file_mime"] == "application/pdf"

    served = await client.get(
        f"/api/v1/subjects/{subject_id}/teaching-guidance/file", headers=tutor["headers"]
    )
    assert served.status_code == 200
    assert served.content == PDF


async def test_uploading_again_replaces_and_removes_the_old_object(client, tutor, subject_id):
    """One document per subject. The old object goes with it — leaving it behind
    would keep a superseded scheme of work readable to anyone who kept the key."""
    from app.services import storage

    first = await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files=upload_files(),
        headers=tutor["headers"],
    )
    assert first.status_code == 200
    async with async_session() as session:
        old_key = (await session.get(Subject, subject_id)).guidance_path

    second = await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files=upload_files(PDF2, "revised.pdf"),
        headers=tutor["headers"],
    )
    assert second.status_code == 200
    assert second.json()["file_name"] == "revised.pdf"

    async with async_session() as session:
        new_key = (await session.get(Subject, subject_id)).guidance_path
    assert new_key != old_key
    with pytest.raises(storage.ObjectNotFoundError):
        await storage.read_file(old_key)

    served = await client.get(
        f"/api/v1/subjects/{subject_id}/teaching-guidance/file", headers=tutor["headers"]
    )
    assert served.content == PDF2


async def test_delete_clears_the_row_and_is_idempotent(client, tutor, subject_id):
    await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files=upload_files(),
        headers=tutor["headers"],
    )
    gone = await client.delete(
        f"/api/v1/subjects/{subject_id}/teaching-guidance", headers=tutor["headers"]
    )
    assert gone.status_code == 200
    assert gone.json()["uploaded"] is False

    async with async_session() as session:
        subject = await session.get(Subject, subject_id)
    assert subject.guidance_path is None
    assert subject.guidance_name is None
    assert subject.guidance_mime is None
    assert subject.guidance_uploaded_at is None

    # Deleting nothing is the state the caller asked for, not an error.
    again = await client.delete(
        f"/api/v1/subjects/{subject_id}/teaching-guidance", headers=tutor["headers"]
    )
    assert again.status_code == 200

    missing = await client.get(
        f"/api/v1/subjects/{subject_id}/teaching-guidance/file", headers=tutor["headers"]
    )
    assert missing.status_code == 404


async def test_a_file_that_is_not_what_it_claims_is_refused(client, tutor, subject_id):
    """SEC-15: uploads are validated by magic bytes, never the client's
    Content-Type."""
    resp = await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files={"file": ("scheme.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 415


async def test_another_organizations_subject_is_404_not_403(client, tutor):
    """QA-12: ids are enumerable, so "not yours" and "does not exist" must look
    identical (API-7, SEC-9)."""
    async with async_session() as session:
        foreign = await other_org_subject(session, code="9ZZ9")
        await session.commit()
        foreign_id = foreign.id

    for call in (
        client.get(f"/api/v1/subjects/{foreign_id}/teaching-guidance", headers=tutor["headers"]),
        client.put(
            f"/api/v1/subjects/{foreign_id}/teaching-guidance",
            files=upload_files(),
            headers=tutor["headers"],
        ),
        client.get(
            f"/api/v1/subjects/{foreign_id}/teaching-guidance/file", headers=tutor["headers"]
        ),
        client.delete(f"/api/v1/subjects/{foreign_id}/teaching-guidance", headers=tutor["headers"]),
    ):
        resp = await call
        assert resp.status_code == 404, resp.text

    async with async_session() as session:
        assert (await session.get(Subject, foreign_id)).guidance_path is None


async def test_a_student_cannot_reach_any_of_it(client, tutor, subject_id):
    """AV-95: a scheme of work tells a student what is coming and in what order.
    Tutor material, gated in the signature (SEC-11, BE-17)."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files=upload_files(),
        headers=tutor["headers"],
    )
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "Chem", "subject_id": subject_id},
            headers=tutor["headers"],
        )
    ).json()
    invite = await client.post(f"/api/v1/groups/{group['id']}/invites", headers=tutor["headers"])
    reg = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara-guidance@example.com",
            "password": "password123",
        },
    )
    headers = {"Authorization": f"Bearer {reg.json()['tokens']['access_token']}"}

    # Enrolled in the subject, and still refused — this is not about visibility.
    for path in ("", "/file"):
        resp = await client.get(
            f"/api/v1/subjects/{subject_id}/teaching-guidance{path}", headers=headers
        )
        assert resp.status_code == 403, path

    anonymous = await client.get(f"/api/v1/subjects/{subject_id}/teaching-guidance")
    assert anonymous.status_code == 401


async def test_the_document_does_not_leak_through_the_subject_list(client, tutor, subject_id):
    """The list every role reads must not start carrying tutor material."""
    await client.put(
        f"/api/v1/subjects/{subject_id}/teaching-guidance",
        files=upload_files(),
        headers=tutor["headers"],
    )
    listed = (await client.get("/api/v1/subjects", headers=tutor["headers"])).json()
    assert listed
    assert all("guidance_path" not in s for s in listed)


async def test_guidance_is_scoped_to_its_own_subject(client, tutor):
    """Two subjects in one organization each keep their own document."""
    async with async_session() as session:
        chem = await make_subject(session, code="4CH1", name="Chemistry")
        bio = await make_subject(session, code="4BI1", name="Biology")
        await session.commit()
        chem_id, bio_id = chem.id, bio.id

    await client.put(
        f"/api/v1/subjects/{chem_id}/teaching-guidance",
        files=upload_files(PDF, "chem.pdf"),
        headers=tutor["headers"],
    )
    await client.put(
        f"/api/v1/subjects/{bio_id}/teaching-guidance",
        files=upload_files(PDF2, "bio.pdf"),
        headers=tutor["headers"],
    )

    async with async_session() as session:
        rows = {
            s.id: s.guidance_name
            for s in (
                await session.scalars(select(Subject).where(Subject.id.in_([chem_id, bio_id])))
            ).all()
        }
    assert rows == {chem_id: "chem.pdf", bio_id: "bio.pdf"}
