"""
Canonicalization Service for Witness Deduplication

Implements a 4-tier hybrid approach:
1. Deterministic matching (normalized names)
2. Fuzzy string matching (Levenshtein/Jaro-Winkler)
3. ML embedding-based semantic matching (Amazon Titan)
4. AI verification (Claude via Bedrock) for uncertain cases

The AI verification step is triggered when fuzzy/embedding scores fall in the
"uncertain" range (e.g., 70-85% for fuzzy, 85-92% for embeddings). Claude
analyzes the context to determine if witnesses like "J. Smith" and "John Smith"
are the same person.

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
from sqlalchemy import select, text, func, update
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db.models import (
    Witness, CanonicalWitness, WitnessRole, RelevanceLevel, ImportanceLevel, Matter
)

logger = logging.getLogger(__name__)

# Matching thresholds
FUZZY_MATCH_THRESHOLD = 0.85  # 85% similarity for fuzzy matching
FUZZY_UNCERTAIN_THRESHOLD = 0.70  # Below 85% but above 70% = use AI to verify
EMBEDDING_MATCH_THRESHOLD = 0.92  # 92% cosine similarity for embedding matching
EMBEDDING_UNCERTAIN_THRESHOLD = 0.85  # Below 92% but above 85% = use AI to verify
TOKEN_SUBSET_CONFIDENCE = 0.95  # Confidence when name is token subset of another
LASTNAME_PRIORITY_CONFIDENCE = 0.90  # Confidence for last-name-first matching

# Common nickname mappings for name matching
NICKNAME_MAP = {
    "mike": ["michael", "mike"],
    "michael": ["michael", "mike"],
    "bob": ["robert", "bob", "bobby", "rob"],
    "robert": ["robert", "bob", "bobby", "rob"],
    "bobby": ["robert", "bob", "bobby", "rob"],
    "rob": ["robert", "bob", "bobby", "rob"],
    "bill": ["william", "bill", "billy", "will"],
    "william": ["william", "bill", "billy", "will"],
    "billy": ["william", "bill", "billy", "will"],
    "will": ["william", "bill", "billy", "will"],
    "jim": ["james", "jim", "jimmy"],
    "james": ["james", "jim", "jimmy"],
    "jimmy": ["james", "jim", "jimmy"],
    "joe": ["joseph", "joe", "joey"],
    "joseph": ["joseph", "joe", "joey"],
    "joey": ["joseph", "joe", "joey"],
    "tom": ["thomas", "tom", "tommy"],
    "thomas": ["thomas", "tom", "tommy"],
    "tommy": ["thomas", "tom", "tommy"],
    "dick": ["richard", "dick", "rick", "ricky", "rich"],
    "richard": ["richard", "dick", "rick", "ricky", "rich"],
    "rick": ["richard", "dick", "rick", "ricky", "rich"],
    "ricky": ["richard", "dick", "rick", "ricky", "rich"],
    "dan": ["daniel", "dan", "danny"],
    "daniel": ["daniel", "dan", "danny"],
    "danny": ["daniel", "dan", "danny"],
    "ed": ["edward", "ed", "eddie", "ted", "teddy"],
    "edward": ["edward", "ed", "eddie", "ted", "teddy"],
    "eddie": ["edward", "ed", "eddie", "ted", "teddy"],
    "ted": ["edward", "ed", "eddie", "ted", "teddy", "theodore"],
    "theodore": ["theodore", "ted", "teddy", "theo"],
    "jack": ["john", "jack", "johnny"],
    "john": ["john", "jack", "johnny"],
    "johnny": ["john", "jack", "johnny"],
    "kate": ["katherine", "kate", "kathy", "cathy", "katie"],
    "katherine": ["katherine", "kate", "kathy", "cathy", "katie"],
    "kathy": ["katherine", "kate", "kathy", "cathy", "katie"],
    "katie": ["katherine", "kate", "kathy", "cathy", "katie"],
    "liz": ["elizabeth", "liz", "lizzy", "beth", "betty", "eliza"],
    "elizabeth": ["elizabeth", "liz", "lizzy", "beth", "betty", "eliza"],
    "beth": ["elizabeth", "liz", "lizzy", "beth", "betty", "eliza"],
    "betty": ["elizabeth", "liz", "lizzy", "beth", "betty", "eliza"],
    "sue": ["susan", "sue", "susie", "suzanne"],
    "susan": ["susan", "sue", "susie", "suzanne"],
    "susie": ["susan", "sue", "susie", "suzanne"],
    "tony": ["anthony", "tony"],
    "anthony": ["anthony", "tony"],
    "chris": ["christopher", "chris", "christine", "christina"],
    "christopher": ["christopher", "chris"],
    "christine": ["christine", "chris", "christy"],
    "matt": ["matthew", "matt"],
    "matthew": ["matthew", "matt"],
    "dave": ["david", "dave", "davey"],
    "david": ["david", "dave", "davey"],
    "steve": ["steven", "stephen", "steve"],
    "steven": ["steven", "stephen", "steve"],
    "stephen": ["steven", "stephen", "steve"],
    "alex": ["alexander", "alexandra", "alex"],
    "alexander": ["alexander", "alex"],
    "alexandra": ["alexandra", "alex"],
    "nick": ["nicholas", "nick", "nicky"],
    "nicholas": ["nicholas", "nick", "nicky"],
    "sam": ["samuel", "samantha", "sam", "sammy"],
    "samuel": ["samuel", "sam", "sammy"],
    "samantha": ["samantha", "sam"],
    "jen": ["jennifer", "jen", "jenny"],
    "jennifer": ["jennifer", "jen", "jenny"],
    "jenny": ["jennifer", "jen", "jenny"],
    "meg": ["margaret", "meg", "maggie", "peggy"],
    "margaret": ["margaret", "meg", "maggie", "peggy"],
    "maggie": ["margaret", "meg", "maggie", "peggy"],
    "peggy": ["margaret", "meg", "maggie", "peggy"],
    "pat": ["patrick", "patricia", "pat", "patty"],
    "patrick": ["patrick", "pat"],
    "patricia": ["patricia", "pat", "patty", "trish"],
    "ben": ["benjamin", "ben", "benny"],
    "benjamin": ["benjamin", "ben", "benny"],
    "charlie": ["charles", "charlie", "chuck"],
    "charles": ["charles", "charlie", "chuck"],
    "chuck": ["charles", "charlie", "chuck"],
    "fred": ["frederick", "fred", "freddy"],
    "frederick": ["frederick", "fred", "freddy"],
    "greg": ["gregory", "greg"],
    "gregory": ["gregory", "greg"],
    "larry": ["lawrence", "larry"],
    "lawrence": ["lawrence", "larry"],
    "vince": ["vincent", "vince", "vinny"],
    "vincent": ["vincent", "vince", "vinny"],
}

# AI verification prompt for ambiguous matches
AI_VERIFICATION_PROMPT = """You are a legal document analyst helping to deduplicate witness lists.

