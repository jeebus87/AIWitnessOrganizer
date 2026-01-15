"""Billing routes for Stripe"""
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models import User
from app.services.stripe_service import (
    create_stripe_customer,
    create_checkout_session,
    create_portal_session
)
import stripe

logger = structlog.get_logger()
router = APIRouter(prefix="/billing", tags=["Billing"])


@router.post("/create-checkout-session")
async def create_checkout_session_endpoint(
    price_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a Stripe checkout session for the current user.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Ensure user has a Stripe Customer ID
    if not current_user.stripe_customer_id:
        customer_id = await create_stripe_customer(
            email=current_user.email,
            name=current_user.display_name or current_user.email,
            metadata={"user_id": str(current_user.id)}
        )
        current_user.stripe_customer_id = customer_id
        await db.commit()
    
    customer_id = current_user.stripe_customer_id
    
    # Create session
    checkout_url = await create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=f"{settings.frontend_url}/settings?success=true",
        cancel_url=f"{settings.frontend_url}/settings?canceled=true",
    )
    
    return {"url": checkout_url}


@router.post("/portal")
async def create_portal_session_endpoint(
    current_user: User = Depends(get_current_user),
):
    """
    Create a Stripe customer portal session for the current user.
    """
    if not current_user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    portal_url = await create_portal_session(
        customer_id=current_user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/settings",
    )
    
    return {"url": portal_url}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Stripe webhook handler.
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

    # Handle the event
    if event["type"] == "customer.subscription.updated":
        await handle_subscription_updated(event["data"]["object"], db)
    elif event["type"] == "customer.subscription.deleted":
        await handle_subscription_deleted(event["data"]["object"], db)

    return {"status": "success"}


async def handle_subscription_updated(subscription, db: AsyncSession):
    """
    Update user subscription status.
    """
    customer_id = subscription["customer"]
    status = subscription["status"]
    # Logic to map price/product to internal tier
    # For now, if active, assume professional
    
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    
    if user:
        if status == "active":
            user.subscription_tier = "professional"  # Simplified
            user.stripe_subscription_id = subscription["id"]
        else:
            user.subscription_tier = "free"
        
        await db.commit()


async def handle_subscription_deleted(subscription, db: AsyncSession):
    """
    Handle subscription cancellation.
    """
    customer_id = subscription["customer"]
    
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    
    if user:
        user.subscription_tier = "free"
        user.stripe_subscription_id = None
        await db.commit()
