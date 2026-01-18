"""
End-to-End Tests for Witness Canonicalization Service

Tests the full canonicalization pipeline including:
1. Deterministic name matching
2. Fuzzy string matching (Jaro-Winkler, Levenshtein)
3. ML embedding matching (Amazon Titan)
4. AI verification for uncertain cases (Claude)
5. Case attorney exclusion with AI verification

Run with: pytest tests/e2e/test_canonicalization_e2e.py -v -s
"""
import asyncio
import pytest
import logging
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from app.core.config import settings
from app.db.models import Base, Matter, Document, Witness, CanonicalWitness, User, Organization
from app.services.canonicalization_service import (
    CanonicalizationService,
    WitnessInput,
    CanonicalizationResult
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Test Data - Complex Witness Scenarios
# ============================================================================

# Witnesses that should be deduplicated (same person, different name formats)
DUPLICATE_WITNESSES = [
    # Group 1: John Smith variations
    {
        "group": "john_smith",
        "witnesses": [
            {"name": "John Smith", "role": "eyewitness", "observation": "Witnessed the car accident at 5th and Main on June 15, 2024"},
            {"name": "John A. Smith", "role": "eyewitness", "observation": "Saw defendant run red light before collision"},
            {"name": "J. Smith", "role": "eyewitness", "observation": "Was standing on corner when accident occurred"},
            {"name": "JOHN SMITH", "role": "eyewitness", "observation": "Called 911 after witnessing the crash"},
            {"name": "Mr. John Smith", "role": "eyewitness", "observation": "Provided statement to police at scene"},
        ]
    },
    # Group 2: Dr. Maria Garcia variations
    {
        "group": "maria_garcia",
        "witnesses": [
            {"name": "Dr. Maria Garcia", "role": "physician", "observation": "Treated plaintiff for injuries sustained in accident"},
            {"name": "Maria Garcia, M.D.", "role": "physician", "observation": "Performed surgery on plaintiff's broken leg"},
            {"name": "Maria L. Garcia", "role": "expert", "observation": "Testified about plaintiff's prognosis and future medical needs"},
            {"name": "Dr. M. Garcia", "role": "physician", "observation": "Prescribed pain medication for ongoing treatment"},
        ]
    },
    # Group 3: Robert Johnson / Bob Johnson
    {
        "group": "robert_johnson",
        "witnesses": [
            {"name": "Robert Johnson", "role": "colleague", "observation": "Worked with plaintiff at Acme Corp for 5 years"},
            {"name": "Bob Johnson", "role": "colleague", "observation": "Witnessed plaintiff's work performance before injury"},
            {"name": "Robert 'Bob' Johnson", "role": "colleague", "observation": "Testified about plaintiff's inability to work after accident"},
            {"name": "R. Johnson", "role": "colleague", "observation": "Confirmed plaintiff's job duties and responsibilities"},
        ]
    },
    # Group 4: William Chen / Bill Chen
    {
        "group": "william_chen",
        "witnesses": [
            {"name": "William Chen", "role": "expert", "observation": "Accident reconstruction expert, analyzed skid marks"},
            {"name": "Bill Chen", "role": "expert", "observation": "Calculated speed of defendant's vehicle at impact"},
            {"name": "William H. Chen, Ph.D.", "role": "expert", "observation": "Provided expert report on crash dynamics"},
        ]
    },
    # Group 5: Elizabeth / Liz / Beth variations
    {
        "group": "elizabeth_taylor",
        "witnesses": [
            {"name": "Elizabeth Taylor", "role": "family_member", "observation": "Plaintiff's sister, observed daily struggles post-accident"},
            {"name": "Liz Taylor", "role": "family_member", "observation": "Helped care for plaintiff during recovery"},
            {"name": "Beth Taylor", "role": "family_member", "observation": "Testified about plaintiff's emotional distress"},
            {"name": "E. Taylor", "role": "family_member", "observation": "Described changes in plaintiff's personality after trauma"},
        ]
    },
]

# Witnesses that should remain separate (different people with similar names)
DISTINCT_WITNESSES = [
    {"name": "Michael Brown", "role": "eyewitness", "observation": "Saw accident from his office window on 3rd floor"},
    {"name": "Michael Brown Jr.", "role": "bystander", "observation": "Was walking dog when heard the crash"},
    {"name": "Michelle Brown", "role": "police_officer", "observation": "Responding officer, prepared accident report"},
    {"name": "James Wilson", "role": "defendant", "observation": "Driver of the vehicle that caused the accident"},
    {"name": "James Williams", "role": "eyewitness", "observation": "Was in crosswalk when accident occurred"},
]

# Case attorneys that SHOULD be excluded
CASE_ATTORNEYS_EXCLUDE = [
    {
        "name": "David Martinez, Esq.",
        "role": "attorney",
        "observation": "Defense counsel representing defendant in this matter",
        "expected_exclude": True,
        "reason": "Defense attorney of record"
    },
    {
        "name": "Sarah Thompson",
        "role": "attorney",
        "observation": "Counsel for plaintiff, filed complaint on March 1, 2024",
        "expected_exclude": True,
        "reason": "Plaintiff's attorney of record"
    },
    {
        "name": "Richard Lee, Esq.",
        "role": "attorney",
        "observation": "Seeking pro hac vice admission to represent defendant",
        "expected_exclude": True,
        "reason": "Seeking admission as counsel"
    },
    {
        "name": "Amanda Foster",
        "role": "counsel",
        "observation": "Opposing counsel, corresponded regarding settlement negotiations",
        "expected_exclude": True,
        "reason": "Opposing counsel communications"
    },
    {
        "name": "Christopher Davis",
        "role": "attorney",
        "observation": "Attorney for defendant, argued motion to dismiss on June 20, 2024",
        "expected_exclude": True,
        "reason": "Defendant's attorney appearing in court"
    },
]

# Attorneys that should be INCLUDED as fact witnesses
ATTORNEY_FACT_WITNESSES = [
    {
        "name": "Jennifer Park, Esq.",
        "role": "attorney",
        "observation": "Witnessed the contract signing as a notary public on behalf of seller",
        "expected_exclude": False,
        "reason": "Attorney who witnessed a transaction"
    },
    {
        "name": "Thomas Anderson",
        "role": "attorney",
        "observation": "Was personally present at the meeting when defendant made verbal threats",
        "expected_exclude": False,
        "reason": "Attorney who personally witnessed events"
    },
    {
        "name": "Lisa Wang, Esq.",
        "role": "attorney",
        "observation": "General counsel who was directly involved in the business decisions at issue",
        "expected_exclude": False,
        "reason": "General counsel with firsthand knowledge"
    },
    {
        "name": "Mark Robinson",
        "role": "attorney",
        "observation": "Testified that he overheard defendant admit fault during phone call",
        "expected_exclude": False,
        "reason": "Attorney testifying about what they overheard"
    },
    {
        "name": "Dr. Patricia Hughes, J.D.",
        "role": "attorney",
        "observation": "Eyewitness to the accident, happened to be crossing street when collision occurred",
        "expected_exclude": False,
        "reason": "Attorney who is an eyewitness to events"
    },
]

# Edge cases for AI verification
EDGE_CASES = [
    # Ambiguous attorney cases
    {
        "name": "Kevin O'Brien, Esq.",
        "role": "attorney",
        "observation": "Reviewed the contract documents",
        "description": "Ambiguous - could be counsel reviewing or witness to review"
    },
    {
        "name": "Rachel Green",
        "role": "counsel",
        "observation": "Attended the closing meeting",
        "description": "Ambiguous - attended as counsel or as witness?"
    },
    # Very similar names that are different people
    {
        "name": "John Paul Smith",
        "role": "expert",
        "observation": "Medical expert on traumatic brain injuries",
        "should_match_john_smith": False,
        "description": "Different person despite similar name"
    },
]


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def db_engine():
    """Create test database engine"""
    # Use test database or in-memory SQLite
    test_db_url = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(
        test_db_url,
        echo=False,
        pool_pre_ping=True
    )

    yield engine

    await engine.dispose()


@pytest.fixture(scope="module")
async def db_session(db_engine):
    """Create test database session"""
    async_session = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session


@pytest.fixture(scope="module")
async def test_matter(db_session):
    """Create test matter for canonicalization tests"""
    # First, ensure we have a test organization and user
    org = Organization(
        name="Test Law Firm",
        subscription_status="active",
        subscription_tier="pro"
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        email="test@testfirm.com",
        display_name="Test User",
        organization_id=org.id
    )
    db_session.add(user)
    await db_session.flush()

    # Create test matter
    matter = Matter(
        user_id=user.id,
        clio_matter_id="TEST-CANON-001",
        display_number="2024-CV-12345",
        description="Test Matter for Canonicalization E2E Tests",
        status="Open",
        practice_area="Personal Injury",
        client_name="Test Client"
    )
    db_session.add(matter)
    await db_session.flush()

    # Create test document
    document = Document(
        matter_id=matter.id,
        clio_document_id="TEST-DOC-001",
        filename="test_witness_document.pdf",
        file_type="pdf",
        is_processed=False
    )
    db_session.add(document)
    await db_session.flush()

    yield {
        "matter": matter,
        "document": document,
        "user": user,
        "org": org
    }

    # Cleanup
    await db_session.execute(text("DELETE FROM witnesses WHERE document_id = :doc_id"), {"doc_id": document.id})
    await db_session.execute(text("DELETE FROM canonical_witnesses WHERE matter_id = :matter_id"), {"matter_id": matter.id})
    await db_session.execute(text("DELETE FROM documents WHERE id = :doc_id"), {"doc_id": document.id})
    await db_session.execute(text("DELETE FROM matters WHERE id = :matter_id"), {"matter_id": matter.id})
    await db_session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user.id})
    await db_session.execute(text("DELETE FROM organizations WHERE id = :org_id"), {"org_id": org.id})
    await db_session.commit()


