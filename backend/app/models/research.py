"""
POC research models: per-session vector chunks, chat history, API cache and
saved analysis artifacts. Everything lives in the SQL database so the app has
a single stateful dependency (PostgreSQL on AWS RDS, or SQLite locally).
"""
from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class PaperChunk(Base):
    """A chunk of a paper's text with its embedding, scoped to one session.

    Embeddings are per session by design (blueprint section 9): the same paper
    added to two sessions is embedded for each.
    """
    __tablename__ = "paper_chunks"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    paper_id = Column(Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=False)  # list[float]
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SessionMessage(Base):
    """Chat message in a session (user question or assistant answer)."""
    __tablename__ = "session_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    role = Column(String(16), nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)  # [{"n": 1, "paper_id": 5, "title": ...}]
    gap_id = Column(Integer, nullable=True, index=True)  # set when the message belongs to a gap's thread
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SessionArtifact(Base):
    """Saved generated output for a session, e.g. discovery stats or a lit review."""
    __tablename__ = "session_artifacts"
    __table_args__ = (UniqueConstraint("session_id", "kind", name="uq_session_artifact_kind"),)

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(50), nullable=False)
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApiCache(Base):
    """Cache of external API responses, to save free-tier quota."""
    __tablename__ = "api_cache"

    id = Column(Integer, primary_key=True)
    cache_key = Column(String(64), unique=True, nullable=False, index=True)  # sha256 hex
    source = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Gap(Base):
    """A research gap: suggested by the AI or added by a user, optionally pinned."""
    __tablename__ = "gaps"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, nullable=True)
    gap_type = Column(String(50), nullable=True)
    research_question = Column(Text, nullable=True)
    confidence = Column(String(20), nullable=True)
    evidence_paper_ids = Column(JSON, nullable=True)   # papers that show the gap
    source = Column(String(10), nullable=False, default="ai")  # "ai" | "user"
    pinned = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="open")  # open | exploring | promising | dropped
    notes = Column(Text, nullable=True)
    assessment = Column(JSON, nullable=True)  # evidence for/against + novelty check result
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WritingSection(Base):
    """One section of the user's literature review: AI guidance plus the user's own text."""
    __tablename__ = "writing_sections"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0)
    heading = Column(String(300), nullable=False)
    kind = Column(String(20), nullable=False, default="theme")  # intro | theme | gaps | conclusion | custom
    guidance = Column(JSON, nullable=True)   # points, agreements, disagreements, questions, target_words
    user_text = Column(Text, nullable=True)
    feedback = Column(JSON, nullable=True)   # last "check my section" result
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
