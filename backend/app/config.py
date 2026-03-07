"""
Configuration management for ResearchMindAI
Uses pydantic-settings for environment variable validation
"""
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import List, Union
import os

class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Application
    APP_NAME: str = "ResearchMindAI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = Field(
        default="postgresql://researchmind:devpassword@localhost:5432/researchmind_db",
        description="PostgreSQL database connection string"
    )

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string"
    )

    # Security
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production",
        description="Secret key for JWT encoding"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # CORS
    CORS_ORIGINS: Union[str, List[str]] = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Allowed CORS origins (comma-separated string or list)"
    )

    @model_validator(mode="after")
    def parse_cors_origins(self):
        """Convert CORS_ORIGINS from comma-separated string to list"""
        if isinstance(self.CORS_ORIGINS, str):
            self.CORS_ORIGINS = [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
        return self

    # OpenAI
    OPENAI_API_KEY: str = Field(
        default="",
        description="OpenAI API key for embeddings and chat"
    )

    # PubMed
    PUBMED_API_KEY: str = Field(
        default="",
        description="PubMed API key (optional but recommended)"
    )
    PUBMED_EMAIL: str = Field(
        default="",
        description="Email for PubMed API (required for higher rate limits)"
    )

    # OpenAlex
    OPENALEX_EMAIL: str = Field(
        default="",
        description="Email for OpenAlex polite pool (recommended)"
    )

    # Celery
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Celery broker URL"
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/0",
        description="Celery result backend URL"
    )

    # File Storage
    UPLOAD_DIR: str = Field(
        default="../data/uploads",
        description="Directory for uploaded files"
    )
    MAX_UPLOAD_SIZE: int = Field(
        default=52428800,  # 50MB
        description="Maximum upload file size in bytes"
    )

    # Vector Store
    CHROMA_PERSIST_DIR: str = Field(
        default="../data/chroma",
        description="Chroma persistence directory"
    )

    # Rate Limiting
    SEMANTIC_SCHOLAR_RATE_LIMIT: float = 1.0  # requests per second
    PUBMED_RATE_LIMIT: float = 3.0  # requests per second (with API key)
    OPENALEX_RATE_LIMIT: float = 10.0  # requests per second (polite pool)

    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()


# Ensure required directories exist
def ensure_directories():
    """Create required directories if they don't exist"""
    directories = [
        settings.UPLOAD_DIR,
        settings.CHROMA_PERSIST_DIR,
    ]

    for directory in directories:
        os.makedirs(directory, exist_ok=True)
