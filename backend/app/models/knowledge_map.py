"""
Knowledge Map models for AI-generated research synthesis
"""
import enum
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class NodeType(str, enum.Enum):
    """Type of knowledge node"""
    CONCEPT = "concept"  # Main research concept/theme
    METHOD = "method"  # Research methodology
    FINDING = "finding"  # Key finding or result
    GAP = "gap"  # Research gap
    TREND = "trend"  # Emerging trend


class RelationType(str, enum.Enum):
    """Type of relationship between nodes"""
    RELATED_TO = "related_to"  # General relationship
    DEPENDS_ON = "depends_on"  # Dependency relationship
    CONTRADICTS = "contradicts"  # Contradictory findings
    SUPPORTS = "supports"  # Supporting evidence
    EXTENDS = "extends"  # Extension/building upon


class KnowledgeNode(Base):
    """
    Knowledge node representing a concept, finding, or theme in the research
    """
    __tablename__ = "knowledge_nodes"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)

    # Node properties
    label = Column(String, nullable=False)  # Short label for the node
    description = Column(Text, nullable=True)  # Detailed description
    node_type = Column(SQLEnum(NodeType, name="nodetype", create_type=True), nullable=False)

    # Importance and positioning
    importance_score = Column(Float, default=0.0)  # 0-1 scale
    x_position = Column(Float, nullable=True)  # For graph visualization
    y_position = Column(Float, nullable=True)

    # Associated papers
    paper_ids = Column(JSON, nullable=True)  # List of paper IDs supporting this node
    citation_count = Column(Integer, default=0)  # Number of papers mentioning this

    # AI-generated content
    summary = Column(Text, nullable=True)  # AI-generated summary
    keywords = Column(JSON, nullable=True)  # Related keywords

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    session = relationship("Session", back_populates="knowledge_nodes")
    outgoing_relations = relationship(
        "NodeRelationship",
        back_populates="source_node",
        foreign_keys="NodeRelationship.source_node_id",
        cascade="all, delete-orphan"
    )
    incoming_relations = relationship(
        "NodeRelationship",
        back_populates="target_node",
        foreign_keys="NodeRelationship.target_node_id",
        cascade="all, delete-orphan"
    )


class NodeRelationship(Base):
    """
    Relationship between two knowledge nodes
    """
    __tablename__ = "node_relationships"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False)

    # Nodes in the relationship
    source_node_id = Column(Integer, ForeignKey("knowledge_nodes.id"), nullable=False)
    target_node_id = Column(Integer, ForeignKey("knowledge_nodes.id"), nullable=False)

    # Relationship properties
    relation_type = Column(SQLEnum(RelationType, name="relationtype", create_type=True), nullable=False)
    strength = Column(Float, default=0.5)  # 0-1 scale, confidence/strength of relationship
    description = Column(Text, nullable=True)  # Explanation of the relationship

    # Supporting evidence
    paper_ids = Column(JSON, nullable=True)  # Papers that evidence this relationship

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    session = relationship("Session")
    source_node = relationship("KnowledgeNode", foreign_keys=[source_node_id], back_populates="outgoing_relations")
    target_node = relationship("KnowledgeNode", foreign_keys=[target_node_id], back_populates="incoming_relations")
