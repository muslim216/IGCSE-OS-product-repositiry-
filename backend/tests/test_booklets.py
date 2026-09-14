"""Task 3.5 (AV-117): a booklet is one upload holding several whole papers.

The AI reads the list of papers inside it, the tutor corrects that list, and
approving it cuts the document into real past papers. Nothing here tests the
extraction prompt itself — `test_booklet_extraction.py` owns that.
"""

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from sqlalchemy import delete, select

from app.db import async_session
from app.models import Booklet, BookletStatus, Job, PastPaper
from app.services import storage
from app.workers.jobs import process_one_job
from tests.factories import other_org_subject

#: Pages are told apart by width, not by text: a wrong slice then fails loudly
#: instead of passing because the page *count* happened to be right.
WIDTH_STEP = 10


def _pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for n in range(pages):
        writer.add_blank_page(width=100 + WIDTH_STEP * n, height=200)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _widths(data: bytes) -> list[float]:
    return [round(float(page.mediabox.width)) for page in PdfReader(BytesIO(data)).pages]


def _draft(*ranges: tuple[int, int]) -> dict:
    return {
        "papers": [
            {
                "title": f"Paper {i} of the booklet",
                "session_label": "November 2026",
                "paper_number": f"Paper {i}",
                "first_page": first,
                "last_page": last,
            }
            for i, (first, last) in enumerate(ranges, start=1)
        ],
        "scheme_papers": None,
        "scheme_mismatch": None,
    }


async def _upload(
    client,
    tutor,
    subject,
    *,
    pages: int = 6,
    mime: str = "application/pdf",
    scheme_pages: int | None = None,
):
    files = [("file", ("booklet.pdf", _pdf(pages), mime))]
    if scheme_pages is not None:
        files.append(("mark_scheme", ("scheme.pdf", _pdf(scheme_pages), "application/pdf")))
    return await client.post(
        "/api/v1/booklets",
        data={"subject_id": str(subject["id"])},
        files=files,
        headers=tutor["headers"],
    )


async def _reviewed(client, tutor, subject, *ranges: tuple[int, int]) -> int:
    """A booklet sitting in review with a draft the tutor has approved of."""
    resp = await _upload(client, tutor, subject)
    assert resp.status_code == 201, resp.text
    booklet_id = resp.json()["id"]
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        booklet.draft = _draft(*ranges)
        booklet.status = BookletStatus.review
        # The upload queued the AI read; these tests put the draft in by hand
        # instead, so that job is dropped rather than left for the next
        # `process_one_job()` to pick up ahead of the split.
        await session.execute(delete(Job))
        await session.commit()
    return booklet_id


async def test_a_booklet_uploads_and_waits_for_the_ai_to_read_it(client, tutor, subject):  # noqa: F811
    resp = await _upload(client, tutor, subject)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "extracting"
    # Nothing is real yet — the papers exist only once the tutor approves.
    assert body["paper_count"] == 0
    assert body["display_title"] == "Untitled booklet"


