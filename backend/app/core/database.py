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

    if engine.dialect.name != "postgresql":
        Base.metadata.create_all(bind=engine)
        _add_missing_columns()
        with engine.begin() as conn:
            backfill_ref_numbers(conn)
        return

    # The UI and API may start at the same time against an empty database.
    # A transaction-scoped advisory lock makes table creation run one at a time.
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(7724831)"))
        Base.metadata.create_all(bind=conn)
        # Databases created before the POC have a "papersource" enum without ARXIV.
        conn.execute(text("ALTER TYPE papersource ADD VALUE IF NOT EXISTS 'ARXIV'"))
        # Columns added after the first deployment
        for table, column, ddl in NEW_COLUMNS:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"))
        backfill_ref_numbers(conn)


# (table, column, type) added to existing tables after first release; create_all
# only creates missing tables, so these are added explicitly and idempotently.
NEW_COLUMNS = [
    ("session_messages", "gap_id", "INTEGER"),
    ("session_papers", "ref_no", "INTEGER"),
    ("session_papers", "status", "VARCHAR(16) NOT NULL DEFAULT 'kept'"),
    ("session_papers", "is_key", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("session_papers", "removed_reason", "VARCHAR(64)"),
    ("session_papers", "status_by_user_id", "INTEGER"),
    ("session_papers", "status_at", "TIMESTAMP WITH TIME ZONE"),
    ("writing_sections", "owner_id", "INTEGER"),
    ("writing_sections", "version", "INTEGER NOT NULL DEFAULT 0"),
]


def backfill_ref_numbers(conn) -> None:
    """Give papers added before fixed numbering their number, in the order the
    app showed them (most relevant first, then date added), after any numbered ones."""
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT id, session_id FROM session_papers WHERE ref_no IS NULL "
        "ORDER BY session_id, CASE WHEN relevance_score IS NULL THEN 1 ELSE 0 END, relevance_score DESC, id")).fetchall()
    if not rows:
        return
    top = dict(conn.execute(text(
        "SELECT session_id, MAX(ref_no) FROM session_papers WHERE ref_no IS NOT NULL GROUP BY session_id")).fetchall())
    for row_id, sid in rows:
        top[sid] = (top.get(sid) or 0) + 1
        conn.execute(text("UPDATE session_papers SET ref_no = :n WHERE id = :i"), {"n": top[sid], "i": row_id})


def _add_missing_columns():
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in NEW_COLUMNS:
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
