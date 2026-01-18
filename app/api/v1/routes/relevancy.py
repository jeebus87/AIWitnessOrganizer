"""API endpoints for relevancy analysis (claims and witness links)"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import User, Matter, CaseClaim, ClaimType
from app.api.deps import get_current_user
from app.services.claims_service import ClaimsService, ExtractedClaim, WitnessClaimLinkData

router = APIRouter(prefix="/relevancy", tags=["relevancy"])


# Request/Response Models
class ClaimCreate(BaseModel):
    """Create a new claim"""
    claim_type: str  # "allegation" or "defense"
    text: str
    page: Optional[int] = None


class ClaimUpdate(BaseModel):
    """Update a claim"""
    text: Optional[str] = None
    is_verified: Optional[bool] = None


class WitnessClaimLinkCreate(BaseModel):
    """Link a witness to a claim"""
    witness_id: int
    claim_number: int
    claim_type: str  # "allegation" or "defense"
    relationship: str  # "supports", "undermines", "neutral"
    explanation: Optional[str] = None


class ClaimResponse(BaseModel):
    """Response for a single claim"""
    id: int
    matter_id: int
    claim_type: str
    claim_number: int
    text: str
    source_page: Optional[int]
    extraction_method: str
    is_verified: bool
    confidence_score: Optional[float]


# Helper to verify matter access
async def verify_matter_access(
    matter_id: int,
    current_user: User,
    db: AsyncSession
) -> Matter:
    """Verify user has access to the matter"""
    from sqlalchemy import select
    result = await db.execute(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.user_id == current_user.id
        )
    )
    matter = result.scalar_one_or_none()
    if not matter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found or access denied"
        )
    return matter


@router.get("/{matter_id}")
async def get_relevancy_analysis(
    matter_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get comprehensive relevancy analysis for a matter.

    Returns allegations, defenses, and all witness linkages.
    """
    await verify_matter_access(matter_id, current_user, db)

    claims_service = ClaimsService()
    analysis = await claims_service.get_relevancy_analysis(db, matter_id)

    return analysis


@router.get("/{matter_id}/claims")
async def get_claims(
    matter_id: int,
    claim_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all claims for a matter, optionally filtered by type.
    """
    await verify_matter_access(matter_id, current_user, db)

    claims_service = ClaimsService()

    type_filter = None
    if claim_type:
        try:
            type_filter = ClaimType(claim_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid claim_type: {claim_type}. Use 'allegation' or 'defense'"
            )

    claims = await claims_service.get_claims_for_matter(db, matter_id, type_filter)

    return {
        "claims": [
            {
                "id": c.id,
                "claim_type": c.claim_type.value,
                "claim_number": c.claim_number,
                "text": c.claim_text,
                "source_page": c.source_page,
                "extraction_method": c.extraction_method,
                "is_verified": c.is_verified,
                "confidence_score": c.confidence_score
            }
            for c in claims
        ]
    }


@router.post("/{matter_id}/claims")
async def create_claim(
    matter_id: int,
    claim: ClaimCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Manually add a claim to a matter.
    """
    await verify_matter_access(matter_id, current_user, db)

    if claim.claim_type not in ["allegation", "defense"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="claim_type must be 'allegation' or 'defense'"
        )

    claims_service = ClaimsService()

    extracted_claim = ExtractedClaim(
        claim_type=claim.claim_type,
        number=0,  # Will be auto-assigned
        text=claim.text,
        page=claim.page,
        confidence=1.0  # Manual entries have full confidence
    )

    created = await claims_service.add_claims(
        db=db,
        matter_id=matter_id,
        claims=[extracted_claim],
        extraction_method="manual"
    )

    if not created:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create claim"
        )

    c = created[0]
    return {
        "id": c.id,
        "claim_type": c.claim_type.value,
        "claim_number": c.claim_number,
        "text": c.claim_text,
        "source_page": c.source_page,
        "extraction_method": c.extraction_method,
        "is_verified": c.is_verified,
        "confidence_score": c.confidence_score
    }


@router.patch("/{matter_id}/claims/{claim_id}")
async def update_claim(
    matter_id: int,
    claim_id: int,
    update: ClaimUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a claim's text or verification status.
    """
    await verify_matter_access(matter_id, current_user, db)

    claims_service = ClaimsService()

    # Verify claim belongs to this matter
    from sqlalchemy import select
    result = await db.execute(
        select(CaseClaim).where(
            CaseClaim.id == claim_id,
            CaseClaim.matter_id == matter_id
        )
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found"
        )

    if update.text is not None:
        claim = await claims_service.update_claim_text(db, claim_id, update.text)

    if update.is_verified is not None:
        claim = await claims_service.verify_claim(db, claim_id, update.is_verified)

    return {
        "id": claim.id,
        "claim_type": claim.claim_type.value,
        "claim_number": claim.claim_number,
        "text": claim.claim_text,
        "is_verified": claim.is_verified
    }


@router.delete("/{matter_id}/claims/{claim_id}")
async def delete_claim(
    matter_id: int,
    claim_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a claim (also removes all witness links to it).
    """
    await verify_matter_access(matter_id, current_user, db)

    # Verify claim belongs to this matter
    from sqlalchemy import select
    result = await db.execute(
        select(CaseClaim).where(
            CaseClaim.id == claim_id,
            CaseClaim.matter_id == matter_id
        )
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found"
        )

    claims_service = ClaimsService()
    deleted = await claims_service.delete_claim(db, claim_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete claim"
        )

    return {"success": True, "message": "Claim deleted"}


@router.post("/{matter_id}/witness-links")
async def create_witness_link(
    matter_id: int,
    link: WitnessClaimLinkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Link a witness to a specific claim.
    """
    await verify_matter_access(matter_id, current_user, db)

    if link.claim_type not in ["allegation", "defense"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="claim_type must be 'allegation' or 'defense'"
        )

    if link.relationship not in ["supports", "undermines", "neutral"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="relationship must be 'supports', 'undermines', or 'neutral'"
        )

    claims_service = ClaimsService()

    link_data = WitnessClaimLinkData(
        claim_number=link.claim_number,
        claim_type=link.claim_type,
        relationship=link.relationship,
        explanation=link.explanation or ""
    )

    created = await claims_service.link_witness_to_claims(
        db=db,
        witness_id=link.witness_id,
        matter_id=matter_id,
        links=[link_data]
    )

    return {
        "success": True,
        "links_created": len(created)
    }


@router.post("/{matter_id}/claims/{claim_id}/verify")
async def verify_claim(
    matter_id: int,
    claim_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a claim as verified by the user.
    """
    await verify_matter_access(matter_id, current_user, db)

    claims_service = ClaimsService()
    claim = await claims_service.verify_claim(db, claim_id, True)

    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Claim not found"
        )

    return {
        "id": claim.id,
        "is_verified": claim.is_verified
    }
