"""Contact points, notification preferences and channel status (task 8.1).

Routes live under three prefixes (`/students`, `/me`, `/notifications`), so the
router carries full paths. A tutor sets a student's and that student's parents'
addresses and confirms them after seeing each shown back (threat review F5);
nothing is ever sent to an unconfirmed address.
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.api.students import _tutor_student
from app.models import (
    ContactPoint,
    Group,
    GroupMember,
    Notification,
    NotificationChannel,
    NotificationKind,
    NotificationPreference,
    NotificationStatus,
    ParentLink,
    User,
    UserRole,
)
from app.models.base import utcnow
from app.schemas.notifications import (
    ChannelStatusOut,
    ContactOut,
    ContactSet,
    PersonContactsOut,
    PreferenceItem,
    PreferencesUpdate,
    SelfContactSet,
    UndeliveredOut,
)
from app.services.groups import live_classes_taught_by
from app.services.notifications.contacts import confirm_contact, contacts_for, set_contact
from app.services.notifications.service import channel_registry

router = APIRouter(tags=["notifications"])

_NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")


def _person(user: User, contacts: list[ContactPoint]) -> PersonContactsOut:
    return PersonContactsOut(
        user_id=user.id,
        name=user.name,
        role=user.role.value,
        contacts=[ContactOut.model_validate(c, from_attributes=True) for c in contacts],
    )


async def _people(db: AsyncSession, student: User, organization_id: int) -> list[User]:
    """The student and their linked parents, inside the tutor's organization.

    A person homed in another organization is left out: this tutor does not get
    to hold a contact point for someone else's tenant (`SEC-7`).
    """
    parents = (
        await db.scalars(
            select(User)
            .join(ParentLink, ParentLink.parent_id == User.id)
            .where(ParentLink.student_id == student.id)
            .order_by(User.name)
        )
    ).all()
    people = [student, *parents]
    return [p for p in people if p.organization_id == organization_id]


@router.get("/students/{student_id}/contacts", response_model=list[PersonContactsOut])
async def list_student_contacts(
    student_id: int, db: DbSession, user: TutorUser
) -> list[PersonContactsOut]:
    student = await _tutor_student(db, user, student_id)
    return [
        _person(p, await contacts_for(db, p.id))
        for p in await _people(db, student, user.organization_id)
    ]


@router.put("/students/{student_id}/contacts", response_model=ContactOut)
async def put_student_contact(
    student_id: int, body: ContactSet, db: DbSession, user: TutorUser
) -> ContactOut:
    student = await _tutor_student(db, user, student_id)
    people = {p.id: p for p in await _people(db, student, user.organization_id)}
    target = people.get(body.user_id if body.user_id is not None else student.id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    try:
        contact = await set_contact(db, user=target, channel=body.channel, address=body.address)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await db.commit()
    return ContactOut.model_validate(contact, from_attributes=True)


@router.post("/students/{student_id}/contacts/{contact_id}/confirm", response_model=ContactOut)
async def confirm_student_contact(
    student_id: int, contact_id: int, db: DbSession, user: TutorUser
) -> ContactOut:
    student = await _tutor_student(db, user, student_id)
    people = {p.id for p in await _people(db, student, user.organization_id)}
    contact = await db.get(ContactPoint, contact_id)
    if (
        contact is None
        or contact.user_id not in people
        or contact.organization_id != user.organization_id
    ):
        raise _NOT_FOUND
    confirm_contact(contact, user)
    await db.commit()
    return ContactOut.model_validate(contact, from_attributes=True)


@router.get("/me/contacts", response_model=list[ContactOut])
async def list_my_contacts(db: DbSession, user: TutorUser) -> list[ContactOut]:
    return [
        ContactOut.model_validate(c, from_attributes=True) for c in await contacts_for(db, user.id)
    ]


@router.put("/me/contacts", response_model=ContactOut)
async def put_my_contact(body: SelfContactSet, db: DbSession, user: TutorUser) -> ContactOut:
    try:
        contact = await set_contact(db, user=user, channel=body.channel, address=body.address)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await db.commit()
    return ContactOut.model_validate(contact, from_attributes=True)


@router.post("/me/contacts/{contact_id}/confirm", response_model=ContactOut)
async def confirm_my_contact(contact_id: int, db: DbSession, user: TutorUser) -> ContactOut:
    """A tutor confirms their own address: they are the one person who can
    check it, and the call is theirs alone (a student's or parent's is
    confirmed by a tutor, never by themselves)."""
    contact = await db.get(ContactPoint, contact_id)
    if contact is None or contact.user_id != user.id:
        raise _NOT_FOUND
    confirm_contact(contact, user)
    await db.commit()
    return ContactOut.model_validate(contact, from_attributes=True)


async def _preferences(db: AsyncSession, user: User) -> list[PreferenceItem]:
    off = {
        (p.kind, p.channel): p.enabled
        for p in await db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    }
    return [
        PreferenceItem(kind=k, channel=c, enabled=off.get((k, c), True))
        for k in NotificationKind
        for c in NotificationChannel
    ]


@router.get("/me/notification-preferences", response_model=list[PreferenceItem])
async def get_preferences(db: DbSession, user: CurrentUser) -> list[PreferenceItem]:
    return await _preferences(db, user)


@router.put("/me/notification-preferences", response_model=list[PreferenceItem])
async def put_preferences(
    body: PreferencesUpdate, db: DbSession, user: CurrentUser
) -> list[PreferenceItem]:
    existing = {
        (p.kind, p.channel): p
        for p in await db.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    }
    # Collapsed first, last one wins: the same (kind, channel) twice in one body
    # would otherwise insert two rows and fail the unique constraint as a 500.
    wanted = {(item.kind, item.channel): item.enabled for item in body.preferences}
    for (kind, channel), enabled in wanted.items():
        row = existing.get((kind, channel))
        if row is None:
            db.add(
                NotificationPreference(user_id=user.id, kind=kind, channel=channel, enabled=enabled)
            )
        else:
            row.enabled = enabled
    await db.commit()
    return await _preferences(db, user)


@router.get("/notifications/status", response_model=ChannelStatusOut)
async def channel_status(user: TutorUser) -> ChannelStatusOut:
    """Whether each channel is configured on the server — booleans only."""
    registry = channel_registry()
    return ChannelStatusOut(
        whatsapp_configured=registry[NotificationChannel.whatsapp].available(),
        email_configured=registry[NotificationChannel.email].available(),
    )


#: How far back the undelivered list looks, how many rows it reads, and how
#: many it returns.
UNDELIVERED_WINDOW = timedelta(days=30)
UNDELIVERED_SCAN = 1000
UNDELIVERED_LIMIT = 100


@router.get("/notifications/undelivered", response_model=list[UndeliveredOut])
async def undelivered(db: DbSession, user: TutorUser) -> list[UndeliveredOut]:
    """Who is not being reached, and why — the newest undelivered message per
    person and reason from the last 30 days.

    Without this a parent who never gets their weekly message is invisible: the
    row ends `failed`, `suppressed` or `no_channel` and only the table knows.
    One row per person and reason, not one per message: a learner with no
    confirmed number misses every reminder for every lesson, and thirty copies
    of "no confirmed number" would bury the one that says a parent opted out.
    A row still `queued` is in flight, not a problem, and is left out.
    """
    query = (
        select(Notification, User)
        .join(User, User.id == Notification.recipient_user_id)
        .where(
            Notification.organization_id == user.organization_id,
            Notification.status.not_in([NotificationStatus.sent, NotificationStatus.queued]),
            Notification.created_at >= utcnow() - UNDELIVERED_WINDOW,
        )
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(UNDELIVERED_SCAN)
    )
    if user.role != UserRole.admin:
        # A tutor sees who is not being reached among *their* people: learners
        # in their own classes and those learners' parents — and themselves,
        # since their own weekly send and review nudge can fail too.
        # Organization alone would show every other tutor's families (an admin
        # keeps that view).
        taught = (
            select(GroupMember.student_id)
            .join(Group, Group.id == GroupMember.group_id)
            .where(*live_classes_taught_by(user.id), Group.organization_id == user.organization_id)
        )
        query = query.where(
            or_(
                Notification.recipient_user_id == user.id,
                Notification.recipient_user_id.in_(taught),
                Notification.recipient_user_id.in_(
                    select(ParentLink.parent_id).where(ParentLink.student_id.in_(taught))
                ),
            )
        )
    rows = (await db.execute(query)).all()
    seen: set[tuple[int, NotificationStatus]] = set()
    out: list[UndeliveredOut] = []
    for note, person in rows:
        key = (person.id, note.status)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            UndeliveredOut(
                id=note.id,
                recipient_user_id=person.id,
                recipient_name=person.name,
                recipient_role=person.role.value,
                kind=note.kind,
                status=note.status,
                reason=note.error,
                created_at=note.created_at,
            )
        )
        if len(out) >= UNDELIVERED_LIMIT:
            break
    return out
