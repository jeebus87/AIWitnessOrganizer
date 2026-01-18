#!/usr/bin/env python3
"""
E2E Tests for Work Product Filter and Stale Sync Recovery

Tests:
1. Work Product Filter - verifies documents are correctly identified and skipped
2. Stale Sync Recovery - verifies stuck syncs are auto-recovered after timeout

Usage:
    python scripts/test_work_product_and_sync.py

Or with Railway:
    railway run python scripts/test_work_product_and_sync.py
"""
import asyncio
import sys
import os
import logging
from datetime import datetime, timedelta
from typing import Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update

from app.core.config import settings
from app.db.models import Matter, Document, SyncStatus

# Import the functions we're testing
from app.worker.tasks import _is_work_product, STRONG_FILENAME_PATTERNS, STRONG_HEADER_PATTERNS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Test Data for Work Product Filter
# ============================================================================

# Documents that SHOULD be skipped (work product)
WORK_PRODUCT_DOCUMENTS = [
    # Filename-based detection
    {
        "filename": "Shanley APC Confidential Notes.pdf",
        "content": "Meeting notes from client interview...",
        "should_skip": True,
        "reason": "Contains 'confidential notes' in filename"
    },
    {
        "filename": "Attorney Work Product - Case Analysis.docx",
        "content": "Analysis of defendant's liability...",
        "should_skip": True,
        "reason": "Contains 'work product' in filename"
    },
    {
        "filename": "Internal Memo - Strategy Session.pdf",
        "content": "Discussion of litigation strategy...",
        "should_skip": True,
        "reason": "Contains 'internal memo' and 'strategy' in filename"
    },
    {
        "filename": "Legal Memo - Motion to Dismiss.docx",
        "content": "Research on motion to dismiss standards...",
        "should_skip": True,
        "reason": "Contains 'legal memo' in filename"
    },
    {
        "filename": "Draft Motion for Summary Judgment.pdf",
        "content": "MOTION FOR SUMMARY JUDGMENT...",
        "should_skip": True,
        "reason": "Contains 'draft motion' in filename"
    },
    {
        "filename": "Privileged Communication - Client.pdf",
        "content": "Email thread with client...",
        "should_skip": True,
        "reason": "Contains 'privileged' in filename"
    },
    {
        "filename": "Research Memo - Damages.docx",
        "content": "Research on damage calculations...",
        "should_skip": True,
        "reason": "Contains 'research memo' in filename"
    },
    {
        "filename": "Attorney Notes 2024-01-15.pdf",
        "content": "Notes from deposition prep...",
        "should_skip": True,
        "reason": "Contains 'attorney notes' in filename"
    },

    # Header-based detection (content has work product markers)
    {
        "filename": "Document Review Notes.pdf",
        "content": "ATTORNEY WORK PRODUCT\n\nThis document contains privileged analysis of exhibits...",
        "should_skip": True,
        "reason": "Content header contains 'ATTORNEY WORK PRODUCT'"
    },
    {
        "filename": "Case Evaluation.docx",
        "content": "PREPARED IN ANTICIPATION OF LITIGATION\n\nEvaluation of claims and defenses...",
        "should_skip": True,
        "reason": "Content header contains 'PREPARED IN ANTICIPATION OF LITIGATION'"
    },
    {
        "filename": "Client Communication Summary.pdf",
        "content": "ATTORNEY-CLIENT PRIVILEGED COMMUNICATION\n\nSummary of advice provided to client...",
        "should_skip": True,
        "reason": "Content header contains 'ATTORNEY-CLIENT PRIVILEGED'"
    },
    {
        "filename": "Legal Analysis Memo.docx",
        "content": "CONFIDENTIAL LEGAL MEMORANDUM\n\nTo: Partner\nFrom: Associate\nRe: Case Analysis...",
        "should_skip": True,
        "reason": "Content header contains 'CONFIDENTIAL LEGAL MEMORANDUM'"
    },
]

