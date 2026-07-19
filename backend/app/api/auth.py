from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.models import Group, GroupMember, Invite, InviteKind, ParentLink
from app.models.users import User, UserRole
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    TutorSignupRequest,
    UserOut,
)
from app.schemas.groups import (
    InvitePreview,
    JoinRequest,
    ParentRegisterRequest,
    StudentRegisterRequest,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_pair(user_id: int) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/register/tutor", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_tutor(body: TutorSignupRequest, db: DbSession) -> AuthResponse:
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.tutor,
        name=body.name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return AuthResponse(user=UserOut.model_validate(user), tokens=_token_pair(user.id))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: DbSession) -> AuthResponse:
    identifier = body.identifier.strip().lower()
    user = await db.scalar(
        select(User).where(
            or_(func.lower(User.email) == identifier, func.lower(User.username) == identifier)
        )
    )
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email/username or password")
    return AuthResponse(user=UserOut.model_validate(user), tokens=_token_pair(user.id))


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, db: DbSession) -> TokenPair:
    user_id = decode_token(body.refresh_token, expected_type="refresh")
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    return _token_pair(user.id)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


async def _valid_invite(db: AsyncSession, code: str, kind: InviteKind) -> Invite:
    invite = await db.scalar(
        select(Invite).where(Invite.code == code).options(selectinload(Invite.group))
    )
    if invite is None or invite.kind != kind:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    if invite.expires_at is not None and invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "This invite link has expired")
    return invite


@router.get("/invites/{code}", response_model=InvitePreview)
async def preview_invite(code: str, db: DbSession) -> InvitePreview:
    """Public preview shown on the join page before signing up."""
    invite = await db.scalar(select(Invite).where(Invite.code == code))
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    if invite.kind == InviteKind.student_join and invite.group_id is not None:
        group = await db.scalar(
            select(Group)
            .where(Group.id == invite.group_id)
            .options(selectinload(Group.subject), selectinload(Group.tutor))
        )
        return InvitePreview(
            kind=invite.kind.value,
            group_name=group.name,
            subject_name=group.subject.name,
            tutor_name=group.tutor.name,
        )
    student = await db.get(User, invite.student_id) if invite.student_id else None
    return InvitePreview(kind=invite.kind.value, student_name=student.name if student else None)


async def _add_to_group(db: AsyncSession, group_id: int, student_id: int) -> None:
    existing = await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.student_id == student_id
        )
    )
    if existing is None:
        db.add(GroupMember(group_id=group_id, student_id=student_id))


@router.post("/register/student", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_student(body: StudentRegisterRequest, db: DbSession) -> AuthResponse:
    invite = await _valid_invite(db, body.invite_code, InviteKind.student_join)
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists — sign in and use the invite link again",
        )
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.student,
        name=body.name,
    )
    db.add(user)
    await db.flush()
    await _add_to_group(db, invite.group_id, user.id)
    await db.commit()
    await db.refresh(user)
    return AuthResponse(user=UserOut.model_validate(user), tokens=_token_pair(user.id))


@router.post("/register/parent", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_parent(body: ParentRegisterRequest, db: DbSession) -> AuthResponse:
    invite = await _valid_invite(db, body.link_code, InviteKind.parent_link)
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists — sign in and use the link again",
        )
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.parent,
        name=body.name,
    )
    db.add(user)
    await db.flush()
    db.add(ParentLink(parent_id=user.id, student_id=invite.student_id))
    await db.commit()
    await db.refresh(user)
    return AuthResponse(user=UserOut.model_validate(user), tokens=_token_pair(user.id))


@router.post("/join", status_code=status.HTTP_204_NO_CONTENT)
async def join_with_invite(body: JoinRequest, db: DbSession, user: CurrentUser) -> None:
    """An existing account accepts an invite: students join a group, parents link a child."""
    invite = await db.scalar(select(Invite).where(Invite.code == body.invite_code))
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    if invite.expires_at is not None and invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "This invite link has expired")

    if invite.kind == InviteKind.student_join:
        if user.role != UserRole.student:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only student accounts can join a group")
        await _add_to_group(db, invite.group_id, user.id)
    else:
        if user.role != UserRole.parent:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only parent accounts can link a child")
        existing = await db.scalar(
            select(ParentLink).where(
                ParentLink.parent_id == user.id, ParentLink.student_id == invite.student_id
            )
        )
        if existing is None:
            db.add(ParentLink(parent_id=user.id, student_id=invite.student_id))
    await db.commit()
