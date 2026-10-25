"""Erasing a child's data (launch audit P-3, part 3 of 3).

A request starts a 14-day undo window: the child at once cannot sign in and drops
out of class lists and messages. When the window ends and nothing cancelled it,
the daily retention sweep wipes the child (`erase_due`). The `users` row stays as
a blank "Deleted student", so rows that must outlive the child keep a valid key.

What is wiped is a list, not a scan (as in `data_export`): `ERASE_ORDER` is the
steps, top to bottom, and `ERASED` / `ANONYMISED` / `KEPT` / `STAFF_ONLY` name
every table that holds a key to a user, with the reason it is where it is.
`tests/test_erasure.py` fails on a table in none of them, which is how the next
one gets noticed. Postgres enforces every foreign key and the test database does
not, so the order is part of the contract; the CI migrations job is the only
place a wrong one is proved, and a test here checks it against the schema.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiUsageEvent,
    AttemptRedo,
    ContactPoint,
    CustomCriterionScoreAudit,
    DataExport,
    ErasureRequest,
    ErasureRequesterRole,
    ErasureRequestStatus,
    Invite,
    Job,
    JobStatus,
    MarkOverrideAudit,
    MeetingParticipant,
    Mistake,
    MistakeTopic,
    Notification,
    NotificationKind,
    ParentLink,
    ParentLinkRemoval,
    QuestionMark,
    RefreshSession,
    RemarkRequest,
    Submission,
    SubmissionFile,
    User,
    UserRole,
    WeeklySend,
)
from app.services import storage
from app.services.data_export import _BY_STUDENT, _KEY, ID_CHUNK

log = logging.getLogger(__name__)

UNDO_WINDOW = timedelta(days=14)

#: Requests wiped per daily pass. A backlog carries on tomorrow rather than
#: holding one job past its time limit (`workers/jobs.py`).
MAX_PER_PASS = 50

PLACEHOLDER_NAME = "Deleted student"
#: Not a bcrypt hash, so `verify_password` (which answers False on ValueError)
#: can never accept anything against it.
UNUSABLE_PASSWORD = "!erased"

NAME_MISMATCH = "The name you typed doesn't match this student's name."


class NameMismatch(Exception):
    """The typed name is not the child's; the router answers 422."""


def names_match(typed: str, actual: str) -> bool:
    return " ".join(typed.casefold().split()) == " ".join(actual.casefold().split())


# --------------------------------------------------------------- the request


async def pending_request(session: AsyncSession, student_id: int) -> ErasureRequest | None:
    return await session.scalar(
        select(ErasureRequest).where(
            ErasureRequest.student_id == student_id,
            ErasureRequest.status == ErasureRequestStatus.pending,
        )
    )


async def request_erasure(
    session: AsyncSession, student: User, requester: User, typed_name: str
) -> ErasureRequest:
    """Schedule the child's deletion, or return the one already waiting.

    The caller has already established that `requester` may act for `student`
    (`SEC-7`). Bumping `token_version` ends every access and refresh token at
    once (`SEC-1`); the child's sign-in is refused separately (`api/auth.py`), so
    an undo that forgot the bump could not let an old token back in."""
    if not names_match(typed_name, student.name):
        raise NameMismatch(NAME_MISMATCH)
    existing = await pending_request(session, student.id)
    if existing is not None:
        return existing
    now = datetime.now(timezone.utc)
    request = ErasureRequest(
        organization_id=student.organization_id,
        student_id=student.id,
        requested_by_id=requester.id,
        requested_role=ErasureRequesterRole(requester.role.value),
        scheduled_for=now + UNDO_WINDOW,
    )
    student.erasure_requested_at = now
    student.token_version += 1
    session.add(request)
    student_id = student.id
    try:
        await session.commit()
    except IntegrityError:
        # Two requests at once: the partial unique index let one through.
        await session.rollback()
        found = await pending_request(session, student_id)
        if found is None:
            raise
        return found
    return request


