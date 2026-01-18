#!/usr/bin/env python3
"""
E2E Test Script for Folder Document Count Issue

This script tests the bug where after processing one matter, selecting another
matter shows 0 documents in the folder selector even though Clio has documents.

Root Cause: Document counts come from local DB, not Clio API.
- Folders are fetched live from Clio (correct)
- Document counts query local database only (problem)
- If matter was never synced, local DB has no documents = 0 count

Usage:
    # Set your OAuth token first
    export CLIO_ACCESS_TOKEN="your_token_here"
    python scripts/test_folder_document_count.py

Or with Railway:
    railway run python scripts/test_folder_document_count.py
"""
import asyncio
import sys
import os
import logging
from datetime import datetime
from typing import Tuple, Optional, Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func

from app.core.config import settings
from app.db.models import Matter, Document, User, ClioIntegration
from app.services.clio_client import ClioClient
from app.core.security import decrypt_token

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def get_clio_document_count(clio_client: ClioClient, clio_matter_id: int, folder_id: Optional[int] = None) -> int:
    """Get document count directly from Clio API."""
    count = 0
    try:
        if folder_id:
            # Get documents in specific folder
            async for doc in clio_client.get_documents_in_folder(folder_id):
                count += 1
        else:
            # Get all documents for matter
            async for doc in clio_client.get_documents(matter_id=clio_matter_id):
                count += 1
    except Exception as e:
        logger.error(f"Error fetching from Clio: {e}")
        return -1
    return count


async def get_local_document_count(session: AsyncSession, matter_id: int, folder_id: Optional[str] = None) -> int:
    """Get document count from local database (current behavior)."""
    query = select(func.count()).select_from(Document).where(
        Document.matter_id == matter_id,
        Document.is_soft_deleted == False
    )
    if folder_id:
        query = query.where(Document.clio_folder_id == folder_id)

    result = await session.scalar(query)
    return result or 0


async def get_clio_folders(clio_client: ClioClient, clio_matter_id: int) -> List[Dict[str, Any]]:
    """Get folder tree from Clio API."""
    try:
        folders = await clio_client.get_folder_tree(clio_matter_id)
        return folders
    except Exception as e:
        logger.error(f"Error fetching folders from Clio: {e}")
        return []


def flatten_folders(folders: List[Dict], parent_path: str = "") -> List[Dict]:
    """Flatten nested folder structure for easier iteration."""
    result = []
    for folder in folders:
        path = f"{parent_path}/{folder['name']}" if parent_path else folder['name']
        result.append({
            "id": folder["id"],
            "name": folder["name"],
            "path": path
        })
        if folder.get("children"):
            result.extend(flatten_folders(folder["children"], path))
    return result


