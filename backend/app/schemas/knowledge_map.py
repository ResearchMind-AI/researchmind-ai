"""
Pydantic schemas for knowledge map
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.models.knowledge_map import NodeType, RelationType


# Knowledge Node Schemas
class KnowledgeNodeBase(BaseModel):
    """Base knowledge node schema"""
    label: str = Field(..., min_length=1, max_length=200, description="Node label")
    description: Optional[str] = Field(None, description="Detailed description")
    node_type: NodeType = Field(..., description="Type of node")
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Importance score")
    keywords: Optional[List[str]] = Field(None, description="Related keywords")


class KnowledgeNodeCreate(KnowledgeNodeBase):
    """Schema for creating a knowledge node"""
    paper_ids: Optional[List[int]] = Field(None, description="Associated paper IDs")
    summary: Optional[str] = Field(None, description="AI-generated summary")
    x_position: Optional[float] = Field(None, description="X position for visualization")
    y_position: Optional[float] = Field(None, description="Y position for visualization")


class KnowledgeNodeUpdate(BaseModel):
    """Schema for updating a knowledge node"""
    label: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    importance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    x_position: Optional[float] = None
    y_position: Optional[float] = None
    keywords: Optional[List[str]] = None


class KnowledgeNodeResponse(KnowledgeNodeBase):
    """Schema for knowledge node response"""
    id: int
    session_id: int
    paper_ids: Optional[List[int]]
    citation_count: int
    summary: Optional[str]
    x_position: Optional[float]
    y_position: Optional[float]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# Node Relationship Schemas
class NodeRelationshipBase(BaseModel):
    """Base relationship schema"""
    source_node_id: int
    target_node_id: int
    relation_type: RelationType
    strength: float = Field(default=0.5, ge=0.0, le=1.0, description="Relationship strength")
    description: Optional[str] = Field(None, description="Relationship description")


class NodeRelationshipCreate(NodeRelationshipBase):
    """Schema for creating a relationship"""
    paper_ids: Optional[List[int]] = Field(None, description="Supporting paper IDs")


class NodeRelationshipUpdate(BaseModel):
    """Schema for updating a relationship"""
    relation_type: Optional[RelationType] = None
    strength: Optional[float] = Field(None, ge=0.0, le=1.0)
    description: Optional[str] = None


class NodeRelationshipResponse(NodeRelationshipBase):
    """Schema for relationship response"""
    id: int
    session_id: int
    paper_ids: Optional[List[int]]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# Knowledge Map Schemas
class KnowledgeMapResponse(BaseModel):
    """Complete knowledge map for a session"""
    session_id: int
    nodes: List[KnowledgeNodeResponse]
    relationships: List[NodeRelationshipResponse]
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class KnowledgeMapGenerationRequest(BaseModel):
    """Request to generate/regenerate knowledge map"""
    force_regenerate: bool = Field(default=False, description="Force regeneration even if map exists")
    max_nodes: int = Field(default=20, ge=5, le=100, description="Maximum number of nodes to generate")
    focus_areas: Optional[List[str]] = Field(None, description="Specific areas to focus on")


class KnowledgeMapGenerationResponse(BaseModel):
    """Response after knowledge map generation"""
    session_id: int
    nodes_created: int
    relationships_created: int
    processing_time: float
    message: str


class NodeSearchRequest(BaseModel):
    """Request to search for nodes"""
    query: str = Field(..., min_length=1, description="Search query")
    node_types: Optional[List[NodeType]] = Field(None, description="Filter by node types")
    min_importance: Optional[float] = Field(None, ge=0.0, le=1.0, description="Minimum importance score")


class NodeSearchResponse(BaseModel):
    """Response for node search"""
    query: str
    total_results: int
    nodes: List[KnowledgeNodeResponse]