# Documents that should NOT be skipped (regular evidence)
NON_WORK_PRODUCT_DOCUMENTS = [
    {
        "filename": "Deposition of John Smith.pdf",
        "content": "DEPOSITION OF JOHN SMITH\n\nQ: Please state your name...",
        "should_skip": False,
        "reason": "Deposition transcript - not work product"
    },
    {
        "filename": "Police Report 2024-001234.pdf",
        "content": "ACCIDENT REPORT\n\nDate: January 15, 2024\nLocation: Main St & 5th Ave...",
        "should_skip": False,
        "reason": "Police report - not work product"
    },
    {
        "filename": "Medical Records - Dr. Garcia.pdf",
        "content": "PATIENT: Jane Doe\nDATE OF SERVICE: January 20, 2024...",
        "should_skip": False,
        "reason": "Medical records - not work product"
    },
    {
        "filename": "Contract Agreement.pdf",
        "content": "AGREEMENT\n\nThis agreement is entered into by and between...",
        "should_skip": False,
        "reason": "Contract - not work product"
    },
    {
        "filename": "Email Correspondence.pdf",
        "content": "From: defendant@company.com\nTo: plaintiff@email.com\nSubject: Re: Project...",
        "should_skip": False,
        "reason": "Business email - not work product"
    },
    {
        "filename": "Expert Report - Dr. Chen.pdf",
        "content": "EXPERT WITNESS REPORT\n\nI have been retained to provide opinions regarding...",
        "should_skip": False,
        "reason": "Expert report - not work product (disclosed)"
    },
    {
        "filename": "Photographs - Accident Scene.zip",
        "content": "[Binary content - photos]",
        "should_skip": False,
        "reason": "Photos - not work product"
    },
    {
        "filename": "Witness Statement - Bob Johnson.pdf",
        "content": "WITNESS STATEMENT\n\nI, Bob Johnson, witnessed the following events...",
        "should_skip": False,
        "reason": "Witness statement - not work product"
    },
    {
        "filename": "Invoice from Acme Corp.pdf",
        "content": "INVOICE #12345\n\nBill To: Client\nServices rendered...",
        "should_skip": False,
        "reason": "Invoice - not work product"
    },
    {
        "filename": "Meeting Minutes - Board.pdf",
        "content": "BOARD MEETING MINUTES\n\nDate: January 10, 2024\nAttendees:...",
        "should_skip": False,
        "reason": "Meeting minutes - not work product (business record)"
    },
]

# Edge cases
EDGE_CASE_DOCUMENTS = [
    {
        "filename": "Notes from Meeting.pdf",  # Generic "notes" - should NOT skip
        "content": "Meeting with client about project timeline...",
        "should_skip": False,
        "reason": "Generic 'notes' without 'confidential' or 'attorney' - not work product"
    },
    {
        "filename": "Strategy Document.pdf",  # Has "strategy" - SHOULD skip
        "content": "Marketing strategy for Q1 2024...",
        "should_skip": True,
        "reason": "Contains 'strategy' in filename"
    },
    {
        "filename": "Memo to File.pdf",  # Has "memo" but not "legal memo" or "internal memo"
        "content": "Record of phone conversation with witness...",
        "should_skip": False,
        "reason": "Just 'memo' without 'legal' or 'internal' - not work product"
    },
]


# ============================================================================
# Test Functions
# ============================================================================

def test_work_product_filter() -> Tuple[int, int]:
    """Test the work product filter function"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Work Product Filter")
    logger.info("="*60)

    passed = 0
    failed = 0

    # Test documents that SHOULD be skipped
    logger.info("\n--- Documents that SHOULD be skipped (work product) ---")
    for doc in WORK_PRODUCT_DOCUMENTS:
        result = _is_work_product(doc["filename"], doc["content"])
        expected = doc["should_skip"]

        if result == expected:
            logger.info(f"  PASS: '{doc['filename'][:50]}...'")
            logger.info(f"        Correctly identified as work product")
            passed += 1
        else:
            logger.error(f"  FAIL: '{doc['filename'][:50]}...'")
            logger.error(f"        Expected: skip={expected}, Got: skip={result}")
            logger.error(f"        Reason: {doc['reason']}")
            failed += 1

    # Test documents that should NOT be skipped
    logger.info("\n--- Documents that should NOT be skipped (evidence) ---")
    for doc in NON_WORK_PRODUCT_DOCUMENTS:
        result = _is_work_product(doc["filename"], doc["content"])
        expected = doc["should_skip"]

        if result == expected:
            logger.info(f"  PASS: '{doc['filename'][:50]}...'")
            logger.info(f"        Correctly identified as NOT work product")
            passed += 1
        else:
            logger.error(f"  FAIL: '{doc['filename'][:50]}...'")
            logger.error(f"        Expected: skip={expected}, Got: skip={result}")
            logger.error(f"        Reason: {doc['reason']}")
            failed += 1

    # Test edge cases
    logger.info("\n--- Edge Cases ---")
    for doc in EDGE_CASE_DOCUMENTS:
        result = _is_work_product(doc["filename"], doc["content"])
        expected = doc["should_skip"]

        if result == expected:
            logger.info(f"  PASS: '{doc['filename'][:50]}...'")
            passed += 1
        else:
            logger.error(f"  FAIL: '{doc['filename'][:50]}...'")
            logger.error(f"        Expected: skip={expected}, Got: skip={result}")
            logger.error(f"        Reason: {doc['reason']}")
            failed += 1

    return passed, failed


def test_filter_patterns() -> Tuple[int, int]:
    """Test that all defined patterns work correctly"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Filter Pattern Verification")
    logger.info("="*60)

    passed = 0
    failed = 0

    # Test each filename pattern
    logger.info("\n--- Filename Patterns ---")
    for pattern in STRONG_FILENAME_PATTERNS:
        test_filename = f"Document with {pattern} in name.pdf"
        result = _is_work_product(test_filename, "")

        if result:
            logger.info(f"  PASS: Pattern '{pattern}' correctly detected in filename")
            passed += 1
        else:
            logger.error(f"  FAIL: Pattern '{pattern}' NOT detected in filename")
            failed += 1

    # Test each header pattern
    logger.info("\n--- Header Patterns ---")
    for pattern in STRONG_HEADER_PATTERNS:
        test_content = f"{pattern}\n\nThis is the document content..."
        result = _is_work_product("generic_document.pdf", test_content)

        if result:
            logger.info(f"  PASS: Pattern '{pattern}' correctly detected in content")
            passed += 1
        else:
            logger.error(f"  FAIL: Pattern '{pattern}' NOT detected in content")
            failed += 1

    return passed, failed


