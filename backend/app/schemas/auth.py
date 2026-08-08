from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.users import UserRole


class TutorSignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
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


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    username: str | None
    role: UserRole
    name: str


class AuthResponse(BaseModel):
    user: UserOut
    tokens: TokenPair
