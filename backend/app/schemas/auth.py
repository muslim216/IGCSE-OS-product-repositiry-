from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field
from pydantic_core import PydanticCustomError

from app.models.users import UserRole

#: bcrypt reads at most 72 bytes, and the installed bcrypt raises past it
#: rather than truncating, so a longer password was a 500 (`SA-05`).
BCRYPT_MAX_BYTES = 72


def _fits_bcrypt(value: str) -> str:
    # Bytes, not characters: an accented or Arabic letter is two in UTF-8, so
    # 40 Arabic letters are already over.
    if len(value.encode()) > BCRYPT_MAX_BYTES:
        raise PydanticCustomError(
            "password_too_long",
            "Must be at most 72 characters, fewer if it uses accented or Arabic letters.",
        )
    return value


#: A password being set. Signing in keeps its own looser field: no account can
#: have a password over 72 bytes, and `verify_password` answers False for one
#: (bcrypt 5 raises, which it catches).
NewPassword = Annotated[
    # The character cap only bounds the input; the byte check is the real limit
    # and the one whose message a person sees.
    str,
    Field(min_length=8, max_length=128),
    AfterValidator(_fits_bcrypt),
]


class TutorSignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: NewPassword
    # IANA zone from the browser, so "today" means the tutor's today from the
    # first session. Optional: a browser that cannot report one still signs up,
    # and the organization falls back to UTC until Settings sets it. Validated
    # server-side against the real tz database before it is stored — length
    # alone does not make a browser-supplied string safe to persist.
    timezone: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    # Email or username — students created by their tutor sign in with a username.
    identifier: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    # Looser than NewPassword for the same reason LoginRequest is: whatever the
    # account has now is checked by hash, not by the registration rules.
    current_password: str = Field(min_length=1, max_length=128)
    new_password: NewPassword


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class TokenPair(BaseModel):
    """Both tokens, minted together server-side. Never sent to a client as
    JSON — see AccessToken. `_set_refresh_cookie` reads `refresh_token` off
    this to set the httpOnly cookie; nothing else should."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    """What a client actually receives in a response body. The refresh token
    travels only in the httpOnly, SameSite=Lax cookie scoped to
    /api/v1/auth — putting it in JSON as well would let a same-origin XSS
    read it, which defeats the point of the cookie (SEC-2)."""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    username: str | None
    role: UserRole
    name: str
    # The user's own IANA zone, or None to follow the organization's. Surfaces
    # resolve the effective zone as time_zone or organization.timezone (E11).
    time_zone: str | None = None


class UserTimezoneUpdate(BaseModel):
    # Same shape and validation contract as OrganizationTimezoneUpdate: null
    # clears back to the org default, the name itself is checked against the
    # real tz database in the handler.
    timezone: str | None = Field(default=None, max_length=64)


class AuthResponse(BaseModel):
    user: UserOut
    tokens: AccessToken
