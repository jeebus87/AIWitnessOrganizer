"""Authentication schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class ClioAuthCallback(BaseModel):
    """Clio OAuth callback parameters"""
    code: str
    state: str


class ClioAuthResponse(BaseModel):
    """Response after successful Clio OAuth"""
    success: bool
    message: str
    clio_user_id: Optional[str] = None


class UserResponse(BaseModel):
    """User information response"""
    id: int
    email: str
    display_name: Optional[str]
    subscription_tier: str
    clio_connected: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenVerifyRequest(BaseModel):
    """Firebase token verification request"""
    id_token: str


class TokenVerifyResponse(BaseModel):
    """Firebase token verification response"""
    valid: bool
    user_id: Optional[int] = None
    firebase_uid: Optional[str] = None
    email: Optional[str] = None
