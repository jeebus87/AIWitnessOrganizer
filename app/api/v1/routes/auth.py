"""Authentication routes for Clio OAuth"""
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.security import encrypt_token, create_access_token
from app.db.session import get_db
from app.db.models import User, ClioIntegration, Organization
from app.services.clio_client import get_clio_authorize_url, exchange_code_for_tokens, get_clio_user_info, get_clio_account_info
from app.services.subscription_service import SubscriptionService
from app.api.v1.schemas.auth import UserResponse
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Redis client for OAuth state storage
_redis_client = None


def get_redis_client():
    """Get or create Redis client for OAuth state storage"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def store_oauth_state(state: str, data: dict, ttl_seconds: int = 600):
    """Store OAuth state in Redis with TTL (default 10 minutes)"""
    client = get_redis_client()
    client.setex(f"oauth_state:{state}", ttl_seconds, json.dumps(data))


def get_oauth_state(state: str) -> Optional[dict]:
    """Get and delete OAuth state from Redis"""
    client = get_redis_client()
    key = f"oauth_state:{state}"
    data = client.get(key)
    if data:
        client.delete(key)
        return json.loads(data)
    return None


@router.get("/clio")
async def initiate_clio_auth(
    redirect_uri: Optional[str] = None,
):
    """
    Initiate Clio OAuth flow.
    This is the login endpoint - redirects user to Clio authorization page.
    """
    # Generate state for CSRF protection and store in Redis
    state = secrets.token_urlsafe(32)
    store_oauth_state(state, {
        "redirect_uri": redirect_uri
    })

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
    Exchanges authorization code for tokens, creates/updates user, and returns JWT.
    """
    # Validate state from Redis
    state_data = get_oauth_state(state)
    if not state_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state"
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

        # Get Clio user info (with account/firm info)
        clio_user = await get_clio_user_info(access_token, include_firm=True)
        clio_user_id = str(clio_user.get("id"))
        email = clio_user.get("email", "")
        name = clio_user.get("name", email)

        # Get account/firm info
        clio_account = await get_clio_account_info(access_token)
        clio_account_id = str(clio_account.get("id", "")) if clio_account else None
        firm_name = clio_account.get("name", "My Firm") if clio_account else "My Firm"

        # Find or create user by Clio user ID
        result = await db.execute(
            select(User).where(User.clio_user_id == clio_user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            # Create new user
            user = User(
                clio_user_id=clio_user_id,
                email=email,
                display_name=name
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            # Update user info
            user.email = email
            user.display_name = name
            await db.commit()

        # Create or link organization based on Clio account
        if clio_account_id:
            subscription_service = SubscriptionService(db)
            await subscription_service.get_or_create_organization(
                clio_account_id=clio_account_id,
                firm_name=firm_name,
                user_id=user.id
            )

        # Encrypt tokens before storage
        access_token_encrypted = encrypt_token(access_token)
        refresh_token_encrypted = encrypt_token(refresh_token)
        token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        # Update or create Clio integration
        result = await db.execute(
            select(ClioIntegration).where(ClioIntegration.user_id == user.id)
        )
        integration = result.scalar_one_or_none()

        if integration:
            integration.access_token_encrypted = access_token_encrypted
            integration.refresh_token_encrypted = refresh_token_encrypted
            integration.token_expires_at = token_expires_at
            integration.clio_user_id = clio_user_id
            integration.clio_account_id = clio_account_id  # Store account ID
            integration.is_active = True
            integration.updated_at = datetime.utcnow()
        else:
            integration = ClioIntegration(
                user_id=user.id,
                clio_user_id=clio_user_id,
                clio_account_id=clio_account_id,  # Store account ID
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                token_expires_at=token_expires_at,
                is_active=True
            )
            db.add(integration)

        await db.commit()

        # Create JWT token for the user
        jwt_token = create_access_token(user.id, user.email)

        # Redirect to frontend with token
        frontend_url = f"{settings.frontend_url}/auth/callback?token={jwt_token}"
        return RedirectResponse(url=frontend_url)

    except Exception as e:
        # Redirect to frontend with error
        error_params = urlencode({"error": str(e)})
        frontend_url = f"{settings.frontend_url}/login?{error_params}"
        return RedirectResponse(url=frontend_url)


@router.post("/logout")
async def logout():
    """
    Logout endpoint.
    Since we use stateless JWT, client just needs to delete the token.
    """
    return {"success": True, "message": "Logged out successfully"}


@router.post("/clio/disconnect")
async def disconnect_clio(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnect Clio integration for the current user.
    """
    result = await db.execute(
        select(ClioIntegration).where(ClioIntegration.user_id == current_user.id)
    )
    integration = result.scalar_one_or_none()

    if integration:
        integration.is_active = False
        await db.commit()

    return {"success": True, "message": "Clio disconnected"}


@router.post("/clio/deauthorize")
async def clio_deauthorize_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Webhook called by Clio when a user revokes app access.
    Clio sends the user's Clio ID in the request body.
    """
    try:
        body = await request.json()
        clio_user_id = body.get("user_id") or body.get("subject")

        if clio_user_id:
            # Find and deactivate integrations for this Clio user
            result = await db.execute(
                select(ClioIntegration).where(
                    ClioIntegration.clio_user_id == str(clio_user_id)
                )
            )
            integrations = result.scalars().all()

            for integration in integrations:
                integration.is_active = False
                integration.access_token_encrypted = None
                integration.refresh_token_encrypted = None

            await db.commit()

        return {"success": True}
    except Exception:
        # Always return 200 to Clio even on errors
        return {"success": True}


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current user information including organization and subscription status.
    """
    # Check if Clio is connected
    result = await db.execute(
        select(ClioIntegration).where(
            ClioIntegration.user_id == current_user.id,
            ClioIntegration.is_active == True
        )
    )
    clio_integration = result.scalar_one_or_none()

    # Get organization info
    org_info = None
    if current_user.organization_id:
        org_result = await db.execute(
            select(Organization).where(Organization.id == current_user.organization_id)
        )
        org = org_result.scalar_one_or_none()
        if org:
            org_info = {
                "id": org.id,
                "name": org.name,
                "subscription_status": org.subscription_status,
                "subscription_tier": org.subscription_tier,
                "user_count": org.user_count,
                "bonus_credits": org.bonus_credits,
                "current_period_end": org.current_period_end.isoformat() if org.current_period_end else None
            }

    return {
        "id": current_user.id,
        "email": current_user.email,
        "display_name": current_user.display_name,
        "subscription_tier": current_user.subscription_tier.value,
        "is_admin": current_user.is_admin,
        "clio_connected": clio_integration is not None,
        "created_at": current_user.created_at.isoformat(),
        "organization": org_info
    }
