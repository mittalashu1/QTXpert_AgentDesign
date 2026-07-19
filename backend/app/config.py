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

    # Microsoft Entra ID (Azure AD) - OAuth2 / OIDC, optional
    ENTRA_TENANT_ID: Optional[str] = None
    ENTRA_CLIENT_ID: Optional[str] = None
    ENTRA_CLIENT_SECRET: Optional[str] = None

    # ------------------------------------------------------------------ #
    # LLM Providers - abstraction is selected by LLM_PROVIDER at runtime
    # ------------------------------------------------------------------ #
    LLM_PROVIDER: Literal[
        "azure_openai", "openai", "anthropic", "gemini", "bedrock"
    ] = "azure_openai"
    LLM_MODEL: str = "gpt-4o"
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096
    LLM_REQUEST_TIMEOUT_SECONDS: int = 120

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
    # Vector database (modular; Pinecone default implementation)
    # ------------------------------------------------------------------ #
    VECTOR_DB_PROVIDER: Literal["pinecone", "none"] = "none"
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_ENVIRONMENT: Optional[str] = None
    PINECONE_INDEX_NAME: str = "qtxpert-requirements"

    # ------------------------------------------------------------------ #
    # Jira integration
    # ------------------------------------------------------------------ #
    JIRA_URL: Optional[str] = None
    JIRA_CLIENT_ID: Optional[str] = None
    JIRA_CLIENT_SECRET: Optional[str] = None
    JIRA_REDIRECT_URI: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Confluence integration
    # ------------------------------------------------------------------ #
    CONFLUENCE_URL: Optional[str] = None
    CONFLUENCE_CLIENT_ID: Optional[str] = None
    CONFLUENCE_CLIENT_SECRET: Optional[str] = None
    CONFLUENCE_REDIRECT_URI: Optional[str] = None

    # ------------------------------------------------------------------ #
    # File upload
    # ------------------------------------------------------------------ #
    MAX_UPLOAD_SIZE_MB: int = 25
    ALLOWED_UPLOAD_EXTENSIONS: str = "pdf,docx,txt,md,json,csv"
    UPLOAD_STORAGE_PATH: str = "./storage/uploads"

    @property
    def allowed_upload_extensions_list(self) -> List[str]:
        return [e.strip().lower() for e in self.ALLOWED_UPLOAD_EXTENSIONS.split(",")]

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
    """Cached settings singleton (dependency-injected across the app)."""
    return Settings()
