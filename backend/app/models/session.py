"""
Session model for research sessions
Manages research collaboration sessions with status tracking and member management
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class SessionStatus(str, enum.Enum):
    """Session status enum"""
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SessionMemberRole(str, enum.Enum):
    """Session member role enum"""
    LEAD = "lead"
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class Session(Base):
    """Research session model"""
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    topic = Column(String, nullable=True)
    research_question = Column(Text, nullable=True)
    status = Column(
        SQLEnum(SessionStatus, name="sessionstatus", create_type=True),
        default=SessionStatus.ACTIVE,
        nullable=False
    )

    # Foreign keys
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    creator = relationship("User", back_populates="sessions")
    team = relationship("Team", back_populates="sessions")
    members = relationship("SessionMember", back_populates="session", cascade="all, delete-orphan")
    session_papers = relationship("SessionPaper", back_populates="session", cascade="all, delete-orphan")
    knowledge_nodes = relationship("KnowledgeNode", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Session(id={self.id}, title={self.title}, status={self.status})>"


class SessionMember(Base):
    """Session member model for tracking session collaborators"""
    __tablename__ = "session_members"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(
        SQLEnum(SessionMemberRole, name="sessionmemberrole", create_type=True),
        default=SessionMemberRole.CONTRIBUTOR,
        nullable=False
    )

    # Timestamps
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("Session", back_populates="members")
    user = relationship("User")

    def __repr__(self):
        return f"<SessionMember(session_id={self.session_id}, user_id={self.user_id}, role={self.role})>"
