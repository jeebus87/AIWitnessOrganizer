"""Authentication routes for Clio OAuth and Firebase"""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import encrypt_token
from app.db.session import get_db
from app.db.models import User, ClioIntegration
from app.services.clio_client import get_clio_authorize_url, exchange_code_for_tokens
from app.api.v1.schemas.auth import ClioAuthCallback, ClioAuthResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory state storage (use Redis in production)
_oauth_states = {}


@router.get("/clio")
async def initiate_clio_auth(
    redirect_uri: Optional[str] = None,
    user_id: Optional[int] = None  # From authenticated session
):
    """
    Initiate Clio OAuth flow.
    Redirects user to Clio authorization page.
    """
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {
        "user_id": user_id,
        "created_at": datetime.utcnow(),
        "redirect_uri": redirect_uri
    }

    # Clean up old states (older than 10 minutes)
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    _oauth_states = {k: v for k, v in _oauth_states.items() if v["created_at"] > cutoff}

    auth_url = get_clio_authorize_url(state=state, redirect_uri=redirect_uri)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def clio_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Clio OAuth callback.
    Exchanges authorization code for tokens and stores them.
    """
    # Validate state
    state_data = _oauth_states.pop(state, None)
    if not state_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state"
        )

    user_id = state_data.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="No user associated with this OAuth flow"
        )

    try:
        # Exchange code for tokens
        token_data = await exchange_code_for_tokens(
            code=code,
            redirect_uri=state_data.get("redirect_uri")
        )

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = token_data.get("expires_in", 86400)  # Default 24 hours

        # Encrypt tokens before storage
        access_token_encrypted = encrypt_token(access_token)
        refresh_token_encrypted = encrypt_token(refresh_token)
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Check if integration already exists
        result = await db.execute(
            select(ClioIntegration).where(ClioIntegration.user_id == user_id)
        )
        integration = result.scalar_one_or_none()

        if integration:
            # Update existing integration
            integration.access_token_encrypted = access_token_encrypted
            integration.refresh_token_encrypted = refresh_token_encrypted
            integration.token_expires_at = token_expires_at
            integration.is_active = True
            integration.updated_at = datetime.utcnow()
        else:
            # Create new integration
            integration = ClioIntegration(
                user_id=user_id,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                token_expires_at=token_expires_at,
                is_active=True
            )
            db.add(integration)

        await db.commit()

        # Redirect to frontend with success
        frontend_url = f"{settings.frontend_url}/settings/integrations?clio=success"
        return RedirectResponse(url=frontend_url)

    except Exception as e:
        # Redirect to frontend with error
        frontend_url = f"{settings.frontend_url}/settings/integrations?clio=error&message={str(e)}"
        return RedirectResponse(url=frontend_url)


@router.post("/clio/disconnect")
async def disconnect_clio(
    user_id: int,  # From authenticated session
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect Clio integration for a user.
    """
    result = await db.execute(
        select(ClioIntegration).where(ClioIntegration.user_id == user_id)
    )
    integration = result.scalar_one_or_none()

    if integration:
        integration.is_active = False
        await db.commit()

    return {"success": True, "message": "Clio disconnected"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user_id: int,  # From authenticated session
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user information.
    """
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if Clio is connected
    result = await db.execute(
        select(ClioIntegration).where(
            ClioIntegration.user_id == user_id,
            ClioIntegration.is_active == True
        )
    )
    clio_integration = result.scalar_one_or_none()

    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        subscription_tier=user.subscription_tier.value,
        clio_connected=clio_integration is not None,
        created_at=user.created_at
    )
