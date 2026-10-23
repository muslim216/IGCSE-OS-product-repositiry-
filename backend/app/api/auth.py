import secrets
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.models import (
    Group,
    GroupMember,
    Invite,
    InviteKind,
    Organization,
    ParentLink,
    RefreshSession,
)
from app.models.users import User, UserRole
from app.schemas.auth import (
    AccessToken,
    AuthResponse,
    ChangePasswordRequest,
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
    create_device_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    hash_password_async,
    known_device,
    run_bcrypt,
    verify_password_async,
)
from app.services import refresh_sessions
from app.services.invites import check_usable, consume
from app.services.rate_limit import login_limiter
from app.services.timezones import normalize_timezone

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "igcse_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


DEVICE_COOKIE = "avora_device"


def _access_only(tokens: TokenPair) -> AccessToken:
    """What actually goes in a JSON response body — never the refresh token.
    See AccessToken's docstring (SEC-2)."""
    return AccessToken(access_token=tokens.access_token, token_type=tokens.token_type)


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_session_max_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _issue(response: Response, user: User, session: RefreshSession) -> AccessToken:
    tokens = TokenPair(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(
            user.id,
            user.token_version,
            session.id,
            session.generation,
            refresh_sessions.expires_at(session, datetime.now(timezone.utc)),
        ),
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return _access_only(tokens)


async def _sign_in(db: AsyncSession, response: Response, user: User) -> AccessToken:
    """Every way into an account ends here: a new refresh session, its first
    token, and this browser marked as known to the account (`SA-06`, `SA-11`)."""
    session = await refresh_sessions.start(db, user)
    await db.commit()
    settings = get_settings()
    response.set_cookie(
        DEVICE_COOKIE,
        create_device_token(user.id),
        max_age=settings.known_device_days * 86400,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )
    return _issue(response, user, session)


@router.post("/register/tutor", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register_tutor(
    body: TutorSignupRequest, db: DbSession, response: Response
) -> AuthResponse:
    email = body.email.lower()
    existing = await db.scalar(select(User).where(func.lower(User.email) == email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    # The browser reported this; treat it as untrusted and drop it if it is not
    # a real zone. Signup is the wrong place to fail over a convenience field —
    # an unusable value leaves the organization on the UTC fallback, which
    # Settings can correct, rather than blocking the account.
    try:
        tz = normalize_timezone(body.timezone)
    except ValueError:
        tz = None
    # A personal organization per tutor — the multi-tenant backbone that keeps
    # the product experience single-tutor (see CLAUDE.md / docs/avora-architecture.md).
    org = Organization(name=f"{body.name}'s Organization", timezone=tz)
    db.add(org)
    await db.flush()
    user = User(
        email=email,
        password_hash=await hash_password_async(body.password),
        role=UserRole.tutor,
        name=body.name,
        organization_id=org.id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    tokens = await _sign_in(db, response, user)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@lru_cache
def _dummy_hash() -> str:
    """A real bcrypt hash of a value nobody knows, verified against when the
    identifier does not exist so a miss costs the same as a wrong password.
    Without it, response time tells an attacker which accounts are real."""
    return hash_password(secrets.token_urlsafe(32))


async def _find_account(db: AsyncSession, identifier: str) -> User | None:
    return await db.scalar(
        select(User).where(
            or_(func.lower(User.email) == identifier, func.lower(User.username) == identifier)
        )
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest, request: Request, db: DbSession, response: Response
) -> AuthResponse:
    identifier = body.identifier.strip().lower()

    # Throttled per identifier, not per client address: the API sits behind
    # Render's proxy, so every request shares one source IP and an address-based
    # limit would lock out the whole platform instead of one attacker. Per
    # identifier is what actually stops guessing a single account's password.
    #
    # But a counter anyone can spend is a lock anyone can turn: ten wrong
    # passwords typed by a classmate used to shut the owner out too (`SA-06`).
    # A browser that has signed in to this account before carries a device
    # cookie, and counts its failures on a key of its own that nobody else can
    # reach. The shared counter still caps everyone else, so guessing gains
    # nothing — a device key is only ever minted after the right password.
    #
    # With a device cookie, the account is looked up before the throttle check
    # so the cookie can be matched to it however the owner typed their name.
    # That opens no timing difference: the bcrypt verify below, which is what
    # an attacker could time, still runs for a miss. Without one, the shared
    # counter is checked first, so hammering a locked identifier costs no query.
    device_cookie = request.cookies.get(DEVICE_COOKIE)
    user = None
    throttle_key = identifier
    if device_cookie:
        user = await _find_account(db, identifier)
        device = known_device(device_cookie, user.id) if user else None
        if user is not None and device is not None:
            throttle_key = f"user:{user.id}\x00device:{device}"
    if await login_limiter.is_limited(throttle_key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed sign-in attempts. Wait a few minutes and try again.",
        )
    if not device_cookie:
        user = await _find_account(db, identifier)

    # The dummy hash off the loop too: the first miss after a restart makes it.
    stored = user.password_hash if user else await run_bcrypt(_dummy_hash)
    password_ok = await verify_password_async(body.password, stored)
    if user is None or not password_ok:
        await login_limiter.record(throttle_key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email/username or password")

    await login_limiter.reset(throttle_key)
    tokens = await _sign_in(db, response, user)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/refresh", response_model=AccessToken)
async def refresh(
    request: Request, response: Response, db: DbSession, body: RefreshRequest | None = None
) -> AccessToken:
    raw_token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if raw_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token provided")
    decoded = decode_refresh_token(raw_token)
    if decoded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token")
    user_id, token_version, session_id, generation = decoded
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    if token_version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")
    session = await refresh_sessions.rotate(db, user, session_id, generation)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")
    return _issue(response, user, session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, db: DbSession, user: CurrentUser) -> None:
    user.token_version += 1
    # The bump has already made every one of these sessions useless.
    await refresh_sessions.end_all(db, user)
    await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.post(
    "/password",
    response_model=AccessToken,
    responses={
        400: {"description": "The current password is wrong."},
        422: {"description": "The new password is invalid or the same as the current one."},
        429: {"description": "Too many wrong current passwords; wait and retry."},
    },
)
async def change_password(
    body: ChangePasswordRequest, response: Response, db: DbSession, user: CurrentUser
) -> AccessToken:
    """Any signed-in user changes their own password. Every other session dies
    (`SEC-1`); this one is re-issued so the person is not signed out of the
    page they are on."""
    # The sign-in limiter, on a key of its own per user (`SEC-14`): a stolen
    # access token must not be a free oracle for the password, but its wrong
    # guesses must not spend the owner's login counter either.
    key = f"user:{user.id}\x00chpw"
    if await login_limiter.is_limited(key):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed attempts. Wait a few minutes and try again.",
        )
    if not await verify_password_async(body.current_password, user.password_hash):
        await login_limiter.record(key)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is incorrect.")
    if body.new_password == body.current_password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Choose a new password that is different from your current one.",
        )
    user.password_hash = await hash_password_async(body.new_password)
    user.token_version += 1
    await refresh_sessions.end_all(db, user)
    tokens = await _sign_in(db, response, user)
    await login_limiter.reset(key)
    return tokens


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


async def _valid_invite(db: AsyncSession, code: str, kind: InviteKind) -> Invite:
    invite = await db.scalar(
        select(Invite).where(Invite.code == code).options(selectinload(Invite.group))
    )
    if invite is None or invite.kind != kind:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
    # A deleted class's code is indistinguishable from one that never existed.
    if invite.group is not None and invite.group.deleted_at is not None:
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
            .where(Group.id == invite.group_id, Group.deleted_at.is_(None))
            .options(selectinload(Group.subject), selectinload(Group.tutor))
        )
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
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
        password_hash=await hash_password_async(body.password),
        role=UserRole.student,
        name=body.name,
        organization_id=tutor.organization_id,
    )
    db.add(user)
    await db.flush()
    await _add_to_group(db, invite.group_id, user.id)
    await db.commit()
    await db.refresh(user)
    tokens = await _sign_in(db, response, user)
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
        password_hash=await hash_password_async(body.password),
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
    tokens = await _sign_in(db, response, user)
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
        group_org = await db.scalar(
            select(Group.organization_id).where(
                Group.id == invite.group_id, Group.deleted_at.is_(None)
            )
        )
        if group_org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "This invite link is not valid")
        # One tutor's workspace per student at launch (owner, 18 Oct 2026). A
        # student in a second organization's class is the shared-student design
        # that was never finished: that tutor could read the first one's records,
        # reset the child's password and mint a parent link to them. This join is
        # the only way such a membership is made, so refusing it here closes all
        # of that at the source; the checks in students.py and groups.py are the
        # second line for memberships made before it.
        if group_org != user.organization_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This account already belongs to another tutor on Avora, so it can't join "
                "this class. Ask this class's tutor to create an account for you.",
            )
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