async def test_document_count_mismatch(
    session: AsyncSession,
    clio_client: ClioClient,
    matter: Matter
) -> Tuple[int, int]:
    """
    Test for mismatch between Clio document count and local database count.

    This is the core test that reproduces the bug:
    - Clio API returns documents
    - Local database query returns 0 (because matter wasn't synced)
    """
    passed = 0
    failed = 0

    logger.info(f"\n{'='*60}")
    logger.info(f"Testing Matter: {matter.display_number}")
    logger.info(f"Matter ID: {matter.id}, Clio Matter ID: {matter.clio_matter_id}")
    logger.info(f"{'='*60}")

    # Get folders from Clio
    logger.info("\n--- Step 1: Fetch folders from Clio API ---")
    folders = await get_clio_folders(clio_client, matter.clio_matter_id)
    flat_folders = flatten_folders(folders)
    logger.info(f"Found {len(flat_folders)} folders in Clio")

    # Get root-level document count from Clio
    logger.info("\n--- Step 2: Compare document counts ---")
    clio_total = await get_clio_document_count(clio_client, matter.clio_matter_id)
    local_total = await get_local_document_count(session, matter.id)

    logger.info(f"  Root level documents:")
    logger.info(f"    Clio API count:     {clio_total}")
    logger.info(f"    Local DB count:     {local_total}")

    if clio_total > 0 and local_total == 0:
        logger.warning(f"  BUG REPRODUCED: Clio has {clio_total} docs, local DB has 0")
        logger.warning(f"  This is the folder selector '0 documents' bug!")
        failed += 1
    elif clio_total == local_total:
        logger.info(f"  PASS: Counts match ({clio_total})")
        passed += 1
    elif local_total > clio_total:
        logger.warning(f"  STALE DATA: Local has more docs than Clio (possible deleted docs)")
        passed += 1  # Not the bug we're looking for
    else:
        logger.info(f"  PARTIAL SYNC: Local has {local_total}/{clio_total} docs")
        passed += 1  # Partial sync is acceptable

    # Test per-folder counts
    logger.info("\n--- Step 3: Per-folder document counts ---")
    folder_mismatches = 0

    for folder in flat_folders[:5]:  # Test first 5 folders
        folder_id = folder["id"]
        clio_count = await get_clio_document_count(clio_client, matter.clio_matter_id, folder_id)
        local_count = await get_local_document_count(session, matter.id, str(folder_id))

        status = "✓" if clio_count == local_count else "✗"
        if clio_count != local_count:
            folder_mismatches += 1

        logger.info(f"  {status} Folder '{folder['path'][:40]}': Clio={clio_count}, Local={local_count}")

    if folder_mismatches > 0:
        logger.warning(f"\n  {folder_mismatches} folder(s) have count mismatches")

    return passed, failed


async def test_multi_matter_sequence(
    session: AsyncSession,
    clio_client: ClioClient,
    matters: List[Matter]
) -> Tuple[int, int]:
    """
    Simulate the user flow:
    1. Open Matter A, see documents
    2. Process Matter A
    3. Open Matter B, see 0 documents (BUG)
    """
    passed = 0
    failed = 0

    logger.info(f"\n{'='*60}")
    logger.info("TEST: Multi-Matter Sequence (Simulating User Flow)")
    logger.info(f"{'='*60}")

    if len(matters) < 2:
        logger.warning("Need at least 2 matters to test sequence")
        return 0, 0

    matter_a = matters[0]
    matter_b = matters[1]

    # Simulate opening Matter A
    logger.info(f"\n--- User opens Matter A: {matter_a.display_number} ---")
    clio_count_a = await get_clio_document_count(clio_client, matter_a.clio_matter_id)
    local_count_a = await get_local_document_count(session, matter_a.id)
    logger.info(f"  Clio: {clio_count_a} docs, Local DB: {local_count_a} docs")

    # Simulate "processing" (we just note the state)
    logger.info(f"\n--- User clicks 'Process' on Matter A ---")
    logger.info(f"  (Processing would sync documents to local DB)")

    # Simulate switching to Matter B
    logger.info(f"\n--- User opens Matter B: {matter_b.display_number} ---")
    clio_count_b = await get_clio_document_count(clio_client, matter_b.clio_matter_id)
    local_count_b = await get_local_document_count(session, matter_b.id)
    logger.info(f"  Clio: {clio_count_b} docs, Local DB: {local_count_b} docs")

    if clio_count_b > 0 and local_count_b == 0:
        logger.error(f"\n  BUG CONFIRMED!")
        logger.error(f"  User sees: '0 documents' in folder selector")
        logger.error(f"  Reality:   {clio_count_b} documents exist in Clio")
        logger.error(f"  Cause:     Matter B was never synced to local database")
        failed += 1
    elif clio_count_b == 0:
        logger.info(f"  Matter B actually has 0 documents in Clio (not the bug)")
        passed += 1
    else:
        logger.info(f"  PASS: Matter B shows correct count")
        passed += 1

    return passed, failed


