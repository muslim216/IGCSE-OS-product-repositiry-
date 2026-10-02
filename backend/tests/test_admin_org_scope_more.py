"""The rest of the admin-crosses-tenants bypass (`SEC-7`, `PROD-4`).

`test_admin_org_scope.py` closed it for students, classes and lessons. The same
shape — `user.role == admin` short-circuiting the ownership test with no
organization check — was still open in nine more routers. One negative test per
router here, each a 404 (`API-7`, `SEC-9`), and one same-organization control
proving the admin branch was narrowed rather than removed.
"""

import pytest
from fastapi import HTTPException

from app.api.knowledge import _owned_entry
from app.db import async_session
from app.models import (
    Assignment,
    AssignmentStatus,
    Group,
    GroupResource,
    KnowledgeEntry,
    KnowledgeEntryKind,
    Organization,
    ResourceKind,
    Submission,
    SyllabusUpload,
    User,
    UserRole,
)
from app.security import decode_token, hash_password
from tests.conftest import PDF_BYTES
from tests.factories import make_subject
from tests.test_admin_org_scope import _admin_headers, foreign_admin, home_org_id  # noqa: F401

API = "/api/v1"


@pytest.fixture
async def submission_id(published_assignment, student) -> int:
    async with async_session() as session:
        assignment = await session.get(Assignment, published_assignment["id"])
        submission = Submission(work_id=assignment.work_id, student_id=student["user"]["id"])
        session.add(submission)
        await session.commit()
        return submission.id


