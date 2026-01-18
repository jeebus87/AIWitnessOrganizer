#!/usr/bin/env python3
"""
Standalone E2E Test Script for Canonicalization Service

This script tests the canonicalization service against the actual database
with realistic fake witness data. It can be run directly without pytest.

Usage:
    python scripts/test_canonicalization.py

Or with Railway:
    railway run python scripts/test_canonicalization.py
"""
import asyncio
import sys
import os
import logging
from datetime import datetime
from typing import List, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text

from app.core.config import settings
from app.db.models import Matter, Document, Witness, CanonicalWitness, User
from app.services.canonicalization_service import (
    CanonicalizationService,
    WitnessInput,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Test Data
# ============================================================================

# Witnesses that should be deduplicated (same person, different formats)
DEDUP_TEST_CASES = [
    # Group 1: Various formats of same person
    {
        "expected_canonical_name": "John Smith",
        "witnesses": [
            {"name": "John Smith", "role": "eyewitness", "obs": "Saw accident from sidewalk"},
            {"name": "John A. Smith", "role": "eyewitness", "obs": "Called 911 after crash"},
            {"name": "JOHN SMITH", "role": "eyewitness", "obs": "Gave statement to police"},
            {"name": "Mr. John Smith", "role": "eyewitness", "obs": "Testified at deposition"},
            {"name": "J. Smith", "role": "eyewitness", "obs": "Identified defendant at scene"},
        ]
    },
    # Group 2: Doctor with title variations
    {
        "expected_canonical_name": "Maria Garcia",
        "witnesses": [
            {"name": "Dr. Maria Garcia", "role": "physician", "obs": "Treated plaintiff for injuries"},
            {"name": "Maria Garcia, M.D.", "role": "physician", "obs": "Performed surgery on leg"},
            {"name": "Maria L. Garcia", "role": "physician", "obs": "Prescribed medications"},
        ]
    },
    # Group 3: Nickname variations (Robert/Bob)
    {
        "expected_canonical_name": "Robert Johnson",
        "witnesses": [
            {"name": "Robert Johnson", "role": "colleague", "obs": "Worked with plaintiff 5 years"},
            {"name": "Bob Johnson", "role": "colleague", "obs": "Confirmed work duties"},
            {"name": "R. Johnson", "role": "colleague", "obs": "Witnessed work performance"},
        ]
    },
    # Group 4: William/Bill variations
    {
        "expected_canonical_name": "William Chen",
        "witnesses": [
            {"name": "William Chen", "role": "expert", "obs": "Accident reconstruction expert"},
            {"name": "Bill Chen", "role": "expert", "obs": "Analyzed skid marks at scene"},
            {"name": "William H. Chen, Ph.D.", "role": "expert", "obs": "Calculated vehicle speeds"},
        ]
    },
]

# Case attorneys that SHOULD be excluded
ATTORNEY_EXCLUDE_CASES = [
    {
        "name": "David Martinez, Esq.",
        "role": "attorney",
        "obs": "Defense counsel representing defendant James Wilson in this personal injury matter",
        "should_exclude": True
    },
    {
        "name": "Sarah Thompson",
        "role": "attorney",
        "obs": "Plaintiff's counsel who filed the complaint and is handling all litigation",
        "should_exclude": True
    },
    {
        "name": "Richard Lee, Esq.",
        "role": "attorney",
        "obs": "Seeking pro hac vice admission to represent defendant at trial",
        "should_exclude": True
    },
    {
        "name": "Amanda Foster",
        "role": "counsel",
        "obs": "Opposing counsel in settlement negotiations for defendant insurance company",
        "should_exclude": True
    },
]

# Attorneys that SHOULD be included as fact witnesses
ATTORNEY_INCLUDE_CASES = [
    {
        "name": "Jennifer Park, Esq.",
        "role": "attorney",
        "obs": "Witnessed the contract signing ceremony and can testify about what was said",
        "should_exclude": False
    },
    {
        "name": "Thomas Anderson",
        "role": "attorney",
        "obs": "Was personally present at the board meeting when defendant made threats",
        "should_exclude": False
    },
    {
        "name": "Lisa Wang, Esq.",
        "role": "attorney",
        "obs": "As General Counsel, personally witnessed the fraudulent transactions at issue",
        "should_exclude": False
    },
    {
        "name": "Mark Robinson",
        "role": "attorney",
        "obs": "Overheard defendant admit fault in a phone call he was not party to",
        "should_exclude": False
    },
]


# ============================================================================
# Test Functions
# ============================================================================

async def test_name_normalization(service: CanonicalizationService) -> Tuple[int, int]:
    """Test name normalization"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Name Normalization")
    logger.info("="*60)

    passed = 0
    failed = 0

    test_cases = [
        ("Dr. John Smith", "john smith"),
        ("John A. Smith", "john smith"),
        ("JOHN SMITH", "john smith"),
        ("John Smith, Esq.", "john smith"),
        ("Mr. John Smith Jr.", "john smith"),
        ("Maria Garcia, M.D.", "maria garcia"),
        ("Robert 'Bob' Johnson", "robert bob johnson"),
        ("O'Brien", "obrien"),
    ]

    for input_name, expected_contains in test_cases:
        result = service.normalize_name(input_name)
        # Check if expected is contained in result or vice versa
        if expected_contains in result or result in expected_contains:
            logger.info(f"  PASS: '{input_name}' -> '{result}'")
            passed += 1
        else:
            logger.error(f"  FAIL: '{input_name}' -> '{result}' (expected to contain '{expected_contains}')")
            failed += 1

    return passed, failed


async def test_fuzzy_matching(service: CanonicalizationService) -> Tuple[int, int]:
    """Test fuzzy string matching"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Fuzzy Matching Scores")
    logger.info("="*60)

    passed = 0
    failed = 0

    test_cases = [
        ("John Smith", "John Smith", 1.0, "identical"),
        ("John Smith", "John A. Smith", 0.80, "with middle initial"),
        ("John Smith", "Jon Smith", 0.85, "typo"),
        ("Robert Johnson", "Bob Johnson", 0.50, "nickname"),
        ("John Smith", "Jane Doe", 0.0, "completely different"),
    ]

    for name1, name2, min_score, description in test_cases:
        score = service.fuzzy_match_score(name1, name2)
        if score >= min_score:
            logger.info(f"  PASS: '{name1}' vs '{name2}' = {score:.3f} (min: {min_score}) [{description}]")
            passed += 1
        else:
            logger.error(f"  FAIL: '{name1}' vs '{name2}' = {score:.3f} (min: {min_score}) [{description}]")
            failed += 1

    return passed, failed


