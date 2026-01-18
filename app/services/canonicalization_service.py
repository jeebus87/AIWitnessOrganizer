"""
Canonicalization Service for Witness Deduplication

Implements a hybrid approach:
1. Deterministic matching (normalized names)
2. Fuzzy string matching (Levenshtein/Jaro-Winkler)
3. ML embedding-based semantic matching (Amazon Titan)

This service consolidates duplicate witness extractions into canonical records.
"""
import json
import logging
import re
import unicodedata
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import (
    Witness, CanonicalWitness, WitnessRole, RelevanceLevel, ImportanceLevel, Matter
)

logger = logging.getLogger(__name__)

# Matching thresholds
FUZZY_MATCH_THRESHOLD = 0.85  # 85% similarity for fuzzy matching
EMBEDDING_MATCH_THRESHOLD = 0.92  # 92% cosine similarity for embedding matching

# Case attorney exclusion patterns
# These witnesses are attorneys OF RECORD for the case, not fact witnesses
CASE_ATTORNEY_ROLE_KEYWORDS = ["attorney", "counsel", "lawyer"]

CASE_ATTORNEY_OBSERVATION_PATTERNS = [
    # Representation patterns
    r"represent(s|ing|ed)?\s+(the\s+)?(defendant|plaintiff|client|party)",
    r"counsel\s+for\s+(the\s+)?(defendant|plaintiff|client|party)",
    r"attorney\s+for\s+(the\s+)?(defendant|plaintiff|client|party)",
    r"on\s+behalf\s+of\s+(the\s+)?(defendant|plaintiff|client|party)",
    r"defense\s+(attorney|counsel|lawyer)",
    r"plaintiff('s|s')?\s+(attorney|counsel|lawyer)",
    r"opposing\s+counsel",
    r"legal\s+counsel\s+for",

    # Pro hac vice (attorney seeking admission to represent)
    r"pro\s+hac\s+vice",
    r"seeking\s+(pro\s+hac\s+vice\s+)?admission\s+to\s+represent",

    # Communication as counsel
    r"(attorney|counsel)\s+communicating\s+with",
    r"(attorney|counsel)\s+corresponding\s+with",

    # Legal representation activities (not fact witnessing)
    r"filed\s+(a\s+)?(motion|complaint|answer|brief|pleading)",
    r"argued\s+(the\s+)?case",
    r"appeared\s+(in\s+court|at\s+hearing|at\s+deposition)",
    r"signed\s+(the\s+)?(pleading|motion|brief|complaint)",
]

# Patterns that indicate the attorney IS a fact witness (should NOT be excluded)
ATTORNEY_FACT_WITNESS_PATTERNS = [
    r"witnessed\s+(the|a)\s+(event|accident|incident|signing|meeting)",
    r"personally\s+(saw|observed|witnessed|attended)",
    r"was\s+present\s+(at|when|during)",
    r"testified\s+(that|about|regarding)",
    r"overheard",
    r"physically\s+present",
    r"eyewitness",
]


@dataclass
class WitnessInput:
    """Input data for witness canonicalization"""
    full_name: str
    role: str
    importance: str
    observation: Optional[str] = None
    source_page: Optional[int] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    confidence_score: Optional[float] = None
    relevance: Optional[str] = None
    relevance_reason: Optional[str] = None


@dataclass
class CanonicalizationResult:
    """Result of witness canonicalization"""
    canonical_witness: Optional[CanonicalWitness]
    witness_record: Optional[Witness]
    is_new_canonical: bool
    is_excluded: bool
    exclusion_reason: Optional[str]
    match_type: Optional[str]  # "exact", "fuzzy", "embedding", "new", or None if excluded
    match_confidence: float