@pytest.fixture
async def mock_id(client, tutor, subject, group) -> int:
    resp = await client.post(
        f"{API}/mocks",
        data={"subject_id": str(subject["id"]), "title": "Mock 1", "group_id": str(group["id"])},
        files={"paper": ("mock.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def past_paper_id(client, tutor, subject) -> int:
    resp = await client.post(
        f"{API}/past-papers",
        data={"subject_id": str(subject["id"])},
        files=[("paper", ("paper.pdf", PDF_BYTES, "application/pdf"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def resource_id(client, tutor, group) -> int:
    resp = await client.post(
        f"{API}/groups/{group['id']}/resources",
        data={"kind": "file", "title": "Notes"},
        files={"file": ("notes.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
async def upload_id(tutor) -> int:
    async with async_session() as session:
        upload = SyllabusUpload(
            tutor_id=tutor["user"]["id"],
            title="Chemistry syllabus",
            file_path="x/syllabus.pdf",
            file_name="syllabus.pdf",
            file_mime="application/pdf",
        )
        session.add(upload)
        await session.commit()
        return upload.id


@pytest.fixture
async def entry_id(tutor, home_org_id) -> int:  # noqa: F811
    async with async_session() as session:
        entry = KnowledgeEntry(
            organization_id=home_org_id,
            tutor_id=tutor["user"]["id"],
            kind=KnowledgeEntryKind.note,
            title="House style",
            body="Show working.",
        )
        session.add(entry)
        await session.commit()
        return entry.id


def _admin_user(headers: dict) -> int:
    """The id of the admin these headers authenticate — read from the token, so
    a second admin in the database cannot make it the wrong one."""
    decoded = decode_token(headers["Authorization"].removeprefix("Bearer "), "access")
    assert decoded is not None
    return decoded[0]


# --- one negative per router -------------------------------------------------


async def test_readiness_refuses_another_organizations_student(client, student, foreign_admin):  # noqa: F811
    resp = await client.get(
        f"{API}/readiness/students/{student['user']['id']}", headers=foreign_admin
    )
    assert resp.status_code == 404, resp.text


async def test_a_student_asking_for_another_students_readiness_gets_404(
    client, tutor, group, student
):
    """`API-7`: a 403 would confirm that a student with that id exists."""
    other = await client.post(
        f"{API}/groups/{group['id']}/students",
        json={"name": "Bob", "username": "bob01", "password": "password123"},
        headers=tutor["headers"],
    )
    assert other.status_code == 201, other.text
    resp = await client.get(
        f"{API}/readiness/students/{other.json()['id']}", headers=student["headers"]
    )
    assert resp.status_code == 404, resp.text


async def test_a_parent_or_student_asking_about_someone_elses_child_gets_404(
    client, tutor, group, student
):
    """`API-7` on the two paths that still answered 403: a parent linked to one
    child asking for another's readiness, and a student asking for another
    student's reports."""
    other = await client.post(
        f"{API}/groups/{group['id']}/students",
        json={"name": "Bob", "username": "bob02", "password": "password123"},
        headers=tutor["headers"],
    )
    assert other.status_code == 201, other.text
    other_id = other.json()["id"]
    code = (
        await client.post(
            f"{API}/students/{student['user']['id']}/parent-code", headers=tutor["headers"]
        )
    ).json()["code"]
    parent = await client.post(
        f"{API}/auth/register/parent",
        json={"link_code": code, "name": "P", "email": "p@example.com", "password": "password123"},
    )
    assert parent.status_code == 201, parent.text
    parent_headers = {"Authorization": f"Bearer {parent.json()['tokens']['access_token']}"}

    own = await client.get(
        f"{API}/readiness/students/{student['user']['id']}", headers=parent_headers
    )
    assert own.status_code == 200, own.text
    resp = await client.get(f"{API}/readiness/students/{other_id}", headers=parent_headers)
    assert resp.status_code == 404, resp.text
    resp = await client.get(f"{API}/reports?student_id={other_id}", headers=student["headers"])
    assert resp.status_code == 404, resp.text


async def test_assignments_refuse_another_organizations_admin(
    client,
    group,
    published_assignment,
    foreign_admin,  # noqa: F811
):
    aid, gid = published_assignment["id"], group["id"]
    for path in (f"{API}/assignments/{aid}", f"{API}/assignments/group/{gid}"):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)
    resp = await client.post(
        f"{API}/assignments/upload",
        data={"group_id": str(gid)},
        files={"file": ("hw.pdf", PDF_BYTES, "application/pdf")},
        headers=foreign_admin,
    )
    assert resp.status_code == 404, resp.text


async def test_submissions_refuse_another_organizations_admin(
    client,
    published_assignment,
    submission_id,
    foreign_admin,  # noqa: F811
):
    for path in (
        f"{API}/submissions/{submission_id}",
        f"{API}/assignments/{published_assignment['id']}/submissions",
    ):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)


async def test_mocks_refuse_another_organizations_admin(client, mock_id, foreign_admin):  # noqa: F811
    for path in (f"{API}/mocks/{mock_id}", f"{API}/mocks/{mock_id}/paper"):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)


async def test_past_papers_refuse_another_organizations_admin(client, past_paper_id, foreign_admin):  # noqa: F811
    resp = await client.get(f"{API}/past-papers/{past_paper_id}", headers=foreign_admin)
    assert resp.status_code == 404, resp.text


async def test_classifieds_refuse_another_organizations_admin(client, classified, foreign_admin):  # noqa: F811
    cid = classified["id"]
    for path in (f"{API}/classifieds/{cid}/file", f"{API}/classifieds/{cid}/mark-scheme"):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)
    resp = await client.patch(
        f"{API}/classifieds/{cid}",
        json={"chapter_id": None, "notes": "mine now"},
        headers=foreign_admin,
    )
    assert resp.status_code == 404, resp.text


async def test_knowledge_refuses_another_organizations_admin(entry_id, foreign_admin):  # noqa: F811
    """The router is unmounted (0.5), so the helper is called directly."""
    async with async_session() as session:
        admin = await session.get(User, _admin_user(foreign_admin))
        with pytest.raises(HTTPException) as refused:
            await _owned_entry(session, admin, entry_id)
    assert refused.value.status_code == 404


async def test_syllabus_uploads_refuse_another_organizations_admin(
    client,
    upload_id,
    foreign_admin,  # noqa: F811
):
    resp = await client.get(f"{API}/syllabus-uploads/{upload_id}", headers=foreign_admin)
    assert resp.status_code == 404, resp.text


async def test_resources_refuse_another_organizations_admin(
    client,
    group,
    resource_id,
    foreign_admin,  # noqa: F811
):
    gid = group["id"]
    for path in (f"{API}/groups/{gid}/resources", f"{API}/resources/{resource_id}/file"):
        resp = await client.get(path, headers=foreign_admin)
        assert resp.status_code == 404, (path, resp.text)
    resp = await client.post(
        f"{API}/groups/{gid}/resources",
        data={"kind": "recording", "title": "Planted", "url": "https://example.com/x"},
        headers=foreign_admin,
    )
    assert resp.status_code == 404, resp.text
    resp = await client.delete(f"{API}/resources/{resource_id}", headers=foreign_admin)
    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        assert await session.get(GroupResource, resource_id) is not None


async def test_a_tutor_cannot_delete_their_own_resource_in_another_organizations_group(
    client, tutor
):
    """Being named on the row is not the organization check (`SEC-7`): the
    resource row carries no organization, so its group's binds — for the owner
    too, not only for an admin."""
    async with async_session() as session:
        org = Organization(name="Org B")
        session.add(org)
        await session.flush()
        teacher = User(
            email="teacher-b@example.com",
            password_hash=hash_password("password123"),
            role=UserRole.tutor,
            name="Teacher B",
            organization_id=org.id,
        )
        session.add(teacher)
        subject = await make_subject(session, organization_id=org.id, code="4PH1", name="Physics")
        await session.flush()
        foreign_group = Group(
            organization_id=org.id, tutor_id=teacher.id, subject_id=subject.id, name="Phys"
        )
        session.add(foreign_group)
        await session.flush()
        resource = GroupResource(
            group_id=foreign_group.id,
            tutor_id=tutor["user"]["id"],
            kind=ResourceKind.recording,
            title="Theirs",
            url="https://example.com/x",
        )
        session.add(resource)
        await session.commit()
        resource_id = resource.id

    resp = await client.delete(f"{API}/resources/{resource_id}", headers=tutor["headers"])
    assert resp.status_code == 404, resp.text
    async with async_session() as session:
        assert await session.get(GroupResource, resource_id) is not None


async def test_an_admin_asking_for_a_colleagues_readiness_gets_404(client, tutor, home_org_id):  # noqa: F811
    """The admin's "homed in my organization" fallback is for students in no
    class yet. A tutor's id is in the organization too, and is not a student:
    a 200 with nothing in it would confirm the account exists (`API-7`)."""
    headers = await _admin_headers(home_org_id)
    tutor_id = tutor["user"]["id"]
    for path in (
        f"{API}/readiness/students/{tutor_id}",
        f"{API}/readiness/students/{tutor_id}/trend",
        f"{API}/reports?student_id={tutor_id}",
    ):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 404, (path, resp.text)


# --- list endpoints: only the admin's own organization's rows ----------------


async def test_attention_list_holds_only_the_admins_organization(
    client,
    published_assignment,
    foreign_admin,
    home_org_id,  # noqa: F811
):
    async with async_session() as session:
        assignment = await session.get(Assignment, published_assignment["id"])
        assignment.status = AssignmentStatus.extraction_failed
        await session.commit()

    resp = await client.get(f"{API}/assignments/attention", headers=foreign_admin)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    resp = await client.get(
        f"{API}/assignments/attention", headers=await _admin_headers(home_org_id)
    )
    assert [a["assignment_id"] for a in resp.json()] == [published_assignment["id"]]


async def test_syllabus_upload_list_holds_only_the_admins_organization(
    client,
    upload_id,
    foreign_admin,
    home_org_id,  # noqa: F811
):
    resp = await client.get(f"{API}/syllabus-uploads", headers=foreign_admin)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    resp = await client.get(f"{API}/syllabus-uploads", headers=await _admin_headers(home_org_id))
    assert [u["id"] for u in resp.json()] == [upload_id]


# --- the control -------------------------------------------------------------


async def test_same_organization_admin_keeps_their_reach(
    client,
    student,
    group,
    classified,
    published_assignment,
    submission_id,
    mock_id,
    past_paper_id,
    resource_id,
    upload_id,
    entry_id,
    home_org_id,  # noqa: F811
):
    """Narrowed to the tenant, not removed: none of these rows is the admin's own."""
    headers = await _admin_headers(home_org_id)
    aid, gid, cid = published_assignment["id"], group["id"], classified["id"]
    for path in (
        f"/readiness/students/{student['user']['id']}",
        f"/assignments/{aid}",
        f"/assignments/group/{gid}",
        f"/submissions/{submission_id}",
        f"/assignments/{aid}/submissions",
        f"/mocks/{mock_id}",
        f"/past-papers/{past_paper_id}",
        f"/classifieds/{cid}/file",
        f"/classifieds/{cid}/mark-scheme",
        f"/syllabus-uploads/{upload_id}",
        f"/groups/{gid}/resources",
        f"/resources/{resource_id}/file",
    ):
        resp = await client.get(f"{API}{path}", headers=headers)
        assert resp.status_code == 200, (path, resp.text)

    async with async_session() as session:
        admin = await session.get(User, _admin_user(headers))
        assert (await _owned_entry(session, admin, entry_id)).id == entry_id

    resp = await client.delete(f"{API}/resources/{resource_id}", headers=headers)
    assert resp.status_code == 204, resp.text