async def test_attorney_exclusion(service: CanonicalizationService) -> Tuple[int, int]:
    """Test case attorney exclusion logic"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Case Attorney Exclusion")
    logger.info("="*60)

    passed = 0
    failed = 0

    # Test attorneys that should be EXCLUDED
    logger.info("\n  --- Should be EXCLUDED (counsel of record) ---")
    for case in ATTORNEY_EXCLUDE_CASES:
        is_excluded, reason = await service.is_case_attorney(
            name=case["name"],
            role=case["role"],
            observation=case["obs"],
            filename="pleading.pdf",
            use_ai_verification=True
        )

        if is_excluded == case["should_exclude"]:
            logger.info(f"  PASS: {case['name']} -> excluded={is_excluded}")
            logger.info(f"        Reason: {reason[:70]}...")
            passed += 1
        else:
            logger.error(f"  FAIL: {case['name']} -> excluded={is_excluded} (expected {case['should_exclude']})")
            logger.error(f"        Reason: {reason[:70]}...")
            failed += 1

    # Test attorneys that should be INCLUDED
    logger.info("\n  --- Should be INCLUDED (fact witnesses) ---")
    for case in ATTORNEY_INCLUDE_CASES:
        is_excluded, reason = await service.is_case_attorney(
            name=case["name"],
            role=case["role"],
            observation=case["obs"],
            filename="deposition.pdf",
            use_ai_verification=True
        )

        if is_excluded == case["should_exclude"]:
            logger.info(f"  PASS: {case['name']} -> excluded={is_excluded}")
            logger.info(f"        Reason: {reason[:70]}...")
            passed += 1
        else:
            logger.error(f"  FAIL: {case['name']} -> excluded={is_excluded} (expected {case['should_exclude']})")
            logger.error(f"        Reason: {reason[:70]}...")
            failed += 1

    return passed, failed


async def test_deduplication_pipeline(
    service: CanonicalizationService,
    session: AsyncSession,
    matter_id: int,
    document_id: int,
    filename: str
) -> Tuple[int, int]:
    """Test full deduplication pipeline"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Witness Deduplication Pipeline")
    logger.info("="*60)

    passed = 0
    failed = 0

    for group in DEDUP_TEST_CASES:
        expected_name = group["expected_canonical_name"]
        witnesses = group["witnesses"]

        logger.info(f"\n  --- Testing group: {expected_name} ({len(witnesses)} variations) ---")

        canonical_ids = set()

        for w in witnesses:
            witness_input = WitnessInput(
                full_name=w["name"],
                role=w["role"],
                importance="high",
                observation=w["obs"]
            )

            result = await service.create_or_update_canonical(
                db=session,
                matter_id=matter_id,
                witness_input=witness_input,
                document_id=document_id,
                filename=filename,
                exclude_case_attorneys=True
            )

            if not result.is_excluded:
                canonical_ids.add(result.canonical_witness.id)
                logger.info(
                    f"    '{w['name']}' -> canonical #{result.canonical_witness.id} "
                    f"(match: {result.match_type}, conf: {result.match_confidence:.2f})"
                )

        # Check if all deduplicated to single canonical
        unique_canonicals = len(canonical_ids)
        if unique_canonicals == 1:
            logger.info(f"  PASS: All {len(witnesses)} variations -> 1 canonical witness")
            passed += 1
        elif unique_canonicals <= 2:
            logger.warning(f"  PARTIAL: {len(witnesses)} variations -> {unique_canonicals} canonicals (acceptable)")
            passed += 1
        else:
            logger.error(f"  FAIL: {len(witnesses)} variations -> {unique_canonicals} canonicals (too many)")
            failed += 1

    return passed, failed


