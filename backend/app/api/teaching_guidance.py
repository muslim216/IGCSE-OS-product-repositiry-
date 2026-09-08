"""The teaching guidance / scheme of work a tutor keeps per subject.

The **second** per-subject setup document (`AV-10`), beside the syllabus itself,
and step 4 of onboarding. Phase 6 reads it to judge which chapters are harder or
slower and weights the plan's time accordingly (`AV-14`) — this task stores and
serves it, and deliberately does not parse it: nothing yet consumes what a model
would extract, and an extraction nothing reads is a prompt to maintain for free.

**Tutor material, not student-visible** (`AV-95`): a scheme of work tells a
student what is coming and in what order. Every route here is tutor-gated in the
signature (`SEC-11`, `BE-17`) and resolves the subject through `owned_subject`,
which is a 404 rather than a 403 for another organization's id (`API-7`,
`SEC-9`).

One document per subject: uploading again replaces what is there.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status

from app.api.deps import DbSession, TutorUser, owned_subject
from app.api.file_responses import signed_or_proxied_file
from app.models import Subject
from app.schemas.teaching_guidance import TeachingGuidanceOut
from app.services import storage

log = logging.getLogger("api")

router = APIRouter(prefix="/subjects", tags=["teaching-guidance"])


async def _discard(key: str, *, why: str) -> None:
    """Delete a stored object that nothing references, never fatally.

    Both callers below have already decided the request's outcome; a storage
    backend that will not delete must not turn a committed write into a 500 the
    client then retries, nor a rolled-back one into a second error that hides
    the first. The object is unreachable either way — no row points at it — and
    the storage orphan sweep is what collects it. Logged at ERROR because an
    accumulating orphan is an operational fact, not a normal one.
    """
    try:
        await storage.delete_file(key)
    except Exception:  # noqa: BLE001 — cleanup must not decide the response
        log.exception("could not delete orphaned teaching-guidance object (%s): %s", why, key)


def _out(subject: Subject) -> TeachingGuidanceOut:
    return TeachingGuidanceOut(
        subject_id=subject.id,
        subject_name=subject.name,
        uploaded=subject.guidance_path is not None,
        file_name=subject.guidance_name,
        file_mime=subject.guidance_mime,
        uploaded_at=subject.guidance_uploaded_at,
    )


@router.get("/{subject_id}/teaching-guidance", response_model=TeachingGuidanceOut)
async def read_teaching_guidance(
    subject_id: int, db: DbSession, user: TutorUser
) -> TeachingGuidanceOut:
    """What is on file, or that nothing is. Never a 404 for "not uploaded" — the
    subject exists either way, and the surface needs to say which."""
    return _out(await owned_subject(db, subject_id, user))


@router.put("/{subject_id}/teaching-guidance", response_model=TeachingGuidanceOut)
async def upload_teaching_guidance(
    subject_id: int,
    db: DbSession,
    user: TutorUser,
    file: Annotated[UploadFile, File()],
) -> TeachingGuidanceOut:
    """Store (or replace) this subject's guidance document.

    `PUT`, not `POST`: there is one document per subject and uploading again
    replaces it, which is the verb's meaning rather than a second row.

    The old object is deleted **after** the row is committed. The other order
    loses the file if the commit then fails, leaving a subject pointing at a key
    that no longer exists; this order can at worst leave an unreferenced object
    behind, which the storage orphan sweep collects and which nobody can reach
    in the meantime.

    The three failure paths are each handled rather than left to bubble
    (cubic): a commit that fails takes the *new* object with it and leaves the
    old document in force, and neither cleanup delete can turn the outcome into
    a 500 the client would retry against a write that already happened.
    """
    subject = await owned_subject(db, subject_id, user)
    # save_upload validates by magic bytes, caps the source bytes at 20 MB and
    # names the stored object itself (SEC-15, SEC-16, SEC-17).
    path, name, mime = await storage.save_upload(file, organization_id=user.organization_id)
    previous = subject.guidance_path
    subject.guidance_path = path
    # The client's filename is metadata (SEC-16) and unbounded. `safe_filename`
    # strips what would break a Content-Disposition header and caps it at 200,
    # inside the column's 255 — without it a long name fails at commit, after
    # the object is already stored.
    subject.guidance_name = storage.safe_filename(name)
    subject.guidance_mime = mime
    subject.guidance_uploaded_at = datetime.now(UTC)
    try:
        await db.commit()
    except Exception:
        # The rollback is best-effort for the same reason the deletes are: if it
        # raises, that error would replace the commit's — the one worth seeing —
        # and skip the cleanup below, leaving the object orphaned as well
        # (cubic). The session is discarded at the end of the request either
        # way.
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 — the commit error is the one to raise
            log.exception("could not roll back after a failed teaching-guidance commit")
        # The row never changed, so the old document is still in force and it is
        # the *new* object that now references nothing.
        await _discard(path, why="commit failed")
        raise
    if previous and previous != path:
        await _discard(previous, why="replaced")
    return _out(subject)


#: What the download actually returns. Without it FastAPI documents a JSON body
#: for a route that answers with PDF or image bytes, and a generated client is
#: entitled to try decoding it as JSON (CodeRabbit). The set mirrors
#: `storage.ALLOWED_MIMES` plus the fallback the handler uses when a row's mime
#: is missing.
FILE_RESPONSES: dict[int | str, dict] = {
    200: {
        "content": {
            mime: {"schema": {"type": "string", "format": "binary"}}
            for mime in (
                "application/pdf",
                "image/jpeg",
                "image/png",
                "image/webp",
                "application/octet-stream",
            )
        },
        "description": "The stored document.",
    }
}


@router.get(
    "/{subject_id}/teaching-guidance/file",
    response_class=Response,
    responses=FILE_RESPONSES,
)
async def download_teaching_guidance(subject_id: int, db: DbSession, user: TutorUser) -> Response:
    subject = await owned_subject(db, subject_id, user)
    if subject.guidance_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No teaching guidance uploaded")
    # The name and mime are nullable columns, so fall back rather than 500 on a
    # row that does have a file to serve (same reason as classifieds.py).
    return await signed_or_proxied_file(
        subject.guidance_path,
        mime=subject.guidance_mime or "application/octet-stream",
        filename=subject.guidance_name or "teaching-guidance",
    )


@router.delete("/{subject_id}/teaching-guidance", response_model=TeachingGuidanceOut)
async def delete_teaching_guidance(
    subject_id: int, db: DbSession, user: TutorUser
) -> TeachingGuidanceOut:
    """Remove the document. Idempotent: deleting when there is nothing on file
    is the state the caller asked for, not an error."""
    subject = await owned_subject(db, subject_id, user)
    previous = subject.guidance_path
    subject.guidance_path = None
    subject.guidance_name = None
    subject.guidance_mime = None
    subject.guidance_uploaded_at = None
    await db.commit()
    if previous:
        await _discard(previous, why="deleted")
    return _out(subject)
