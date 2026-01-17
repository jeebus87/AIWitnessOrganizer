"""Subscription service for organization billing via Stripe"""
import stripe
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
import structlog

from app.core.config import settings
from app.db.models import User, Organization, OrganizationJobCounter

logger = structlog.get_logger()

# Initialize Stripe
if settings.stripe_secret_key:
    stripe.api_key = settings.stripe_secret_key


# Stripe Price IDs - PLACEHOLDER values to be replaced with actual IDs
STRIPE_PRICE_IDS = {
    "firm_monthly": settings.stripe_price_id_monthly or "PLACEHOLDER_PRICE_ID_FIRM_MONTHLY",
    "topup_10": settings.stripe_price_id_topup_10 or "PLACEHOLDER_PRICE_ID_TOPUP_10",
    "topup_25": settings.stripe_price_id_topup_25 or "PLACEHOLDER_PRICE_ID_TOPUP_25",
    "topup_50": settings.stripe_price_id_topup_50 or "PLACEHOLDER_PRICE_ID_TOPUP_50",
}

# Top-up package details
TOPUP_PACKAGES = {
    "small": {"credits": 10, "price_cents": 499, "price_id": STRIPE_PRICE_IDS["topup_10"]},
    "medium": {"credits": 25, "price_cents": 1249, "price_id": STRIPE_PRICE_IDS["topup_25"]},
    "large": {"credits": 50, "price_cents": 2499, "price_id": STRIPE_PRICE_IDS["topup_50"]},
}


