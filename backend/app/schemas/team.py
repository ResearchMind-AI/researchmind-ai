"""
Pydantic schemas for Team model
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from app.models.team import TeamRole


# Shared properties
class TeamBase(BaseModel):
    """Base team schema with common properties"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


# Properties to receive via API on creation
class TeamCreate(TeamBase):
    """Schema for team creation"""
    pass


# Properties to receive via API on update
class TeamUpdate(BaseModel):
    """Schema for team update"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None


# Team member schemas
class TeamMemberBase(BaseModel):
    """Base team member schema"""
    user_id: int
    role: TeamRole = TeamRole.MEMBER


class TeamMemberCreate(BaseModel):
    """Schema for adding a team member"""
    user_id: int
    role: TeamRole = TeamRole.MEMBER


class TeamMemberUpdate(BaseModel):
    """Schema for updating team member role"""
    role: TeamRole


class TeamMemberResponse(BaseModel):
    """Schema for team member response"""
    id: int
    user_id: int
    team_id: int
    role: TeamRole
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Properties to return via API
class TeamResponse(TeamBase):
    """Schema for team response (what API returns)"""
    id: int
    owner_id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TeamWithMembersResponse(TeamResponse):
    """Schema for team response with members"""
    members: List[TeamMemberResponse] = []

    model_config = ConfigDict(from_attributes=True)


# Invitation schema
class TeamInvite(BaseModel):
    """Schema for team invitation"""
    email: str
    role: TeamRole = TeamRole.MEMBER
