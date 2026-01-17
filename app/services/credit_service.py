"""Credit service for tracking report credit usage"""
from datetime import datetime, date
from typing import Dict, Tuple, Optional
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
import structlog

from app.db.models import (
    User, Organization, ReportCreditUsage, CreditPurchase
)

logger = structlog.get_logger()


class CreditService:
    """Service for managing report credits"""

    # Free tier daily limit per user
    FREE_DAILY_CREDITS = 10

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_remaining_credits(self, user_id: int) -> Dict:
        """
        Get remaining credits for a user.

        Returns:
            {
                "daily_remaining": int,  # Free tier daily limit remaining
                "bonus_remaining": int,  # Org-level bonus credits from top-ups
                "is_paid": bool,         # Whether org has active subscription
                "unlimited": bool        # Whether user has unlimited credits
            }
        """
        # Get user with organization
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            return {
                "daily_remaining": 0,
                "bonus_remaining": 0,
                "is_paid": False,
                "unlimited": False
            }

        # Check organization subscription status
        org = None
        if user.organization_id:
            org_result = await self.db.execute(
                select(Organization).where(Organization.id == user.organization_id)
            )
            org = org_result.scalar_one_or_none()

        # Active or trialing subscriptions get unlimited credits
        is_paid = org and org.subscription_status in ("active", "trialing")

        # Paid/trialing users have unlimited credits
        if is_paid:
            return {
                "daily_remaining": self.FREE_DAILY_CREDITS,  # Still track for analytics
                "bonus_remaining": org.bonus_credits if org else 0,
                "is_paid": True,
                "unlimited": True
            }

        # Get today's usage for free tier
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        usage_result = await self.db.execute(
            select(ReportCreditUsage)
            .where(and_(
                ReportCreditUsage.user_id == user_id,
                ReportCreditUsage.date >= today_start,
                ReportCreditUsage.date <= today_end
            ))
        )
        usage = usage_result.scalar_one_or_none()

        daily_used = usage.credits_used if usage else 0
        daily_remaining = max(0, self.FREE_DAILY_CREDITS - daily_used)
        bonus_remaining = org.bonus_credits if org else 0

        return {
            "daily_remaining": daily_remaining,
            "bonus_remaining": bonus_remaining,
            "is_paid": False,
            "unlimited": False
        }

    async def check_and_consume_credit(self, user_id: int) -> Tuple[bool, Dict]:
        """
        Check if user has credits available and consume one if available.

        Returns:
            (success: bool, credits_info: Dict)
            - success: True if credit was consumed, False if no credits available
            - credits_info: Updated credit information
        """
        credits = await self.get_remaining_credits(user_id)

        # Paid users always have credits
        if credits["unlimited"]:
            # Still track usage for analytics, but don't block
            await self._record_usage(user_id)
            credits["daily_remaining"] = max(0, credits["daily_remaining"] - 1)
            return True, credits

        # Check if free credits available
        if credits["daily_remaining"] > 0:
            await self._record_usage(user_id)
            credits["daily_remaining"] -= 1
            return True, credits

        # Check bonus credits
        if credits["bonus_remaining"] > 0:
            await self._consume_bonus_credit(user_id)
            credits["bonus_remaining"] -= 1
            return True, credits

        # No credits available
        logger.warning(
            "Credit limit reached",
            user_id=user_id,
            daily_remaining=credits["daily_remaining"],
            bonus_remaining=credits["bonus_remaining"]
        )
        return False, credits

    async def _record_usage(self, user_id: int) -> None:
        """Record a credit usage for today"""
        today = datetime.combine(date.today(), datetime.min.time())

        # Get user's org_id
        user_result = await self.db.execute(
            select(User.organization_id).where(User.id == user_id)
        )
        org_id = user_result.scalar_one_or_none()

        # Upsert: insert or update credits_used
        stmt = insert(ReportCreditUsage).values(
            user_id=user_id,
            organization_id=org_id,
            date=today,
            credits_used=1
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "date"],
            set_={"credits_used": ReportCreditUsage.credits_used + 1}
        )

        await self.db.execute(stmt)
        await self.db.commit()

    async def _consume_bonus_credit(self, user_id: int) -> None:
        """Consume one bonus credit from the organization"""
        # Get user's organization
        user_result = await self.db.execute(
            select(User.organization_id).where(User.id == user_id)
        )
        org_id = user_result.scalar_one_or_none()

        if not org_id:
            return

        # Decrement org bonus credits (atomic)
        await self.db.execute(
            update(Organization)
            .where(and_(
                Organization.id == org_id,
                Organization.bonus_credits > 0
            ))
            .values(bonus_credits=Organization.bonus_credits - 1)
        )
        await self.db.commit()

    async def add_bonus_credits(
        self,
        organization_id: int,
        credits: int,
        purchased_by_user_id: int,
        stripe_payment_intent_id: Optional[str] = None,
        amount_cents: int = 0
    ) -> Dict:
        """
        Add bonus credits to an organization from a top-up purchase.

        Args:
            organization_id: The organization receiving credits
            credits: Number of credits to add
            purchased_by_user_id: User who made the purchase
            stripe_payment_intent_id: Stripe payment intent ID
            amount_cents: Amount paid in cents

        Returns:
            Updated credit info
        """
        # Record the purchase
        purchase = CreditPurchase(
            organization_id=organization_id,
            purchased_by_user_id=purchased_by_user_id,
            stripe_payment_intent_id=stripe_payment_intent_id,
            credits_purchased=credits,
            amount_cents=amount_cents
        )
        self.db.add(purchase)

        # Add credits to organization (atomic)
        await self.db.execute(
            update(Organization)
            .where(Organization.id == organization_id)
            .values(bonus_credits=Organization.bonus_credits + credits)
        )

        await self.db.commit()

        logger.info(
            "Bonus credits added",
            organization_id=organization_id,
            credits=credits,
            purchased_by=purchased_by_user_id
        )

        # Return updated info
        return await self.get_remaining_credits(purchased_by_user_id)

    async def get_usage_history(
        self,
        user_id: int,
        days: int = 30
    ) -> list:
        """Get credit usage history for the past N days"""
        from datetime import timedelta

        start_date = datetime.combine(
            date.today() - timedelta(days=days),
            datetime.min.time()
        )

        result = await self.db.execute(
            select(ReportCreditUsage)
            .where(and_(
                ReportCreditUsage.user_id == user_id,
                ReportCreditUsage.date >= start_date
            ))
            .order_by(ReportCreditUsage.date.desc())
        )

        return [
            {
                "date": usage.date.isoformat(),
                "credits_used": usage.credits_used
            }
            for usage in result.scalars().all()
        ]
