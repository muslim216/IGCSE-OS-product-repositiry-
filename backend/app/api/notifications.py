"""Contact points, notification preferences and channel status (task 8.1).

Routes live under three prefixes (`/students`, `/me`, `/notifications`), so the
router carries full paths. A tutor sets a student's and that student's parents'
addresses and confirms them after seeing each shown back (threat review F5);
nothing is ever sent to an unconfirmed address.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.api.students import _tutor_student
from app.models import (
    ContactPoint,
    NotificationChannel,
    NotificationKind,
    NotificationPreference,
    ParentLink,
    User,
)
from app.schemas.notifications import (
    ChannelStatusOut,
    ContactOut,
    ContactSet,
    PersonContactsOut,
    PreferenceItem,
    PreferencesUpdate,
    SelfContactSet,
)
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
    for item in body.preferences:
        row = existing.get((item.kind, item.channel))
        if row is None:
            db.add(
                NotificationPreference(
                    user_id=user.id, kind=item.kind, channel=item.channel, enabled=item.enabled
                )
            )
        else:
            row.enabled = item.enabled
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