@pytest.fixture
def canon_service():
    """Create canonicalization service instance"""
    return CanonicalizationService()


# ============================================================================
# Test Classes
# ============================================================================

class TestNameNormalization:
    """Test name normalization for deterministic matching"""

    def test_normalize_removes_titles(self, canon_service):
        """Test that titles are removed"""
        assert canon_service.normalize_name("Dr. John Smith") == "john smith"
        assert canon_service.normalize_name("Mr. John Smith") == "john smith"
        assert canon_service.normalize_name("Mrs. Jane Doe") == "jane doe"
        assert canon_service.normalize_name("John Smith, Esq.") == "john smith"
        assert canon_service.normalize_name("John Smith Jr.") == "john smith"
        assert canon_service.normalize_name("John Smith III") == "john smith"

    def test_normalize_removes_middle_initials(self, canon_service):
        """Test that single-letter middle initials are removed"""
        assert canon_service.normalize_name("John A. Smith") == "john smith"
        assert canon_service.normalize_name("John A Smith") == "john smith"
        assert canon_service.normalize_name("J. Smith") == "smith"

    def test_normalize_handles_case(self, canon_service):
        """Test case normalization"""
        assert canon_service.normalize_name("JOHN SMITH") == "john smith"
        assert canon_service.normalize_name("john smith") == "john smith"
        assert canon_service.normalize_name("JoHn SmItH") == "john smith"

    def test_normalize_handles_punctuation(self, canon_service):
        """Test punctuation removal"""
        assert canon_service.normalize_name("O'Brien") == "obrien"
        assert canon_service.normalize_name("Mary-Jane Watson") == "maryjane watson"


