import secrets
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.models import Group, GroupMember, Invite, InviteKind, Organization, ParentLink
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
from app.services.invites import check_usable, consume
from app.services.rate_limit import login_limiter

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "igcse_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


@router.post("/register/tutor", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_tutor(
    body: TutorSignupRequest, db: DbSession, response: Response
) -> AuthResponse:
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    # A personal organization per tutor — the multi-tenant backbone that keeps
    # the product experience single-tutor (see CLAUDE.md / manara-architecture.md).
    org = Organization(name=f"{body.name}'s Organization")
    db.add(org)
    await db.flush()
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.tutor,
        name=body.name,
        organization_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    tokens = _token_pair(user)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@lru_cache
def _dummy_hash() -> str:
    """A real bcrypt hash of a value nobody knows, verified against when the
    identifier does not exist so a miss costs the same as a wrong password.
    Without it, response time tells an attacker which accounts are real."""
    return hash_password(secrets.token_urlsafe(32))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: DbSession, response: Response) -> AuthResponse:
    identifier = body.identifier.strip().lower()

    # Throttled per identifier, not per client address: the API sits behind
    # Render's proxy, so every request shares one source IP and an address-based
    # limit would lock out the whole platform instead of one attacker. Per
    # identifier is what actually stops guessing a single account's password.
    if login_limiter.is_limited(identifier):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-in attempts. Wait a few minutes and try again.",
        )

    user = await db.scalar(
        select(User).where(
            or_(func.lower(User.email) == identifier, func.lower(User.username) == identifier)
        )
    )
    password_ok = verify_password(body.password, user.password_hash if user else _dummy_hash())
    if user is None or not password_ok:
        login_limiter.record(identifier)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email/username or password")

    login_limiter.reset(identifier)
    tokens = _token_pair(user)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    request: Request, response: Response, db: DbSession, body: RefreshRequest | None = None
) -> TokenPair:
    raw_token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if raw_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token provided")
    decoded = decode_token(raw_token, expected_type="refresh")
    if decoded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    user_id, token_version = decoded
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    if token_version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")
    tokens = _token_pair(user)
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, db: DbSession, user: CurrentUser) -> None:
    user.token_version += 1
    await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


async def _valid_invite(db: AsyncSession, code: str, kind: InviteKind) -> Invite:
    invite = await db.scalar(
        select(Invite).where(Invite.code == code).options(selectinload(Invite.group))
    )
    if invite is None or invite.kind != kind:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    check_usable(invite)
    return invite


@router.get("/invites/{code}", response_model=InvitePreview)
async def preview_invite(code: str, db: DbSession) -> InvitePreview:
    """Public preview shown on the join page before signing up."""
    invite = await db.scalar(select(Invite).where(Invite.code == code))
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    # Unauthenticated endpoint: a spent or expired code must stop disclosing the
    # tutor's name, the group, and the student's name along with it.
    check_usable(invite)
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
async def register_student(
    body: StudentRegisterRequest, db: DbSession, response: Response
) -> AuthResponse:
    invite = await _valid_invite(db, body.invite_code, InviteKind.student_join)
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists — sign in and use the invite link again",
        )
    # Students inherit the organization of the tutor whose group they're joining.
    tutor = await db.get(User, invite.group.tutor_id)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.student,
        name=body.name,
        organization_id=tutor.organization_id,
    )
    db.add(user)
    await db.flush()
    await _add_to_group(db, invite.group_id, user.id)
    await db.commit()
    await db.refresh(user)
    tokens = _token_pair(user)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/register/parent", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_parent(
    body: ParentRegisterRequest, db: DbSession, response: Response
) -> AuthResponse:
    invite = await _valid_invite(db, body.link_code, InviteKind.parent_link)
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An account with this email already exists — sign in and use the link again",
        )
    # Parents inherit the organization of the student they're linking to.
    student = await db.get(User, invite.student_id)
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=UserRole.parent,
        name=body.name,
        organization_id=student.organization_id,
    )
    db.add(user)
    await db.flush()
    db.add(ParentLink(parent_id=user.id, student_id=invite.student_id))
    await consume(db, invite)
    await db.commit()
    await db.refresh(user)
    tokens = _token_pair(user)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/join", status_code=status.HTTP_204_NO_CONTENT)
async def join_with_invite(body: JoinRequest, db: DbSession, user: CurrentUser) -> None:
    """An existing account accepts an invite: students join a group, parents link a child."""
    invite = await db.scalar(select(Invite).where(Invite.code == body.invite_code))
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    check_usable(invite)

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
        await consume(db, invite)
    await db.commit()
