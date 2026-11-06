"""Test setup: SQLite database + offline fakes (no network, no API keys)."""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["OFFLINE_DEMO"] = "true"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402

from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def make_user(db):
    from app.core.security import get_password_hash
    from app.models.user import User

    def _make(email="owner@example.com"):
        u = User(email=email, hashed_password=get_password_hash("password123"), full_name=email.split("@")[0])
        db.add(u)
        db.commit()
        return u
    return _make


@pytest.fixture()
def make_session(db):
    from app.models.session import Session

    def _make(user, topic="LLMs for clinical decision support"):
        s = Session(title=topic, topic=topic, creator_id=user.id)
        db.add(s)
        db.commit()
        return s
    return _make