Determine if these two witness references likely refer to the SAME PERSON:

WITNESS A:
- Name: {name_a}
- Role: {role_a}
- Observation: {observation_a}

WITNESS B (from existing records):
- Name: {name_b}
- Role: {role_b}
- Observations: {observations_b}

Consider:
1. Name variations (nicknames, initials, titles like Dr./Mr./Esq.)
2. Role consistency (same role suggests same person)
3. Context clues in observations
4. Common name variations (e.g., "Robert" = "Bob", "William" = "Bill")

Respond with ONLY a JSON object:
{{"same_person": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation"}}
"""

# AI verification prompt for case attorney exclusion
ATTORNEY_EXCLUSION_PROMPT = """You are a legal document analyst determining if an attorney should be included as a FACT WITNESS or excluded as COUNSEL OF RECORD.

CONTEXT:
An attorney CAN be a fact witness if they personally witnessed events (e.g., attended a meeting, saw an accident, witnessed a contract signing). However, attorneys who are COUNSEL OF RECORD (representing a party in this lawsuit) should NOT be included as witnesses because their observations come from their role as advocate, not as a fact witness.

ATTORNEY INFORMATION:
- Name: {name}
- Role extracted: {role}
- Observation/Context: {observation}
- Document filename: {filename}

DETERMINE:
1. Is this attorney likely COUNSEL OF RECORD for a party in this case? (representing plaintiff, defendant, or a party)
2. Or are they a FACT WITNESS who happens to be an attorney? (personally witnessed relevant events)

INDICATORS OF COUNSEL OF RECORD (EXCLUDE):
- "Counsel for [party]", "Attorney for [party]", "Representing [party]"
- Filing motions, pleadings, or legal documents on behalf of a party
- Seeking pro hac vice admission
- Corresponding as legal representative
- Signing declarations summarizing what others told them

INDICATORS OF FACT WITNESS (INCLUDE):
- Personally witnessed events (accident, signing, meeting)
- Testifying about what they saw/heard firsthand
- Acting as a witness to a transaction (not legal representation)
- General counsel involved in business decisions being litigated

Respond with ONLY a JSON object:
{{"exclude": true/false, "is_fact_witness": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation"}}
"""

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
        """Initialize Bedrock client for embeddings and AI verification"""
        try:
            self.bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
            )
        except Exception as e:
            logger.error(f"Failed to initialize Bedrock client: {e}")
            self.bedrock_client = None

    # =========================================================================
    # Case Attorney Detection
    # =========================================================================

    async def is_case_attorney(
        self,
        name: str,
        role: str,
        observation: str,
        filename: str = "",
        use_ai_verification: bool = True
    ) -> Tuple[bool, str]:
        """
        Determine if a witness should be excluded as a case attorney of record.

        Case attorneys are lawyers representing parties in THIS case - they are
        advocates, not fact witnesses. However, attorneys CAN be fact witnesses
        if they personally witnessed events.

        Uses a 2-tier approach:
        1. Pattern matching for clear cases
        2. AI verification for ambiguous cases

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

        # If attorney role but no clear indicator either way, use AI verification
        if use_ai_verification and self.bedrock_client:
            should_exclude, reason = await self._verify_attorney_exclusion_with_ai(
                name=name,
                role=role,
                observation=observation,
                filename=filename
            )
            return should_exclude, reason

        # Fallback: don't exclude (conservative approach)
        return False, "Attorney role but no clear representation indicator"

    async def _verify_attorney_exclusion_with_ai(
        self,
        name: str,
        role: str,
        observation: str,
        filename: str
    ) -> Tuple[bool, str]:
        """
        Use Claude to determine if an attorney should be excluded as counsel of record
        or included as a fact witness.

        Returns:
            Tuple of (should_exclude: bool, reason: str)
        """
        try:
            prompt = ATTORNEY_EXCLUSION_PROMPT.format(
                name=name,
                role=role or "attorney",
                observation=(observation or "No observation provided")[:500],
                filename=filename or "Unknown document"
            )

            response = self.bedrock_client.invoke_model(
                modelId=settings.bedrock_model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 256,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                })
            )

            result = json.loads(response["body"].read())
            response_text = result.get("content", [{}])[0].get("text", "{}")

            # Parse JSON response
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            ai_result = json.loads(response_text.strip())

            should_exclude = ai_result.get("exclude", False)
            is_fact_witness = ai_result.get("is_fact_witness", False)
            confidence = float(ai_result.get("confidence", 0.5))
            reasoning = ai_result.get("reasoning", "No reasoning provided")

            logger.info(
                f"AI attorney exclusion check for '{name}': "
                f"exclude={should_exclude}, fact_witness={is_fact_witness}, "
                f"confidence={confidence:.2f}, reason={reasoning[:100]}"
            )

            # Only exclude if AI is confident (>= 0.7)
            if should_exclude and confidence >= 0.7:
                return True, f"AI: {reasoning}"
            elif is_fact_witness and confidence >= 0.7:
                return False, f"AI: Fact witness - {reasoning}"
            else:
                # Uncertain - don't exclude (conservative)
                return False, f"AI uncertain (confidence={confidence:.2f}): {reasoning}"

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI attorney exclusion response: {e}")
            return False, f"AI parse error, defaulting to include"
        except Exception as e:
            logger.error(f"AI attorney exclusion check failed: {e}")
            return False, f"AI error, defaulting to include"

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
    # Enhanced Name Matching (Token/Nickname/LastName Priority)
    # =========================================================================

    def token_subset_match(self, name1: str, name2: str) -> Tuple[bool, float]:
        """
        Check if one name is a token subset of another (handles middle name variations).

        Examples:
        - "John Carroll" is subset of "John Mike Carroll" -> True, 0.95
        - "Mike Carroll" tokens overlap with "John Mike Carroll" -> check further

        Returns:
            Tuple of (is_match: bool, confidence: float)
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())

        # Need at least 2 tokens (first + last name) for meaningful comparison
        if len(tokens1) < 2 or len(tokens2) < 2:
            return False, 0.0

        # If all tokens of shorter name exist in longer name
        shorter, longer = (tokens1, tokens2) if len(tokens1) <= len(tokens2) else (tokens2, tokens1)

        if shorter.issubset(longer):
            # High confidence - all tokens match
            return True, TOKEN_SUBSET_CONFIDENCE

        return False, 0.0

    def names_could_be_nicknames(self, name1: str, name2: str) -> bool:
        """
        Check if two first names could be nickname variations.

        Args:
            name1: First name to check
            name2: Second name to check

        Returns:
            True if names could be nickname variants of each other
        """
        name1_lower = name1.lower().strip()
        name2_lower = name2.lower().strip()

        # Direct match
        if name1_lower == name2_lower:
            return True

        # Check nickname mapping
        variants1 = set(NICKNAME_MAP.get(name1_lower, [name1_lower]))
        variants2 = set(NICKNAME_MAP.get(name2_lower, [name2_lower]))

        return bool(variants1 & variants2)

    def last_name_priority_match(self, name1: str, name2: str) -> Tuple[bool, float]:
        """
        If last names match exactly, check for first/middle name overlap or nickname match.

        Handles cases like:
        - "John Carroll" vs "John Mike Carroll" (John overlaps)
        - "Mike Carroll" vs "John Mike Carroll" (Mike overlaps as middle name)
        - "Mike Carroll" vs "Michael Carroll" (nickname match)

        Returns:
            Tuple of (is_match: bool, confidence: float)
        """
        norm1 = self.normalize_name(name1)
        norm2 = self.normalize_name(name2)

        parts1 = self.extract_name_parts(norm1)
        parts2 = self.extract_name_parts(norm2)

        # Last names must match exactly
        if parts1["last"] != parts2["last"] or not parts1["last"]:
            return False, 0.0

        # Collect all first/middle name tokens for each name
        first1_tokens = set(parts1["first"].split() + parts1["middle"].split())
        first2_tokens = set(parts2["first"].split() + parts2["middle"].split())

        # Remove empty strings
        first1_tokens.discard("")
        first2_tokens.discard("")

        # Direct token overlap (e.g., "John" in both)
        if first1_tokens & first2_tokens:
            return True, LASTNAME_PRIORITY_CONFIDENCE

        # Check nickname matches between first names
        for token1 in first1_tokens:
            for token2 in first2_tokens:
                if self.names_could_be_nicknames(token1, token2):
                    logger.info(
                        f"Nickname match: '{token1}' <-> '{token2}' in "
                        f"'{name1}' vs '{name2}'"
                    )
                    return True, LASTNAME_PRIORITY_CONFIDENCE

        return False, 0.0

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
    # AI Verification for Ambiguous Matches
    # =========================================================================

    async def verify_match_with_ai(
        self,
        new_name: str,
        new_role: str,
        new_observation: Optional[str],
        canonical: 'CanonicalWitness'
    ) -> Tuple[bool, float, str]:
        """
        Use Claude to verify if two witnesses are the same person.
        Called for ambiguous cases where fuzzy/embedding scores are borderline.

        Returns:
            Tuple of (is_same_person: bool, confidence: float, reasoning: str)
        """
        if not self.bedrock_client:
            logger.warning("Bedrock client not available for AI verification")
            return False, 0.0, "AI verification unavailable"

        try:
            # Build observations summary from canonical
            observations_summary = ""
            if canonical.merged_observations:
                obs_texts = [
                    o.get("text", "")[:200] for o in canonical.merged_observations
                    if isinstance(o, dict)
                ][:3]  # Limit to first 3
                observations_summary = " | ".join(obs_texts)

            prompt = AI_VERIFICATION_PROMPT.format(
                name_a=new_name,
                role_a=new_role or "unknown",
                observation_a=(new_observation or "No observation")[:300],
                name_b=canonical.full_name,
                role_b=canonical.role.value if canonical.role else "unknown",
                observations_b=observations_summary or "No observations recorded"
            )

            # Call Claude via Bedrock
            response = self.bedrock_client.invoke_model(
                modelId=settings.bedrock_model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 256,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                })
            )

            result = json.loads(response["body"].read())
            response_text = result.get("content", [{}])[0].get("text", "{}")

            # Parse JSON response
            # Handle potential markdown code blocks
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0]

            ai_result = json.loads(response_text.strip())

            is_same = ai_result.get("same_person", False)
            confidence = float(ai_result.get("confidence", 0.5))
            reasoning = ai_result.get("reasoning", "No reasoning provided")

            logger.info(
                f"AI verification for '{new_name}' vs '{canonical.full_name}': "
                f"same={is_same}, confidence={confidence:.2f}, reason={reasoning[:100]}"
            )

            return is_same, confidence, reasoning

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse AI verification response: {e}")
            return False, 0.0, f"Parse error: {e}"
        except Exception as e:
            logger.error(f"AI verification failed: {e}")
            return False, 0.0, f"Error: {e}"

    # =========================================================================
    # Main Canonicalization Logic
    # =========================================================================

    async def find_canonical_witness(
        self,
        db: AsyncSession,
        matter_id: int,
        name: str,
        role: Optional[str] = None,
        observation: Optional[str] = None,
        use_embeddings: bool = True,
        use_ai_verification: bool = True
    ) -> Tuple[Optional[CanonicalWitness], str, float]:
        """
        Find a matching canonical witness for the given name.

        Uses a 6-tier matching approach:
        1. Exact match (normalized names)
        2. Token subset match (e.g., "John Carroll" subset of "John Mike Carroll")
        3. Last-name priority match (same last name + first/middle name overlap or nickname)
        4. Fuzzy match (Jaro-Winkler + Levenshtein)
        5. Embedding match (semantic similarity)
        6. AI verification (for uncertain cases)

        Returns:
            Tuple of (canonical_witness or None, match_type, confidence)
            match_type: "exact", "token_subset", "lastname_priority", "fuzzy",
                        "embedding", "ai_verified", or "none"
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

        # Track uncertain matches for potential AI verification
        uncertain_matches: List[Tuple[CanonicalWitness, float, str]] = []

        for canonical in existing_witnesses:
            canonical_normalized = self.normalize_name(canonical.full_name)

            # 1. Exact match (after normalization)
            if normalized_name == canonical_normalized:
                return canonical, "exact", 1.0

            # 2. Token subset match (handles middle name variations)
            # e.g., "John Carroll" matches "John Mike Carroll"
            is_subset, subset_score = self.token_subset_match(name, canonical.full_name)
            if is_subset:
                logger.info(
                    f"Token subset match: '{name}' -> '{canonical.full_name}' "
                    f"(confidence: {subset_score:.2f})"
                )
                return canonical, "token_subset", subset_score

            # 3. Last-name priority match (same last name + first/middle overlap or nickname)
            # e.g., "Mike Carroll" matches "John Mike Carroll" (Mike is middle name)
            # e.g., "Mike Carroll" matches "Michael Carroll" (nickname)
            is_lastname_match, ln_score = self.last_name_priority_match(name, canonical.full_name)
            if is_lastname_match:
                logger.info(
                    f"Last-name priority match: '{name}' -> '{canonical.full_name}' "
                    f"(confidence: {ln_score:.2f})"
                )
                return canonical, "lastname_priority", ln_score

            # 4. Fuzzy matching
            fuzzy_score = self.fuzzy_match_score(name, canonical.full_name)
            if fuzzy_score >= FUZZY_MATCH_THRESHOLD and fuzzy_score > best_score:
                best_match = canonical
                best_score = fuzzy_score
                best_type = "fuzzy"
            elif fuzzy_score >= FUZZY_UNCERTAIN_THRESHOLD:
                # Track for potential AI verification
                uncertain_matches.append((canonical, fuzzy_score, "fuzzy"))

        # 3. Embedding matching (if fuzzy didn't find a confident match)
        if use_embeddings and (best_match is None or best_score < EMBEDDING_MATCH_THRESHOLD):
            name_embedding = await self.get_name_embedding(name, observation or "")

            if name_embedding:
                for canonical in existing_witnesses:
                    # Skip if already a confident match
                    if canonical == best_match and best_score >= FUZZY_MATCH_THRESHOLD:
                        continue

                    # Get or compute canonical embedding
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
                        elif similarity >= EMBEDDING_UNCERTAIN_THRESHOLD:
                            # Add to uncertain matches for AI verification
                            uncertain_matches.append((canonical, similarity, "embedding"))

        # 4. AI Verification for uncertain matches (when no confident match found)
        if use_ai_verification and best_match is None and uncertain_matches:
            # Sort by score descending, take top candidates
            uncertain_matches.sort(key=lambda x: x[1], reverse=True)

            for candidate, score, match_source in uncertain_matches[:3]:  # Check top 3
                is_same, ai_confidence, reasoning = await self.verify_match_with_ai(
                    new_name=name,
                    new_role=role,
                    new_observation=observation,
                    canonical=candidate
                )

                if is_same and ai_confidence >= 0.7:
                    # AI confirmed match
                    combined_confidence = (score + ai_confidence) / 2
                    logger.info(
                        f"AI verified match: '{name}' -> '{candidate.full_name}' "
                        f"(fuzzy/embed: {score:.2f}, AI: {ai_confidence:.2f}, reason: {reasoning[:50]})"
                    )
                    return candidate, "ai_verified", combined_confidence

        if best_match and best_score >= FUZZY_MATCH_THRESHOLD:
            return best_match, best_type, best_score

        return None, "none", 0.0

    def is_own_firm_staff(
        self,
        witness_email: Optional[str],
        firm_email_domain: Optional[str]
    ) -> Tuple[bool, str]:
        """
        Check if witness is from the user's own law firm based on email domain.

        Args:
            witness_email: Witness email address
            firm_email_domain: User's firm email domain (e.g., "shanleyapc.com")

        Returns:
            Tuple of (should_exclude: bool, reason: str)
        """
        if not witness_email or not firm_email_domain:
            return False, ""

        # Extract domain from witness email
        if "@" not in witness_email:
            return False, ""

        witness_domain = witness_email.lower().split("@")[-1].strip()
        firm_domain = firm_email_domain.lower().strip()

        if witness_domain == firm_domain:
            return True, f"Own firm staff (email domain: {witness_domain})"

        return False, ""

    async def create_or_update_canonical(
        self,
        db: AsyncSession,
        matter_id: int,
        witness_input: WitnessInput,
        document_id: int,
        filename: str,
        exclude_case_attorneys: bool = True,
        firm_email_domain: Optional[str] = None
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
            firm_email_domain: User's firm email domain to exclude own firm staff

        Returns:
            CanonicalizationResult with canonical witness, witness record, and metadata
        """
        # Check if this is own firm staff that should be excluded
        if firm_email_domain:
            is_firm_staff, exclusion_reason = self.is_own_firm_staff(
                witness_email=witness_input.email,
                firm_email_domain=firm_email_domain
            )

            if is_firm_staff:
                logger.info(
                    f"Excluding own firm staff '{witness_input.full_name}': {exclusion_reason}"
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

        # Check if this is a case attorney that should be excluded
        if exclude_case_attorneys:
            is_excluded, exclusion_reason = await self.is_case_attorney(
                name=witness_input.full_name,
                role=witness_input.role,
                observation=witness_input.observation,
                filename=filename,
                use_ai_verification=True
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
            role=witness_input.role,
            observation=witness_input.observation,
            use_embeddings=True,
            use_ai_verification=True
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
        """Merge new witness data into existing canonical record.

        Uses atomic SQL UPDATE for source_document_count to prevent deadlocks
        when multiple workers process documents with the same witness.
        """
        # Build updates dict for atomic update
        updates = {}

        # Update name if new one is more detailed
        if len(witness_input.full_name) > len(canonical.full_name):
            updates["full_name"] = witness_input.full_name

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
                    updates["relevance"] = new_relevance
                    updates["relevance_reason"] = witness_input.relevance_reason
            except (ValueError, AttributeError):
                pass

        # Merge observations
        new_observations = canonical.merged_observations or []
        if witness_input.observation:
            # Check if this observation from this doc already exists
            existing_doc_ids = [
                o.get("doc_id") for o in new_observations
                if isinstance(o, dict)
            ]

            if document_id not in existing_doc_ids:
                new_observations = new_observations + [{
                    "doc_id": document_id,
                    "filename": filename,
                    "page": witness_input.source_page,
                    "text": witness_input.observation
                }]
                updates["merged_observations"] = new_observations

        # Update contact info (prefer non-empty values)
        if witness_input.email and not canonical.email:
            updates["email"] = witness_input.email
        if witness_input.phone and not canonical.phone:
            updates["phone"] = witness_input.phone
        if witness_input.address and not canonical.address:
            updates["address"] = witness_input.address

        # Update confidence (take max)
        if witness_input.confidence_score:
            if canonical.max_confidence_score is None or \
               witness_input.confidence_score > canonical.max_confidence_score:
                updates["max_confidence_score"] = witness_input.confidence_score

        # Use atomic SQL UPDATE to increment source_document_count
        # This prevents deadlocks from concurrent read-modify-write operations
        await db.execute(
            text("""
                UPDATE canonical_witnesses
                SET source_document_count = source_document_count + 1,
                    updated_at = NOW()
                WHERE id = :canonical_id
            """),
            {"canonical_id": canonical.id}
        )

        # Apply other updates if any
        if updates:
            for key, value in updates.items():
                setattr(canonical, key, value)

        # Refresh the canonical object to get updated source_document_count
        await db.refresh(canonical)

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

        # Re-process each witness - find or create canonical, but don't create new witness records
        for witness in witnesses:
            # Try to find existing canonical witness
            canonical, match_type, confidence = await self.find_canonical_witness(
                db=db,
                matter_id=matter_id,
                name=witness.full_name,
                role=witness.role.value if witness.role else None,
                observation=witness.observation,
                use_embeddings=False,  # Skip embeddings for speed
                use_ai_verification=False  # Skip AI verification for speed
            )

            if canonical:
                # Merge into existing canonical
                canonical = await self._merge_into_canonical(
                    db=db,
                    canonical=canonical,
                    witness_input=WitnessInput(
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
                    ),
                    document_id=witness.document_id,
                    filename=witness.document.filename if witness.document else "Unknown"
                )
                witness.canonical_witness_id = canonical.id
                stats["canonical_merged"] += 1
            else:
                # Create new canonical witness
                canonical = await self._create_canonical(
                    db=db,
                    matter_id=matter_id,
                    witness_input=WitnessInput(
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
                    ),
                    document_id=witness.document_id,
                    filename=witness.document.filename if witness.document else "Unknown"
                )
                witness.canonical_witness_id = canonical.id
                stats["canonical_created"] += 1

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
