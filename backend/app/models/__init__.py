"""
Database models package
Import all models here to ensure they're registered with SQLAlchemy
"""
from app.models.user import User
from app.models.team import Team, TeamMember, TeamRole
from app.models.session import Session, SessionMember, SessionStatus, SessionMemberRole
from app.models.paper import Paper, SessionPaper, PaperSource
from app.models.knowledge_map import KnowledgeNode, NodeRelationship, NodeType, RelationType
from app.models.research import PaperChunk, SessionMessage, SessionArtifact, ApiCache, Gap, WritingSection
from app.models.collab import Activity, Comment, Proposal, Suggestion, SessionVisit
from app.core.database import Base

__all__ = [
    "User",
    "Team",
    "TeamMember",
    "TeamRole",
    "Session",
    "SessionMember",
    "SessionStatus",
    "SessionMemberRole",
    "Paper",
    "SessionPaper",
    "PaperSource",
    "KnowledgeNode",
    "NodeRelationship",
    "NodeType",
    "RelationType",
    "PaperChunk",
    "SessionMessage",
    "SessionArtifact",
    "ApiCache",
    "Gap",
    "WritingSection",
    "Activity",
    "Comment",
    "Proposal",
    "Suggestion",
    "SessionVisit",
    "Base",
]
