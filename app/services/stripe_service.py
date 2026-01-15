"""Stripe service for billing and subscriptions"""
import stripe
from typing import Optional, Dict, Any
from fastapi import HTTPException
import structlog

from app.core.config import settings
from app.db.models import SubscriptionTier

logger = structlog.get_logger()

# Initialize Stripe
if settings.stripe_secret_key:
    stripe.api_key = settings.stripe_secret_key


async def create_stripe_customer(email: str, name: str, metadata: Dict[str, str]) -> str:
    """
    Create a Stripe customer or return existing one.
    """
    try:
        # Check if customer already exists by email
        existing = stripe.Customer.list(email=email, limit=1)
        if existing.data:
            customer = existing.data[0]
            # Update metadata if needed
            if metadata:
                stripe.Customer.modify(customer.id, metadata=metadata)
            return customer.id

        # Create new customer
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata=metadata
        )
        return customer.id
    except stripe.error.StripeError as e:
        logger.error("Stripe customer creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Billing service error")


async def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    mode: str = "subscription"
) -> str:
    """
    Create Stripe Checkout session.
    """
    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                },
            ],
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            allow_promotion_codes=True,
        )
        return session.url
    except stripe.error.StripeError as e:
        logger.error("Stripe checkout session creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


async def create_portal_session(customer_id: str, return_url: str) -> str:
    """
    Create Stripe Customer Portal session.
    """
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url,
        )
        return session.url
    except stripe.error.StripeError as e:
        logger.error("Stripe portal session creation failed", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to access billing portal")


def get_tier_from_price_id(price_id: str) -> SubscriptionTier:
    """
    Map Stripe Price ID to SubscriptionTier.
    TODO: Move these mappings to config or DB.
    """
    # Example mapping - replace with actual Price IDs from env/config
    # In a real app, you might look this up in a Product->Tier map
    return SubscriptionTier.PROFESSIONAL
