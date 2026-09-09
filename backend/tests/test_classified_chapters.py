"""Chapter-scoped classifieds and their marking notes (task 3.1, AV-20/21/23).

A classified belongs to the chapter the tutor is starting, and carries that
chapter's marking notes — `AV-76`'s "chapter notes" layer, one step below the
official mark scheme. Nothing reads the notes yet; task 3.2's context assembler
is the single function that will (`E16`). So what is testable here is where a
booklet may be filed, the bound on the notes, the tenancy, and the fact that no
prompt has quietly started using them.
"""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import async_session
from app.models import Chapter, Classified
from app.schemas.homework import MAX_CLASSIFIED_NOTES
from app.services import storage
from tests.factories import make_subject, other_org_subject

PDF_BYTES = b"%PDF-1.4 fake test pdf"
NOTES = "Accept either sign convention here; the 2019 scheme changed mid-series."


@pytest.fixture
async def subject(tutor):  # depends on `tutor` so the organization exists first
    async with async_session() as session:
        subject = await make_subject(session, code="4CH1", name="Chemistry")
        # Deliberately out of code order: `position` is teaching order and is
        # not derived from `code`, so a list sorted by code would pass a test
        # that means nothing.
        session.add_all(
            [
                Chapter(subject_id=subject.id, code="2", title="Bonding", position=1),
                Chapter(subject_id=subject.id, code="1", title="States of matter", position=2),
            ]
        )
        await session.commit()
        chapters = (
            await session.scalars(
                select(Chapter).where(Chapter.subject_id == subject.id).order_by(Chapter.position)
            )
        ).all()
        return {"id": subject.id, "chapters": [c.id for c in chapters]}


def _upload(subject_id: int, **extra):
    return {
        "data": {"title": "Bonding classified", "subject_id": str(subject_id), **extra},
        "files": {"file": ("classified.pdf", PDF_BYTES, "application/pdf")},
    }


