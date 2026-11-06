"""
Database configuration and session management (SQLAlchemy 2.0)
Works with PostgreSQL (Docker/AWS RDS) and SQLite (quick local runs, tests).
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=False,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables (idempotent)"""
    import app.models  # noqa: F401  (registers all models)
    from sqlalchemy import text

    Base.metadata.create_all(bind=engine)

    # Databases created before the POC have a "papersource" enum without ARXIV.
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("ALTER TYPE papersource ADD VALUE IF NOT EXISTS 'ARXIV'"))
