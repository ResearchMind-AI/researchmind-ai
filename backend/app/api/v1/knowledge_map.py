"""
Knowledge Map API endpoints
Handles knowledge map generation, retrieval, and management
"""
import time
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.models.user import User
from app.models.knowledge_map import KnowledgeNode, NodeRelationship
from app.schemas.knowledge_map import (
    KnowledgeMapResponse,
    KnowledgeMapGenerationRequest,
    KnowledgeMapGenerationResponse,
    KnowledgeNodeResponse,
    NodeRelationshipResponse,
    KnowledgeNodeCreate,
    KnowledgeNodeUpdate,
    NodeRelationshipCreate,
)
from app.api.deps import get_current_active_user
from app.api.v1.sessions import check_session_permission
from app.models.session import SessionMemberRole

EDIT_ROLES = [SessionMemberRole.LEAD, SessionMemberRole.CONTRIBUTOR]
from app.services.knowledge_map_service import KnowledgeMapService
import logging

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/sessions/{session_id}/generate", response_model=KnowledgeMapGenerationResponse)
async def generate_knowledge_map(
    session_id: int,
    request: KnowledgeMapGenerationRequest,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Generate or regenerate knowledge map for a session

    Args:
        session_id: Session ID
        request: Generation parameters
        current_user: Current authenticated user
        db: Database session

    Returns:
        Generation response with statistics
    """
    # Check session permission
    check_session_permission(session_id, current_user, db, EDIT_ROLES)

    # Generate knowledge map
    service = KnowledgeMapService()
    start_time = time.time()

    try:
        nodes_created, relationships_created = await service.generate_knowledge_map(
            session_id=session_id,
            db=db,
            max_nodes=request.max_nodes,
            force_regenerate=request.force_regenerate
        )

        processing_time = time.time() - start_time

        return KnowledgeMapGenerationResponse(
            session_id=session_id,
            nodes_created=nodes_created,
            relationships_created=relationships_created,
            processing_time=processing_time,
            message=f"Successfully generated knowledge map with {nodes_created} nodes and {relationships_created} relationships"
        )

    except Exception as e:
        logger.error(f"Error generating knowledge map: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate knowledge map: {str(e)}"
        )


@router.get("/sessions/{session_id}", response_model=KnowledgeMapResponse)
def get_knowledge_map(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Get complete knowledge map for a session

    Args:
        session_id: Session ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Complete knowledge map with nodes and relationships
    """
    # Check session permission
    check_session_permission(session_id, current_user, db)

    # Get nodes
    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.session_id == session_id
    ).all()

    # Get relationships
    relationships = db.query(NodeRelationship).filter(
        NodeRelationship.session_id == session_id
    ).all()

    return KnowledgeMapResponse(
        session_id=session_id,
        nodes=[KnowledgeNodeResponse.from_orm(n) for n in nodes],
        relationships=[NodeRelationshipResponse.from_orm(r) for r in relationships],
        metadata={
            "total_nodes": len(nodes),
            "total_relationships": len(relationships)
        }
    )


@router.get("/sessions/{session_id}/nodes", response_model=List[KnowledgeNodeResponse])
def list_nodes(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    List all knowledge nodes in a session

    Args:
        session_id: Session ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of knowledge nodes
    """
    # Check session permission
    check_session_permission(session_id, current_user, db)

    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.session_id == session_id
    ).order_by(KnowledgeNode.importance_score.desc()).all()

    return nodes


@router.get("/nodes/{node_id}", response_model=KnowledgeNodeResponse)
def get_node(
    node_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Get a specific knowledge node

    Args:
        node_id: Node ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Knowledge node details
    """
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()

    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found"
        )

    # Check session permission
    check_session_permission(node.session_id, current_user, db)

    return node


@router.put("/nodes/{node_id}", response_model=KnowledgeNodeResponse)
def update_node(
    node_id: int,
    update_data: KnowledgeNodeUpdate,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Update a knowledge node

    Args:
        node_id: Node ID
        update_data: Update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated node
    """
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()

    if not node:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Node not found"
        )

    # Check session permission
    check_session_permission(node.session_id, current_user, db, EDIT_ROLES)

    # Update fields
    if update_data.label is not None:
        node.label = update_data.label
    if update_data.description is not None:
        node.description = update_data.description
    if update_data.importance_score is not None:
        node.importance_score = update_data.importance_score
    if update_data.x_position is not None:
        node.x_position = update_data.x_position
    if update_data.y_position is not None:
        node.y_position = update_data.y_position
    if update_data.keywords is not None:
        node.keywords = update_data.keywords

    db.commit()
    db.refresh(node)

    return node


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_knowledge_map(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Delete entire knowledge map for a session

    Args:
        session_id: Session ID
        current_user: Current authenticated user
        db: Database session
    """
    # Check session permission
    check_session_permission(session_id, current_user, db, EDIT_ROLES)

    # Delete relationships first (foreign key constraint)
    db.query(NodeRelationship).filter(NodeRelationship.session_id == session_id).delete()

    # Delete nodes
    db.query(KnowledgeNode).filter(KnowledgeNode.session_id == session_id).delete()

    db.commit()
