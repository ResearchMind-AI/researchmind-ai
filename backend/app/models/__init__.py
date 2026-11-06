"""
Database models package
Import all models here to ensure they're registered with SQLAlchemy
"""
from app.models.user import User
from app.models.team import Team, TeamMember, TeamRole
from app.models.session import Session, SessionMember, SessionStatus, SessionMemberRole
from app.models.paper import Paper, SessionPaper, PaperSource
from app.models.knowledge_map import KnowledgeNode, NodeRelationship, NodeType, RelationType

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
]
