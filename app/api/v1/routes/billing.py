"""Billing routes for Stripe subscriptions and credits"""
import structlog
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import User
from app.services.subscription_service import SubscriptionService
from app.services.credit_service import CreditService
import stripe

logger = structlog.get_logger()
router = APIRouter(prefix="/billing", tags=["Billing"])


# Request/Response models
class CheckoutRequest(BaseModel):
    user_count: int = 1


class TopupRequest(BaseModel):
    package: str  # "small", "medium", "large"


class UpdateOrgNameRequest(BaseModel):
    name: str


# ============================================================================
# Subscription Endpoints
# ============================================================================

@router.get("/status")
async def get_subscription_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current subscription status for the user's organization.
    """
    service = SubscriptionService(db)
    return await service.get_subscription_status(current_user.id)


@router.post("/checkout")
async def create_checkout_session_endpoint(
    request: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe checkout session for subscription.
    Only organization admins can subscribe.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    service = SubscriptionService(db)
    checkout_url = await service.create_checkout_session(
        user_id=current_user.id,
        user_count=request.user_count,
        success_url=f"{settings.frontend_url}/settings?subscription=success",
        cancel_url=f"{settings.frontend_url}/settings?subscription=canceled"
    )

    return {"url": checkout_url}


@router.post("/portal")
async def create_portal_session_endpoint(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe customer portal session.
    Only organization admins can access the portal.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    service = SubscriptionService(db)
    portal_url = await service.create_portal_session(
        user_id=current_user.id,
        return_url=f"{settings.frontend_url}/settings"
    )

    return {"url": portal_url}


# ============================================================================
# Credit Endpoints
# ============================================================================

@router.get("/credits")
async def get_credits(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get remaining credits for the current user.
    """
    service = CreditService(db)
    return await service.get_remaining_credits(current_user.id)


@router.post("/credits/check")
async def check_and_consume_credit(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Check if user has credits and consume one.
    Returns success status and remaining credits.
    """
    service = CreditService(db)
    success, credits_info = await service.check_and_consume_credit(current_user.id)

    return {
        "success": success,
        "credits": credits_info
    }


@router.get("/credits/history")
async def get_credit_history(
    days: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get credit usage history for the past N days.
    """
    service = CreditService(db)
    return await service.get_usage_history(current_user.id, days)


@router.post("/credits/topup")
async def create_topup_checkout(
    request: TopupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a checkout session for credit top-up purchase.
    Only organization admins can purchase credits.

    Packages:
    - small: 10 credits for $4.99
    - medium: 25 credits for $12.49
    - large: 50 credits for $24.99
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Verify user is an admin - check database value first for quick rejection
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Only organization admins can purchase credits"
        )

    # Verify user has an organization
    if not current_user.organization_id:
        raise HTTPException(
            status_code=400,
            detail="You must belong to an organization to purchase credits"
        )

    service = SubscriptionService(db)
    checkout_url = await service.create_topup_checkout(
        user_id=current_user.id,
        package=request.package,
        success_url=f"{settings.frontend_url}/settings?topup=success",
        cancel_url=f"{settings.frontend_url}/settings?topup=canceled"
    )

    return {"url": checkout_url}


# ============================================================================
# Organization Endpoints
# ============================================================================

@router.put("/organization/name")
async def update_organization_name(
    request: UpdateOrgNameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update organization name (admin only).
    """
    service = SubscriptionService(db)
    org = await service.update_organization_name(
        user_id=current_user.id,
        new_name=request.name
    )

    return {
        "id": org.id,
        "name": org.name,
        "updated": True
    }


# ============================================================================
# Stripe Webhook
# ============================================================================

@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Stripe webhook handler for subscription and payment events.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")

    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event using SubscriptionService
    service = SubscriptionService(db)
    await service.handle_webhook_event(event)

    return {"status": "success"}