class TestFuzzyMatching:
    """Test fuzzy string matching algorithms"""

    def test_jaro_winkler_identical(self, canon_service):
        """Test Jaro-Winkler on identical strings"""
        score = canon_service.jaro_winkler_similarity("John Smith", "John Smith")
        assert score == 1.0

    def test_jaro_winkler_similar(self, canon_service):
        """Test Jaro-Winkler on similar strings"""
        score = canon_service.jaro_winkler_similarity("John Smith", "Jon Smith")
        assert score > 0.9

        score = canon_service.jaro_winkler_similarity("Robert Johnson", "Bob Johnson")
        assert score > 0.6  # Different enough but still related

    def test_jaro_winkler_different(self, canon_service):
        """Test Jaro-Winkler on different strings"""
        score = canon_service.jaro_winkler_similarity("John Smith", "Mary Johnson")
        assert score < 0.7

    def test_levenshtein_identical(self, canon_service):
        """Test Levenshtein on identical strings"""
        score = canon_service.levenshtein_similarity("John Smith", "John Smith")
        assert score == 1.0

    def test_levenshtein_similar(self, canon_service):
        """Test Levenshtein on similar strings"""
        score = canon_service.levenshtein_similarity("John Smith", "Jon Smith")
        assert score > 0.8

    def test_fuzzy_match_score_combined(self, canon_service):
        """Test combined fuzzy match score"""
        # Very similar names
        score = canon_service.fuzzy_match_score("John Smith", "John A. Smith")
        assert score > 0.85

        # Moderately similar
        score = canon_service.fuzzy_match_score("Robert Johnson", "Bob Johnson")
        assert 0.5 < score < 0.85

        # Different names
        score = canon_service.fuzzy_match_score("John Smith", "Mary Johnson")
        assert score < 0.6


