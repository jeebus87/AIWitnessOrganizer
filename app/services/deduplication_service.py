"""Service for deduplicating witnesses across documents in a matter"""
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from thefuzz import fuzz
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Witness, CanonicalWitness, Document, Matter,
    WitnessRole, RelevanceLevel
)

logger = logging.getLogger(__name__)


class DeduplicationService:
    """
    Service for deduplicating witnesses across multiple documents in a matter.

    Uses fuzzy string matching to identify witnesses that are likely the same person
    mentioned in different documents, then creates canonical records that consolidate
    information from all sources.
    """

    # Similarity threshold for considering two names as the same person (0-100)
    NAME_SIMILARITY_THRESHOLD = 85

    # Common name prefixes/suffixes to normalize
    PREFIXES = ['mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 'hon', 'judge', 'esq']
    SUFFIXES = ['jr', 'sr', 'ii', 'iii', 'iv', 'md', 'phd', 'esq', 'jd', 'llb', 'cpa']

    def normalize_name(self, name: str) -> str:
        """
        Normalize a name for comparison by:
        - Converting to lowercase
        - Removing common prefixes/suffixes (Mr., Dr., Jr., etc.)
        - Removing punctuation
        - Normalizing whitespace
        """
        if not name:
            return ""

        # Lowercase
        normalized = name.lower().strip()

        # Remove punctuation except hyphens (for hyphenated names)
        normalized = re.sub(r'[^\w\s\-]', '', normalized)

        # Split into parts
        parts = normalized.split()

        # Remove prefixes
        while parts and parts[0] in self.PREFIXES:
            parts.pop(0)

        # Remove suffixes
        while parts and parts[-1] in self.SUFFIXES:
            parts.pop()

        # Rejoin and normalize whitespace
        normalized = ' '.join(parts)

        return normalized

    def names_match(self, name1: str, name2: str) -> Tuple[bool, int]:
        """
        Determine if two names likely refer to the same person using
        multiple fuzzy matching algorithms.

        Args:
            name1: First name to compare
            name2: Second name to compare

        Returns:
            Tuple of (is_match, similarity_score)
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        if not norm1 or not norm2:
            return False, 0

        # Exact match after normalization
        if norm1 == norm2:
            return True, 100

        # Use multiple fuzzy matching algorithms and take the best score
        scores = [
            fuzz.ratio(norm1, norm2),           # Simple ratio
            fuzz.partial_ratio(norm1, norm2),    # Partial match for substrings
            fuzz.token_sort_ratio(norm1, norm2), # Order-independent token matching
        ]

        best_score = max(scores)
        return best_score >= self.NAME_SIMILARITY_THRESHOLD, best_score

    def _select_best_role(self, roles: List[WitnessRole]) -> WitnessRole:
        """Select the most specific/important role from a list of roles"""
        # Priority order (more specific roles first)
        priority = [
            WitnessRole.PLAINTIFF,
            WitnessRole.DEFENDANT,
            WitnessRole.EXPERT,
            WitnessRole.PHYSICIAN,
            WitnessRole.ATTORNEY,
            WitnessRole.POLICE_OFFICER,
            WitnessRole.EYEWITNESS,
            WitnessRole.FAMILY_MEMBER,
            WitnessRole.COLLEAGUE,
            WitnessRole.BYSTANDER,
            WitnessRole.MENTIONED,
            WitnessRole.OTHER,
        ]

        for role in priority:
            if role in roles:
                return role

        return roles[0] if roles else WitnessRole.OTHER

    def _select_best_relevance(self, relevances: List[RelevanceLevel]) -> RelevanceLevel:
        """Select the highest relevance level from a list"""
        priority = [
            RelevanceLevel.HIGHLY_RELEVANT,
            RelevanceLevel.RELEVANT,
            RelevanceLevel.SOMEWHAT_RELEVANT,
            RelevanceLevel.NOT_RELEVANT,
        ]

        for rel in priority:
            if rel in relevances:
                return rel

        return relevances[0] if relevances else RelevanceLevel.RELEVANT

    async def deduplicate_matter_witnesses(
        self,
        db: AsyncSession,
        matter_id: int,
        job_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Deduplicate witnesses for a matter by grouping similar names
        and creating canonical witness records.

        Args:
            db: Database session
            matter_id: ID of the matter to deduplicate
            job_id: Optional job ID to filter witnesses (only dedup from this job)

        Returns:
            Dictionary with deduplication statistics
        """
        logger.info(f"Starting deduplication for matter {matter_id}")

        # Get all witnesses for this matter (not already assigned to canonical)
        query = (
            select(Witness)
            .join(Document)
            .where(
                Document.matter_id == matter_id,
                Witness.canonical_witness_id.is_(None)
            )
            .options(selectinload(Witness.document))
        )

        if job_id:
            query = query.where(Witness.job_id == job_id)

        result = await db.execute(query)
        witnesses = result.scalars().all()

        if not witnesses:
            logger.info(f"No unlinked witnesses found for matter {matter_id}")
            return {
                "success": True,
                "matter_id": matter_id,
                "witnesses_processed": 0,
                "canonical_witnesses_created": 0,
                "duplicates_merged": 0
            }

        logger.info(f"Found {len(witnesses)} unlinked witnesses to process")

        # Group witnesses by similar names
        groups: List[List[Witness]] = []
        processed_ids = set()

        for witness in witnesses:
            if witness.id in processed_ids:
                continue

            # Start a new group with this witness
            group = [witness]
            processed_ids.add(witness.id)

            # Find all other witnesses that match this name
            for other in witnesses:
                if other.id in processed_ids:
                    continue

                is_match, score = self.names_match(witness.full_name, other.full_name)
                if is_match:
                    group.append(other)
                    processed_ids.add(other.id)
                    logger.debug(
                        f"Matched '{witness.full_name}' with '{other.full_name}' (score: {score})"
                    )

            groups.append(group)

        logger.info(f"Grouped {len(witnesses)} witnesses into {len(groups)} canonical records")

        # Create canonical witnesses for each group
        canonical_created = 0
        duplicates_merged = 0

        for group in groups:
            # Merge information from all witnesses in the group
            canonical = await self._create_canonical_from_group(db, matter_id, group)
            db.add(canonical)
            await db.flush()  # Get the ID

            # Link all source witnesses to this canonical
            for witness in group:
                witness.canonical_witness_id = canonical.id

            canonical_created += 1
            if len(group) > 1:
                duplicates_merged += len(group) - 1

        await db.commit()

        logger.info(
            f"Deduplication complete for matter {matter_id}: "
            f"{canonical_created} canonical, {duplicates_merged} duplicates merged"
        )

        return {
            "success": True,
            "matter_id": matter_id,
            "witnesses_processed": len(witnesses),
            "canonical_witnesses_created": canonical_created,
            "duplicates_merged": duplicates_merged
        }

    async def _create_canonical_from_group(
        self,
        db: AsyncSession,
        matter_id: int,
        witnesses: List[Witness]
    ) -> CanonicalWitness:
        """
        Create a canonical witness record from a group of matching witnesses.

        Merges information by:
        - Using the most common name variation
        - Selecting the most specific role
        - Selecting the highest relevance
        - Combining all observations
        - Taking best contact info available
        """
        # Find most common/longest name (likely the most complete)
        names = [w.full_name for w in witnesses if w.full_name]
        best_name = max(names, key=len) if names else "Unknown"

        # Collect roles and relevances
        roles = [w.role for w in witnesses if w.role]
        relevances = [w.relevance for w in witnesses if w.relevance]
        relevance_reasons = [w.relevance_reason for w in witnesses if w.relevance_reason]

        # Merge observations
        merged_observations = []
        for w in witnesses:
            if w.observation:
                merged_observations.append({
                    "document_id": w.document_id,
                    "document_filename": w.document.filename if w.document else "Unknown",
                    "page": w.source_page,
                    "observation": w.observation,
                    "source_quote": w.source_quote,
                    "confidence": w.confidence_score
                })

        # Get best contact info (prefer non-empty)
        email = next((w.email for w in witnesses if w.email), None)
        phone = next((w.phone for w in witnesses if w.phone), None)
        address = next((w.address for w in witnesses if w.address), None)

        # Get max confidence
        confidences = [w.confidence_score for w in witnesses if w.confidence_score]
        max_confidence = max(confidences) if confidences else None

        # Combine relevance reasons
        combined_reason = " | ".join(relevance_reasons) if relevance_reasons else None

        return CanonicalWitness(
            matter_id=matter_id,
            full_name=best_name,
            role=self._select_best_role(roles) if roles else WitnessRole.OTHER,
            relevance=self._select_best_relevance(relevances) if relevances else RelevanceLevel.RELEVANT,
            relevance_reason=combined_reason,
            merged_observations=merged_observations,
            email=email,
            phone=phone,
            address=address,
            source_document_count=len(set(w.document_id for w in witnesses)),
            max_confidence_score=max_confidence
        )

    async def get_canonical_witnesses_for_matter(
        self,
        db: AsyncSession,
        matter_id: int
    ) -> List[CanonicalWitness]:
        """Get all canonical witnesses for a matter"""
        result = await db.execute(
            select(CanonicalWitness)
            .where(CanonicalWitness.matter_id == matter_id)
            .options(selectinload(CanonicalWitness.source_witnesses))
            .order_by(CanonicalWitness.full_name)
        )
        return result.scalars().all()
