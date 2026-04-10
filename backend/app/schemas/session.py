"""
Pydantic schemas for session management
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.session import SessionStatus, SessionMemberRole


# Session Schemas
class SessionBase(BaseModel):
    """Base session schema"""
    title: str = Field(..., min_length=1, max_length=200, description="Session title")
    description: Optional[str] = Field(None, description="Session description")
    topic: Optional[str] = Field(None, max_length=100, description="Research topic")
    research_question: Optional[str] = Field(None, description="Research question to investigate")


class SessionCreate(SessionBase):
    """Schema for creating a new session"""
    team_id: Optional[int] = Field(None, description="Optional team ID to associate with session")


class SessionUpdate(BaseModel):
    """Schema for updating a session"""
    title: Optional[str] = Field(None, min_length=1, max_length=200, description="Session title")
    description: Optional[str] = Field(None, description="Session description")
    topic: Optional[str] = Field(None, max_length=100, description="Research topic")
    research_question: Optional[str] = Field(None, description="Research question")
    status: Optional[SessionStatus] = Field(None, description="Session status")


class SessionResponse(SessionBase):
    """Schema for session response"""
    id: int
    status: SessionStatus
    creator_id: int
    team_id: Optional[int]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class SessionMemberBase(BaseModel):
    """Base session member schema"""
    user_id: int = Field(..., description="User ID")
    role: SessionMemberRole = Field(default=SessionMemberRole.CONTRIBUTOR, description="Member role")


class SessionMemberCreate(SessionMemberBase):
    """Schema for adding a member to a session"""
    pass


class SessionMemberUpdate(BaseModel):
    """Schema for updating a session member"""
    role: SessionMemberRole = Field(..., description="New member role")


class SessionMemberResponse(BaseModel):
    """Schema for session member response"""
    id: int
    session_id: int
    user_id: int
    role: SessionMemberRole
    joined_at: datetime

    class Config:
        from_attributes = True


class SessionWithMembersResponse(SessionResponse):
    """Schema for session response with members"""
    members: List[SessionMemberResponse] = []

    class Config:
        from_attributes = True
