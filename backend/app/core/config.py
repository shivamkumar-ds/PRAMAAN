"""
BidOps AI — application settings.

Centralizes all configuration in one place, loaded from environment
variables (and a local .env file in development). No other module
should read os.environ directly — everything goes through `get_settings()`.

DATABASE_URL is defined here now, ahead of Step 4, so that Postgres
wiring later is "read an existing setting" rather than a second,
separate configuration decision.

Consolidation note (BidOps_Final): this file merges the provider settings
from both prior lineages — Qwen/Gemini/Vertex (the startup repository) and
OpenAI (the OpenAI Build Week repository) — behind the same `LLMClient`
interface. Per the founder engineering direction: OpenAI is the
operational reference implementation (the only provider with a verified
end-to-end Decision Engine run); Vertex AI remains the strategic
long-term provider, pending equivalent real production verification. The
code-level default below is unchanged from ADR-001 ("mock" — every real
provider is opt-in via explicit configuration); the *recommended* .env
value is documented in .env.example.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# NOTE:
# All application configuration must be defined in this Settings class.
# Do not access environment variables directly (os.getenv / os.environ)
# anywhere else in the codebase — every setting flows through get_settings().
class Settings(BaseSettings):
    app_name: str = "BidOps AI"
    app_env: str = "development"
    debug: bool = False

    database_url: str = "postgresql+psycopg2://bidops:bidops@localhost:5432/bidops"

    # Connection pool sizing (Phase 3: GCP deployment). Deliberately small
    # defaults -- on Cloud Run, every concurrent container instance holds
    # its own independent pool, so a large per-instance pool multiplies
    # into far more simultaneous Cloud SQL connections than intended as
    # traffic scales instances up. 5+2=7 max connections per instance is
    # conservative and matches Cloud SQL for PostgreSQL's own default
    # max_connections headroom for an early-stage deployment; raise this
    # deliberately (and raise Cloud SQL's max_connections to match) if
    # instance count or per-instance concurrency grows.
    db_pool_size: int = 5
    db_max_overflow: int = 2
    # Recycles a pooled connection after this many seconds, closing it
    # proactively rather than waiting to discover Cloud SQL (or any
    # managed proxy in front of it) has already dropped it. pool_pre_ping
    # (below, always on) already guards against using a dead connection;
    # this reduces how often pre_ping actually has to catch one.
    db_pool_recycle_seconds: int = 1800

    # JWT auth (M1). The default secret_key is dev-only — any real
    # deployment must override this via the environment, never ship
    # the default. Enforced below, not just documented: _validate_secret_key
    # refuses to start if app_env != "development" and this is still the
    # shipped default (BidOps_Final Milestone 5).
    secret_key: str = "dev-only-insecure-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # CORS (BidOps_Final Milestone 4). Comma-separated list of allowed
    # frontend origins, parsed in main.py. Defaults to the local Vite dev
    # server so local development is unaffected; a real deployment must set
    # this explicitly. Never a wildcard — an explicit, reviewable list only.
    allowed_origins: str = "http://localhost:5173"

    # Document storage (M2). Local disk for MVP — see storage.py for why.
    storage_root: str = "storage"
    max_upload_size_mb: int = 50

    # Storage backend (Phase 3: GCP deployment). "local" (default, unchanged
    # from M2) writes under storage_root on the container's own filesystem
    # -- fine for local dev, but Cloud Run's filesystem is ephemeral and not
    # shared across instances, so anything written there is not durable
    # application storage in production. "gcs" switches every document
    # read/write/delete to a Google Cloud Storage bucket instead, using the
    # exact same {company_id}/documents/{uuid}.{ext} key layout the local
    # backend already used as its relative path -- no document metadata
    # (Document.storage_path in the database) changes shape at all between
    # the two backends. Required when storage_backend="gcs".
    storage_backend: str = "local"
    gcs_bucket_name: str = ""

    # LLM provider. "mock" (default — every real provider is opt-in via
    # explicit configuration, per ADR-001; this default never changes
    # silently), "openai" (operational reference implementation — the only
    # provider with a verified end-to-end Decision Engine run), "gemini"
    # (Vertex AI mode below is the strategic long-term provider, pending
    # equivalent real production verification), or "qwen" (frozen —
    # Alibaba Cloud/DashScope is unreachable for new accounts from this
    # deployment's region; kept as a working, verified implementation, not
    # deleted). See 99_DECISIONS_LOG.md.
    llm_provider: str = "mock"

    # OpenAI (operational reference implementation — BidOps_Final
    # consolidation). Uses the official `openai` SDK. openai_base_url is an
    # escape hatch for local testing against a proxy/mock server; None by
    # default so the SDK's own default endpoint is used untouched.
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6"
    openai_base_url: str | None = None

    # OpenAI provider robustness. Same conservative posture as the other
    # providers — 60s timeout, 3 retries with exponential backoff
    # (base 1.0s -> waits of 1s/2s/4s). See llm_client.py's _backoff()
    # docstring for why exponential over fixed.
    #
    # Raised from the original 30s (Bug #008 investigation, 15 Aug 2026):
    # a real 30-page government tender's denser chunks (e.g. 5 pages of
    # dense legal/contract clauses) were timing out against gpt-5.6's
    # default "medium" reasoning_effort before a response ever came back
    # -- TCP connect/TLS succeeded instantly every attempt, only the
    # response itself stalled past 30s. This is a deliberately isolated,
    # single-variable change (see Bug Bucket) -- reasoning_effort,
    # chunk size, and retry logic are all left untouched so the effect
    # of this change alone can be measured before considering anything
    # else.
    openai_timeout_seconds: float = 120.0
    openai_max_retries: int = 3
    openai_retry_backoff_seconds: float = 1.0

    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    # Qwen provider robustness (M11). Conservative, production-reasonable
    # defaults — not aggressive. 30s covers realistic completion latency
    # for chat-completion-sized responses without masking a genuinely
    # hung connection. 3 retries with exponential backoff (base 1.0s ->
    # waits of 1s/2s/4s) absorbs momentary rate-limiting or network
    # blips without turning a real outage into a long hang; see
    # llm_client.py's _backoff() docstring for why exponential over fixed.
    qwen_timeout_seconds: float = 30.0
    qwen_max_retries: int = 3
    qwen_retry_backoff_seconds: float = 1.0

    # Gemini provider (strategic long-term provider — see module docstring
    # above). Uses the native `google-genai` SDK in Gemini Developer API
    # mode (a plain API key from Google AI Studio, not a GCP service
    # account) — see 99_DECISIONS_LOG.md for why the native SDK was chosen
    # over Gemini's OpenAI-compatibility endpoint. "gemini-2.5-flash" is
    # the default model: it sits on Gemini's permanent free tier.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Gemini authentication mode (Vertex AI migration). "developer" (default)
    # keeps the existing Gemini Developer API / API-key path exactly as-is --
    # this remains the local-dev path, since it needs zero GCP setup on a
    # new machine. "vertex" switches GeminiClient to Vertex AI mode
    # (Application Default Credentials, no API key, no JSON service-account
    # key file) -- the intended production path once verified. This is a
    # deliberate, explicit choice (validated below, fails fast at startup)
    # rather than an implicit fallback based on which credentials happen to
    # be present.
    gemini_auth_mode: str = "developer"

    # Required only when gemini_auth_mode="vertex". google_cloud_location
    # defaults to "us-central1" for the initial migration verification;
    # the us-central1-vs-asia-south1 (Mumbai) region decision is
    # deliberately deferred until after GeminiClient's Vertex path is
    # verified end-to-end -- see 99_DECISIONS_LOG.md.
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"

    # Gemini provider robustness (M11.5). Same conservative posture as
    # Qwen's, but implemented differently: the `google-genai` SDK has its
    # own built-in tenacity-based retry mechanism (unlike `openai`, which
    # has none), so these settings configure the SDK's native retry
    # rather than a hand-rolled loop — see GeminiClient in llm_client.py.
    # gemini_max_retry_delay_seconds exists because the SDK's retry
    # mechanism requires an explicit backoff ceiling; Qwen's hand-rolled
    # loop never needed one since qwen_max_retries alone bounds it.
    gemini_timeout_seconds: float = 30.0
    gemini_max_retries: int = 3
    gemini_retry_backoff_seconds: float = 1.0
    gemini_max_retry_delay_seconds: float = 30.0

    # Freshness (M4). No document specifies a number — 180 days (6 months)
    # is the proposed default, configurable rather than hardcoded.
    capability_staleness_days: int = 180

    # Tender chunking (M5). No document specifies a number — 5 pages per
    # chunk is the proposed default, configurable rather than hardcoded.
    tender_chunk_page_size: int = 5

    # Decision Intelligence (M6). No document specifies a number — 2 is
    # the proposed default, configurable rather than hardcoded.
    max_optional_review_items: int = 2

    # Decision Engine concurrency (RC-2 remediation): bounded, not unlimited
    # — caps how many per-requirement LLM matches run in parallel during one
    # evaluation. See app/services/decision_service.py::run_evaluation().
    decision_engine_max_concurrency: int = 5

    # Rate limiting (RC-2 audit finding H-2). On by default everywhere;
    # the test suite sets this false via a fixture so repeated calls in a
    # single test run are never throttled by accident.
    rate_limit_enabled: bool = True

    # Migration safety system (docs/BUG_BUCKET.md Bug #001). On startup,
    # the app compares the database's current Alembic revision against
    # the code's migration head -- see app/core/migration_guard.py.
    # migration_guard_enabled is a full kill switch (e.g. for a one-off
    # script that intentionally runs before migrating). Everywhere else,
    # leave it on. migration_guard_fail_on_mismatch controls what
    # happens on a detected mismatch: True (the default, everywhere,
    # including production) aborts startup outright per the engineering
    # rule that a schema mismatch is a fatal startup error, not a
    # runtime one. An operator can set this False in production only if
    # they've deliberately decided a logged warning is preferable to
    # startup downtime for their deployment process -- the check still
    # runs and still logs loudly either way, this only changes whether
    # it's allowed to block startup.
    migration_guard_enabled: bool = True
    migration_guard_fail_on_mismatch: bool = True

    # Google Authentication (Phase 2). This is the OAuth 2.0 Client ID
    # created in Google Cloud Console (APIs & Services -> Credentials ->
    # OAuth client ID -> Web application) -- a public identifier, safe to
    # also embed in the frontend, used here only to verify that an
    # incoming ID token was actually issued for *this* app (the `aud`
    # claim) and not lifted from some other Google-authenticated site.
    # Empty by default: POST /auth/google fails fast with a clear
    # configuration error rather than silently accepting tokens for any
    # audience if this is never set.
    google_oauth_client_id: str = ""

    # Contact form email delivery (Contact Form Backend feature). All
    # three default to empty/safe values deliberately -- local dev and
    # the test suite must both run with zero real Resend credentials
    # (see app/core/email.py, which treats a missing key or sender as
    # "email not configured," not a startup error). resend_api_key is a
    # secret (Secret Manager in production, see docs/DEPLOYMENT.md);
    # contact_sender_email must be an address/domain verified with
    # Resend before real sending works -- not invented here, since no
    # such domain has been configured yet. contact_notification_email
    # defaults to BidOps's existing, already-public contact address (the
    # same one the frontend's mailto fallback and Login.tsx's
    # forgot-password link already use) rather than leaving it unset.
    resend_api_key: str = ""
    contact_sender_email: str = ""
    contact_notification_email: str = "team.pramaan@gmail.com"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _validate_storage_backend(self) -> "Settings":
        """Same fail-fast-at-startup posture as GEMINI_AUTH_MODE below --
        an invalid or incomplete storage configuration should be impossible
        to accidentally boot with, not discovered on the first upload."""
        if self.storage_backend not in ("local", "gcs"):
            raise ValueError(
                f"STORAGE_BACKEND must be 'local' or 'gcs', got {self.storage_backend!r}."
            )
        if self.storage_backend == "gcs" and not self.gcs_bucket_name:
            raise ValueError("STORAGE_BACKEND=gcs requires GCS_BUCKET_NAME to be set.")
        return self

    @model_validator(mode="after")
    def _validate_gemini_auth_mode(self) -> "Settings":
        """
        Fail fast at process startup, not at the first Gemini call. Per the
        Vertex AI migration review: GEMINI_AUTH_MODE must be an explicit,
        valid choice -- never a silent fallback to whichever credentials
        happen to be configured.
        """
        if self.gemini_auth_mode not in ("developer", "vertex"):
            raise ValueError(
                f"GEMINI_AUTH_MODE must be 'developer' or 'vertex', got "
                f"{self.gemini_auth_mode!r}."
            )
        if self.gemini_auth_mode == "vertex" and not self.google_cloud_project:
            raise ValueError(
                "GEMINI_AUTH_MODE=vertex requires GOOGLE_CLOUD_PROJECT to be set."
            )
        return self

    @model_validator(mode="after")
    def _validate_secret_key(self) -> "Settings":
        """
        Fail fast at process startup (BidOps_Final Milestone 5), closing a
        gap flagged and left open across two prior sessions' handoff docs.

        Only enforced outside "development" -- app_env is itself explicit,
        developer-controlled configuration (same trust level as
        GEMINI_AUTH_MODE), so this never blocks a fresh local checkout that
        hasn't set app_env at all (it defaults to "development"). Anything
        else -- "staging", "production", or any other explicit value -- is
        being deliberately told "this is not a local dev box," and running
        it with the publicly-known default JWT signing secret would let
        anyone forge a valid access token for any user.
        """
        insecure_default = "dev-only-insecure-secret-change-me"
        if self.app_env != "development" and self.secret_key == insecure_default:
            raise ValueError(
                "SECRET_KEY is still the insecure default outside a development "
                "environment (APP_ENV != 'development'). Generate a real secret, "
                "e.g.: python -c \"import secrets; print(secrets.token_hex(32))\", "
                "and set it via the environment before starting this process."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — environment is read once per process, not per request."""
    return Settings()
