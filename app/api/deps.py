"""API dependencies for authentication and authorization"""
from typing import Optional
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.session import get_db
from app.db.models import User

# Initialize Firebase Admin SDK
_firebase_app = None


def get_firebase_app():
    """Get or initialize Firebase Admin app"""
    global _firebase_app
    if _firebase_app is None:
        try:
            _firebase_app = firebase_admin.get_app()
        except ValueError:
            # App not initialized, initialize it
            if settings.firebase_private_key:
                cred = credentials.Certificate({
                    "type": "service_account",
                    "project_id": settings.firebase_project_id,
                    "private_key_id": settings.firebase_private_key_id,
                    "private_key": settings.firebase_private_key.replace("\\n", "\n"),
                    "client_email": settings.firebase_client_email,
                    "client_id": settings.firebase_client_id,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                })
                _firebase_app = firebase_admin.initialize_app(cred)
            else:
                # Initialize with project ID only (for ID token verification)
                _firebase_app = firebase_admin.initialize_app(
                    options={"projectId": settings.firebase_project_id}
                )
    return _firebase_app


async def get_current_user_optional(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Get current user from Firebase token (optional).
    Returns None if no token provided.
    """
    if not authorization:
        return None

    if not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")

    try:
        get_firebase_app()
        decoded_token = firebase_auth.verify_id_token(token)
        firebase_uid = decoded_token["uid"]

        # Get or create user
        result = await db.execute(
            select(User).where(User.firebase_uid == firebase_uid)
        )
        user = result.scalar_one_or_none()

        if not user:
            # Create new user
            user = User(
                firebase_uid=firebase_uid,
                email=decoded_token.get("email", ""),
                display_name=decoded_token.get("name", decoded_token.get("email", ""))
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        return user
    except Exception:
        return None


async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Get current user from Firebase token (required).
    Raises 401 if not authenticated.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization.replace("Bearer ", "")

    try:
        get_firebase_app()
        decoded_token = firebase_auth.verify_id_token(token)
        firebase_uid = decoded_token["uid"]

        # Get or create user
        result = await db.execute(
            select(User).where(User.firebase_uid == firebase_uid)
        )
        user = result.scalar_one_or_none()

        if not user:
            # Create new user
            user = User(
                firebase_uid=firebase_uid,
                email=decoded_token.get("email", ""),
                display_name=decoded_token.get("name", decoded_token.get("email", ""))
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        return user
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