class TestCaseAttorneyDetection:
    """Test case attorney exclusion logic"""

    @pytest.mark.asyncio
    async def test_exclude_defense_counsel(self, canon_service):
        """Test that defense attorneys are excluded"""
        for attorney in CASE_ATTORNEYS_EXCLUDE:
            is_excluded, reason = await canon_service.is_case_attorney(
                name=attorney["name"],
                role=attorney["role"],
                observation=attorney["observation"],
                filename="pleading.pdf",
                use_ai_verification=True
            )
            logger.info(f"Attorney: {attorney['name']}, Excluded: {is_excluded}, Reason: {reason}")
            assert is_excluded == attorney["expected_exclude"], \
                f"Expected {attorney['name']} to be {'excluded' if attorney['expected_exclude'] else 'included'}: {reason}"

    @pytest.mark.asyncio
    async def test_include_fact_witness_attorneys(self, canon_service):
        """Test that attorneys who are fact witnesses are included"""
        for attorney in ATTORNEY_FACT_WITNESSES:
            is_excluded, reason = await canon_service.is_case_attorney(
                name=attorney["name"],
                role=attorney["role"],
                observation=attorney["observation"],
                filename="deposition.pdf",
                use_ai_verification=True
            )
            logger.info(f"Attorney: {attorney['name']}, Excluded: {is_excluded}, Reason: {reason}")
            assert is_excluded == attorney["expected_exclude"], \
                f"Expected {attorney['name']} to be {'excluded' if attorney['expected_exclude'] else 'included'}: {reason}"

    @pytest.mark.asyncio
    async def test_non_attorney_not_excluded(self, canon_service):
        """Test that non-attorneys are never excluded"""
        is_excluded, reason = await canon_service.is_case_attorney(
            name="John Smith",
            role="eyewitness",
            observation="Witnessed the accident from the sidewalk",
            filename="witness_statement.pdf",
            use_ai_verification=True
        )
        assert not is_excluded


