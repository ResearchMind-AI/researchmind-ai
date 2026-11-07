"""
Paper models for research document management
"""
import enum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Enum as SQLEnum, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, false
from app.core.database import Base


class PaperSource(str, enum.Enum):
    """Source of the paper"""
    PUBMED = "pubmed"
    OPENALEX = "openalex"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    MANUAL_UPLOAD = "manual_upload"


class Paper(Base):
    """
    Research paper model
    Stores metadata and content of academic papers
    """
    __tablename__ = "papers"

    id = Column(Integer, primary_key=True, index=True)

    # Basic metadata
    title = Column(String, nullable=False, index=True)
    abstract = Column(Text, nullable=True)
    authors = Column(JSON, nullable=True)  # List of author names
    publication_date = Column(DateTime(timezone=True), nullable=True)
    journal = Column(String, nullable=True)
    doi = Column(String, nullable=True, unique=True, index=True)

    # Source information
    source = Column(SQLEnum(PaperSource, name="papersource", create_type=True), nullable=False)
    source_id = Column(String, nullable=True, index=True)  # ID from external API (PubMed ID, OpenAlex ID, etc.)

    # Content
    full_text = Column(Text, nullable=True)  # Extracted text content
    file_path = Column(String, nullable=True)  # Path to uploaded PDF/DOCX
    url = Column(String, nullable=True)  # External URL to paper

    # Additional metadata
    keywords = Column(JSON, nullable=True)  # List of keywords/topics
    citations_count = Column(Integer, default=0)
    extra_metadata = Column(JSON, nullable=True)  # Additional metadata from APIs

    # Vector embedding info
    embedding_generated = Column(Boolean, default=False)
    embedding_model = Column(String, nullable=True)  # e.g., "text-embedding-ada-002"

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    session_papers = relationship("SessionPaper", back_populates="paper", cascade="all, delete-orphan")


class SessionPaper(Base):
    """
    Association between sessions and papers
    Tracks which papers are added to which research sessions
    """
    __tablename__ = "session_papers"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    paper_id = Column(Integer, ForeignKey("papers.id"), nullable=False)

    # User who added this paper to the session
    added_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Notes or annotations for this paper in this session
    notes = Column(Text, nullable=True)

    # Relevance score (optional, for AI-suggested papers)
    relevance_score = Column(Integer, nullable=True)  # 1-5 scale

    # Fixed citation number [n] in this session. Assigned once, never reused,
    # so citations in the researcher's writing always point at the same paper.
    ref_no = Column(Integer, nullable=True)

    # Triage: "kept" papers feed themes, gaps, chat and writing; "removed" ones don't.
    status = Column(String(16), nullable=False, default="kept", server_default="kept")
    is_key = Column(Boolean, nullable=False, default=False, server_default=false())
    removed_reason = Column(String(64), nullable=True)
    status_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("Session", back_populates="session_papers")
    paper = relationship("Paper", back_populates="session_papers")
    added_by = relationship("User", foreign_keys=[added_by_user_id])