async def cancel_erasure(session: AsyncSession, student: User) -> bool:
    """Undo a waiting deletion. False when none is waiting.

    The row is locked first, so a cancel and the sweep cannot both win: the sweep
    takes the same lock and re-reads the status. `token_version` is not wound
    back; the child simply signs in again."""
    request = await session.scalar(
        select(ErasureRequest)
        .where(
            ErasureRequest.student_id == student.id,
            ErasureRequest.status == ErasureRequestStatus.pending,
        )
        .with_for_update()
    )
    if request is None:
        return False
    request.status = ErasureRequestStatus.cancelled
    request.cancelled_at = datetime.now(timezone.utc)
    student.erasure_requested_at = None
    await session.commit()
    return True


# --------------------------------------------------------------- the sweep


@dataclass
class Scope:
    """What one erasure is about, read before anything is deleted."""

    session: AsyncSession
    student_id: int
    name: str
    email: str | None
    now: datetime
    parent_ids: list[int] = field(default_factory=list)
    submission_ids: list[int] = field(default_factory=list)
    #: Submissions the child's replaced attempts used to be (kept only inside a
    #: redo record): notifications about them name the child too.
    old_submission_ids: list[int] = field(default_factory=list)
    mark_ids: list[int] = field(default_factory=list)
    mistake_ids: list[int] = field(default_factory=list)


def _chunks(ids: Sequence[int]) -> list[Sequence[int]]:
    return [ids[i : i + ID_CHUNK] for i in range(0, len(ids), ID_CHUNK)] if ids else []


async def _ids(session: AsyncSession, query) -> list[Any]:
    return list((await session.scalars(query)).all())


async def _delete_in(session: AsyncSession, model: type, column: str, ids: Sequence[int]) -> None:
    col = getattr(model, column)
    for chunk in _chunks(ids):
        await session.execute(delete(model).where(col.in_(chunk)))


async def _null_in(
    session: AsyncSession, model: type, column: str, ids: Sequence[int], target: str | None = None
) -> None:
    col = getattr(model, column)
    for chunk in _chunks(ids):
        await session.execute(update(model).where(col.in_(chunk)).values({target or column: None}))


async def storage_keys(scope: Scope) -> list[str]:
    """Every stored file that belongs to the child: their pages, their data
    exports, and the replaced pages kept inside a redo record."""
    session, sid = scope.session, scope.student_id
    keys: list[str] = []
    for chunk in _chunks(scope.submission_ids):
        keys += await _ids(
            session, select(SubmissionFile.path).where(SubmissionFile.submission_id.in_(chunk))
        )
    keys += await _ids(
        session,
        select(DataExport.storage_key).where(
            DataExport.student_id == sid, DataExport.storage_key.is_not(None)
        ),
    )
    for record in (
        await session.scalars(select(AttemptRedo.record).where(AttemptRedo.student_id == sid))
    ).all():
        keys += _keys_in(record)
    return sorted(set(keys))


