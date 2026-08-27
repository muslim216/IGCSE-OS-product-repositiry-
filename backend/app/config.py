from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Avora"
    database_url: str = "postgresql+asyncpg://igcse:igcse@localhost:5432/igcse"

    @field_validator("database_url")
    @classmethod
    def _force_asyncpg(cls, v: str) -> str:
        # Hosting providers (e.g. Render) hand out postgres:// URLs; the async
        # SQLAlchemy engine needs the asyncpg driver spelled out.
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"
    # Google Gemini — the second AI provider. Unset -> every surface routed to
    # gemini fails with a clear "not configured" error, exactly like
    # ANTHROPIC_API_KEY does today; the rest of the app keeps working.
    gemini_api_key: str | None = None
    # Placeholder default. The real model id is owner-supplied: set GEMINI_MODEL
    # in the environment. Never hardcode a marketing name here.
    gemini_model: str = "gemini-2.5-pro"
    # Per-surface model routing (see services/ai.py resolve_surface). Provider
    # is "anthropic" or "gemini"; leaving the model blank uses that provider's
    # default model above. Marking/extraction default to Gemini (bulk document
    # work), chat to a cheap Anthropic model, reports/readiness to Opus.
    ai_marking_provider: str = "gemini"
    ai_marking_model: str = ""
    ai_extraction_provider: str = "gemini"
    ai_extraction_model: str = ""
    ai_syllabus_provider: str = "gemini"
    ai_syllabus_model: str = ""
    ai_reports_provider: str = "anthropic"
    ai_reports_model: str = ""
    ai_readiness_provider: str = "anthropic"
    ai_readiness_model: str = ""
    ai_class_brief_provider: str = "anthropic"
    ai_class_brief_model: str = ""
    # The stored narrative (services/narrative.py) — a report-shaped paragraph,
    # so it routes to Opus by default like reports.
    ai_narrative_provider: str = "anthropic"
    ai_narrative_model: str = ""
    # Per-token prices used to estimate ai_usage_events.cost_usd, as JSON:
    # {"<model id>": {"input_per_1m": 3.0, "output_per_1m": 15.0}}. Deliberately
    # empty by default — a model with no entry records cost_usd = NULL rather
    # than a guessed figure (see services/ai.py model_pricing()).
    ai_model_pricing: str = "{}"
    # Readiness Engine v2 is now what the readiness UI/API serve. This is the
    # kill switch, not a shadow flag: turning it off stops v2 runs being
    # enqueued, and since services/readiness_summary_v2.py falls back to v1 for
    # any subject with no snapshot, the app degrades to the v1 engine instead
    # of breaking. Kept under its original name so an existing deployment's
    # env var keeps working.
    readiness_v2_shadow_enabled: bool = True
    # Readiness v2 synthesis is an expensive AI call, and auto-marking can
    # finalize a burst of submissions in seconds. Triggers for the same
    # (student, subject) collapse into one run scheduled this many seconds
    # after the first trigger in the burst — see
    # readiness_v2_ai.enqueue_readiness_v2_debounced().
    readiness_v2_coalesce_seconds: int = 600
    # The precomputed narrative (services/narrative.py) adds a recurring model
    # call proportional to evidence volume. This is its kill switch: off stops
    # new narratives being enqueued (class triggers and the weekly parent sweep)
    # while leaving every stored narrative readable — instant rollback, no
    # deploy. Default on.
    narrative_enabled: bool = True
    # How stale a parent narrative may get before the weekly sweep refreshes it.
    narrative_parent_max_age_days: int = Field(default=7, ge=1)
    # The sweep re-enqueues itself this far out; a failed sweep costs one cycle
    # and self-corrects on the next.
    # ge=1: at zero or negative the successor is already due on arrival and the
    # sweep re-arms itself continuously, spinning the worker.
    narrative_sweep_interval_hours: int = Field(default=24, ge=1)
    # Most learners one sweep will enqueue. ge=1: at zero the sweep runs
    # forever and writes nothing. The cap exists so a first run against an
    # established installation drains over several cycles rather than spending
    # one AI call per learner in a single burst.
    narrative_sweep_max_students: int = Field(default=250, ge=1)
    # Extra delay on an evidence-triggered class narrative, on top of
    # readiness_v2_coalesce_seconds. The narrative is grounded in the v2
    # snapshot, so it must run *after* the debounced recompute has written one —
    # otherwise it describes pre-marking readiness and then looks fresh. This is
    # the margin for the run itself, not just for it becoming due.
    narrative_readiness_margin_seconds: int = 300
    # Google Classroom integration (see services/google_classroom.py). Both
    # unset -> the feature reports "not configured" everywhere and the app
    # runs fine without it, mirroring ANTHROPIC_API_KEY's graceful
    # degradation. From a Google Cloud project's OAuth 2.0 Client with the
    # Classroom + Drive (readonly) APIs enabled.
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:5173/settings/classroom/callback"
    # Encrypts stored Google refresh tokens at rest. Falls back to deriving a
    # key from JWT_SECRET when unset, so tokens are never stored in plaintext
    # even without extra config — set a dedicated value in production.
    google_token_encryption_key: str | None = None
    upload_dir: str = "uploads"
    # "local" writes under upload_dir; "s3" targets any S3-compatible store
    # (AWS S3, Cloudflare R2, MinIO). Local is the default so development and
    # tests need no object store, and so a missing bucket cannot silently
    # become the production configuration. A Literal rather than a bare str:
    # a typo (e.g. "S3") must fail startup, not silently keep production on
    # the single-instance-pinning local disk this task exists to remove
    # (RISK-1).
    storage_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    # Empty targets AWS itself. R2 and MinIO require their own endpoint.
    s3_endpoint_url: str = ""
    # R2 ignores the region but the SDK requires one; "auto" is what R2 documents.
    s3_region: str = "auto"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    # Signed URLs are bearer credentials that cannot be revoked before they
    # expire, so the window is short by default (threat review F3). They are
    # minted only for tutor material — student submissions proxy through the
    # API so the ownership check runs on every view.
    signed_url_ttl_seconds: int = 300
    cors_origins: str = "http://localhost:5173"
    # Disable only for plain-HTTP local dev/tests; production (HTTPS) should keep this True.
    refresh_cookie_secure: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _s3_backend_needs_a_bucket(self) -> "Settings":
        # A valid storage_backend value with no bucket is still a
        # misconfiguration — better to fail startup than to have S3Backend's
        # first real call fail confusingly against an empty bucket name.
        if self.storage_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_BACKEND=s3")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
