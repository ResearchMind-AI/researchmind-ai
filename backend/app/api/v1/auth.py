"""
Authentication endpoints
"""
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, Token, UserLogin
from app.api.deps import get_current_active_user
from app.config import settings

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    user_in: UserCreate,
    invite_code: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Register a new user

    Args:
        user_in: User registration data
        db: Database session

    Returns:
        Created user object

    Raises:
        HTTPException: If email already registered
    """
    # Optional invite code (INVITE_CODE) keeps public test deployments private
    if settings.INVITE_CODE and not secrets.compare_digest(invite_code or "", settings.INVITE_CODE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A valid invite code is required")

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create new user
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        is_active=user_in.is_active if user_in.is_active is not None else True,
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return db_user


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    OAuth2 compatible login endpoint

    Args:
        form_data: OAuth2 password form with username (email) and password
        db: Database session

    Returns:
        Access token

    Raises:
        HTTPException: If credentials are invalid
    """
    # Authenticate user
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login/json", response_model=Token)
def login_json(
    user_in: UserLogin,
    db: Session = Depends(get_db)
):
    """
    JSON-based login endpoint (alternative to OAuth2 form)

    Args:
        user_in: Login credentials
        db: Database session

    Returns:
        Access token

    Raises:
        HTTPException: If credentials are invalid
    """
    # Authenticate user
    user = db.query(User).filter(User.email == user_in.email).first()

    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get current user information

    Args:
        current_user: Current authenticated user

    Returns:
        Current user object
    """
    return current_user


@router.get("/test-token", response_model=UserResponse)
def test_token(
    current_user: User = Depends(get_current_active_user)
):
    """
    Test if the access token is valid

    Args:
        current_user: Current authenticated user

    Returns:
        Current user object
    """
    return current_user