class CanonicalizationService:
    """
    Service for deduplicating witnesses using hybrid matching:
    1. Deterministic (exact normalized name match)
    2. Fuzzy (string similarity)
    3. Semantic (ML embeddings)
    """

    def __init__(self):
        self.bedrock_client = None
        self._init_bedrock()

    def _init_bedrock(self):
        """Initialize Bedrock client for embeddings"""
        try:
            self.bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=settings.AWS_REGION,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {e}")
            self.bedrock_client = None

    # =========================================================================
    # Case Attorney Detection
    # =========================================================================

    def is_case_attorney(self, role: str, observation: str) -> Tuple[bool, str]:
        """
        Determine if a witness should be excluded as a case attorney of record.

        Case attorneys are lawyers representing parties in THIS case - they are
        advocates, not fact witnesses. However, attorneys CAN be fact witnesses
        if they personally witnessed events.

        Returns:
            Tuple of (should_exclude: bool, reason: str)
        """
        if not role:
            return False, ""

        role_lower = role.lower()
        observation_lower = (observation or "").lower()

        # Check if role is attorney-related
        is_attorney_role = any(
            keyword in role_lower for keyword in CASE_ATTORNEY_ROLE_KEYWORDS
        )

        if not is_attorney_role:
            return False, ""

        # Check if attorney is acting as a fact witness (don't exclude)
        for pattern in ATTORNEY_FACT_WITNESS_PATTERNS:
            if re.search(pattern, observation_lower, re.IGNORECASE):
                return False, f"Attorney retained as fact witness (matched: {pattern})"

        # Check if observation indicates case attorney role (exclude)
        for pattern in CASE_ATTORNEY_OBSERVATION_PATTERNS:
            if re.search(pattern, observation_lower, re.IGNORECASE):
                return True, f"Case attorney of record (matched pattern: {pattern})"

        # If attorney role but no clear indicator either way, don't exclude
        # (conservative approach - let user decide)
        return False, "Attorney role but no clear representation indicator"

    # =========================================================================
    # Name Normalization
    # =========================================================================

    def normalize_name(self, name: str) -> str:
        """
        Normalize a name for deterministic matching.

        - Lowercase
        - Remove punctuation
        - Remove titles (Mr., Mrs., Dr., Esq., etc.)
        - Remove middle initials
        - Remove extra whitespace
        - Unicode normalization
        """
        if not name:
            return ""

        # Unicode normalization
        name = unicodedata.normalize('NFKD', name)

        # Lowercase
        name = name.lower()

        # Remove common titles
        titles = [
            r'\bmr\.?\s*', r'\bmrs\.?\s*', r'\bms\.?\s*', r'\bdr\.?\s*',
            r'\besq\.?\s*', r'\bjr\.?\s*', r'\bsr\.?\s*', r'\biii\b', r'\bii\b',
            r'\biv\b', r'\battorney\b', r'\bcounsel\b'
        ]
        for title in titles:
            name = re.sub(title, '', name, flags=re.IGNORECASE)

        # Remove punctuation except spaces
        name = re.sub(r'[^\w\s]', '', name)

        # Remove single letter middle initials (e.g., "John A Smith" -> "John Smith")
        name = re.sub(r'\b[a-z]\b', '', name)

        # Normalize whitespace
        name = ' '.join(name.split())

        return name.strip()

    def extract_name_parts(self, name: str) -> Dict[str, str]:
        """Extract first, middle, and last name parts"""
        parts = name.strip().split()

        if len(parts) == 0:
            return {"first": "", "middle": "", "last": ""}
        elif len(parts) == 1:
            return {"first": parts[0], "middle": "", "last": ""}
        elif len(parts) == 2:
            return {"first": parts[0], "middle": "", "last": parts[1]}
        else:
            return {
                "first": parts[0],
                "middle": " ".join(parts[1:-1]),
                "last": parts[-1]
            }

    # =========================================================================
    # Fuzzy Matching
    # =========================================================================

    def jaro_winkler_similarity(self, s1: str, s2: str) -> float:
        """
        Compute Jaro-Winkler similarity between two strings.
        Returns a value between 0 and 1 (1 = identical).
        """
        if s1 == s2:
            return 1.0

        if not s1 or not s2:
            return 0.0

        len1, len2 = len(s1), len(s2)
        match_distance = max(len1, len2) // 2 - 1

        if match_distance < 0:
            match_distance = 0

        s1_matches = [False] * len1
        s2_matches = [False] * len2

        matches = 0
        transpositions = 0

        # Find matches
        for i in range(len1):
            start = max(0, i - match_distance)
            end = min(i + match_distance + 1, len2)

            for j in range(start, end):
                if s2_matches[j] or s1[i] != s2[j]:
                    continue
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

        if matches == 0:
            return 0.0

        # Count transpositions
        k = 0
        for i in range(len1):
            if not s1_matches[i]:
                continue
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

        jaro = (matches / len1 + matches / len2 +
                (matches - transpositions / 2) / matches) / 3

        # Winkler modification: boost for common prefix
        prefix = 0
        for i in range(min(len1, len2, 4)):
            if s1[i] == s2[i]:
                prefix += 1
            else:
                break

        return jaro + prefix * 0.1 * (1 - jaro)

    def levenshtein_similarity(self, s1: str, s2: str) -> float:
        """
        Compute Levenshtein similarity (1 - normalized edit distance).
        Returns a value between 0 and 1 (1 = identical).
        """
        if s1 == s2:
            return 1.0

        if not s1 or not s2:
            return 0.0

        len1, len2 = len(s1), len(s2)

        # Create distance matrix
        dp = [[0] * (len2 + 1) for _ in range(len1 + 1)]

        for i in range(len1 + 1):
            dp[i][0] = i
        for j in range(len2 + 1):
            dp[0][j] = j

        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                cost = 0 if s1[i-1] == s2[j-1] else 1
                dp[i][j] = min(
                    dp[i-1][j] + 1,      # deletion
                    dp[i][j-1] + 1,      # insertion
                    dp[i-1][j-1] + cost  # substitution
                )

        distance = dp[len1][len2]
        max_len = max(len1, len2)

        return 1 - (distance / max_len)

    def fuzzy_match_score(self, name1: str, name2: str) -> float:
        """
        Compute combined fuzzy match score using multiple algorithms.
        Returns average of Jaro-Winkler and Levenshtein similarity.
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        jw_score = self.jaro_winkler_similarity(norm1, norm2)
        lev_score = self.levenshtein_similarity(norm1, norm2)

        # Weight Jaro-Winkler slightly higher for names
        return (jw_score * 0.6 + lev_score * 0.4)

    # =========================================================================
    # ML Embedding Matching
    # =========================================================================

    async def get_name_embedding(self, name: str, context: str = "") -> Optional[List[float]]:
        """
        Get embedding vector for a witness name with optional context.
        Uses Amazon Titan Text Embeddings V2.
        """
        if not self.bedrock_client:
            logger.warning("Bedrock client not initialized, skipping embedding")
            return None

        try:
            # Combine name with context for better semantic matching
            text_to_embed = name
            if context:
                text_to_embed = f"{name}: {context[:500]}"

            response = self.bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v2:0",
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "inputText": text_to_embed[:8000],
                    "dimensions": 1536,
                    "normalize": True
                })
            )

            result = json.loads(response["body"].read())
            return result.get("embedding")

        except Exception as e:
            logger.error(f"Failed to get name embedding: {e}")
            return None

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors"""
        import math
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    # =========================================================================
    # Main Canonicalization Logic
    # =========================================================================

    async def find_canonical_witness(
        self,
        db: AsyncSession,
        matter_id: int,
        name: str,
        observation: Optional[str] = None,
        use_embeddings: bool = True
    ) -> Tuple[Optional[CanonicalWitness], str, float]:
        """
        Find a matching canonical witness for the given name.

        Returns:
            Tuple of (canonical_witness or None, match_type, confidence)
            match_type: "exact", "fuzzy", "embedding", or "none"
        """
        normalized_name = self.normalize_name(name)

        # Get all canonical witnesses for this matter
        result = await db.execute(
            select(CanonicalWitness).where(
                CanonicalWitness.matter_id == matter_id
            )
        )
        existing_witnesses = result.scalars().all()

        if not existing_witnesses:
            return None, "none", 0.0

        best_match = None
        best_score = 0.0
        best_type = "none"

        for canonical in existing_witnesses:
            canonical_normalized = self.normalize_name(canonical.full_name)

            # 1. Exact match (after normalization)
            if normalized_name == canonical_normalized:
                return canonical, "exact", 1.0

            # 2. Fuzzy matching
            fuzzy_score = self.fuzzy_match_score(name, canonical.full_name)
            if fuzzy_score >= FUZZY_MATCH_THRESHOLD and fuzzy_score > best_score:
                best_match = canonical
                best_score = fuzzy_score
                best_type = "fuzzy"

        # 3. Embedding matching (if fuzzy didn't find a good match and embeddings enabled)
        if use_embeddings and (best_match is None or best_score < EMBEDDING_MATCH_THRESHOLD):
            name_embedding = await self.get_name_embedding(name, observation or "")

            if name_embedding:
                for canonical in existing_witnesses:
                    # Get or compute canonical embedding
                    canonical_embedding = None

                    # Try to get stored embedding
                    if canonical.merged_observations:
                        obs_text = " ".join([
                            o.get("text", "") for o in canonical.merged_observations
                            if isinstance(o, dict)
                        ])[:500]
                    else:
                        obs_text = ""

                    canonical_embedding = await self.get_name_embedding(
                        canonical.full_name, obs_text
                    )

                    if canonical_embedding:
                        similarity = self.cosine_similarity(name_embedding, canonical_embedding)

                        if similarity >= EMBEDDING_MATCH_THRESHOLD and similarity > best_score:
                            best_match = canonical
                            best_score = similarity
                            best_type = "embedding"

        if best_match and best_score >= FUZZY_MATCH_THRESHOLD:
            return best_match, best_type, best_score

        return None, "none", 0.0

    async def create_or_update_canonical(
        self,
        db: AsyncSession,
        matter_id: int,
        witness_input: WitnessInput,
        document_id: int,
        filename: str,
        exclude_case_attorneys: bool = True
    ) -> CanonicalizationResult:
        """
        Create or update a canonical witness and link a new witness record.

        Args:
            db: Database session
            matter_id: ID of the matter
            witness_input: Witness data from extraction
            document_id: Source document ID
            filename: Source document filename
            exclude_case_attorneys: If True, filter out attorneys of record

        Returns:
            CanonicalizationResult with canonical witness, witness record, and metadata
        """
        # Check if this is a case attorney that should be excluded
        if exclude_case_attorneys:
            is_excluded, exclusion_reason = self.is_case_attorney(
                role=witness_input.role,
                observation=witness_input.observation
            )

            if is_excluded:
                logger.info(
                    f"Excluding case attorney '{witness_input.full_name}': {exclusion_reason}"
                )
                return CanonicalizationResult(
                    canonical_witness=None,
                    witness_record=None,
                    is_new_canonical=False,
                    is_excluded=True,
                    exclusion_reason=exclusion_reason,
                    match_type=None,
                    match_confidence=0.0
                )

        # Try to find existing canonical witness
        canonical, match_type, confidence = await self.find_canonical_witness(
            db=db,
            matter_id=matter_id,
            name=witness_input.full_name,
            observation=witness_input.observation,
            use_embeddings=True
        )

        is_new_canonical = False

        if canonical:
            # Update existing canonical witness with merged data
            canonical = await self._merge_into_canonical(
                db, canonical, witness_input, document_id, filename
            )
            logger.info(
                f"Matched witness '{witness_input.full_name}' to canonical "
                f"'{canonical.full_name}' via {match_type} (score: {confidence:.2f})"
            )
        else:
            # Create new canonical witness
            canonical = await self._create_canonical(
                db, matter_id, witness_input, document_id, filename
            )
            is_new_canonical = True
            match_type = "new"
            confidence = 1.0
            logger.info(f"Created new canonical witness: '{canonical.full_name}'")

        # Create the individual witness record linked to canonical
        witness = await self._create_witness_record(
            db, canonical, witness_input, document_id
        )

        return CanonicalizationResult(
            canonical_witness=canonical,
            witness_record=witness,
            is_new_canonical=is_new_canonical,
            is_excluded=False,
            exclusion_reason=None,
            match_type=match_type,
            match_confidence=confidence
        )

    async def _create_canonical(
        self,
        db: AsyncSession,
        matter_id: int,
        witness_input: WitnessInput,
        document_id: int,
        filename: str
    ) -> CanonicalWitness:
        """Create a new canonical witness record"""

        # Parse role enum
        try:
            role = WitnessRole(witness_input.role.lower())
        except (ValueError, AttributeError):
            role = WitnessRole.OTHER

        # Parse relevance enum
        relevance = RelevanceLevel.RELEVANT
        if witness_input.relevance:
            try:
                relevance = RelevanceLevel(witness_input.relevance.lower())
            except (ValueError, AttributeError):
                pass

        # Create merged observations structure
        merged_observations = []
        if witness_input.observation:
            merged_observations.append({
                "doc_id": document_id,
                "filename": filename,
                "page": witness_input.source_page,
                "text": witness_input.observation
            })

        canonical = CanonicalWitness(
            matter_id=matter_id,
            full_name=witness_input.full_name,
            role=role,
            relevance=relevance,
            relevance_reason=witness_input.relevance_reason,
            merged_observations=merged_observations,
            email=witness_input.email,
            phone=witness_input.phone,
            address=witness_input.address,
            source_document_count=1,
            max_confidence_score=witness_input.confidence_score
        )

        db.add(canonical)
        await db.flush()

        return canonical

    async def _merge_into_canonical(
        self,
        db: AsyncSession,
        canonical: CanonicalWitness,
        witness_input: WitnessInput,
        document_id: int,
        filename: str
    ) -> CanonicalWitness:
        """Merge new witness data into existing canonical record"""

        # Update name if new one is more detailed
        if len(witness_input.full_name) > len(canonical.full_name):
            canonical.full_name = witness_input.full_name

        # Update relevance if higher
        if witness_input.relevance:
            try:
                new_relevance = RelevanceLevel(witness_input.relevance.lower())
                relevance_order = [
                    RelevanceLevel.NOT_RELEVANT,
                    RelevanceLevel.SOMEWHAT_RELEVANT,
                    RelevanceLevel.RELEVANT,
                    RelevanceLevel.HIGHLY_RELEVANT
                ]
                if canonical.relevance is None or (
                    relevance_order.index(new_relevance) >
                    relevance_order.index(canonical.relevance)
                ):
                    canonical.relevance = new_relevance
                    canonical.relevance_reason = witness_input.relevance_reason
            except (ValueError, AttributeError):
                pass

        # Merge observations
        if witness_input.observation:
            if canonical.merged_observations is None:
                canonical.merged_observations = []

            # Check if this observation from this doc already exists
            existing_doc_ids = [
                o.get("doc_id") for o in canonical.merged_observations
                if isinstance(o, dict)
            ]

            if document_id not in existing_doc_ids:
                canonical.merged_observations.append({
                    "doc_id": document_id,
                    "filename": filename,
                    "page": witness_input.source_page,
                    "text": witness_input.observation
                })

        # Update contact info (prefer non-empty values)
        if witness_input.email and not canonical.email:
            canonical.email = witness_input.email
        if witness_input.phone and not canonical.phone:
            canonical.phone = witness_input.phone
        if witness_input.address and not canonical.address:
            canonical.address = witness_input.address

        # Update confidence (take max)
        if witness_input.confidence_score:
            if canonical.max_confidence_score is None or \
               witness_input.confidence_score > canonical.max_confidence_score:
                canonical.max_confidence_score = witness_input.confidence_score

        # Increment document count
        canonical.source_document_count += 1

        return canonical

    async def _create_witness_record(
        self,
        db: AsyncSession,
        canonical: CanonicalWitness,
        witness_input: WitnessInput,
        document_id: int
    ) -> Witness:
        """Create individual witness record linked to canonical"""

        # Parse role enum
        try:
            role = WitnessRole(witness_input.role.lower())
        except (ValueError, AttributeError):
            role = WitnessRole.OTHER

        # Parse importance enum
        try:
            importance = ImportanceLevel(witness_input.importance.lower())
        except (ValueError, AttributeError):
            importance = ImportanceLevel.MEDIUM

        # Parse relevance enum
        relevance = None
        if witness_input.relevance:
            try:
                relevance = RelevanceLevel(witness_input.relevance.lower())
            except (ValueError, AttributeError):
                pass

        witness = Witness(
            document_id=document_id,
            canonical_witness_id=canonical.id,
            full_name=witness_input.full_name,
            role=role,
            importance=importance,
            relevance=relevance,
            relevance_reason=witness_input.relevance_reason,
            observation=witness_input.observation,
            source_page=witness_input.source_page,
            email=witness_input.email,
            phone=witness_input.phone,
            address=witness_input.address,
            confidence_score=witness_input.confidence_score
        )

        db.add(witness)
        await db.flush()

        return witness

    # =========================================================================
    # Batch Operations
    # =========================================================================

    async def recanonicalize_matter(
        self,
        db: AsyncSession,
        matter_id: int
    ) -> Dict[str, int]:
        """
        Re-run canonicalization for all witnesses in a matter.
        Useful after improving the algorithm.

        Returns statistics about the operation.
        """
        # Get all witnesses for the matter
        result = await db.execute(
            select(Witness)
            .join(Witness.document)
            .where(Witness.document.has(matter_id=matter_id))
            .options(selectinload(Witness.document))
        )
        witnesses = result.scalars().all()

        if not witnesses:
            return {"total_witnesses": 0, "canonical_created": 0, "canonical_merged": 0}

        # Clear existing canonical witnesses for this matter
        await db.execute(
            text("DELETE FROM canonical_witnesses WHERE matter_id = :matter_id"),
            {"matter_id": matter_id}
        )

        # Reset canonical_witness_id on all witnesses
        for w in witnesses:
            w.canonical_witness_id = None

        await db.flush()

        stats = {"total_witnesses": len(witnesses), "canonical_created": 0, "canonical_merged": 0}

        # Re-process each witness
        for witness in witnesses:
            witness_input = WitnessInput(
                full_name=witness.full_name,
                role=witness.role.value if witness.role else "other",
                importance=witness.importance.value if witness.importance else "medium",
                observation=witness.observation,
                source_page=witness.source_page,
                email=witness.email,
                phone=witness.phone,
                address=witness.address,
                confidence_score=witness.confidence_score,
                relevance=witness.relevance.value if witness.relevance else None,
                relevance_reason=witness.relevance_reason
            )

            canonical, _, is_new = await self.create_or_update_canonical(
                db=db,
                matter_id=matter_id,
                witness_input=witness_input,
                document_id=witness.document_id,
                filename=witness.document.filename if witness.document else "Unknown"
            )

            # Update the existing witness record with canonical link
            witness.canonical_witness_id = canonical.id

            if is_new:
                stats["canonical_created"] += 1
            else:
                stats["canonical_merged"] += 1

        await db.commit()

        logger.info(
            f"Recanonicalized matter {matter_id}: "
            f"{stats['total_witnesses']} witnesses -> "
            f"{stats['canonical_created']} canonical (+ {stats['canonical_merged']} merged)"
        )

        return stats

    async def get_canonicalization_stats(
        self,
        db: AsyncSession,
        matter_id: int
    ) -> Dict[str, Any]:
        """Get statistics about canonicalization for a matter"""

        # Count total witnesses
        total_result = await db.execute(
            select(func.count(Witness.id))
            .join(Witness.document)
            .where(Witness.document.has(matter_id=matter_id))
        )
        total_witnesses = total_result.scalar() or 0

        # Count canonical witnesses
        canonical_result = await db.execute(
            select(func.count(CanonicalWitness.id))
            .where(CanonicalWitness.matter_id == matter_id)
        )
        canonical_count = canonical_result.scalar() or 0

        # Count witnesses with canonical links
        linked_result = await db.execute(
            select(func.count(Witness.id))
            .join(Witness.document)
            .where(
                Witness.document.has(matter_id=matter_id),
                Witness.canonical_witness_id.isnot(None)
            )
        )
        linked_count = linked_result.scalar() or 0

        dedup_ratio = 1 - (canonical_count / total_witnesses) if total_witnesses > 0 else 0

        return {
            "matter_id": matter_id,
            "total_witness_mentions": total_witnesses,
            "canonical_witnesses": canonical_count,
            "linked_witnesses": linked_count,
            "unlinked_witnesses": total_witnesses - linked_count,
            "deduplication_ratio": round(dedup_ratio * 100, 1)
        }
