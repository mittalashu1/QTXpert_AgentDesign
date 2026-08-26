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
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
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
    LLM_ROUTER_LOW_COST: str = "gemini:gemini-2.5-flash-lite,azure_openai:configured"
    LLM_ROUTER_STANDARD: str = "gemini:gemini-2.5-flash,azure_openai:configured"
    LLM_ROUTER_COMPLEX: str = "azure_openai:configured"
    LLM_ROUTER_FALLBACK: str = "azure_openai:configured"
    LLM_ROUTER_COMPLEX_INPUT_CHARS: int = 30000
    LLM_COST_RATES_JSON: str = "{}"

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

    @property
    def allowed_upload_extensions_list(self) -> List[str]:
        return [e.strip().lower() for e in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")]

    # ------------------------------------------------------------------ #
    # Mobile Autopilot prototype
    # ------------------------------------------------------------------ #
    AUTOPILOT_MAX_UPLOAD_SIZE_MB: int = Field(default=250, ge=1, le=2048)
    AUTOPILOT_STORAGE_PATH: str = "./storage/autopilot"
    AUTOPILOT_DB_PERSISTENCE_ENABLED: bool = True
    # Large APKs can take several minutes to install on an emulator or a
    # cloud device. Keep these limits explicit and configurable instead of
    # relying on Appium's 90-second default.
    AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS: int = Field(default=300, ge=30, le=900)
    AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS: int = Field(default=120, ge=30, le=600)
    AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS: int = Field(default=120, ge=30, le=600)
    AUTOPILOT_SMOKE_TIMEOUT_SECONDS: int = Field(default=600, ge=60, le=1800)
    AUTOPILOT_BROWSERSTACK_UPLOAD_TIMEOUT_SECONDS: int = Field(default=600, ge=60, le=1800)

    BROWSERSTACK_USERNAME: Optional[str] = None
    BROWSERSTACK_ACCESS_KEY: Optional[str] = None
    BROWSERSTACK_HUB_URL: str = "https://hub-cloud.browserstack.com/wd/hub"
    BROWSERSTACK_UPLOAD_URL: str = "https://api-cloud.browserstack.com/app-automate/upload"
    BROWSERSTACK_PROJECT_NAME: str = "QTXpert Autopilot"

    @property
    def browserstack_configured(self) -> bool:
        return bool(self.BROWSERSTACK_USERNAME and self.BROWSERSTACK_ACCESS_KEY)

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
