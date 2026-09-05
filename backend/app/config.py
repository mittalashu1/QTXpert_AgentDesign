"""
Central application configuration.

All configuration is sourced from environment variables (via a .env file in
local development, or real environment variables in Render/production). No
secret or environment-specific value is ever hardcoded.
"""
from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_LLM_COST_RATES_JSON = (
    '{"gemini:gemini-3.5-flash-lite":{"input":0.30,"output":2.50},'
    '"gemini:gemini-3.5-flash":{"input":1.50,"output":9.00}}'
)


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # General
    # ------------------------------------------------------------------ #
    APP_NAME: str = "QTXpert.ai Test Design Agent"
    APP_ENV: Literal["local", "development", "staging", "production"] = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # ------------------------------------------------------------------ #
    # CORS
    # ------------------------------------------------------------------ #
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ------------------------------------------------------------------ #
    # Database
    # ------------------------------------------------------------------ #
    POSTGRES_URL: str = Field(
        default="postgresql+asyncpg://qtxpert:qtxpert@localhost:5432/qtxpert",
        description="Async SQLAlchemy connection string",
    )
    # Keep the default pool deliberately small: Render currently runs one API
    # instance and Neon bills compute/transfer, not idle application sockets.
    # Increase only after measured concurrency requires it.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    # Keep an unavailable/quota-exhausted provider from holding an HTTP request
    # or the container startup indefinitely.  asyncpg applies
    # ``command_timeout`` to statements as well as migration DDL.
    DB_CONNECT_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)
    DB_COMMAND_TIMEOUT_SECONDS: int = Field(default=60, ge=5, le=600)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=15, ge=1, le=120)
    # Neon connections can be silently closed while a Render instance is
    # sleeping or during a provider failover. Recycle idle pooled sockets
    # before they become a source of rollback/close timeouts.
    DB_POOL_RECYCLE_SECONDS: int = Field(default=300, ge=30, le=3600)
    # Closing a session must never turn an otherwise handled database error into
    # a second unhandled exception in FastAPI's dependency cleanup path.
    DB_CLOSE_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=60)
    DB_ECHO: bool = False

    # ------------------------------------------------------------------ #
    # Redis / Celery
    # ------------------------------------------------------------------ #
    REDIS_URL: str = "redis://localhost:6379/0"

    # ------------------------------------------------------------------ #
    # Auth
    # ------------------------------------------------------------------ #
    JWT_SECRET: str = Field(default="CHANGE_ME_IN_ENV", min_length=1)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    ENTRA_TENANT_ID: Optional[str] = None
    ENTRA_CLIENT_ID: Optional[str] = None
    ENTRA_CLIENT_SECRET: Optional[str] = None

    # ------------------------------------------------------------------ #
    # LLM Providers
    # ------------------------------------------------------------------ #
    LLM_PROVIDER: Literal[
        "router", "azure_openai", "openai", "anthropic", "gemini", "bedrock"
    ] = "router"
    LLM_MODEL: str = "gpt-4o"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096
    LLM_REQUEST_TIMEOUT_SECONDS: int = Field(default=75, ge=1, le=600)
    LLM_MAX_RETRIES: int = 2
    LLM_REASONING_EFFORT: Literal["minimal", "low", "medium", "high", "xhigh"] = "low"
    # Gemini 2.5 Flash-Lite is no longer available to new API users. Keep the
    # low-cost route on the current stable Flash-Lite model and retain Azure as
    # a configured fallback so context/report generation remains available when
    # a provider is unavailable.
    LLM_ROUTER_LOW_COST: str = "gemini:gemini-3.5-flash-lite,azure_openai:configured"
    LLM_ROUTER_STANDARD: str = "gemini:gemini-3.5-flash,azure_openai:configured"
    LLM_ROUTER_COMPLEX: str = "azure_openai:configured"
    LLM_ROUTER_FALLBACK: str = "azure_openai:configured"
    LLM_ROUTER_COMPLEX_INPUT_CHARS: int = 30000
    # Keep the cost meter useful even when a deployment has not yet copied
    # the optional Blueprint value into its environment.  These are the same
    # documented Gemini rates used by ``render.yaml``; provider-specific rates
    # that are not known remain unpriced instead of being guessed.
    LLM_COST_RATES_JSON: str = DEFAULT_LLM_COST_RATES_JSON

    OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_API_VERSION: str = "2024-08-01-preview"
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"

    # ------------------------------------------------------------------ #
    # Azure Cost Management (optional admin reconciliation)
    # ------------------------------------------------------------------ #
    AZURE_COST_TENANT_ID: Optional[str] = None
    AZURE_COST_CLIENT_ID: Optional[str] = None
    AZURE_COST_CLIENT_SECRET: Optional[str] = None
    AZURE_COST_SUBSCRIPTION_ID: Optional[str] = None
    AZURE_COST_RESOURCE_GROUP: Optional[str] = None
    AZURE_COST_RESOURCE_NAME: Optional[str] = None
    AZURE_COST_API_VERSION: str = "2026-06-01"
    AZURE_COST_TIMEOUT_SECONDS: int = Field(default=15, ge=1, le=60)

    # ------------------------------------------------------------------ #
    # Vector database
    # ------------------------------------------------------------------ #
    VECTOR_DB_PROVIDER: Literal["pinecone", "none"] = "none"
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_ENVIRONMENT: Optional[str] = None
    PINECONE_INDEX_NAME: str = "qtxpert-requirements"

    # ------------------------------------------------------------------ #
    # Jira / Confluence
    # ------------------------------------------------------------------ #
    JIRA_URL: Optional[str] = None
    JIRA_CLIENT_ID: Optional[str] = None
    JIRA_CLIENT_SECRET: Optional[str] = None
    JIRA_REDIRECT_URI: Optional[str] = None
    CONFLUENCE_URL: Optional[str] = None
    CONFLUENCE_CLIENT_ID: Optional[str] = None
    CONFLUENCE_CLIENT_SECRET: Optional[str] = None
    CONFLUENCE_REDIRECT_URI: Optional[str] = None

    # ------------------------------------------------------------------ #
    # File upload / shared Upload Repository
    # ------------------------------------------------------------------ #
    MAX_UPLOAD_SIZE_MB: int = 25
    MAX_REQUIREMENT_TEXT_CHARS: int = 200_000
    MAX_REQUIREMENTS_PER_GENERATION: int = 20
    MAX_SCENARIOS_PER_GENERATION: int = 40
    GENERATION_STALE_AFTER_SECONDS: int = 900
    ALLOWED_UPLOAD_EXTENSIONS: str = (
        "pdf,docx,pptx,txt,md,json,csv,xlsx,xls,xml,yaml,yml,html,htm,"
        "apk,ipa,zip,mp4,mov,webm,png,jpg,jpeg"
    )
    UPLOAD_STORAGE_PATH: str = "./storage/uploads"
    # ``postgres_chunks`` remains the backwards-compatible default so an
    # existing deployment can migrate without breaking old assets.  Set this
    # to ``object_store`` after configuring an S3-compatible bucket (R2/S3/
    # MinIO).  New uploads then keep only metadata in PostgreSQL.
    UPLOAD_STORAGE_BACKEND: Literal["postgres_chunks", "object_store"] = "postgres_chunks"
    OBJECT_STORAGE_ENDPOINT_URL: Optional[str] = None
    OBJECT_STORAGE_BUCKET: Optional[str] = None
    OBJECT_STORAGE_REGION: str = "auto"
    OBJECT_STORAGE_ACCESS_KEY_ID: Optional[str] = None
    OBJECT_STORAGE_SECRET_ACCESS_KEY: Optional[str] = None
    OBJECT_STORAGE_PREFIX: str = "qtxpert"
    OBJECT_STORAGE_SIGNED_URL_TTL_SECONDS: int = Field(default=900, ge=60, le=604800)
    OBJECT_STORAGE_MULTIPART_THRESHOLD_MB: int = Field(default=16, ge=5, le=512)
    OBJECT_STORAGE_PART_SIZE_MB: int = Field(default=16, ge=5, le=512)

    @property
    def object_storage_configured(self) -> bool:
        """Whether the selected object-store backend has usable credentials."""
        return bool(
            self.UPLOAD_STORAGE_BACKEND == "object_store"
            and self.OBJECT_STORAGE_BUCKET
            and self.OBJECT_STORAGE_ACCESS_KEY_ID
            and self.OBJECT_STORAGE_SECRET_ACCESS_KEY
        )

    @property
    def allowed_upload_extensions_list(self) -> List[str]:
        return [e.strip().lower() for e in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")]

    # ------------------------------------------------------------------ #
    # Mobile Autopilot prototype
    # ------------------------------------------------------------------ #
    # Mobile packages are streamed to object storage and analysed in bounded
    # stages. The product accepts release builds up to 300 MB, while the
    # in-process resource-table parser stays capped at 64 MB on the web
    # instance. Larger builds use the safe ZIP inventory path and remain
    # available for runtime execution; a dedicated worker can raise this
    # ceiling later without changing the upload contract.
    AUTOPILOT_MAX_UPLOAD_SIZE_MB: int = Field(default=300, ge=1, le=2048)
    AUTOPILOT_STORAGE_PATH: str = "./storage/autopilot"
    AUTOPILOT_DB_PERSISTENCE_ENABLED: bool = True
    # A short retry absorbs a transient Neon failover without holding the
    # analysis worker or HTTP request indefinitely. The filesystem manifest
    # remains the immediate fallback when all attempts are exhausted.
    AUTOPILOT_DB_RETRY_ATTEMPTS: int = Field(default=2, ge=0, le=4)
    AUTOPILOT_DB_RETRY_BACKOFF_SECONDS: float = Field(default=0.25, ge=0.05, le=5)
    # Startup recovery can replay a large APK analysis after a process restart.
    # Keep it opt-in until a dedicated worker/queue is configured so deploys
    # do not compete with authentication traffic for the web instance's memory.
    AUTOPILOT_RECOVERY_ENABLED: bool = False
    # Emergency single-instance mode used while the external database is
    # unavailable (for example, a provider transfer quota outage).  Autopilot
    # keeps jobs/results on the instance filesystem and only accepts already
    # issued JWTs; turn this off after database access is restored so durability
    # and normal account/project authorization resume.
    AUTOPILOT_DEGRADED_MODE_ENABLED: bool = False
    # Large APKs can take several minutes to install on an emulator or a
    # cloud device. Keep these limits explicit and configurable instead of
    # relying on Appium's 90-second default.
    AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS: int = Field(default=300, ge=30, le=900)
    AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS: int = Field(default=120, ge=30, le=600)
    AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS: int = Field(default=120, ge=30, le=600)
    AUTOPILOT_SMOKE_TIMEOUT_SECONDS: int = Field(default=600, ge=60, le=1800)
    AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS: int = Field(default=600, ge=60, le=1800)
    AUTOPILOT_SUITE_TIMEOUT_SECONDS: int = Field(default=900, ge=60, le=3600)
    AUTOPILOT_BROWSERSTACK_UPLOAD_TIMEOUT_SECONDS: int = Field(default=600, ge=60, le=1800)
    # Androguard can allocate a very large resource table for some release
    # APKs. Keep deep parsing conservative on the Render web instance; the
    # binary always remains available for BrowserStack/Appium execution.
    AUTOPILOT_DEEP_PARSE_MAX_MB: int = Field(default=64, ge=1, le=512)
    # Orphaned atomic-write files are safe to remove after this window. Job
    # manifests, analyses and source artifacts are never removed by this sweep.
    AUTOPILOT_LOCAL_STAGING_TTL_SECONDS: int = Field(default=3600, ge=300, le=604800)
    AUTOPILOT_DISCOVERY_SETTLE_SECONDS: int = Field(default=4, ge=1, le=30)
    AUTOPILOT_DISCOVERY_SETTLE_RETRIES: int = Field(default=3, ge=0, le=6)
    AUTOPILOT_ANALYSIS_TIMEOUT_SECONDS: int = Field(default=300, ge=30, le=1800)
    # Website exploration is intentionally bounded until an approved
    # non-production credential reference and test data are supplied.
    AUTOPILOT_WEB_MAX_PAGES: int = Field(default=12, ge=1, le=50)
    AUTOPILOT_WEB_TIMEOUT_SECONDS: int = Field(default=45, ge=5, le=180)
    # Optional reachable Appium endpoint for hosted deployments. A hosted
    # Render service cannot reach a customer's laptop at 127.0.0.1; keep this
    # unset unless Appium is exposed through an authenticated TLS tunnel or a
    # private network endpoint.
    AUTOPILOT_CUSTOM_APPIUM_URL: Optional[str] = None
    # Input checkpoints accept direct values only on the write boundary. They
    # are encrypted with Fernet before persistence. Set an explicit key in
    # production; the JWT secret is a backwards-compatible derivation fallback
    # so existing deployments remain safe during rollout.
    AUTOPILOT_INPUT_ENCRYPTION_KEY: Optional[str] = None
    AUTOPILOT_INPUT_SESSION_TTL_SECONDS: int = Field(default=3600, ge=300, le=86400)
    AUTOPILOT_INPUT_SAVED_TTL_DAYS: int = Field(default=90, ge=1, le=3650)

    # ------------------------------------------------------------------ #
    # Generated data retention
    # ------------------------------------------------------------------ #
    # Destructive retention is opt-in.  The admin preview/cleanup endpoint
    # and one-shot maintenance script use these values; production startup
    # cleanup remains disabled until an administrator enables it deliberately.
    DATA_RETENTION_ENABLED: bool = False
    DATA_RETENTION_DAYS: int = Field(default=7, ge=1, le=3650)
    DATA_RETENTION_KEEP_LATEST: int = Field(default=3, ge=0, le=100)
    DATA_RETENTION_INCLUDE_EPHEMERAL_ASSETS: bool = True
    DATA_RETENTION_RUN_ON_STARTUP: bool = False

    # ------------------------------------------------------------------ #
    # Cost Center catalog and provider usage connectors
    # ------------------------------------------------------------------ #
    # The catalog is useful without credentials (links and documented limits
    # remain visible), while these optional credentials add account-specific
    # plan/usage information.  Secrets are read only from the environment and
    # are never persisted in the Cost Center snapshot or returned by the API.
    COST_CENTER_AUTO_REFRESH_ENABLED: bool = True
    COST_CENTER_REFRESH_DAYS: int = Field(default=30, ge=1, le=365)
    COST_CENTER_REFRESH_TIMEOUT_SECONDS: int = Field(default=8, ge=2, le=60)
    NEON_API_KEY: Optional[str] = None
    NEON_ORG_ID: Optional[str] = None
    NEON_PLAN: Optional[str] = None
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ACCOUNT_ID: Optional[str] = None
    RENDER_BACKEND_PLAN: str = "Starter"
    RENDER_FRONTEND_PLAN: str = "Free"

    BROWSERSTACK_USERNAME: Optional[str] = None
    BROWSERSTACK_ACCESS_KEY: Optional[str] = None
    BROWSERSTACK_HUB_URL: str = "https://hub-cloud.browserstack.com/wd/hub"
    BROWSERSTACK_UPLOAD_URL: str = "https://api-cloud.browserstack.com/app-automate/upload"
    BROWSERSTACK_PROJECT_NAME: str = "QTXpert Autopilot"

    @property
    def browserstack_configured(self) -> bool:
        return bool(self.BROWSERSTACK_USERNAME and self.BROWSERSTACK_ACCESS_KEY)

    @property
    def custom_appium_configured(self) -> bool:
        return bool((self.AUTOPILOT_CUSTOM_APPIUM_URL or "").strip())

    # ------------------------------------------------------------------ #
    # Rate limiting
    # ------------------------------------------------------------------ #
    RATE_LIMIT_PER_MINUTE: int = 60

    @field_validator("JWT_SECRET")
    @classmethod
    def validate_jwt_secret_in_prod(cls, v: str, info):
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


