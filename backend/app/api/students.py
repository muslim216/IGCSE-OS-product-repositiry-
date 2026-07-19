import secrets

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Group, GroupMember, Invite, InviteKind, User, UserRole
from app.schemas.groups import InviteOut

router = APIRouter(prefix="/students", tags=["students"])


@router.post(
    "/{student_id}/parent-code", response_model=InviteOut, status_code=status.HTTP_201_CREATED
)
async def create_parent_code(student_id: int, db: DbSession, user: CurrentUser) -> InviteOut:
    """Generate a code a parent uses to create an account linked to this student."""
    if user.role not in (UserRole.tutor, UserRole.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")
    shares_group = await db.scalar(
        select(GroupMember.id)
        .join(Group, Group.id == GroupMember.group_id)
        .where(GroupMember.student_id == student_id, Group.tutor_id == user.id)
    )
    if shares_group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found in your groups")
    student = await db.get(User, student_id)
    if student is None or student.role != UserRole.student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    invite = Invite(
        code=secrets.token_urlsafe(8),
        kind=InviteKind.parent_link,
        student_id=student.id,
        created_by_id=user.id,
    )
    db.add(invite)
    await db.commit()
    return InviteOut(code=invite.code, kind=invite.kind.value, expires_at=invite.expires_at)
