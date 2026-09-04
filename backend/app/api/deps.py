from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.syllabus import Subject
from app.models.users import User, UserRole
from app.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    decoded = decode_token(credentials.credentials, expected_type="access")
    if decoded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user_id, token_version = decoded
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    # CODE-12: token_version is the single revocation signal. Every access
    # and refresh token is minted at the user's current version; bumping
    # users.token_version (logout, password reset, disable) invalidates all
    # outstanding tokens at once because this check rejects any token whose
    # version no longer matches. A new login mints tokens at the new version.
    if token_version != user.token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token has been revoked")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_org_id(user: CurrentUser) -> int:
    """Every request is scoped to the caller's organization. Services should
    filter every top-level aggregate query by this id rather than trusting
    path/body-supplied ids alone."""
    return user.organization_id


CurrentOrg = Annotated[int, Depends(get_current_org_id)]


def require_role(*roles: UserRole, detail: str = "Insufficient permissions"):
    """Build a dependency admitting only `roles`, wrapped for use in a signature.

    Where the check lives is the whole point. In a signature it is part of
    resolving the request, so the handler cannot run without it. In the body it
    is one line somebody has to remember to write, and forgetting it produces an
    endpoint with no role check at all that no test, linter or type error
    notices. That was not hypothetical: this check existed as ten byte-identical
    private copies of `_require_tutor` plus one `_require_student`, called in 35
    handler bodies (RISK-7).
    """

    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail)
        return user

    return Depends(checker)


#: Admin counts as a tutor everywhere a tutor is required. That was true of all
#: ten copies replaced here, and the 403 detail strings are preserved exactly so
#: no client sees a changed message.
TUTOR_ROLES = (UserRole.tutor, UserRole.admin)


def assert_tutor(user: User) -> None:
    """The tutor gate in imperative form.

    Prefer `TutorUser` on the handler — a signature cannot be forgotten the way
    a call can. This exists for the ownership helpers that sit below the routing
    layer (`_owned_group`, `_owned_entry`, `_owned_upload`), which take a plain
    User rather than a request-scoped dependency. Keeping their check is defence
    in depth; routing it through here means the condition is still written once.
    """
    if user.role not in TUTOR_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tutor account required")


def assert_student(user: User) -> None:
    if user.role != UserRole.student:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student account required")


async def require_tutor(user: CurrentUser) -> User:
    assert_tutor(user)
    return user


async def require_student(user: CurrentUser) -> User:
    assert_student(user)
    return user


#: The two annotations routers should use. `user: TutorUser` documents and
#: enforces in the same token, and a test can assert the dependency is present on
#: a route without calling it — see tests/test_authorization.py, which fails if
#: any route loses its gate.
TutorUser = Annotated[User, Depends(require_tutor)]
StudentUser = Annotated[User, Depends(require_student)]


async def owned_subject(db: AsyncSession, subject_id: int, user: User) -> Subject:
    """A subject in the caller's own organization, or 404.

    Subjects became tenant-owned in task 2.2 (AV-6). Every one of the ten
    routers that resolves a caller-supplied `subject_id` needs the same two
    conditions, and writing them ten times is how the eleventh gets one of them
    wrong — the same argument `require_role` makes about role gates (RISK-7).

    **404, not 403** (`API-7`, `SEC-9`): integer keys are enumerable, and a 403
    would confirm that a subject with that id exists in someone else's account.
    The two cases are deliberately indistinguishable to the caller.

    Tutor-facing only. A student may be taught a subject outside their own
    organization — an invite to a second tutor's group does not move them — so
    student-reachable routes use `services.subjects.visible_subject_ids`
    instead, which scopes by enrolment (`SEC-8`).
    """
    subject = await db.get(Subject, subject_id)
    if subject is None or subject.organization_id != user.organization_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    return subject


async def visible_subject(db: AsyncSession, subject_id: int, user: User) -> Subject:
    """A subject this caller may *see*, or 404 — for routes any role can reach.

    `owned_subject` is wrong on both sides for a mixed-role route. It is too
    permissive, letting a student read a subject in their organization that they
    are not enrolled in; and too strict, because a student invited into a second
    tutor's group keeps their original organization, so an organization check
    404s them on a subject they are actively being taught (`SEC-8`).

    Scoping goes through `visible_subject_ids`, which answers per role: tutors by
    organization, students by enrolment, parents by their children's enrolment.
    """
    from app.services.subjects import visible_subject_ids

    if subject_id not in await visible_subject_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    subject = await db.get(Subject, subject_id)
    if subject is None:  # pragma: no cover - id came from the visibility query
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subject not found")
    return subject