async def test_sync_status_check(session: AsyncSession, matter: Matter) -> Tuple[int, int]:
    """Check if matter sync status might be affecting document visibility."""
    passed = 0
    failed = 0

    logger.info(f"\n--- Sync Status Check for {matter.display_number} ---")
    logger.info(f"  sync_status: {matter.sync_status}")
    logger.info(f"  last_synced_at: {matter.last_synced_at}")
    logger.info(f"  sync_started_at: {getattr(matter, 'sync_started_at', 'N/A')}")

    # Check for soft-deleted documents
    soft_deleted_count = await session.scalar(
        select(func.count()).select_from(Document).where(
            Document.matter_id == matter.id,
            Document.is_soft_deleted == True
        )
    )

    if soft_deleted_count and soft_deleted_count > 0:
        logger.warning(f"  Found {soft_deleted_count} soft-deleted documents")
        logger.warning(f"  These won't appear in folder counts")

    passed += 1
    return passed, failed


async def main():
    """Main test runner."""
    logger.info("="*60)
    logger.info("FOLDER DOCUMENT COUNT E2E TESTS")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("="*60)

    # Check for OAuth token
    access_token = os.environ.get("CLIO_ACCESS_TOKEN")
    if not access_token:
        logger.error("CLIO_ACCESS_TOKEN environment variable not set!")
        logger.error("Set it with: export CLIO_ACCESS_TOKEN='your_token'")
        sys.exit(1)

    total_passed = 0
    total_failed = 0

    try:
        # Connect to database
        db_url = os.environ.get("DATABASE_URL") or settings.database_url
        logger.info(f"Connecting to database...")
        if not db_url.startswith("postgresql+asyncpg://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # Find matters with documents in Clio
            logger.info("\n--- Finding test matters ---")
            result = await session.execute(
                select(Matter)
                .where(Matter.clio_matter_id.isnot(None))
                .order_by(Matter.id.desc())
                .limit(5)
            )
            matters = list(result.scalars().all())

            if not matters:
                logger.error("No matters found with Clio IDs!")
                sys.exit(1)

            logger.info(f"Found {len(matters)} matters to test")

            # Get Clio integration for token
            integration_result = await session.execute(
                select(ClioIntegration)
                .where(ClioIntegration.access_token_encrypted.isnot(None))
                .limit(1)
            )
            integration = integration_result.scalar_one_or_none()

            if not integration:
                logger.error("No Clio integration found in database!")
                logger.error("Please ensure you have a user with Clio connected.")
                sys.exit(1)

            # Use token from database (decrypted)
            decrypted_access = decrypt_token(integration.access_token_encrypted)
            decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)
            logger.info(f"Using Clio token from ClioIntegration (user_id: {integration.user_id})")

            # Use ClioClient as async context manager
            async with ClioClient(
                access_token=decrypted_access,
                refresh_token=decrypted_refresh,
                token_expires_at=integration.token_expires_at
            ) as clio_client:
                # Run tests
                for matter in matters[:2]:  # Test first 2 matters
                    p, f = await test_document_count_mismatch(session, clio_client, matter)
                    total_passed += p
                    total_failed += f

                    p, f = await test_sync_status_check(session, matter)
                    total_passed += p
                    total_failed += f

                # Multi-matter sequence test
                p, f = await test_multi_matter_sequence(session, clio_client, matters)
                total_passed += p
                total_failed += f

        await engine.dispose()

    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        total_failed += 1

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"  Total Passed: {total_passed}")
    logger.info(f"  Total Failed: {total_failed}")
    if total_passed + total_failed > 0:
        logger.info(f"  Success Rate: {total_passed / (total_passed + total_failed) * 100:.1f}%")
    logger.info(f"{'='*60}")

    if total_failed > 0:
        logger.error("\nBUG DETECTED: Document count mismatch between Clio and local DB")
        logger.error("RECOMMENDATION: Modify /api/v1/matters/{id}/documents/count to:")
        logger.error("  1. Fetch count from Clio API directly, OR")
        logger.error("  2. Auto-sync documents before returning count, OR")
        logger.error("  3. Add 'Sync' button in folder selector dialog")
        sys.exit(1)
    else:
        logger.info("All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