class SubscriptionService:
    """Service for managing organization subscriptions via Stripe"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_organization(
        self,
        clio_account_id: str,
        firm_name: str,
        user_id: int
    ) -> Organization:
        """
        Get existing organization or create new one.
        Called during Clio OAuth callback.
        """
        # Check if org exists
        result = await self.db.execute(
            select(Organization).where(Organization.clio_account_id == clio_account_id)
        )
        org = result.scalar_one_or_none()

        if org:
            # Link user to existing org
            await self.db.execute(
                update(User)
                .where(User.id == user_id)
                .values(organization_id=org.id)
            )
            await self.db.commit()
            return org

        # Create new organization
        org = Organization(
            name=firm_name,
            clio_account_id=clio_account_id,
            subscription_status="free",
            subscription_tier="free",
            user_count=1
        )
        self.db.add(org)
        await self.db.flush()

        # Create job counter for the org
        counter = OrganizationJobCounter(
            organization_id=org.id,
            job_counter=0
        )
        self.db.add(counter)

        # Link user to org and make them admin (first user from this firm)
        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(organization_id=org.id, is_admin=True)
        )

        await self.db.commit()

        logger.info(
            "Organization created",
            org_id=org.id,
            name=firm_name,
            clio_account_id=clio_account_id
        )

        return org

    async def get_subscription_status(self, user_id: int) -> Dict[str, Any]:
        """Get current subscription status for user's organization"""
        # Get user with org
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.organization_id:
            return {
                "status": "free",
                "tier": "free",
                "is_admin": False,
                "user_count": 1,
                "organization_name": None,
                "current_period_end": None,
                "bonus_credits": 0
            }

        org_result = await self.db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        org = org_result.scalar_one_or_none()

        if not org:
            return {
                "status": "free",
                "tier": "free",
                "is_admin": user.is_admin,
                "user_count": 1,
                "organization_name": None,
                "current_period_end": None,
                "bonus_credits": 0
            }

        return {
            "status": org.subscription_status,
            "tier": org.subscription_tier,
            "is_admin": user.is_admin,
            "user_count": org.user_count,
            "organization_name": org.name,
            "current_period_end": org.current_period_end.isoformat() if org.current_period_end else None,
            "bonus_credits": org.bonus_credits
        }

    async def create_checkout_session(
        self,
        user_id: int,
        user_count: int,
        success_url: str,
        cancel_url: str
    ) -> str:
        """
        Create Stripe Checkout session for subscription with per-seat billing.

        Args:
            user_id: The user initiating checkout (must be admin)
            user_count: Number of seats to purchase
            success_url: URL to redirect after successful payment
            cancel_url: URL to redirect if payment cancelled

        Returns:
            Stripe Checkout URL
        """
        # Verify user is admin
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.organization_id:
            raise HTTPException(status_code=400, detail="User not in an organization")

        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Only organization admins can manage billing")

        # Get organization
        org_result = await self.db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        org = org_result.scalar_one_or_none()

        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        try:
            # Create or get Stripe customer
            if not org.stripe_customer_id:
                customer = stripe.Customer.create(
                    email=user.email,
                    name=org.name,
                    metadata={
                        "organization_id": str(org.id),
                        "clio_account_id": org.clio_account_id or ""
                    }
                )
                org.stripe_customer_id = customer.id
                await self.db.commit()

            # Create checkout session with quantity (per-seat billing)
            # Include 14-day free trial for new subscriptions
            session = stripe.checkout.Session.create(
                customer=org.stripe_customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": STRIPE_PRICE_IDS["firm_monthly"],
                        "quantity": user_count,
                    },
                ],
                mode="subscription",
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,
                subscription_data={
                    "trial_period_days": 14,  # 14-day free trial
                    "metadata": {
                        "organization_id": str(org.id),
                        "user_count": str(user_count)
                    }
                }
            )

            logger.info(
                "Checkout session created",
                org_id=org.id,
                user_count=user_count,
                session_id=session.id
            )

            return session.url

        except stripe.error.StripeError as e:
            logger.error("Stripe checkout creation failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to create checkout session")

    async def create_topup_checkout(
        self,
        user_id: int,
        package: str,
        success_url: str,
        cancel_url: str
    ) -> str:
        """
        Create checkout session for credit top-up (one-time purchase).

        Args:
            user_id: The user making purchase (must be admin)
            package: Package name ("small", "medium", "large")
            success_url: URL to redirect after payment
            cancel_url: URL to redirect if cancelled

        Returns:
            Stripe Checkout URL
        """
        if package not in TOPUP_PACKAGES:
            raise HTTPException(status_code=400, detail=f"Invalid package: {package}")

        # Verify user is admin
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user or not user.organization_id:
            raise HTTPException(status_code=400, detail="User not in an organization")

        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Only organization admins can purchase credits")

        # Get organization
        org_result = await self.db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        org = org_result.scalar_one_or_none()

        if not org or not org.stripe_customer_id:
            raise HTTPException(status_code=400, detail="Organization must have active billing")

        package_info = TOPUP_PACKAGES[package]

        try:
            session = stripe.checkout.Session.create(
                customer=org.stripe_customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": package_info["price_id"],
                        "quantity": 1,
                    },
                ],
                mode="payment",  # One-time payment, not subscription
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "type": "topup",
                    "organization_id": str(org.id),
                    "user_id": str(user_id),
                    "package": package,
                    "credits": str(package_info["credits"])
                }
            )

            logger.info(
                "Topup checkout created",
                org_id=org.id,
                package=package,
                credits=package_info["credits"]
            )

            return session.url

        except stripe.error.StripeError as e:
            logger.error("Stripe topup checkout failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to create checkout session")

    async def create_portal_session(
        self,
        user_id: int,
        return_url: str
    ) -> str:
        """
        Create Stripe Customer Portal session for managing subscription.

        Args:
            user_id: User requesting portal access (must be admin)
            return_url: URL to return to after portal session

        Returns:
            Stripe Portal URL
        """
        # Verify user is admin
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user or not user.organization_id:
            raise HTTPException(status_code=400, detail="User not in an organization")

        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Only organization admins can access billing portal")

        org_result = await self.db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        org = org_result.scalar_one_or_none()

        if not org or not org.stripe_customer_id:
            raise HTTPException(status_code=400, detail="No billing account found")

        try:
            session = stripe.billing_portal.Session.create(
                customer=org.stripe_customer_id,
                return_url=return_url,
            )
            return session.url

        except stripe.error.StripeError as e:
            logger.error("Stripe portal session failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to access billing portal")

    async def handle_webhook_event(self, event: Dict[str, Any]) -> None:
        """
        Handle Stripe webhook events.

        Called from the webhook endpoint.
        """
        event_type = event.get("type")
        data = event.get("data", {}).get("object", {})

        logger.info("Processing Stripe webhook", event_type=event_type)

        if event_type == "checkout.session.completed":
            await self._handle_checkout_completed(data)

        elif event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(data)

        elif event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(data)

        elif event_type == "invoice.payment_failed":
            await self._handle_payment_failed(data)

        elif event_type == "payment_intent.succeeded":
            await self._handle_payment_succeeded(data)

    async def _handle_checkout_completed(self, data: Dict) -> None:
        """Handle successful checkout completion"""
        mode = data.get("mode")
        metadata = data.get("metadata", {})

        if mode == "subscription":
            # Subscription checkout completed
            org_id = metadata.get("organization_id")
            subscription_id = data.get("subscription")

            if org_id and subscription_id:
                # Get subscription details
                sub = stripe.Subscription.retrieve(subscription_id)
                user_count = int(metadata.get("user_count", 1))

                # Detect if subscription is in trial period
                is_trial = sub.status == "trialing"
                status = "trialing" if is_trial else "active"
                period_end = sub.trial_end if is_trial else sub.current_period_end

                await self.db.execute(
                    update(Organization)
                    .where(Organization.id == int(org_id))
                    .values(
                        stripe_subscription_id=subscription_id,
                        subscription_status=status,
                        subscription_tier="firm",
                        user_count=user_count,
                        current_period_end=datetime.fromtimestamp(period_end) if period_end else None
                    )
                )
                await self.db.commit()

                logger.info(
                    "Subscription activated",
                    org_id=org_id,
                    user_count=user_count,
                    status=status,
                    is_trial=is_trial
                )

        elif mode == "payment" and metadata.get("type") == "topup":
            # Credit top-up completed
            org_id = metadata.get("organization_id")
            user_id = metadata.get("user_id")
            credits = int(metadata.get("credits", 0))
            package = metadata.get("package")

            if org_id and credits > 0:
                # Add credits using CreditService
                from app.services.credit_service import CreditService
                credit_service = CreditService(self.db)

                await credit_service.add_bonus_credits(
                    organization_id=int(org_id),
                    credits=credits,
                    purchased_by_user_id=int(user_id) if user_id else None,
                    stripe_payment_intent_id=data.get("payment_intent"),
                    amount_cents=TOPUP_PACKAGES.get(package, {}).get("price_cents", 0)
                )

                logger.info(
                    "Credits added from topup",
                    org_id=org_id,
                    credits=credits,
                    package=package
                )

    async def _handle_subscription_updated(self, data: Dict) -> None:
        """Handle subscription updates (quantity changes, etc.)"""
        subscription_id = data.get("id")
        status = data.get("status")
        quantity = data.get("items", {}).get("data", [{}])[0].get("quantity", 1)

        # Find organization by subscription ID
        result = await self.db.execute(
            select(Organization).where(Organization.stripe_subscription_id == subscription_id)
        )
        org = result.scalar_one_or_none()

        if org:
            await self.db.execute(
                update(Organization)
                .where(Organization.id == org.id)
                .values(
                    subscription_status=status,
                    user_count=quantity,
                    current_period_end=datetime.fromtimestamp(data.get("current_period_end", 0))
                )
            )
            await self.db.commit()

            logger.info(
                "Subscription updated",
                org_id=org.id,
                status=status,
                user_count=quantity
            )

    async def _handle_subscription_deleted(self, data: Dict) -> None:
        """Handle subscription cancellation"""
        subscription_id = data.get("id")

        result = await self.db.execute(
            select(Organization).where(Organization.stripe_subscription_id == subscription_id)
        )
        org = result.scalar_one_or_none()

        if org:
            await self.db.execute(
                update(Organization)
                .where(Organization.id == org.id)
                .values(
                    subscription_status="canceled",
                    subscription_tier="free"
                )
            )
            await self.db.commit()

            logger.info("Subscription canceled", org_id=org.id)

    async def _handle_payment_failed(self, data: Dict) -> None:
        """Handle failed payment"""
        subscription_id = data.get("subscription")

        if subscription_id:
            result = await self.db.execute(
                select(Organization).where(Organization.stripe_subscription_id == subscription_id)
            )
            org = result.scalar_one_or_none()

            if org:
                await self.db.execute(
                    update(Organization)
                    .where(Organization.id == org.id)
                    .values(subscription_status="past_due")
                )
                await self.db.commit()

                logger.warning("Subscription payment failed", org_id=org.id)

    async def _handle_payment_succeeded(self, data: Dict) -> None:
        """Handle successful payment (mainly for top-ups processed outside checkout)"""
        # Most top-ups are handled in checkout.session.completed
        # This is a fallback for direct PaymentIntent flows
        pass

    async def update_organization_name(
        self,
        user_id: int,
        new_name: str
    ) -> Organization:
        """
        Update organization name (admin only).
        """
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user or not user.organization_id:
            raise HTTPException(status_code=400, detail="User not in an organization")

        if not user.is_admin:
            raise HTTPException(status_code=403, detail="Only admins can update organization name")

        await self.db.execute(
            update(Organization)
            .where(Organization.id == user.organization_id)
            .values(name=new_name)
        )
        await self.db.commit()

        org_result = await self.db.execute(
            select(Organization).where(Organization.id == user.organization_id)
        )
        return org_result.scalar_one()