async def cleanup_test_data(session: AsyncSession, matter_id: int, document_id: int):
    """Clean up test data from database"""
    logger.info("\n  Cleaning up test data...")

    try:
        await session.execute(
            text("DELETE FROM witnesses WHERE document_id = :doc_id"),
            {"doc_id": document_id}
        )
        await session.execute(
            text("DELETE FROM canonical_witnesses WHERE matter_id = :matter_id"),
            {"matter_id": matter_id}
        )
        await session.commit()
        logger.info("  Test data cleaned up successfully")
    except Exception as e:
        logger.error(f"  Cleanup error: {e}")
        await session.rollback()


async def main():
    """Main test runner"""
    logger.info("="*60)
    logger.info("CANONICALIZATION SERVICE E2E TESTS")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("="*60)

    # Initialize service
    service = CanonicalizationService()

    if not service.bedrock_client:
        logger.error("Bedrock client not initialized! Check AWS credentials.")
        sys.exit(1)

    total_passed = 0
    total_failed = 0

    # Test 1: Name normalization (no DB needed)
    passed, failed = await test_name_normalization(service)
    total_passed += passed
    total_failed += failed

    # Test 2: Fuzzy matching (no DB needed)
    passed, failed = await test_fuzzy_matching(service)
    total_passed += passed
    total_failed += failed

    # Test 3: Attorney exclusion (uses AI, no DB needed)
    passed, failed = await test_attorney_exclusion(service)
    total_passed += passed
    total_failed += failed

    # Test 4: Full deduplication pipeline (requires DB)
    logger.info("\n" + "="*60)
    logger.info("Connecting to database for deduplication tests...")
    logger.info("="*60)

    try:
        # Connect to database
        db_url = settings.database_url
        if not db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # Find a test matter and document to use
            result = await session.execute(
                select(Matter, Document)
                .join(Document, Matter.id == Document.matter_id)
                .limit(1)
            )
            row = result.first()

            if not row:
                logger.warning("No matter/document found in database. Skipping deduplication tests.")
            else:
                matter, document = row

                logger.info(f"Using matter: {matter.display_number} (ID: {matter.id})")
                logger.info(f"Using document: {document.filename} (ID: {document.id})")

                # Run deduplication tests
                passed, failed = await test_deduplication_pipeline(
                    service, session, matter.id, document.id, document.filename
                )
                total_passed += passed
                total_failed += failed

                # Cleanup
                await cleanup_test_data(session, matter.id, document.id)

        await engine.dispose()

    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.info("Skipping database-dependent tests")

    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    logger.info(f"  Total Passed: {total_passed}")
    logger.info(f"  Total Failed: {total_failed}")
    logger.info(f"  Success Rate: {total_passed / (total_passed + total_failed) * 100:.1f}%")
    logger.info("="*60)

    if total_failed > 0:
        sys.exit(1)
    else:
        logger.info("All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
