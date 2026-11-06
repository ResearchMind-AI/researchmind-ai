"""
Configuration management for ResearchMindAI
Uses pydantic-settings for environment variable validation.

Optional API keys (OpenAlex, Semantic Scholar, PubMed, Anthropic) can be left
empty: the app still runs in "limited" mode and automatically uses higher
limits and extra features once a key is added.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import List, Union
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # Application
    APP_NAME: str = "ResearchMindAI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Database. PostgreSQL in Docker/AWS; "sqlite:///./researchmind.db" also works.
    DATABASE_URL: str = Field(
        default="postgresql://researchmind:devpassword@localhost:5432/researchmind_db",
        description="Database connection string"
    )

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # Security
    SECRET_KEY: str = Field(default="dev-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # If set, new accounts need this code (keeps a public test link private)
    INVITE_CODE: str = ""

    # CORS
    CORS_ORIGINS: Union[str, List[str]] = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:8501"
    )

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalise_database_url(cls, v: str) -> str:
        # Railway/Render/Heroku-style "postgres://" URLs are rejected by SQLAlchemy 2
        if v.startswith("postgres://"):
            return "postgresql://" + v[len("postgres://"):]
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # ── LLMs ──────────────────────────────────────────────────────────────────
    # OpenAI is required for embeddings. Chat/synthesis uses Claude when
    # ANTHROPIC_API_KEY is set, otherwise falls back to the OpenAI CHAT_MODEL.
    OPENAI_API_KEY: str = ""
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    CHAT_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-5-5"
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # ── Paper sources (all free) ──────────────────────────────────────────────
    # Leave keys empty to run in limited mode.
    OPENALEX_API_KEY: str = ""
    OPENALEX_EMAIL: str = ""
    SEMANTIC_SCHOLAR_API_KEY: str = ""
    PUBMED_API_KEY: str = ""
    PUBMED_EMAIL: str = ""
    CROSSREF_EMAIL: str = ""

    # Discovery tuning
    MAX_PAPERS_PER_SESSION: int = 40
    CACHE_TTL_HOURS: int = 72

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"

    # File Storage (uploaded PDFs are stored as extracted text in the database)
    UPLOAD_DIR: str = "../data/uploads"
    MAX_UPLOAD_SIZE: int = 52428800  # 50MB

    # Offline test mode: fake sources/LLM/embeddings, for tests and UI checks only.
    OFFLINE_DEMO: bool = False

    # Rate limiting (requests per second)
    SEMANTIC_SCHOLAR_RATE_LIMIT: float = 1.0
    PUBMED_RATE_LIMIT: float = 3.0
    OPENALEX_RATE_LIMIT: float = 10.0

    @property
    def llm_provider(self) -> str:
        return "anthropic" if self.ANTHROPIC_API_KEY else "openai"


# Global settings instance
settings = Settings()


def ensure_directories():
    """Create required directories if they don't exist"""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
