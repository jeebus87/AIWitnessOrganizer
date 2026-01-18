"""Clio webhook routes for real-time document sync"""
import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.config import settings
from app.core.security import decrypt_token
from app.db.session import get_db
from app.db.models import (
    User, ClioIntegration, ClioWebhookSubscription, Document, Matter
)
from app.services.clio_client import ClioClient
from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# Pydantic models for webhook payloads
class WebhookSubscriptionRequest(BaseModel):
    """Request to create webhook subscriptions"""
    events: list[str] = ["document.create", "document.update", "document.delete"]


class WebhookSubscriptionResponse(BaseModel):
    """Response for webhook subscription"""
    id: int
    clio_subscription_id: str
    event_type: str
    webhook_url: str
    is_active: bool
    expires_at: datetime
    created_at: datetime


def verify_clio_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify Clio webhook signature using HMAC-SHA256.

    Clio sends the signature in the X-Hook-Signature header.
    """
    if not secret or not signature:
        return False

    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(signature, expected_signature)


@router.post("/clio")
async def handle_clio_webhook(
    request: Request,
    x_hook_signature: Optional[str] = Header(None, alias="X-Hook-Signature"),
    db: AsyncSession = Depends(get_db)
):
    """
    Handle incoming Clio webhooks for document events.

    This endpoint receives callbacks when documents are created, updated, or deleted in Clio.
    It triggers appropriate sync actions to keep local data in sync.
    """
    payload = await request.body()

    # Verify signature if webhook secret is configured
    if settings.clio_webhook_secret:
        if not verify_clio_signature(payload, x_hook_signature or "", settings.clio_webhook_secret):
            logger.warning("Invalid Clio webhook signature received")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = data.get("type")
    event_data = data.get("data", {})

    logger.info(f"Received Clio webhook: {event_type}")
    logger.debug(f"Webhook data: {data}")

    if event_type == "document.create":
        await _handle_document_create(event_data, db)
    elif event_type == "document.update":
        await _handle_document_update(event_data, db)
    elif event_type == "document.delete":
        await _handle_document_delete(event_data, db)
    else:
        logger.warning(f"Unknown webhook event type: {event_type}")

    # Update last_triggered_at for tracking
    clio_doc_id = str(event_data.get("id", ""))
    if clio_doc_id:
        # Find subscription and update last_triggered_at
        result = await db.execute(
            select(ClioWebhookSubscription)
            .where(ClioWebhookSubscription.event_type == event_type)
            .where(ClioWebhookSubscription.is_active == True)
        )
        subscription = result.scalar_one_or_none()
        if subscription:
            subscription.last_triggered_at = datetime.utcnow()
            await db.commit()

    return {"status": "received", "event_type": event_type}


async def _handle_document_create(event_data: dict, db: AsyncSession):
    """Handle document.create webhook event"""
    clio_doc_id = str(event_data.get("id"))
    logger.info(f"Document created in Clio: {clio_doc_id}")

    # Queue sync task for the new document
    # Note: The document may not be associated with a matter we track yet
    # This is handled by the periodic sync or next matter sync

    # For now, just log - full implementation would queue a Celery task
    # sync_single_document.delay(clio_doc_id)


async def _handle_document_update(event_data: dict, db: AsyncSession):
    """Handle document.update webhook event"""
    clio_doc_id = str(event_data.get("id"))
    logger.info(f"Document updated in Clio: {clio_doc_id}")

    # Find local document and mark for re-processing if content changed
    result = await db.execute(
        select(Document).where(Document.clio_document_id == clio_doc_id)
    )
    document = result.scalar_one_or_none()

    if document:
        # Clear content hash to force re-processing on next sync
        document.content_hash = None
        document.is_processed = False
        document.updated_at = datetime.utcnow()
        await db.commit()
        logger.info(f"Marked document {document.id} for re-processing")


async def _handle_document_delete(event_data: dict, db: AsyncSession):
    """Handle document.delete webhook event"""
    clio_doc_id = str(event_data.get("id"))
    logger.info(f"Document deleted in Clio: {clio_doc_id}")

    # Soft-delete the local document
    result = await db.execute(
        select(Document).where(Document.clio_document_id == clio_doc_id)
    )
    document = result.scalar_one_or_none()

    if document:
        document.is_soft_deleted = True
        document.updated_at = datetime.utcnow()
        await db.commit()
        logger.info(f"Soft-deleted document {document.id}")


# ============================================================================
# Webhook Management Endpoints
# ============================================================================

@router.post("/subscribe", response_model=list[WebhookSubscriptionResponse])
async def subscribe_to_webhooks(
    request: WebhookSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Subscribe to Clio document webhooks.

    Creates webhook subscriptions in Clio for document.create, document.update,
    and document.delete events. These webhooks enable real-time document sync.

    Note: Clio webhooks expire after 31 days and must be renewed.
    """
    if not settings.clio_webhook_base_url:
        raise HTTPException(
            status_code=400,
            detail="Webhook base URL not configured. Set CLIO_WEBHOOK_BASE_URL."
        )

    # Get user's Clio integration
    result = await db.execute(
        select(ClioIntegration).where(ClioIntegration.user_id == current_user.id)
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=400, detail="Clio integration not found")

    # Decrypt tokens
    access_token = decrypt_token(integration.access_token_encrypted)
    refresh_token = decrypt_token(integration.refresh_token_encrypted)

    # Generate webhook secret for this user
    webhook_secret = secrets.token_urlsafe(32)
    callback_url = f"{settings.clio_webhook_base_url}/api/v1/webhooks/clio"

    # Create webhook subscriptions in Clio
    async with ClioClient(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=integration.token_expires_at,
        region=integration.clio_region
    ) as clio:
        try:
            webhooks = await clio.subscribe_to_webhook(
                callback_url=callback_url,
                events=request.events,
                secret=webhook_secret
            )
        except Exception as e:
            logger.error(f"Failed to create Clio webhooks: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create Clio webhooks: {str(e)}"
            )

    # Store webhook subscriptions locally
    created_subscriptions = []
    for webhook in webhooks:
        # Calculate expiration (31 days from now)
        expires_at = datetime.utcnow() + timedelta(days=31)

        subscription = ClioWebhookSubscription(
            user_id=current_user.id,
            clio_subscription_id=str(webhook.get("id")),
            event_type=webhook.get("events", ["unknown"])[0] if webhook.get("events") else "unknown",
            webhook_url=callback_url,
            secret=webhook_secret,
            expires_at=expires_at,
            is_active=True
        )
        db.add(subscription)
        created_subscriptions.append(subscription)

    await db.commit()

    # Refresh to get IDs
    for sub in created_subscriptions:
        await db.refresh(sub)

    return [
        WebhookSubscriptionResponse(
            id=sub.id,
            clio_subscription_id=sub.clio_subscription_id,
            event_type=sub.event_type,
            webhook_url=sub.webhook_url,
            is_active=sub.is_active,
            expires_at=sub.expires_at,
            created_at=sub.created_at
        )
        for sub in created_subscriptions
    ]