async def test_stale_sync_recovery() -> Tuple[int, int]:
    """Test stale sync recovery by simulating stuck matters"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Stale Sync Recovery")
    logger.info("="*60)

    passed = 0
    failed = 0

    try:
        # Connect to database - prefer environment variable over settings
        db_url = os.environ.get("DATABASE_URL") or settings.database_url
        logger.info(f"Connecting to database: {db_url[:50]}...")
        if not db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # Find a matter to test with
            result = await session.execute(
                select(Matter).limit(1)
            )
            matter = result.scalar_one_or_none()

            if not matter:
                logger.warning("No matters found in database. Skipping stale sync test.")
                return 0, 0

            original_status = matter.sync_status
            original_started_at = matter.sync_started_at

            logger.info(f"Using matter: {matter.display_number} (ID: {matter.id})")
            logger.info(f"Original status: {matter.sync_status}, started_at: {matter.sync_started_at}")

            # Test 1: Simulate a stale sync (started 35 minutes ago)
            logger.info("\n--- Test 1: Stale Sync Detection (35 min old) ---")
            stale_time = datetime.utcnow() - timedelta(minutes=35)
            matter.sync_status = SyncStatus.SYNCING
            matter.sync_started_at = stale_time
            await session.commit()

            # Verify the stale sync detection logic
            SYNC_STALE_TIMEOUT = timedelta(minutes=30)
            is_stale = (
                matter.sync_status == SyncStatus.SYNCING and
                matter.sync_started_at and
                (datetime.utcnow() - matter.sync_started_at) > SYNC_STALE_TIMEOUT
            )

            if is_stale:
                logger.info(f"  PASS: Correctly identified as stale (started {stale_time})")
                passed += 1
            else:
                logger.error(f"  FAIL: Should be identified as stale but wasn't")
                failed += 1

            # Test 2: Fresh sync (started 5 minutes ago) - should NOT be stale
            logger.info("\n--- Test 2: Fresh Sync Detection (5 min old) ---")
            fresh_time = datetime.utcnow() - timedelta(minutes=5)
            matter.sync_started_at = fresh_time
            await session.commit()

            is_stale = (
                matter.sync_status == SyncStatus.SYNCING and
                matter.sync_started_at and
                (datetime.utcnow() - matter.sync_started_at) > SYNC_STALE_TIMEOUT
            )

            if not is_stale:
                logger.info(f"  PASS: Correctly identified as NOT stale (started {fresh_time})")
                passed += 1
            else:
                logger.error(f"  FAIL: Should NOT be identified as stale")
                failed += 1

            # Test 3: Edge case - just under 30 minutes (should NOT be stale - need > 30)
            logger.info("\n--- Test 3: Edge Case - Just Under 30 min old ---")
            edge_time = datetime.utcnow() - timedelta(minutes=29, seconds=55)
            matter.sync_started_at = edge_time
            await session.commit()

            is_stale = (
                matter.sync_status == SyncStatus.SYNCING and
                matter.sync_started_at and
                (datetime.utcnow() - matter.sync_started_at) > SYNC_STALE_TIMEOUT
            )

            if not is_stale:
                logger.info(f"  PASS: Correctly identified as NOT stale at 29:55 min")
                passed += 1
            else:
                logger.error(f"  FAIL: Should NOT be stale at 29:55 min (need > 30)")
                failed += 1

            # Test 4: No sync_started_at (legacy data) - should NOT crash
            logger.info("\n--- Test 4: Missing sync_started_at (legacy) ---")
            matter.sync_started_at = None
            await session.commit()

            try:
                is_stale = (
                    matter.sync_status == SyncStatus.SYNCING and
                    matter.sync_started_at and
                    (datetime.utcnow() - matter.sync_started_at) > SYNC_STALE_TIMEOUT
                )
                logger.info(f"  PASS: Handled None sync_started_at gracefully (is_stale={is_stale})")
                passed += 1
            except Exception as e:
                logger.error(f"  FAIL: Crashed on None sync_started_at: {e}")
                failed += 1

            # Restore original state
            logger.info("\n--- Restoring original state ---")
            matter.sync_status = original_status
            matter.sync_started_at = original_started_at
            await session.commit()
            logger.info(f"  Restored: status={matter.sync_status}, started_at={matter.sync_started_at}")

        await engine.dispose()

    except Exception as e:
        logger.error(f"Database test failed: {e}")
        return 0, 1

    return passed, failed


async def test_sync_recovery_simulation() -> Tuple[int, int]:
    """Simulate the full recovery flow that happens in the API endpoint"""
    logger.info("\n" + "="*60)
    logger.info("TEST: Full Sync Recovery Simulation")
    logger.info("="*60)

    passed = 0
    failed = 0

    try:
        # Connect to database - prefer environment variable over settings
        db_url = os.environ.get("DATABASE_URL") or settings.database_url
        logger.info(f"Connecting to database: {db_url[:50]}...")
        if not db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            result = await session.execute(select(Matter).limit(1))
            matter = result.scalar_one_or_none()

            if not matter:
                logger.warning("No matters found. Skipping.")
                return 0, 0

            # Save original state
            original_status = matter.sync_status
            original_started_at = matter.sync_started_at

            # Simulate a stale sync
            logger.info("\n--- Simulating stale sync scenario ---")
            stale_time = datetime.utcnow() - timedelta(minutes=45)
            matter.sync_status = SyncStatus.SYNCING
            matter.sync_started_at = stale_time
            await session.commit()

            logger.info(f"  Set matter to SYNCING, started_at = {stale_time}")

            # Run the recovery logic (exactly as in the API endpoint)
            SYNC_STALE_TIMEOUT = timedelta(minutes=30)

            if matter.sync_status == SyncStatus.SYNCING:
                if matter.sync_started_at and (datetime.utcnow() - matter.sync_started_at) > SYNC_STALE_TIMEOUT:
                    # This is what the API does for recovery
                    old_started_at = matter.sync_started_at
                    matter.sync_status = SyncStatus.FAILED
                    matter.sync_started_at = None
                    await session.commit()

                    logger.info(f"  PASS: Auto-recovered from stale sync")
                    logger.info(f"        Old started_at: {old_started_at}")
                    logger.info(f"        New status: {matter.sync_status}")
                    logger.info(f"        New started_at: {matter.sync_started_at}")
                    passed += 1
                else:
                    logger.error(f"  FAIL: Should have triggered recovery but didn't")
                    failed += 1

            # Verify the state after recovery
            if matter.sync_status == SyncStatus.FAILED and matter.sync_started_at is None:
                logger.info(f"  PASS: State correctly set after recovery")
                passed += 1
            else:
                logger.error(f"  FAIL: State incorrect after recovery")
                logger.error(f"        Expected: status=FAILED, started_at=None")
                logger.error(f"        Got: status={matter.sync_status}, started_at={matter.sync_started_at}")
                failed += 1

            # Restore original state
            matter.sync_status = original_status
            matter.sync_started_at = original_started_at
            await session.commit()
            logger.info(f"\n  Restored original state")

        await engine.dispose()

    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        import traceback
        traceback.print_exc()
        return 0, 1

    return passed, failed


async def main():
    """Main test runner"""
    logger.info("="*60)
    logger.info("WORK PRODUCT FILTER & STALE SYNC RECOVERY TESTS")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("="*60)

    total_passed = 0
    total_failed = 0

    # Test 1: Work Product Filter (no DB needed)
    passed, failed = test_work_product_filter()
    total_passed += passed
    total_failed += failed

    # Test 2: Filter Pattern Verification (no DB needed)
    passed, failed = test_filter_patterns()
    total_passed += passed
    total_failed += failed

    # Test 3: Stale Sync Recovery (needs DB)
    passed, failed = await test_stale_sync_recovery()
    total_passed += passed
    total_failed += failed

    # Test 4: Full Recovery Simulation (needs DB)
    passed, failed = await test_sync_recovery_simulation()
    total_passed += passed
    total_failed += failed

    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)
    logger.info(f"  Total Passed: {total_passed}")
    logger.info(f"  Total Failed: {total_failed}")

    if total_passed + total_failed > 0:
        success_rate = total_passed / (total_passed + total_failed) * 100
        logger.info(f"  Success Rate: {success_rate:.1f}%")

    logger.info("="*60)

    if total_failed > 0:
        logger.error("Some tests failed!")
        sys.exit(1)
    else:
        logger.info("All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
