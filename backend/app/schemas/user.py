"""
Pydantic schemas for User model
"""
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import Optional
from datetime import datetime


# Shared properties
class UserBase(BaseModel):
    """Base user schema with common properties"""
    email: EmailStr
    full_name: Optional[str] = None
    is_active: Optional[bool] = True


# Properties to receive via API on creation
class UserCreate(UserBase):
    """Schema for user registration"""
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")


# Properties to receive via API on update
class UserUpdate(BaseModel):
    """Schema for user update"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)


# Properties to return via API
class UserResponse(UserBase):
    """Schema for user response (what API returns)"""
    id: int
    is_superuser: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Properties stored in DB
class UserInDB(UserBase):
    """User schema as stored in database"""
    id: int
    hashed_password: str
    is_superuser: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Token schemas
class Token(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data encoded in JWT token"""
    email: Optional[str] = None


# Login schema
class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str
