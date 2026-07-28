"""Import Classroom submissions into the existing marking pipeline.

Everything downstream of `enqueue("mark_submission")` is untouched: imported
work becomes an ordinary Submission with SubmissionFile rows and is marked by
the same worker as an in-app upload.
"""

from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Assignment,
    GoogleAccount,
    GoogleCourseLink,
    GoogleCourseworkLink,
    GoogleImportRun,
    GoogleStudentLink,
    GoogleSubmissionImport,
    ImportOutcome,
    ImportRunStatus,
    SubmissionFile,
)
from app.services import google_api, storage
from app.services.google_oauth import GoogleReauthRequired, ensure_access_token
from app.services.submission_intake import SubmissionFinalized, open_submission_for_files
from app.workers.jobs import enqueue

MAX_ATTACHMENTS = 10
TURNED_IN = {"TURNED_IN", "RETURNED"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _download_attachments(
    http: httpx.AsyncClient, token: str, attachments: list[dict]
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Returns (saved files, per-file problems worth telling the tutor about)."""
    saved: list[tuple[str, str, str]] = []
    problems: list[str] = []

    for attachment in attachments[:MAX_ATTACHMENTS]:
        drive_file = attachment.get("driveFile")
        if not drive_file:
            kind = next(iter(attachment), "attachment")
            problems.append(f"{kind} attachments can't be imported")
            continue

        file_id = drive_file.get("id")
        title = drive_file.get("title") or file_id
        try:
            meta = await google_api.drive_metadata(http, token, file_id)
            # A shortcut points at the real file; follow it once.
            if meta.get("mimeType") == google_api.SHORTCUT:
                target = (meta.get("shortcutDetails") or {}).get("targetId")
                if not target:
                    problems.append(f"{title} — shortcut could not be resolved")
                    continue
                meta = await google_api.drive_metadata(http, token, target)
                file_id = meta["id"]

            mime = meta.get("mimeType", "")
            size = int(meta.get("size") or 0)
            if size > storage.MAX_FILE_BYTES:
                problems.append(f"{title} — larger than 20 MB")
                continue
            if mime.startswith("application/vnd.google-apps.") and mime not in google_api.EXPORTABLE:
                problems.append(f"{title} — this kind of Google file can't be imported")
                continue

            data = await google_api.drive_download(http, token, file_id, mime)
            stored_mime = "application/pdf" if mime in google_api.EXPORTABLE else mime
            saved.append(storage.save_bytes(data, stored_mime, meta.get("name") or title))
        except google_api.GoogleApiError as exc:
            problems.append(f"{title} — Google returned {exc.status_code}")
        except HTTPException as exc:
            # storage.save_bytes rejected it (type or size); its detail is
            # already written for a human.
            problems.append(f"{title} — {exc.detail}")

    if len(attachments) > MAX_ATTACHMENTS:
        problems.append(f"only the first {MAX_ATTACHMENTS} attachments were imported")
    return saved, problems


async def import_coursework(session: AsyncSession, payload: dict) -> None:
    run = await session.get(GoogleImportRun, payload["run_id"])
    if run is None:
        return

    link = await session.get(GoogleCourseworkLink, run.coursework_link_id)
    course_link = await session.get(GoogleCourseLink, link.course_link_id)
    account = await session.get(GoogleAccount, course_link.account_id)
    assignment = await session.get(Assignment, link.assignment_id)

    run.status = ImportRunStatus.running
    await session.commit()

    try:
        token = await ensure_access_token(session, account)
    except GoogleReauthRequired:
        run.status = ImportRunStatus.failed
        run.error = "Google access expired — reconnect your Google account and try again."
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        raise

    mapping = {
        row.google_user_id: row.student_id
        for row in (
            await session.scalars(
                select(GoogleStudentLink).where(GoogleStudentLink.account_id == account.id)
            )
        ).all()
    }

    async with httpx.AsyncClient(timeout=30) as http:
        try:
            submissions = await google_api.list_student_submissions(
                http, token, course_link.course_id, link.coursework_id
            )
        except google_api.GoogleApiError as exc:
            run.status = ImportRunStatus.failed
            run.error = f"Could not read Classroom submissions ({exc.status_code})."
            run.finished_at = datetime.now(timezone.utc)
            await session.commit()
            raise

        run.total = len(submissions)
        await session.commit()

        for gc in submissions:
            try:
                await _import_one(session, http, token, run, link, assignment, mapping, gc)
            except Exception as exc:  # one bad submission must not sink the run
                run.failed += 1
                await _record(
                    session, link, gc, ImportOutcome.failed, detail=str(exc) or exc.__class__.__name__
                )
            # Commit per student so a partial import keeps what it managed.
            await session.commit()

    run.status = ImportRunStatus.done
    run.finished_at = datetime.now(timezone.utc)
    await session.commit()


async def _record(
    session: AsyncSession,
    link: GoogleCourseworkLink,
    gc: dict,
    outcome: ImportOutcome,
    *,
    submission_id: int | None = None,
    file_count: int = 0,
    detail: str | None = None,
) -> GoogleSubmissionImport:
    row = await session.scalar(
        select(GoogleSubmissionImport).where(
            GoogleSubmissionImport.coursework_link_id == link.id,
            GoogleSubmissionImport.gc_submission_id == gc["id"],
        )
    )
    if row is None:
        row = GoogleSubmissionImport(
            coursework_link_id=link.id,
            gc_submission_id=gc["id"],
            google_user_id=gc.get("userId", ""),
            outcome=outcome,
        )
        session.add(row)
    row.outcome = outcome
    row.submission_id = submission_id
    row.imported_file_count = file_count
    row.detail = detail
    row.gc_update_time = _parse_time(gc.get("updateTime"))
    await session.flush()
    return row


async def _import_one(
    session: AsyncSession,
    http: httpx.AsyncClient,
    token: str,
    run: GoogleImportRun,
    link: GoogleCourseworkLink,
    assignment: Assignment,
    mapping: dict[str, int],
    gc: dict,
) -> None:
    existing = await session.scalar(
        select(GoogleSubmissionImport).where(
            GoogleSubmissionImport.coursework_link_id == link.id,
            GoogleSubmissionImport.gc_submission_id == gc["id"],
        )
    )
    remote_updated = _parse_time(gc.get("updateTime"))

    # Already imported and unchanged since — nothing to do, and no double count.
    if (
        existing is not None
        and existing.outcome == ImportOutcome.imported
        and existing.gc_update_time is not None
        and remote_updated is not None
        and existing.gc_update_time >= remote_updated
    ):
        return

    if gc.get("state") not in TURNED_IN:
        run.skipped += 1
        await _record(session, link, gc, ImportOutcome.skipped_not_turned_in)
        return

    student_id = mapping.get(gc.get("userId", ""))
    if student_id is None:
        run.skipped += 1
        await _record(
            session,
            link,
            gc,
            ImportOutcome.skipped_unmapped,
            detail="This Classroom student isn't linked to an app account yet.",
        )
        return

    attachments = (gc.get("assignmentSubmission") or {}).get("attachments") or []
    if not attachments:
        run.skipped += 1
        await _record(session, link, gc, ImportOutcome.skipped_no_attachments)
        return

    saved, problems = await _download_attachments(http, token, attachments)
    if not saved:
        run.skipped += 1
        await _record(
            session,
            link,
            gc,
            ImportOutcome.unsupported_files,
            detail="; ".join(problems) or "No importable attachments.",
        )
        return

    try:
        submission = await open_submission_for_files(
            session,
            assignment.id,
            student_id,
            # Use the real Classroom hand-in time, not now().
            submitted_at=remote_updated,
        )
    except SubmissionFinalized:
        run.skipped += 1
        await _record(
            session,
            link,
            gc,
            ImportOutcome.skipped_finalized,
            detail="Already marked and finalized here — left untouched.",
        )
        return

    for position, (path, name, mime) in enumerate(saved):
        session.add(
            SubmissionFile(
                submission_id=submission.id, position=position, path=path, name=name, mime=mime
            )
        )
    await enqueue(session, "mark_submission", {"submission_id": submission.id})

    run.imported += 1
    await _record(
        session,
        link,
        gc,
        ImportOutcome.imported,
        submission_id=submission.id,
        file_count=len(saved),
        detail="; ".join(problems) or None,
    )