async def test_a_booklet_that_is_not_a_pdf_is_refused_at_the_door(client, tutor, subject):  # noqa: F811
    """A photo cannot be cut into papers. Refusing on upload beats accepting it
    and failing at approval, after the tutor has done the review."""
    resp = await client.post(
        "/api/v1/booklets",
        data={"subject_id": str(subject["id"])},
        files=[("file", ("paper.png", b"\x89PNG\r\n\x1a\n fake", "image/png"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 415
    assert "single paper" in resp.json()["detail"]


async def test_the_tutor_can_rewrite_the_ai_list_completely(client, tutor, subject):  # noqa: F811
    """`PROD-7` — final authority. Adding a paper the AI missed and renaming
    another are both ordinary edits, not special cases."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    draft = _draft((1, 2), (3, 6))
    draft["papers"][0]["title"] = "The one the tutor renamed"
    resp = await client.put(
        f"/api/v1/booklets/{booklet_id}/draft", json=draft, headers=tutor["headers"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "review"
    assert [p["title"] for p in body["draft"]["papers"]] == [
        "The one the tutor renamed",
        "Paper 2 of the booklet",
    ]


async def test_two_papers_cannot_claim_the_same_page(client, tutor, subject):  # noqa: F811
    """Overlapping ranges mean one is wrong, and cutting them would hand a
    student a paper holding half of someone else's."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    resp = await client.put(
        f"/api/v1/booklets/{booklet_id}/draft",
        json=_draft((1, 4), (3, 6)),
        headers=tutor["headers"],
    )
    assert resp.status_code == 422
    assert "overlaps" in resp.text


async def test_approving_cuts_the_booklet_into_its_papers(client, tutor, subject):  # noqa: F811
    """The heart of the feature: one document in, N self-contained papers out,
    each holding exactly the pages the tutor approved."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 2), (3, 6))
    resp = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    # The cutting is a job, so the papers are not there yet — saying otherwise
    # would be a screen that lies for as long as the split takes.
    assert resp.json()["status"] == "applying"

    assert await process_one_job() is True  # split_booklet

    async with async_session() as session:
        papers = (
            await session.scalars(
                select(PastPaper)
                .where(PastPaper.booklet_id == booklet_id)
                .order_by(PastPaper.booklet_index)
            )
        ).all()
        assert [p.booklet_index for p in papers] == [1, 2]
        assert [(p.first_page, p.last_page) for p in papers] == [(1, 2), (3, 6)]
        # Named from the list the tutor reviewed, not guessed again later.
        assert papers[0].title == "Paper 1 of the booklet"
        assert papers[0].paper_number == "Paper 1"
        # Each paper holds its own pages and nobody else's.
        from app.services import storage

        assert _widths(await storage.read_file(papers[0].paper_path)) == [100, 110]
        assert _widths(await storage.read_file(papers[1].paper_path)) == [120, 130, 140, 150]
        booklet = await session.get(Booklet, booklet_id)
        assert booklet.status is BookletStatus.applied


async def test_a_half_finished_split_finishes_on_its_second_run(client, tutor, subject):  # noqa: F811
    """`BE-6`. A worker that dies mid-split is handed the same payload again;
    it must finish the job rather than duplicate the papers it already cut."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 2), (3, 6))
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200

    # Stand in for the death: the first paper already exists, the booklet is
    # still `applying`, and the job has not run.
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        session.add(
            PastPaper(
                organization_id=booklet.organization_id,
                booklet_id=booklet.id,
                booklet_index=1,
                subject_id=booklet.subject_id,
                title="Already cut",
            )
        )
        await session.commit()

    assert await process_one_job() is True

    async with async_session() as session:
        papers = (
            await session.scalars(
                select(PastPaper)
                .where(PastPaper.booklet_id == booklet_id)
                .order_by(PastPaper.booklet_index)
            )
        ).all()
        assert [p.booklet_index for p in papers] == [1, 2]
        # The half-created one is left exactly as it was, not cut a second time.
        assert papers[0].title == "Already cut"


async def test_an_approved_booklet_cannot_be_edited_or_approved_again(client, tutor, subject):  # noqa: F811
    booklet_id = await _reviewed(client, tutor, subject, (1, 6))
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    again = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert again.status_code == 409
    edit = await client.put(
        f"/api/v1/booklets/{booklet_id}/draft", json=_draft((1, 3)), headers=tutor["headers"]
    )
    assert edit.status_code == 409


async def test_a_student_sees_the_booklet_only_once_its_papers_exist(
    client,
    tutor,
    subject,
    student,  # noqa: F811
):
    """The owner's decision: students see the booklet, not just a flat list of
    papers. But not while the tutor is still correcting the list."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    listed = await client.get("/api/v1/booklets", headers=student["headers"])
    assert listed.status_code == 200
    assert listed.json() == []
    # `404`, not `403` — an id is enumerable and must not confirm a booklet
    # exists (`API-7`).
    assert (
        await client.get(f"/api/v1/booklets/{booklet_id}", headers=student["headers"])
    ).status_code == 404

    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    assert await process_one_job() is True

    listed = await client.get("/api/v1/booklets", headers=student["headers"])
    assert [b["id"] for b in listed.json()] == [booklet_id]
    # And never the mark scheme, nor whether one exists.
    assert listed.json()[0]["mark_scheme_name"] is None
    detail = await client.get(f"/api/v1/booklets/{booklet_id}", headers=student["headers"])
    assert detail.json()["draft"] is None
    assert (
        await client.get(f"/api/v1/booklets/{booklet_id}/mark-scheme", headers=student["headers"])
    ).status_code == 403


async def test_another_tenants_booklet_is_invisible(client, tutor, subject):  # noqa: F811
    """`SEC-8`/`PROD-4` — subjects are global, so scoping on subject alone would
    show one tutor's booklets to another's students."""
    async with async_session() as session:
        foreign = await other_org_subject(session)
        booklet = Booklet(
            organization_id=foreign.organization_id,
            subject_id=foreign.id,
            status=BookletStatus.applied,
        )
        session.add(booklet)
        await session.commit()
        foreign_id = booklet.id

    assert (await client.get("/api/v1/booklets", headers=tutor["headers"])).json() == []
    assert (
        await client.get(f"/api/v1/booklets/{foreign_id}", headers=tutor["headers"])
    ).status_code == 404


async def test_a_hidden_paper_leaves_the_tutors_shelf_and_stays_with_students(
    client,
    tutor,
    subject,
    student,  # noqa: F811
):
    """The owner's decision, and the reason this is a flag rather than a delete:
    a student mid-attempt must not watch the paper vanish."""
    upload = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(subject["id"])},
        files=[("paper", ("paper.pdf", _pdf(1), "application/pdf"))],
        headers=tutor["headers"],
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["id"]

    resp = await client.delete(f"/api/v1/past-papers/{paper_id}", headers=tutor["headers"])
    assert resp.status_code == 204

    tutor_list = await client.get("/api/v1/past-papers", headers=tutor["headers"])
    assert [p["id"] for p in tutor_list.json()] == []

    student_list = await client.get("/api/v1/past-papers", headers=student["headers"])
    assert [p["id"] for p in student_list.json()] == [paper_id]
    # And still openable, not just listed.
    assert (
        await client.get(f"/api/v1/past-papers/{paper_id}", headers=student["headers"])
    ).status_code == 200


async def test_hiding_twice_keeps_the_first_answer(client, tutor, subject):  # noqa: F811
    """ "When did this leave my shelf" has one answer."""
    resp = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(subject["id"]), "duration_minutes": "90"},
        files=[("paper", ("paper.pdf", _pdf(1), "application/pdf"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    paper_id = resp.json()["id"]

    assert (
        await client.delete(f"/api/v1/past-papers/{paper_id}", headers=tutor["headers"])
    ).status_code == 204
    async with async_session() as session:
        first = (await session.get(PastPaper, paper_id)).hidden_at
    assert (
        await client.delete(f"/api/v1/past-papers/{paper_id}", headers=tutor["headers"])
    ).status_code == 204
    async with async_session() as session:
        assert (await session.get(PastPaper, paper_id)).hidden_at == first


async def test_a_student_cannot_hide_a_paper(client, tutor, subject, student):  # noqa: F811
    """`QA-12` — the negative case ships with the change."""
    resp = await client.post(
        "/api/v1/past-papers",
        data={"subject_id": str(subject["id"])},
        files=[("paper", ("paper.pdf", _pdf(1), "application/pdf"))],
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    paper_id = resp.json()["id"]
    assert (
        await client.delete(f"/api/v1/past-papers/{paper_id}", headers=student["headers"])
    ).status_code == 403
    async with async_session() as session:
        assert (await session.get(PastPaper, paper_id)).hidden_at is None


async def test_a_student_cannot_upload_a_booklet(client, subject, student):  # noqa: F811
    resp = await client.post(
        "/api/v1/booklets",
        data={"subject_id": str(subject["id"])},
        files=[("file", ("booklet.pdf", _pdf(2), "application/pdf"))],
        headers=student["headers"],
    )
    assert resp.status_code == 403
    async with async_session() as session:
        assert (await session.scalars(select(Booklet))).all() == []


@pytest.mark.parametrize("status_before", [BookletStatus.review, BookletStatus.applied])
async def test_a_stale_split_job_does_nothing(client, tutor, subject, status_before):  # noqa: F811
    """The job is only ever right for a booklet the tutor just approved. A
    requeued job meeting a booklet the tutor has sent back to review must not
    cut papers against a list nobody approved."""
    from app.services.booklets import split_booklet

    booklet_id = await _reviewed(client, tutor, subject, (1, 2))
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        booklet.status = status_before
        await session.commit()
        await split_booklet(session, {"booklet_id": booklet_id})
        assert (await session.scalars(select(PastPaper))).all() == []


async def test_approving_a_draft_the_tutor_never_saw_is_still_checked(client, tutor, subject):  # noqa: F811
    """The AI writes the draft directly, so `PUT /draft` is not the only way a
    list reaches approval — and an overlapping range from extraction would be
    cut into two papers sharing pages. This is the only place that is caught."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 2))
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        booklet.draft = _draft((1, 4), (3, 6))  # as extraction might write it
        await session.commit()

    resp = await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    assert resp.status_code == 422
    assert "overlaps" in resp.text
    async with async_session() as session:
        assert (await session.get(Booklet, booklet_id)).status is BookletStatus.review
        assert (await session.scalars(select(PastPaper))).all() == []


async def test_the_booklet_file_opens_for_a_tutor_and_for_a_student_who_can_see_it(
    client,
    tutor,
    subject,
    student,  # noqa: F811
):
    """Students read the booklet itself, not only its papers — they can already
    read every paper cut from it, so withholding the parent protects nothing."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 6))
    assert (
        await client.get(f"/api/v1/booklets/{booklet_id}/file", headers=tutor["headers"])
    ).status_code == 200
    # Not while it is still the tutor's working copy, though.
    assert (
        await client.get(f"/api/v1/booklets/{booklet_id}/file", headers=student["headers"])
    ).status_code == 404

    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    assert await process_one_job() is True
    assert (
        await client.get(f"/api/v1/booklets/{booklet_id}/file", headers=student["headers"])
    ).status_code == 200


async def test_a_failed_read_can_be_retried_and_nothing_else_can(client, tutor, subject):  # noqa: F811
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    # Only a failed read is retryable — re-reading a booklet the tutor is
    # already correcting would throw their corrections away.
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/retry", headers=tutor["headers"])
    ).status_code == 409

    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        booklet.status = BookletStatus.extraction_failed
        booklet.error = "The AI could not read this"
        await session.commit()

    resp = await client.post(f"/api/v1/booklets/{booklet_id}/retry", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "extracting"
    assert resp.json()["error"] is None
    async with async_session() as session:
        assert (await session.scalars(select(Job))).all(), "the re-read was never queued"


async def test_the_tutors_shelf_holds_booklets_that_are_not_finished_yet(client, tutor, subject):  # noqa: F811
    """The daily view: a tutor watches a booklet through extraction and review.
    Only students are held back until the papers exist."""
    resp = await _upload(client, tutor, subject)
    assert resp.status_code == 201
    listed = await client.get("/api/v1/booklets", headers=tutor["headers"])
    assert [b["status"] for b in listed.json()] == ["extracting"]


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/file"),
        ("get", "/mark-scheme"),
        ("put", "/draft"),
        ("post", "/retry"),
        ("post", "/approve"),
    ],
)
async def test_no_route_reaches_another_tenants_booklet(client, tutor, subject, method, path):  # noqa: F811
    """`SEC-8`/`API-7` — every route, not just the ones that read it."""
    async with async_session() as session:
        foreign = await other_org_subject(session)
        booklet = Booklet(
            organization_id=foreign.organization_id,
            subject_id=foreign.id,
            status=BookletStatus.review,
            draft=_draft((1, 2)),
            file_path="somewhere/else.pdf",
            file_name="else.pdf",
            file_mime="application/pdf",
            mark_scheme_path="somewhere/scheme.pdf",
            mark_scheme_name="scheme.pdf",
            mark_scheme_mime="application/pdf",
        )
        session.add(booklet)
        await session.commit()
        foreign_id = booklet.id

    call = getattr(client, method)
    kwargs = {"json": _draft((1, 2))} if method == "put" else {}
    resp = await call(f"/api/v1/booklets/{foreign_id}{path}", headers=tutor["headers"], **kwargs)
    # 404, never 403: a tutor must not learn that another tenant's booklet
    # exists.
    assert resp.status_code == 404, resp.text


@pytest.mark.parametrize(
    "method,path",
    [("put", "/draft"), ("post", "/retry"), ("post", "/approve")],
)
async def test_a_student_cannot_drive_a_booklet_through_review(
    client,
    tutor,
    subject,
    student,
    method,
    path,  # noqa: F811
):
    """`QA-12` — the negative case ships with the route."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 3))
    call = getattr(client, method)
    kwargs = {"json": _draft((1, 2))} if method == "put" else {}
    resp = await call(f"/api/v1/booklets/{booklet_id}{path}", headers=student["headers"], **kwargs)
    assert resp.status_code == 403
    async with async_session() as session:
        # Nothing moved, and the list they tried to write is not there.
        booklet = await session.get(Booklet, booklet_id)
        assert booklet.status is BookletStatus.review
        assert len(booklet.draft["papers"]) == 1


async def test_a_failed_cut_leaves_no_orphaned_slices(client, tutor, subject, monkeypatch):  # noqa: F811
    """The paper is stored before its mark scheme is cut, and the scheme's page
    range comes from a second AI pass the tutor never corrected — so the scheme
    cut failing after the paper cut succeeded is the ordinary case. Without
    cleanup it leaves a file nothing points at, once per retry."""
    resp = await _upload(client, tutor, subject, scheme_pages=2)
    assert resp.status_code == 201, resp.text
    booklet_id = resp.json()["id"]
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        draft = _draft((1, 2), (3, 6))
        # The scheme is two pages, and its second entry asks for pages 3-6 of
        # it — the shape an uncorrected second AI pass actually produces. The
        # first paper cuts fine; the second one's scheme does not.
        draft["scheme_papers"] = _draft((1, 1), (3, 6))["papers"]
        booklet.draft = draft
        booklet.status = BookletStatus.review
        await session.execute(delete(Job))
        await session.commit()

    deleted: list[str] = []
    saved: list[str] = []
    real_delete = storage.delete_file
    real_save = storage.save_bytes

    async def _save(*args, **kwargs):
        result = await real_save(*args, **kwargs)
        saved.append(result[0])
        return result

    async def _delete(path, *args, **kwargs):
        deleted.append(path)
        return await real_delete(path, *args, **kwargs)

    monkeypatch.setattr(storage, "save_bytes", _save)
    monkeypatch.setattr(storage, "delete_file", _delete)

    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    # The job runs and fails on the second paper's mark scheme.
    assert await process_one_job() is True

    assert saved, "the test proves nothing if nothing was cut"
    async with async_session() as session:
        # Every slice that reached disk is either pointed at by a paper or was
        # deleted. The first paper's slices are kept on purpose — its row exists
        # and the re-run skips it — so this is not "delete everything", it is
        # "nothing is left that nothing points at".
        kept = set()
        for paper in (
            await session.scalars(select(PastPaper).where(PastPaper.booklet_id == booklet_id))
        ).all():
            kept.update(p for p in (paper.paper_path, paper.mark_scheme_path) if p)
        orphans = set(saved) - kept - set(deleted)
        assert not orphans, f"orphaned slices: {orphans}"
        assert deleted, "the failed paper's slice was never cleaned up"
        booklet = await session.get(Booklet, booklet_id)
        # Its own failure state, not the AI-read one — they recover differently.
        assert booklet.status is BookletStatus.split_failed
        assert booklet.error


async def test_a_failed_cut_is_retried_by_cutting_not_by_reading_again(
    client,
    tutor,
    subject,  # noqa: F811
):
    """Re-reading after a partial cut would overwrite the list the tutor
    approved (`PROD-7`), while the papers already cut keep their old indexes —
    so the entries at those positions would silently never be created."""
    booklet_id = await _reviewed(client, tutor, subject, (1, 2), (3, 6))
    assert (
        await client.post(f"/api/v1/booklets/{booklet_id}/approve", headers=tutor["headers"])
    ).status_code == 200
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        booklet.status = BookletStatus.split_failed
        booklet.error = "disk was full"
        await session.execute(delete(Job))
        await session.commit()

    # The list is settled from here: some papers exist and are keyed by their
    # position in it.
    assert (
        await client.put(
            f"/api/v1/booklets/{booklet_id}/draft",
            json=_draft((1, 3)),
            headers=tutor["headers"],
        )
    ).status_code == 409

    resp = await client.post(f"/api/v1/booklets/{booklet_id}/retry", headers=tutor["headers"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "applying"
    async with async_session() as session:
        queued = (await session.scalars(select(Job))).all()
        assert [j.type for j in queued] == ["split_booklet"]

    # And it finishes the job it was given.
    assert await process_one_job() is True
    async with async_session() as session:
        booklet = await session.get(Booklet, booklet_id)
        assert booklet.status is BookletStatus.applied
        papers = (
            await session.scalars(select(PastPaper).where(PastPaper.booklet_id == booklet_id))
        ).all()
        assert len(papers) == 2