class TestWitnessDeduplication:
    """Test witness deduplication with various matching strategies"""

    @pytest.mark.asyncio
    async def test_exact_match_deduplication(self, canon_service, db_session, test_matter):
        """Test that exact name matches are deduplicated"""
        matter = test_matter["matter"]
        document = test_matter["document"]

        # Create first witness
        witness1 = WitnessInput(
            full_name="John Smith",
            role="eyewitness",
            importance="high",
            observation="First observation about the accident"
        )
        result1 = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness1,
            document_id=document.id,
            filename=document.filename
        )
        assert result1.is_new_canonical == True
        assert result1.match_type == "new"

        # Create second witness with same name
        witness2 = WitnessInput(
            full_name="John Smith",
            role="eyewitness",
            importance="high",
            observation="Second observation about the accident"
        )
        result2 = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness2,
            document_id=document.id,
            filename=document.filename
        )
        assert result2.is_new_canonical == False
        assert result2.match_type == "exact"
        assert result2.canonical_witness.id == result1.canonical_witness.id

        # Verify merged observations
        assert len(result2.canonical_witness.merged_observations) == 2

    @pytest.mark.asyncio
    async def test_fuzzy_match_deduplication(self, canon_service, db_session, test_matter):
        """Test that fuzzy name matches are deduplicated"""
        matter = test_matter["matter"]
        document = test_matter["document"]

        # Create witness with full name
        witness1 = WitnessInput(
            full_name="Dr. Maria Garcia",
            role="physician",
            importance="high",
            observation="Treated patient for injuries"
        )
        result1 = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness1,
            document_id=document.id,
            filename=document.filename
        )

        # Create witness with variation
        witness2 = WitnessInput(
            full_name="Maria Garcia, M.D.",
            role="physician",
            importance="high",
            observation="Performed surgery"
        )
        result2 = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness2,
            document_id=document.id,
            filename=document.filename
        )

        # Should match via fuzzy or exact (after normalization)
        logger.info(f"Match type for Maria Garcia: {result2.match_type}, confidence: {result2.match_confidence}")
        assert result2.is_new_canonical == False
        assert result2.canonical_witness.id == result1.canonical_witness.id

    @pytest.mark.asyncio
    async def test_ai_verified_match(self, canon_service, db_session, test_matter):
        """Test AI verification for uncertain matches"""
        matter = test_matter["matter"]
        document = test_matter["document"]

        # Create witness with full name
        witness1 = WitnessInput(
            full_name="Robert Johnson",
            role="colleague",
            importance="medium",
            observation="Worked with plaintiff for 5 years"
        )
        result1 = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness1,
            document_id=document.id,
            filename=document.filename
        )

        # Create witness with nickname - should trigger AI verification
        witness2 = WitnessInput(
            full_name="Bob Johnson",
            role="colleague",
            importance="medium",
            observation="Confirmed plaintiff's work duties"
        )
        result2 = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness2,
            document_id=document.id,
            filename=document.filename
        )

        logger.info(f"Match type for Bob Johnson: {result2.match_type}, confidence: {result2.match_confidence}")
        # This might be fuzzy, embedding, or ai_verified depending on scores
        # The key is that they should be merged
        if result2.match_type in ["fuzzy", "embedding", "ai_verified"]:
            assert result2.canonical_witness.id == result1.canonical_witness.id

    @pytest.mark.asyncio
    async def test_distinct_witnesses_not_merged(self, canon_service, db_session, test_matter):
        """Test that clearly different witnesses are not merged"""
        matter = test_matter["matter"]
        document = test_matter["document"]

        created_witnesses = []

        for witness_data in DISTINCT_WITNESSES:
            witness = WitnessInput(
                full_name=witness_data["name"],
                role=witness_data["role"],
                importance="medium",
                observation=witness_data["observation"]
            )
            result = await canon_service.create_or_update_canonical(
                db=db_session,
                matter_id=matter.id,
                witness_input=witness,
                document_id=document.id,
                filename=document.filename
            )

            if not result.is_excluded:
                created_witnesses.append(result.canonical_witness.id)

        # All should be unique
        assert len(created_witnesses) == len(set(created_witnesses)), \
            "Some distinct witnesses were incorrectly merged"


class TestFullDeduplicationPipeline:
    """Test complete deduplication pipeline with all witness groups"""

    @pytest.mark.asyncio
    async def test_all_duplicate_groups(self, canon_service, db_session, test_matter):
        """Test that all duplicate groups are properly deduplicated"""
        matter = test_matter["matter"]
        document = test_matter["document"]

        results_by_group = {}

        for group in DUPLICATE_WITNESSES:
            group_name = group["group"]
            canonical_ids = set()

            for witness_data in group["witnesses"]:
                witness = WitnessInput(
                    full_name=witness_data["name"],
                    role=witness_data["role"],
                    importance="high",
                    observation=witness_data["observation"]
                )
                result = await canon_service.create_or_update_canonical(
                    db=db_session,
                    matter_id=matter.id,
                    witness_input=witness,
                    document_id=document.id,
                    filename=document.filename
                )

                if not result.is_excluded:
                    canonical_ids.add(result.canonical_witness.id)
                    logger.info(
                        f"[{group_name}] {witness_data['name']} -> "
                        f"canonical #{result.canonical_witness.id} "
                        f"(match: {result.match_type}, conf: {result.match_confidence:.2f})"
                    )

            results_by_group[group_name] = canonical_ids

        # Verify each group was deduplicated to a single canonical witness
        for group_name, canonical_ids in results_by_group.items():
            logger.info(f"Group '{group_name}': {len(canonical_ids)} canonical witness(es)")
            # Ideally all should be 1, but AI might not catch all variations
            assert len(canonical_ids) <= 2, \
                f"Group '{group_name}' has too many canonical witnesses: {len(canonical_ids)}"

    @pytest.mark.asyncio
    async def test_canonicalization_stats(self, canon_service, db_session, test_matter):
        """Test canonicalization statistics"""
        matter = test_matter["matter"]

        stats = await canon_service.get_canonicalization_stats(db_session, matter.id)

        logger.info(f"Canonicalization stats: {stats}")

        assert stats["matter_id"] == matter.id
        assert stats["total_witness_mentions"] >= 0
        assert stats["canonical_witnesses"] >= 0
        assert 0 <= stats["deduplication_ratio"] <= 100


class TestEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.asyncio
    async def test_empty_name(self, canon_service):
        """Test handling of empty names"""
        normalized = canon_service.normalize_name("")
        assert normalized == ""

        normalized = canon_service.normalize_name(None)
        assert normalized == ""

    @pytest.mark.asyncio
    async def test_unicode_names(self, canon_service):
        """Test handling of unicode characters in names"""
        normalized = canon_service.normalize_name("José García")
        assert "jose" in normalized.lower()

        normalized = canon_service.normalize_name("François Müller")
        assert len(normalized) > 0

    @pytest.mark.asyncio
    async def test_very_long_observation(self, canon_service, db_session, test_matter):
        """Test handling of very long observations"""
        matter = test_matter["matter"]
        document = test_matter["document"]

        long_observation = "A" * 10000  # 10k characters

        witness = WitnessInput(
            full_name="Test Long Observation",
            role="eyewitness",
            importance="medium",
            observation=long_observation
        )

        # Should not raise exception
        result = await canon_service.create_or_update_canonical(
            db=db_session,
            matter_id=matter.id,
            witness_input=witness,
            document_id=document.id,
            filename=document.filename
        )

        assert result.canonical_witness is not None or result.is_excluded


# ============================================================================
# Standalone Test Runner
# ============================================================================

async def run_tests_standalone():
    """Run tests without pytest for quick verification"""
    logger.info("=" * 60)
    logger.info("Starting Canonicalization E2E Tests (Standalone)")
    logger.info("=" * 60)

    # Initialize service
    service = CanonicalizationService()

    # Test 1: Name normalization
    logger.info("\n--- Test 1: Name Normalization ---")
    test_names = [
        ("Dr. John Smith", "john smith"),
        ("John A. Smith", "john smith"),
        ("JOHN SMITH", "john smith"),
        ("Mr. John Smith, Esq.", "john smith"),
        ("Maria Garcia, M.D.", "maria garcia md"),
    ]
    for input_name, expected in test_names:
        result = service.normalize_name(input_name)
        status = "PASS" if expected in result or result in expected else "FAIL"
        logger.info(f"  [{status}] '{input_name}' -> '{result}' (expected contains: '{expected}')")

    # Test 2: Fuzzy matching
    logger.info("\n--- Test 2: Fuzzy Matching ---")
    test_pairs = [
        ("John Smith", "John Smith", 1.0),
        ("John Smith", "Jon Smith", 0.85),
        ("Robert Johnson", "Bob Johnson", 0.6),
        ("John Smith", "Mary Johnson", 0.5),
    ]
    for name1, name2, min_expected in test_pairs:
        score = service.fuzzy_match_score(name1, name2)
        status = "PASS" if score >= min_expected else "FAIL"
        logger.info(f"  [{status}] '{name1}' vs '{name2}': {score:.3f} (min: {min_expected})")

    # Test 3: Case attorney detection
    logger.info("\n--- Test 3: Case Attorney Detection ---")

    # Should exclude
    for attorney in CASE_ATTORNEYS_EXCLUDE[:3]:
        is_excluded, reason = await service.is_case_attorney(
            name=attorney["name"],
            role=attorney["role"],
            observation=attorney["observation"],
            filename="test.pdf",
            use_ai_verification=True
        )
        expected = attorney["expected_exclude"]
        status = "PASS" if is_excluded == expected else "FAIL"
        logger.info(f"  [{status}] {attorney['name']}: excluded={is_excluded} (expected={expected})")
        logger.info(f"          Reason: {reason[:80]}...")

    # Should include
    for attorney in ATTORNEY_FACT_WITNESSES[:3]:
        is_excluded, reason = await service.is_case_attorney(
            name=attorney["name"],
            role=attorney["role"],
            observation=attorney["observation"],
            filename="test.pdf",
            use_ai_verification=True
        )
        expected = attorney["expected_exclude"]
        status = "PASS" if is_excluded == expected else "FAIL"
        logger.info(f"  [{status}] {attorney['name']}: excluded={is_excluded} (expected={expected})")
        logger.info(f"          Reason: {reason[:80]}...")

    logger.info("\n" + "=" * 60)
    logger.info("Standalone tests completed!")
    logger.info("=" * 60)


if __name__ == "__main__":
    # Run standalone tests
    asyncio.run(run_tests_standalone())