def _keys_in(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if _KEY.fullmatch(value) else []
    if isinstance(value, dict):
        return [k for v in value.values() for k in _keys_in(v)]
    if isinstance(value, list):
        return [k for v in value for k in _keys_in(v)]
    return []


# Each step below is one numbered item of the order; see ERASE_ORDER.


async def _unlink_audits(scope: Scope) -> None:
    """The tutor's own record of what they decided stays (`PROD-7`); only its
    pointer to the child goes. Nullable for exactly this."""
    s, sid = scope.session, scope.student_id
    await _null_in(s, MarkOverrideAudit, "question_mark_id", scope.mark_ids)
    await s.execute(
        update(CustomCriterionScoreAudit)
        .where(CustomCriterionScoreAudit.student_id == sid)
        .values(student_id=None)
    )
    # The tutor's AI cost record survives (`AI-17`).
    await s.execute(
        update(AiUsageEvent).where(AiUsageEvent.student_id == sid).values(student_id=None)
    )


async def _meeting_rows(scope: Scope) -> None:
    s, sid = scope.session, scope.student_id
    await s.execute(
        update(MeetingParticipant)
        .where(MeetingParticipant.suggested_student_id == sid)
        .values(suggested_student_id=None)
    )
    # The display name and email on these rows are the child's own.
    match = MeetingParticipant.matched_student_id == sid
    if scope.email:
        match = or_(match, func.lower(MeetingParticipant.email) == scope.email.lower())
    await s.execute(delete(MeetingParticipant).where(match))


async def _marks_and_mistakes(scope: Scope) -> None:
    """Mistakes point at question marks, so they go first."""
    s, sid = scope.session, scope.student_id
    for chunk in _chunks(scope.mark_ids):
        await s.execute(delete(RemarkRequest).where(RemarkRequest.question_mark_id.in_(chunk)))
    await s.execute(delete(RemarkRequest).where(RemarkRequest.requested_by_id == sid))
    await _delete_in(s, MistakeTopic, "mistake_id", scope.mistake_ids)
    await s.execute(delete(Mistake).where(Mistake.student_id == sid))


async def _submissions(scope: Scope) -> None:
    s = scope.session
    await _delete_in(s, QuestionMark, "submission_id", scope.submission_ids)
    await _delete_in(s, SubmissionFile, "submission_id", scope.submission_ids)
    await s.execute(delete(Submission).where(Submission.student_id == scope.student_id))


#: Handled by their own steps; every other `_BY_STUDENT` table is deleted by its
#: student column in `_the_rest`.
_OWN_STEP = frozenset({"submissions", "mistakes", "meeting_participants", "ai_usage_events"})
_UNLINKED = frozenset({"custom_criterion_score_audit"})


async def _the_rest(scope: Scope) -> None:
    s, sid = scope.session, scope.student_id
    for model, column in _BY_STUDENT:
        name = model.__tablename__  # type: ignore[attr-defined]
        if name in _OWN_STEP or name in _UNLINKED:
            continue
        await s.execute(delete(model).where(getattr(model, column) == sid))
    # An address the tutor confirmed as the child's own is the child's too.
    await s.execute(
        update(ContactPoint).where(ContactPoint.confirmed_by_id == sid).values(confirmed_by_id=None)
    )


async def _credentials(scope: Scope) -> None:
    s, sid = scope.session, scope.student_id
    await s.execute(
        delete(Invite).where(or_(Invite.student_id == sid, Invite.created_by_id == sid))
    )
    await s.execute(delete(RefreshSession).where(RefreshSession.user_id == sid))
    await s.execute(delete(DataExport).where(DataExport.student_id == sid))


async def _queued_work(scope: Scope) -> None:
    """Jobs still waiting that name the child, or one of their submissions: a
    handler would find nothing, but a readiness or narrative run might write a
    fresh row about the blank placeholder. Payloads are ids only (`BE-9`)."""
    s = scope.session
    mine, theirs = scope.student_id, set(scope.submission_ids) | set(scope.old_submission_ids)
    waiting = (await s.scalars(select(Job).where(Job.status == JobStatus.pending))).all()
    for job in waiting:
        payload = job.payload if isinstance(job.payload, dict) else {}
        if payload.get("student_id") == mine or payload.get("submission_id") in theirs:
            await s.delete(job)


def _is_this_child_key(note: Notification, scope: Scope) -> bool | None:
    """Whether a parent's notification is about this child, by the idempotency key
    it was queued under (`notifications/triggers.py`), or None when the key
    does not say."""
    parts = note.idempotency_key.split(":")
    try:
        if note.kind == NotificationKind.homework_set and parts[0] == "homework_set":
            return int(parts[2]) == scope.student_id
        if note.kind == NotificationKind.marked_work_ready and parts[0] == "marked_work":
            return int(parts[1]) in set(scope.submission_ids) | set(scope.old_submission_ids)
    except (IndexError, ValueError):
        return None
    return None


async def _readers_of_the_child(scope: Scope) -> None:
    """What the child's parents were told about them.

    A notification is attributed by the key it was queued under, which names
    the child or their submission exactly; only one whose key says nothing falls
    back to the child's name in its params. Weekly sends hold one block per
    child, so the child's block and paragraph go and a send left with no child
    is deleted with the notification that points at it."""
    s, name = scope.session, scope.name
    if not scope.parent_ids:
        return
    notes = (
        await s.scalars(
            select(Notification).where(Notification.recipient_user_id.in_(scope.parent_ids))
        )
    ).all()
    for note in notes:
        verdict = _is_this_child_key(note, scope)
        if verdict is None and note.kind in (
            NotificationKind.homework_set,
            NotificationKind.marked_work_ready,
        ):
            verdict = isinstance(note.params, dict) and note.params.get("student_name") == name
        if verdict:
            await s.delete(note)

    sends = (
        await s.scalars(
            select(WeeklySend).where(WeeklySend.recipient_user_id.in_(scope.parent_ids))
        )
    ).all()
    for send in sends:
        facts = dict(send.facts) if isinstance(send.facts, dict) else {}
        children = facts.get("children")
        if not isinstance(children, list):
            continue
        kept = [c for c in children if not _block_is_child(c, scope)]
        if len(kept) == len(children):
            continue
        if not kept:
            await s.execute(
                delete(Notification).where(
                    Notification.recipient_user_id == send.recipient_user_id,
                    Notification.link_path == f"/weekly/{send.id}",
                )
            )
            await s.delete(send)
            continue
        # Reassigned, not edited in place: the JSON column does not see a mutation.
        send.facts = {**facts, "children": kept}
        send.paragraphs = [p for p in send.paragraphs if not _block_is_child(p, scope, "about")]


def _block_is_child(block: object, scope: Scope, name_key: str = "child_name") -> bool:
    """Matched by id; by name only for a block stored before ids existed."""
    if not isinstance(block, dict):
        return False
    if block.get("child_id") is not None:
        return block["child_id"] == scope.student_id
    return block.get(name_key) == scope.name


async def _anonymise_user(scope: Scope) -> None:
    student = await scope.session.get(User, scope.student_id)
    if student is None:
        return
    student.name = PLACEHOLDER_NAME
    student.email = None
    student.username = None
    student.password_hash = UNUSABLE_PASSWORD
    student.time_zone = None
    student.token_version += 1
    student.deleted_at = scope.now


#: The order a child is wiped in, top to bottom; Postgres enforces every foreign
#: key, so a step may only run once nothing later still points at what it deletes.
#: `tests/test_erasure.py` checks this against the schema.
ERASE_ORDER: tuple[Callable[[Scope], Awaitable[None]], ...] = (
    _unlink_audits,
    _meeting_rows,
    _marks_and_mistakes,
    _submissions,
    _the_rest,
    _credentials,
    # Reads the child's name and submissions, so before the users row is blanked.
    _readers_of_the_child,
    _queued_work,
    _anonymise_user,
)

#: Tables that are wiped, anonymised, kept, or can never hold a student, each
#: with the reason. The guard test makes this list total.
ERASED: frozenset[str] = frozenset(
    {model.__tablename__ for model, _ in _BY_STUDENT}  # type: ignore[attr-defined]
    - {"ai_usage_events", "custom_criterion_score_audit"}
    | {
        "submission_files",
        "question_marks",
        "remark_requests",
        "mistake_topics",
        "invites",
        "refresh_sessions",
        "data_exports",
    }
)
ANONYMISED: dict[str, str] = {
    "users": "the row stays as a blank 'Deleted student' so keys that must outlive the child stay valid",
    "mark_override_audit": "the tutor's decision stays (PROD-7); its link to the mark is cut",
    "custom_criterion_score_audit": "the tutor's decision stays (PROD-7); its student id is cut",
    "ai_usage_events": "the tutor's AI cost record stays (AI-17); its student id is cut",
}
KEPT: dict[str, str] = {
    "erasure_requests": "the audit row: who asked, when, and that it was done",
    "mistake_revision_audit": "plain-integer mistake_id, no personal data; the tutor's decision (PROD-7)",
    "jobs": "ids only; pending ones naming the child are removed, finished ones hold nothing personal",
}
STAFF_ONLY: dict[str, str] = {
    "assessments": "tutor_id: the author, always a tutor",
    "booklets": "tutor_id: the author",
    "classifieds": "tutor_id: the uploader",
    "custom_criteria": "created_by_id: a tutor",
    "google_accounts": "tutor_id: a tutor's own integration",
    "groups": "tutor_id, deleted_by_id: staff",
    "group_resources": "tutor_id: the uploader",
    "knowledge_entries": "tutor_id: the author",
    "lesson_meeting_imports": "requested_by_id: a tutor",
    "meeting_connections": "tutor_id: a tutor's own integration",
    "mocks": "tutor_id: the author",
    "past_papers": "tutor_id: the uploader",
    "plan_slots": "cancelled_by_id: a tutor",
    "readiness_weights": "tutor_id: a tutor's own settings",
    "setup_acknowledgements": "acknowledged_by_id: a tutor",
    "syllabus_uploads": "tutor_id: the uploader",
    "taught_before_topics": "created_by_id: a tutor",
    "teaching_plans": "accepted_by_id: a tutor",
}


async def _scope(session: AsyncSession, request: ErasureRequest, now: datetime) -> Scope | None:
    student = await session.get(User, request.student_id)
    if student is None or student.role != UserRole.student:
        return None
    sid = student.id
    scope = Scope(session, sid, student.name, student.email, now)
    removed = await _ids(
        session, select(ParentLinkRemoval.parent_id).where(ParentLinkRemoval.student_id == sid)
    )
    linked = await _ids(session, select(ParentLink.parent_id).where(ParentLink.student_id == sid))
    scope.parent_ids = sorted({*linked, *(p for p in removed if p is not None)})
    scope.submission_ids = await _ids(
        session, select(Submission.id).where(Submission.student_id == sid)
    )
    scope.old_submission_ids = [
        i
        for i in await _ids(
            session, select(AttemptRedo.previous_submission_id).where(AttemptRedo.student_id == sid)
        )
        if i is not None
    ]
    for chunk in _chunks(scope.submission_ids):
        scope.mark_ids += await _ids(
            session, select(QuestionMark.id).where(QuestionMark.submission_id.in_(chunk))
        )
    scope.mistake_ids = await _ids(session, select(Mistake.id).where(Mistake.student_id == sid))
    return scope


async def erase_student(session: AsyncSession, request: ErasureRequest, now: datetime) -> None:
    """Wipe one child in the caller's transaction. Does not commit: either all of
    it happens or none, and the files are deleted only after the commit, from the
    list stored on the request (`erase_due`)."""
    scope = await _scope(session, request, now)
    if scope is None:
        raise LookupError(f"erasure {request.id} names no student")
    request.pending_paths = await storage_keys(scope)
    for step in ERASE_ORDER:
        await step(scope)
    request.status = ErasureRequestStatus.done
    request.completed_at = now


async def _due_ids(session: AsyncSession, now: datetime) -> list[int]:
    return await _ids(
        session,
        select(ErasureRequest.id)
        .where(
            ErasureRequest.status == ErasureRequestStatus.pending,
            ErasureRequest.scheduled_for <= now,
        )
        .order_by(ErasureRequest.scheduled_for, ErasureRequest.id)
        .limit(MAX_PER_PASS),
    )


async def _delete_pending_files(session: AsyncSession) -> int:
    """Finish the file half of every erasure that is done. A crash between the
    row commit and the deletes leaves the keys on the request, so this is what
    makes the sweep safe to re-run (`BE-6`). A file already gone is not an
    error; one that will not delete stays listed for tomorrow."""
    # ponytail: scans every finished request, few and tiny; index `pending_paths` if erasures become routine.
    done = (
        await session.scalars(
            select(ErasureRequest).where(ErasureRequest.status == ErasureRequestStatus.done)
        )
    ).all()
    removed = 0
    for request in done:
        if not request.pending_paths:
            continue
        left = []
        for key in request.pending_paths:
            try:
                await storage.delete_file(key)
                removed += 1
            except Exception:  # noqa: BLE001 - kept for the next pass
                log.warning("erasure %s: could not delete %s", request.id, key, exc_info=True)
                left.append(key)
        request.pending_paths = left or None
        await session.commit()
    return removed


async def erase_due(session: AsyncSession, now: datetime) -> int:
    """The retention step: wipe every child whose undo window has passed, then
    finish any file deletes still owed. Returns how many children were wiped.

    Each request is its own transaction and takes the row lock before re-reading
    its status, so a cancel that committed first wins. One failing does not stop
    the rest; it is re-raised at the end so the job counts as failed."""
    erased = 0
    failed: list[int] = []
    for request_id in await _due_ids(session, now):
        try:
            request = await session.scalar(
                select(ErasureRequest).where(ErasureRequest.id == request_id).with_for_update()
            )
            if request is None or request.status != ErasureRequestStatus.pending:
                await session.rollback()
                continue
            await erase_student(session, request, now)
            await session.commit()
            erased += 1
        except Exception:  # noqa: BLE001 - re-raised below, after the others
            await session.rollback()
            log.exception("erasure %s failed", request_id)
            failed.append(request_id)
    await _delete_pending_files(session)
    if failed:
        raise RuntimeError(f"erasure {failed} failed; see the log")
    return erased
