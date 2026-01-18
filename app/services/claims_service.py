"""Service for extracting and managing case claims (allegations and defenses)"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    CaseClaim, ClaimType, WitnessClaimLink, Witness, Document, Matter
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractedClaim:
    """A claim extracted from a document"""
    claim_type: str  # "allegation" or "defense"
    number: int
    text: str
    page: Optional[int] = None
    confidence: float = 0.8


@dataclass
class WitnessClaimLinkData:
    """Data for linking a witness to a claim"""
    claim_number: int
    claim_type: str  # "allegation" or "defense"
    relationship: str  # "supports", "undermines", "neutral"
    explanation: str


class ClaimsService:
    """
    Service for extracting allegations and defenses from legal documents
    and linking witnesses to specific claims.
    """

    async def get_claims_for_matter(
        self,
        db: AsyncSession,
        matter_id: int,
        claim_type: Optional[ClaimType] = None
    ) -> List[CaseClaim]:
        """
        Get all claims for a matter, optionally filtered by type.

        Args:
            db: Database session
            matter_id: ID of the matter
            claim_type: Optional filter for allegation or defense

        Returns:
            List of CaseClaim records
        """
        query = (
            select(CaseClaim)
            .where(CaseClaim.matter_id == matter_id)
            .options(selectinload(CaseClaim.witness_links))
            .order_by(CaseClaim.claim_type, CaseClaim.claim_number)
        )

        if claim_type:
            query = query.where(CaseClaim.claim_type == claim_type)

        result = await db.execute(query)
        return result.scalars().all()

    async def get_next_claim_number(
        self,
        db: AsyncSession,
        matter_id: int,
        claim_type: ClaimType
    ) -> int:
        """Get the next sequential claim number for a matter and type"""
        result = await db.execute(
            select(func.max(CaseClaim.claim_number))
            .where(
                CaseClaim.matter_id == matter_id,
                CaseClaim.claim_type == claim_type
            )
        )
        max_num = result.scalar()
        return (max_num or 0) + 1

    async def add_claims(
        self,
        db: AsyncSession,
        matter_id: int,
        claims: List[ExtractedClaim],
        source_document_id: Optional[int] = None,
        extraction_method: str = "discovery"
    ) -> List[CaseClaim]:
        """
        Add extracted claims to a matter.

        Args:
            db: Database session
            matter_id: ID of the matter
            claims: List of extracted claims
            source_document_id: ID of the source document
            extraction_method: How claims were extracted ("pleading", "discovery", "manual")

        Returns:
            List of created CaseClaim records
        """
        created_claims = []

        # Group claims by type to assign sequential numbers
        allegations = [c for c in claims if c.claim_type == "allegation"]
        defenses = [c for c in claims if c.claim_type == "defense"]

        # Get next numbers for each type
        next_allegation = await self.get_next_claim_number(db, matter_id, ClaimType.ALLEGATION)
        next_defense = await self.get_next_claim_number(db, matter_id, ClaimType.DEFENSE)

        for claim in allegations:
            db_claim = CaseClaim(
                matter_id=matter_id,
                claim_type=ClaimType.ALLEGATION,
                claim_number=next_allegation,
                claim_text=claim.text,
                source_document_id=source_document_id,
                source_page=claim.page,
                extraction_method=extraction_method,
                confidence_score=claim.confidence
            )
            db.add(db_claim)
            created_claims.append(db_claim)
            next_allegation += 1

        for claim in defenses:
            db_claim = CaseClaim(
                matter_id=matter_id,
                claim_type=ClaimType.DEFENSE,
                claim_number=next_defense,
                claim_text=claim.text,
                source_document_id=source_document_id,
                source_page=claim.page,
                extraction_method=extraction_method,
                confidence_score=claim.confidence
            )
            db.add(db_claim)
            created_claims.append(db_claim)
            next_defense += 1

        await db.commit()

        logger.info(
            f"Added {len(allegations)} allegations and {len(defenses)} defenses "
            f"to matter {matter_id}"
        )

        return created_claims

    async def link_witness_to_claims(
        self,
        db: AsyncSession,
        witness_id: int,
        matter_id: int,
        links: List[WitnessClaimLinkData]
    ) -> List[WitnessClaimLink]:
        """
        Link a witness to specific claims.

        Args:
            db: Database session
            witness_id: ID of the witness
            matter_id: ID of the matter (to find claims)
            links: List of link data

        Returns:
            List of created WitnessClaimLink records
        """
        created_links = []

        for link_data in links:
            # Find the claim
            claim_type = ClaimType(link_data.claim_type)
            result = await db.execute(
                select(CaseClaim).where(
                    CaseClaim.matter_id == matter_id,
                    CaseClaim.claim_type == claim_type,
                    CaseClaim.claim_number == link_data.claim_number
                )
            )
            claim = result.scalar_one_or_none()

            if not claim:
                logger.warning(
                    f"Claim not found: {link_data.claim_type} #{link_data.claim_number} "
                    f"for matter {matter_id}"
                )
                continue

            # Check if link already exists
            result = await db.execute(
                select(WitnessClaimLink).where(
                    WitnessClaimLink.witness_id == witness_id,
                    WitnessClaimLink.case_claim_id == claim.id
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing link
                existing.relevance_explanation = link_data.explanation
                existing.supports_or_undermines = link_data.relationship
            else:
                # Create new link
                db_link = WitnessClaimLink(
                    witness_id=witness_id,
                    case_claim_id=claim.id,
                    relevance_explanation=link_data.explanation,
                    supports_or_undermines=link_data.relationship
                )
                db.add(db_link)
                created_links.append(db_link)

        await db.commit()
        return created_links

    async def get_relevancy_analysis(
        self,
        db: AsyncSession,
        matter_id: int
    ) -> Dict[str, Any]:
        """
        Get comprehensive relevancy analysis for a matter.

        Returns:
            Dictionary containing:
            - allegations: List of allegations with linked witnesses
            - defenses: List of defenses with linked witnesses
            - witness_summary: Each witness with their claim links
            - unlinked_witnesses: Witnesses not yet linked to claims
        """
        # Get all claims with their witness links
        allegations = await self.get_claims_for_matter(db, matter_id, ClaimType.ALLEGATION)
        defenses = await self.get_claims_for_matter(db, matter_id, ClaimType.DEFENSE)

        # Get all witnesses for the matter
        result = await db.execute(
            select(Witness)
            .join(Document)
            .where(Document.matter_id == matter_id)
            .options(selectinload(Witness.document))
        )
        all_witnesses = result.scalars().all()

        # Get all witness-claim links
        result = await db.execute(
            select(WitnessClaimLink)
            .join(CaseClaim)
            .where(CaseClaim.matter_id == matter_id)
            .options(
                selectinload(WitnessClaimLink.witness),
                selectinload(WitnessClaimLink.case_claim)
            )
        )
        all_links = result.scalars().all()

        # Build linked witness IDs set
        linked_witness_ids = {link.witness_id for link in all_links}

        # Build response
        def format_claim(claim: CaseClaim) -> Dict:
            claim_links = [l for l in all_links if l.case_claim_id == claim.id]
            return {
                "id": claim.id,
                "number": claim.claim_number,
                "type": claim.claim_type.value,
                "text": claim.claim_text,
                "source_page": claim.source_page,
                "extraction_method": claim.extraction_method,
                "is_verified": claim.is_verified,
                "linked_witnesses": [
                    {
                        "witness_id": link.witness_id,
                        "witness_name": link.witness.full_name if link.witness else "Unknown",
                        "relationship": link.supports_or_undermines,
                        "explanation": link.relevance_explanation
                    }
                    for link in claim_links
                ]
            }

        def format_witness_summary(witness: Witness) -> Dict:
            witness_links = [l for l in all_links if l.witness_id == witness.id]
            return {
                "witness_id": witness.id,
                "name": witness.full_name,
                "role": witness.role.value if witness.role else None,
                "document": witness.document.filename if witness.document else None,
                "claim_links": [
                    {
                        "claim_id": link.case_claim_id,
                        "claim_type": link.case_claim.claim_type.value if link.case_claim else None,
                        "claim_number": link.case_claim.claim_number if link.case_claim else None,
                        "relationship": link.supports_or_undermines,
                        "explanation": link.relevance_explanation
                    }
                    for link in witness_links
                ]
            }

        return {
            "allegations": [format_claim(c) for c in allegations],
            "defenses": [format_claim(c) for c in defenses],
            "witness_summary": [
                format_witness_summary(w)
                for w in all_witnesses
                if w.id in linked_witness_ids
            ],
            "unlinked_witnesses": [
                {
                    "witness_id": w.id,
                    "name": w.full_name,
                    "role": w.role.value if w.role else None,
                    "document": w.document.filename if w.document else None
                }
                for w in all_witnesses
                if w.id not in linked_witness_ids
            ],
            "stats": {
                "total_allegations": len(allegations),
                "total_defenses": len(defenses),
                "total_witnesses": len(all_witnesses),
                "linked_witnesses": len(linked_witness_ids),
                "unlinked_witnesses": len(all_witnesses) - len(linked_witness_ids)
            }
        }

    async def delete_claim(
        self,
        db: AsyncSession,
        claim_id: int
    ) -> bool:
        """Delete a claim (cascade deletes witness links)"""
        result = await db.execute(
            select(CaseClaim).where(CaseClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()

        if not claim:
            return False

        await db.delete(claim)
        await db.commit()
        return True

    async def verify_claim(
        self,
        db: AsyncSession,
        claim_id: int,
        verified: bool = True
    ) -> Optional[CaseClaim]:
        """Mark a claim as verified/unverified by user"""
        result = await db.execute(
            select(CaseClaim).where(CaseClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()

        if not claim:
            return None

        claim.is_verified = verified
        await db.commit()
        return claim

    async def update_claim_text(
        self,
        db: AsyncSession,
        claim_id: int,
        new_text: str
    ) -> Optional[CaseClaim]:
        """Update the text of a claim"""
        result = await db.execute(
            select(CaseClaim).where(CaseClaim.id == claim_id)
        )
        claim = result.scalar_one_or_none()

        if not claim:
            return None

        claim.claim_text = new_text
        claim.extraction_method = "manual"  # Mark as manually edited
        await db.commit()
        return claim

    async def compute_witness_relevance(
        self,
        db: AsyncSession,
        witness_id: int
    ) -> tuple[str, str]:
        """
        Compute aggregate relevance for a witness from their claim links.

        Args:
            db: Database session
            witness_id: ID of the witness

        Returns:
            Tuple of (relevance_level, relevance_reason)
            - relevance_level: HIGHLY_RELEVANT, RELEVANT, SOMEWHAT_RELEVANT, NOT_RELEVANT, or UNKNOWN
            - relevance_reason: Concatenated reasons from claim links
        """
        result = await db.execute(
            select(WitnessClaimLink)
            .where(WitnessClaimLink.witness_id == witness_id)
            .options(selectinload(WitnessClaimLink.case_claim))
        )
        links = result.scalars().all()

        if not links:
            return ("UNKNOWN", "No claim links found")

        # Score: each link adds points, "supports" weighted higher than others
        score = sum(2 if l.supports_or_undermines == "supports" else 1 for l in links)
        claim_count = len(links)

        # Determine relevance level based on score and claim count
        if score >= 4 or claim_count >= 3:
            level = "HIGHLY_RELEVANT"
        elif score >= 2:
            level = "RELEVANT"
        elif score >= 1:
            level = "SOMEWHAT_RELEVANT"
        else:
            level = "NOT_RELEVANT"

        # Build relevance reason from top 3 claim links
        reasons = []
        for link in links[:3]:
            if link.case_claim:
                claim_ref = f"{link.case_claim.claim_type.value[0].upper()}{link.case_claim.claim_number}"
                reasons.append(f"{claim_ref}: {link.relevance_explanation}")

        reason = "; ".join(reasons) if reasons else "Linked to case claims"

        return (level, reason)
