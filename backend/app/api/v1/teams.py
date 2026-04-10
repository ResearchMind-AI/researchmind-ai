"""
Team management endpoints
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.models.team import Team, TeamMember, TeamRole
from app.schemas.team import (
    TeamCreate,
    TeamUpdate,
    TeamResponse,
    TeamWithMembersResponse,
    TeamMemberCreate,
    TeamMemberUpdate,
    TeamMemberResponse,
)
from app.api.deps import get_current_active_user

router = APIRouter()


def check_team_permission(
    team_id: int,
    user: User,
    db: Session,
    required_roles: List[TeamRole] = None
) -> Team:
    """
    Check if user has permission to access team

    Args:
        team_id: Team ID
        user: Current user
        db: Database session
        required_roles: Required roles to perform action (None = any member)

    Returns:
        Team object if user has permission

    Raises:
        HTTPException: If team not found or user lacks permission
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Owner always has permission
    if team.owner_id == user.id:
        return team

    # Check membership
    membership = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == user.id
    ).first()

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this team"
        )

    # Check role if required
    if required_roles and membership.role not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

    return team


@router.post("/", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
def create_team(
    team_in: TeamCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Create a new team

    Args:
        team_in: Team creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created team object
    """
    db_team = Team(
        name=team_in.name,
        description=team_in.description,
        owner_id=current_user.id
    )

    db.add(db_team)
    db.commit()
    db.refresh(db_team)

    return db_team


@router.get("/", response_model=List[TeamResponse])
def list_teams(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    List all teams the current user owns or is a member of

    Args:
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of teams
    """
    # Get teams owned by user
    owned_teams = db.query(Team).filter(Team.owner_id == current_user.id).all()

    # Get teams where user is a member
    memberships = db.query(TeamMember).filter(TeamMember.user_id == current_user.id).all()
    member_team_ids = [m.team_id for m in memberships]
    member_teams = db.query(Team).filter(Team.id.in_(member_team_ids)).all() if member_team_ids else []

    # Combine and deduplicate
    all_teams = {team.id: team for team in owned_teams + member_teams}

    return list(all_teams.values())


@router.get("/{team_id}", response_model=TeamWithMembersResponse)
def get_team(
    team_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Get team details with members

    Args:
        team_id: Team ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Team object with members
    """
    team = check_team_permission(team_id, current_user, db)
    return team


@router.put("/{team_id}", response_model=TeamResponse)
def update_team(
    team_id: int,
    team_in: TeamUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Update team details (owner or admin only)

    Args:
        team_id: Team ID
        team_in: Team update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated team object
    """
    team = check_team_permission(team_id, current_user, db, [TeamRole.OWNER, TeamRole.ADMIN])

    # Update fields
    if team_in.name is not None:
        team.name = team_in.name
    if team_in.description is not None:
        team.description = team_in.description

    db.commit()
    db.refresh(team)

    return team


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Delete a team (owner only)

    Args:
        team_id: Team ID
        current_user: Current authenticated user
        db: Database session
    """
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found"
        )

    # Only owner can delete team
    if team.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team owner can delete team"
        )

    db.delete(team)
    db.commit()


@router.post("/{team_id}/members", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
def add_team_member(
    team_id: int,
    member_in: TeamMemberCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Add a member to the team (owner or admin only)

    Args:
        team_id: Team ID
        member_in: Member data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created team member object
    """
    team = check_team_permission(team_id, current_user, db, [TeamRole.OWNER, TeamRole.ADMIN])

    # Check if user exists
    user_to_add = db.query(User).filter(User.id == member_in.user_id).first()
    if not user_to_add:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if already a member
    existing_member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == member_in.user_id
    ).first()

    if existing_member:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a team member"
        )

    # Add member
    db_member = TeamMember(
        team_id=team_id,
        user_id=member_in.user_id,
        role=member_in.role
    )

    db.add(db_member)
    db.commit()
    db.refresh(db_member)

    return db_member


@router.put("/{team_id}/members/{user_id}", response_model=TeamMemberResponse)
def update_team_member_role(
    team_id: int,
    user_id: int,
    member_in: TeamMemberUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Update team member role (owner or admin only)

    Args:
        team_id: Team ID
        user_id: User ID to update
        member_in: Member update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated team member object
    """
    team = check_team_permission(team_id, current_user, db, [TeamRole.OWNER, TeamRole.ADMIN])

    # Get member
    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == user_id
    ).first()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found"
        )

    # Update role
    member.role = member_in.role
    db.commit()
    db.refresh(member)

    return member


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    team_id: int,
    user_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Remove a member from the team (owner or admin only, or self)

    Args:
        team_id: Team ID
        user_id: User ID to remove
        current_user: Current authenticated user
        db: Database session
    """
    team = check_team_permission(team_id, current_user, db)

    # Can't remove owner
    if user_id == team.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove team owner"
        )

    # Get member
    member = db.query(TeamMember).filter(
        TeamMember.team_id == team_id,
        TeamMember.user_id == user_id
    ).first()

    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team member not found"
        )

    # Check permission: owner, admin, or removing self
    if current_user.id != user_id:
        check_team_permission(team_id, current_user, db, [TeamRole.OWNER, TeamRole.ADMIN])

    db.delete(member)
    db.commit()