@router.get("/subscriptions", response_model=list[WebhookSubscriptionResponse])
async def list_webhook_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List all webhook subscriptions for the current user"""
    result = await db.execute(
        select(ClioWebhookSubscription)
        .where(ClioWebhookSubscription.user_id == current_user.id)
        .order_by(ClioWebhookSubscription.created_at.desc())
    )
    subscriptions = result.scalars().all()

    return [
        WebhookSubscriptionResponse(
            id=sub.id,
            clio_subscription_id=sub.clio_subscription_id,
            event_type=sub.event_type,
            webhook_url=sub.webhook_url,
            is_active=sub.is_active,
            expires_at=sub.expires_at,
            created_at=sub.created_at
        )
        for sub in subscriptions
    ]


@router.post("/subscriptions/{subscription_id}/renew")
async def renew_webhook_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Renew a webhook subscription before it expires.

    Clio webhooks expire after 31 days. Call this endpoint to extend
    the expiration for another 31 days.
    """
    # Get subscription
    result = await db.execute(
        select(ClioWebhookSubscription)
        .where(ClioWebhookSubscription.id == subscription_id)
        .where(ClioWebhookSubscription.user_id == current_user.id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Get user's Clio integration
    result = await db.execute(
        select(ClioIntegration).where(ClioIntegration.user_id == current_user.id)
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=400, detail="Clio integration not found")

    # Decrypt tokens
    access_token = decrypt_token(integration.access_token_encrypted)
    refresh_token = decrypt_token(integration.refresh_token_encrypted)

    # Renew in Clio
    async with ClioClient(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=integration.token_expires_at,
        region=integration.clio_region
    ) as clio:
        try:
            renewed = await clio.renew_webhook(subscription.clio_subscription_id)

            # Update local expiration
            subscription.expires_at = datetime.utcnow() + timedelta(days=31)
            subscription.updated_at = datetime.utcnow()
            await db.commit()

            return {
                "status": "renewed",
                "subscription_id": subscription.id,
                "new_expires_at": subscription.expires_at
            }
        except Exception as e:
            logger.error(f"Failed to renew webhook: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to renew webhook: {str(e)}"
            )


@router.delete("/subscriptions/{subscription_id}")
async def delete_webhook_subscription(
    subscription_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a webhook subscription"""
    # Get subscription
    result = await db.execute(
        select(ClioWebhookSubscription)
        .where(ClioWebhookSubscription.id == subscription_id)
        .where(ClioWebhookSubscription.user_id == current_user.id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription not found")

    # Get user's Clio integration
    result = await db.execute(
        select(ClioIntegration).where(ClioIntegration.user_id == current_user.id)
    )
    integration = result.scalar_one_or_none()

    if integration:
        # Decrypt tokens
        access_token = decrypt_token(integration.access_token_encrypted)
        refresh_token = decrypt_token(integration.refresh_token_encrypted)

        # Delete from Clio
        async with ClioClient(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            try:
                await clio.delete_webhook(subscription.clio_subscription_id)
            except Exception as e:
                logger.warning(f"Failed to delete webhook from Clio: {e}")
                # Continue to delete locally even if Clio deletion fails

    # Delete locally
    await db.delete(subscription)
    await db.commit()

    return {"status": "deleted", "subscription_id": subscription_id}