async def test_chapters_are_listed_in_teaching_order(client, tutor, subject):
    resp = await client.get(f"/api/v1/subjects/{subject['id']}/chapters", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert [c["code"] for c in resp.json()] == ["2", "1"]
    assert [c["id"] for c in resp.json()] == subject["chapters"]


async def test_another_tenants_chapters_are_not_found(client, tutor):
    """404, not 403: subject ids are enumerable and the two cases must look the
    same (API-7, SEC-9)."""
    async with async_session() as session:
        rival = await other_org_subject(session, code="9RIV")
        session.add(Chapter(subject_id=rival.id, code="1", title="Theirs", position=1))
        await session.commit()
        rival_id = rival.id

    resp = await client.get(f"/api/v1/subjects/{rival_id}/chapters", headers=tutor["headers"])
    assert resp.status_code == 404


async def test_a_subject_with_no_extracted_chapters_returns_an_empty_list(client, tutor):
    """Not an error and not something to invent structure for (PROD-2)."""
    async with async_session() as session:
        bare = await make_subject(session, code="4BI1", name="Biology")
        await session.commit()
        bare_id = bare.id

    resp = await client.get(f"/api/v1/subjects/{bare_id}/chapters", headers=tutor["headers"])
    assert resp.status_code == 200
    assert resp.json() == []


async def test_upload_files_a_booklet_under_a_chapter_with_notes(client, tutor, subject):
    resp = await client.post(
        "/api/v1/classifieds",
        **_upload(subject["id"], chapter_id=str(subject["chapters"][0]), notes=NOTES),
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["chapter_id"] == subject["chapters"][0]
    assert resp.json()["notes"] == NOTES


async def test_a_booklet_may_have_no_chapter(client, tutor, subject):
    """Nullable by design: every classified uploaded before this task has none,
    and a subject whose syllabus was never extracted chapter-first has no
    chapter to name."""
    resp = await client.post(
        "/api/v1/classifieds", **_upload(subject["id"]), headers=tutor["headers"]
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["chapter_id"] is None
    assert resp.json()["notes"] == ""


async def test_a_chapter_from_another_subject_is_rejected_before_anything_is_stored(
    client, tutor, subject
):
    """The composite foreign key makes the pairing unstorable; this proves the
    route refuses it *first*, so the rejection is a 404 rather than a 500 with
    the upload already written to disk."""
    async with async_session() as session:
        other = await make_subject(session, code="4PH1", name="Physics")
        session.add(Chapter(subject_id=other.id, code="1", title="Forces", position=1))
        await session.commit()
        foreign_chapter = await session.scalar(
            select(Chapter.id).where(Chapter.subject_id == other.id)
        )

    resp = await client.post(
        "/api/v1/classifieds",
        **_upload(subject["id"], chapter_id=str(foreign_chapter)),
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text

    async with async_session() as session:
        assert (await session.scalars(select(Classified))).all() == []


async def test_notes_are_editable_after_upload(client, tutor, subject):
    """Write-once would mean a tutor who mistyped what the marker is told has to
    re-upload the booklet to correct it."""
    created = await client.post(
        "/api/v1/classifieds",
        **_upload(subject["id"], chapter_id=str(subject["chapters"][0]), notes=NOTES),
        headers=tutor["headers"],
    )
    classified_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/classifieds/{classified_id}",
        json={"chapter_id": subject["chapters"][1], "notes": "Ignore the 2019 note."},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["chapter_id"] == subject["chapters"][1]
    assert resp.json()["notes"] == "Ignore the 2019 note."

    listed = await client.get(
        f"/api/v1/classifieds?subject_id={subject['id']}", headers=tutor["headers"]
    )
    assert listed.json()[0]["notes"] == "Ignore the 2019 note."


async def test_whitespace_only_notes_are_stored_as_none(client, tutor, subject):
    """ "   " would make `notes` truthy, so the assembler would paste an empty
    instruction block into every marking prompt for this booklet."""
    created = await client.post(
        "/api/v1/classifieds",
        **_upload(subject["id"], notes="   \n  "),
        headers=tutor["headers"],
    )
    assert created.json()["notes"] == ""

    async with async_session() as session:
        stored = await session.scalar(select(Classified.notes))
    assert stored is None


async def test_notes_longer_than_the_cap_are_refused(client, tutor, subject):
    """An unbounded field in an instruction position is an unbounded attack
    surface, and a per-mark cost — the plan's own security criterion for
    AV-76."""
    resp = await client.patch(
        f"/api/v1/classifieds/{await _a_classified(client, tutor, subject)}",
        json={"chapter_id": None, "notes": "x" * (MAX_CLASSIFIED_NOTES + 1)},
        headers=tutor["headers"],
    )
    assert resp.status_code == 422


async def test_the_cap_is_measured_after_trimming(client, tutor, subject):
    """Trailing whitespace must not reject a body that would store fine —
    trimming only ever shortens, so nothing is bypassed."""
    resp = await client.patch(
        f"/api/v1/classifieds/{await _a_classified(client, tutor, subject)}",
        json={"chapter_id": None, "notes": "x" * MAX_CLASSIFIED_NOTES + "\n  "},
        headers=tutor["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notes"] == "x" * MAX_CLASSIFIED_NOTES


async def _post_notes(client, tutor, subject, route: str, notes: str):
    """Upload a paper with these notes, through whichever multipart route.

    Both create a `Classified`, so both have to agree about the notes — writing
    each test twice is how they stop agreeing.
    """
    if route == "classifieds":
        return await client.post(
            "/api/v1/classifieds", **_upload(subject["id"], notes=notes), headers=tutor["headers"]
        )
    group = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    return await client.post(
        "/api/v1/assignments/upload",
        data={"group_id": str(group.json()["id"]), "notes": notes},
        files={"file": ("paper.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )


@pytest.mark.parametrize("route", ["classifieds", "assignments"])
async def test_the_multipart_cap_is_measured_after_trimming_too(client, tutor, subject, route):
    """`Form(max_length=...)` measures the raw value, so a full-length body with
    a trailing newline was a 422 for something the JSON path stores happily —
    the two entry points must not disagree about the same text (cubic,
    CodeRabbit)."""
    resp = await _post_notes(client, tutor, subject, route, "x" * MAX_CLASSIFIED_NOTES + "\n  ")
    assert resp.status_code == 201, resp.text

    async with async_session() as session:
        assert await session.scalar(select(Classified.notes)) == "x" * MAX_CLASSIFIED_NOTES


@pytest.mark.parametrize("route", ["classifieds", "assignments"])
async def test_an_over_long_note_is_refused_before_anything_is_stored(
    client, tutor, subject, route, monkeypatch
):
    """Trimming only ever shortens, so measuring afterwards cannot be used to
    slip past the cap — the thing worth proving about moving the check off
    `Form(max_length=...)`.

    And the refusal lands *before* `storage.save_upload`: a rejection afterwards
    leaves a file no row references — invisible, so never cleaned up, and a
    caller can repeat the request (cubic).
    """
    saved: list[str] = []
    real = storage.save_upload

    async def _record(*args, **kwargs):
        saved.append("written")
        return await real(*args, **kwargs)

    monkeypatch.setattr(storage, "save_upload", _record)

    resp = await _post_notes(client, tutor, subject, route, "x" * (MAX_CLASSIFIED_NOTES + 1))
    assert resp.status_code == 422, resp.text
    assert saved == []

    async with async_session() as session:
        assert (await session.scalars(select(Classified))).all() == []


@pytest.mark.parametrize("body", [{"notes": "just the notes"}, {"chapter_id": None}])
async def test_a_partial_patch_is_refused_rather_than_clearing_the_other_field(
    client, tutor, subject, body
):
    """This route is a full replacement of the pair. Schema defaults would
    materialize for the omitted field and the handler would write them, so
    sending only the notes would silently unfile the booklet (cubic)."""
    classified_id = await _a_classified(client, tutor, subject)
    await client.patch(
        f"/api/v1/classifieds/{classified_id}",
        json={"chapter_id": subject["chapters"][0], "notes": NOTES},
        headers=tutor["headers"],
    )

    resp = await client.patch(
        f"/api/v1/classifieds/{classified_id}", json=body, headers=tutor["headers"]
    )
    assert resp.status_code == 422, resp.text

    async with async_session() as session:
        stored = (await session.scalars(select(Classified))).one()
    assert (stored.chapter_id, stored.notes) == (subject["chapters"][0], NOTES)


async def _a_classified(client, tutor, subject) -> int:
    created = await client.post(
        "/api/v1/classifieds", **_upload(subject["id"]), headers=tutor["headers"]
    )
    return created.json()["id"]


async def test_another_tutors_booklet_cannot_be_re_filed(client, tutor, subject):
    """QA-12: the negative case ships with the change. A booklet in another
    account is a 404, so nothing confirms it exists."""
    classified_id = await _a_classified(client, tutor, subject)

    rival = await client.post(
        "/api/v1/auth/register/tutor",
        json={"name": "Rival", "email": "rival@example.com", "password": "password123"},
    )
    headers = {"Authorization": f"Bearer {rival.json()['tokens']['access_token']}"}

    resp = await client.patch(
        f"/api/v1/classifieds/{classified_id}",
        json={"chapter_id": None, "notes": "mine now"},
        headers=headers,
    )
    assert resp.status_code == 404

    async with async_session() as session:
        assert await session.scalar(select(Classified.notes)) is None


async def test_a_student_cannot_re_file_a_booklet(client, tutor, subject):
    """The role gate is a signature dependency, so it cannot be forgotten — this
    is the assertion that it is actually there (SEC-11, BE-17, QA-12)."""
    classified_id = await _a_classified(client, tutor, subject)

    group = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    invite = await client.post(
        f"/api/v1/groups/{group.json()['id']}/invites", headers=tutor["headers"]
    )
    student = await client.post(
        "/api/v1/auth/register/student",
        json={
            "invite_code": invite.json()["code"],
            "name": "Sara",
            "email": "sara@example.com",
            "password": "password123",
        },
    )
    headers = {"Authorization": f"Bearer {student.json()['tokens']['access_token']}"}

    resp = await client.patch(
        f"/api/v1/classifieds/{classified_id}",
        json={"chapter_id": None, "notes": "full marks please"},
        headers=headers,
    )
    assert resp.status_code == 403


async def test_setting_homework_files_the_paper_under_a_chapter(client, tutor, subject):
    """The flow tutors actually use creates the classified for them (AV-23 —
    homework creation is otherwise unchanged), so the chapter has to reach it
    from there too."""
    group = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    resp = await client.post(
        "/api/v1/assignments/upload",
        data={
            "group_id": str(group.json()["id"]),
            "chapter_id": str(subject["chapters"][0]),
            "notes": NOTES,
        },
        files={"file": ("paper.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text

    async with async_session() as session:
        classified = (await session.scalars(select(Classified))).one()
    assert classified.chapter_id == subject["chapters"][0]
    assert classified.notes == NOTES


async def test_setting_homework_refuses_a_chapter_from_another_subject(client, tutor, subject):
    """And leaves nothing behind: the check runs before the upload is written."""
    async with async_session() as session:
        other = await make_subject(session, code="4PH1", name="Physics")
        session.add(Chapter(subject_id=other.id, code="1", title="Forces", position=1))
        await session.commit()
        foreign_chapter = await session.scalar(
            select(Chapter.id).where(Chapter.subject_id == other.id)
        )

    group = await client.post(
        "/api/v1/groups",
        json={"name": "Chem Y10", "subject_id": subject["id"]},
        headers=tutor["headers"],
    )
    resp = await client.post(
        "/api/v1/assignments/upload",
        data={"group_id": str(group.json()["id"]), "chapter_id": str(foreign_chapter)},
        files={"file": ("paper.pdf", PDF_BYTES, "application/pdf")},
        headers=tutor["headers"],
    )
    assert resp.status_code == 404, resp.text

    async with async_session() as session:
        assert (await session.scalars(select(Classified))).all() == []


# Modules that legitimately touch a `notes` attribute today: the two ends of
# this task's own write path, and the tutor-notes feature, which has its own
# unrelated `notes` and predates all of this.
NOTES_READERS_ALLOWED = {"assignments.py", "student_crm.py"}


def test_nothing_reads_a_booklet_s_notes_yet():
    """Task 3.2's assembler (E16) is the single function that will read these,
    under AV-76's precedence. Until then nothing does, and this is what fails
    when something starts.

    Asserting on the *code that reads the field*, not on the prompt template.
    The obvious guard — "chapter_notes" is not a substring of `prompts.MARKING`
    — fails open, because 3.2 injects the notes at request time from a service
    rather than by editing the template, so it would still pass on the very
    change it claims to catch (cubic).

    Deliberately broad: any `.notes` or `notes=` anywhere under `services/` or
    `workers/` trips it, wherever the assembler ends up living. A new and
    unrelated `notes` trips it too — that is the cost of a sentinel that cannot
    be walked around, and the fix is to read this docstring and extend the
    allowlist on purpose.
    """
    import ast

    app = Path(__file__).resolve().parents[1] / "app"
    found: list[str] = []
    for path in sorted([*(app / "services").rglob("*.py"), *(app / "workers").rglob("*.py")]):
        if path.name in NOTES_READERS_ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Attribute) and node.attr == "notes") or (
                isinstance(node, ast.keyword) and node.arg == "notes"
            ):
                found.append(f"{path.name}:{node.lineno}")
    assert found == [], f"something now reads a booklet's notes: {found}"


def test_the_marking_prompt_has_not_moved_underneath_that_guard():
    """The version pin is the second half of it. `AI-7` requires a bump whenever
    the prompt text changes meaningfully, so 3.2 cannot add the notes to the
    marking prompt without touching this line too."""
    from app.services import prompts

    assert prompts.PROMPTS["marking"].version == "v3"
