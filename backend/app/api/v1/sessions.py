"""
Session management endpoints
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from app.core.database import get_db
from app.models.user import User
from app.models.session import Session, SessionMember, SessionMemberRole, SessionStatus
from app.models.team import TeamMember, TeamRole
from app.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionWithMembersResponse,
    SessionMemberCreate,
    SessionMemberUpdate,
    SessionMemberResponse,
)
from app.api.deps import get_current_active_user

router = APIRouter()


def check_session_permission(
    session_id: int,
    user: User,
    db: DBSession,
    required_roles: List[SessionMemberRole] = None
) -> Session:
    """
    Check if user has permission to access session

    Args:
        session_id: Session ID
        user: Current user
        db: Database session
        required_roles: Required roles to perform action (None = any member)

    Returns:
        Session object if user has permission

    Raises:
        HTTPException: If session not found or user lacks permission
    """
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Creator always has permission
    if session.creator_id == user.id:
        return session

    # Check membership
    membership = db.query(SessionMember).filter(
        SessionMember.session_id == session_id,
        SessionMember.user_id == user.id
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this session"
        )

    # Check role if required
    if required_roles and membership.role not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

    return session


@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    session_in: SessionCreate,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Create a new research session

    Args:
        session_in: Session creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created session object
    """
    # If team_id is provided, verify user is a member
    if session_in.team_id:
        team_member = db.query(TeamMember).filter(
            TeamMember.team_id == session_in.team_id,
            TeamMember.user_id == current_user.id
        ).first()

        if not team_member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be a team member to create a session for this team"
            )

    db_session = Session(
        title=session_in.title,
        description=session_in.description,
        topic=session_in.topic,
        research_question=session_in.research_question,
        creator_id=current_user.id,
        team_id=session_in.team_id
    )

    db.add(db_session)
    db.commit()
    db.refresh(db_session)

    return db_session


@router.get("/", response_model=List[SessionResponse])
def list_sessions(
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db),
    team_id: int = None,
    status_filter: SessionStatus = None
):
    """
    List all sessions the current user has access to

    Args:
        current_user: Current authenticated user
        db: Database session
        team_id: Optional filter by team ID
        status_filter: Optional filter by status

    Returns:
        List of sessions
    """
    # Build query
    query = db.query(Session)

    # Filter by team if specified
    if team_id:
        query = query.filter(Session.team_id == team_id)

    # Filter by status if specified
    if status_filter:
        query = query.filter(Session.status == status_filter)

    # Get sessions created by user
    owned_sessions = query.filter(Session.creator_id == current_user.id).all()

    # Get sessions where user is a member
    memberships = db.query(SessionMember).filter(SessionMember.user_id == current_user.id).all()
    member_session_ids = [m.session_id for m in memberships]

    member_sessions = query.filter(Session.id.in_(member_session_ids)).all() if member_session_ids else []

    # Combine and deduplicate
    all_sessions = {s.id: s for s in owned_sessions + member_sessions}

    return list(all_sessions.values())


@router.get("/{session_id}", response_model=SessionWithMembersResponse)
def get_session(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Get session details with members

    Args:
        session_id: Session ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Session object with members
    """
    session = check_session_permission(session_id, current_user, db)
    return session


@router.put("/{session_id}", response_model=SessionResponse)
def update_session(
    session_id: int,
    session_in: SessionUpdate,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Update session details (creator or lead only)

    Args:
        session_id: Session ID
        session_in: Session update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated session object
    """
    session = check_session_permission(session_id, current_user, db, [SessionMemberRole.LEAD])

    # Update fields
    if session_in.title is not None:
        session.title = session_in.title
    if session_in.description is not None:
        session.description = session_in.description
    if session_in.topic is not None:
        session.topic = session_in.topic
    if session_in.research_question is not None:
        session.research_question = session_in.research_question
    if session_in.status is not None:
        session.status = session_in.status

    db.commit()
    db.refresh(session)

    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Delete a session (creator only)

    Args:
        session_id: Session ID
        current_user: Current authenticated user
        db: Database session
    """
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )

    # Only creator can delete session
    if session.creator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only session creator can delete session"
        )

    db.delete(session)
    db.commit()


@router.post("/{session_id}/members", response_model=SessionMemberResponse, status_code=status.HTTP_201_CREATED)
def add_session_member(
    session_id: int,
    member_in: SessionMemberCreate,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Add a member to the session (creator or lead only)

    Args:
        session_id: Session ID
        member_in: Member data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created session member object
    """
    session = check_session_permission(session_id, current_user, db, [SessionMemberRole.LEAD])

    # Check if user exists
    user_to_add = db.query(User).filter(User.id == member_in.user_id).first()
    if not user_to_add:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if already a member
    existing_member = db.query(SessionMember).filter(
        SessionMember.session_id == session_id,
        SessionMember.user_id == member_in.user_id
    ).first()

    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a session member"
        )

    # Add member
    db_member = SessionMember(
        session_id=session_id,
        user_id=member_in.user_id,
        role=member_in.role
    )

    db.add(db_member)
    db.commit()
    db.refresh(db_member)

    return db_member


@router.put("/{session_id}/members/{user_id}", response_model=SessionMemberResponse)
def update_session_member_role(
    session_id: int,
    user_id: int,
    member_in: SessionMemberUpdate,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Update session member role (creator or lead only)

    Args:
        session_id: Session ID
        user_id: User ID to update
        member_in: Member update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated session member object
    """
    session = check_session_permission(session_id, current_user, db, [SessionMemberRole.LEAD])

    # Get member
    member = db.query(SessionMember).filter(
        SessionMember.session_id == session_id,
        SessionMember.user_id == user_id
    ).first()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session member not found"
        )

    # Update role
    member.role = member_in.role
    db.commit()
    db.refresh(member)

    return member


@router.delete("/{session_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_session_member(
    session_id: int,
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: DBSession = Depends(get_db)
):
    """
    Remove a member from the session (creator, lead, or self)

    Args:
        session_id: Session ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session
    """
    session = check_session_permission(session_id, current_user, db)

    # Can't remove creator
    if user_id == session.creator_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove session creator"
        )

    # Get member
    member = db.query(SessionMember).filter(
        SessionMember.session_id == session_id,
        SessionMember.user_id == user_id
    ).first()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session member not found"
        )

    # Check permission: creator, lead, or removing self
    if current_user.id != user_id:
        check_session_permission(session_id, current_user, db, [SessionMemberRole.LEAD])

    db.delete(member)
    db.commit()
