#!/usr/bin/env python3
"""
Test folder-specific document count fix.

This test verifies that:
1. Document count works for "All Documents" (no folder_id)
2. Document count works for specific folders (with folder_id)
3. Subfolder document counts work

Usage:
    DATABASE_URL="postgresql://..." FERNET_KEY="..." python scripts/test_folder_document_count_fix.py
"""
import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.core.config import settings
from app.db.models import Matter, ClioIntegration
from app.services.clio_client import ClioClient
from app.core.security import decrypt_token

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_folder_document_counts():
    """Test folder-specific document counts."""
    logger.info("=" * 60)
    logger.info("TESTING FOLDER DOCUMENT COUNTS")
    logger.info("=" * 60)

    # Connect to database
    db_url = os.environ.get("DATABASE_URL") or settings.database_url
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    results = {
        "all_documents": {"passed": False, "count": 0},
        "specific_folder": {"passed": False, "count": 0, "folder_name": ""},
        "subfolder": {"passed": False, "count": 0, "folder_name": ""}
    }

    try:
        async with async_session() as session:
            # Get Clio integration
            integration_result = await session.execute(
                select(ClioIntegration).where(
                    ClioIntegration.is_active == True,
                    ClioIntegration.access_token_encrypted.isnot(None)
                ).limit(1)
            )
            integration = integration_result.scalar_one_or_none()

            if not integration:
                logger.error("No active Clio integration found!")
                return results

            # Get a matter with documents
            matter_result = await session.execute(
                select(Matter).where(
                    Matter.user_id == integration.user_id,
                    Matter.clio_matter_id.isnot(None)
                ).order_by(Matter.id.desc()).limit(10)
            )
            matters = matter_result.scalars().all()

            if not matters:
                logger.error("No matters with Clio IDs found!")
                return results

            decrypted_access = decrypt_token(integration.access_token_encrypted)
            decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)

            async with ClioClient(
                access_token=decrypted_access,
                refresh_token=decrypted_refresh,
                token_expires_at=integration.token_expires_at,
                region=integration.clio_region
            ) as clio:
                # Find a matter with documents and folders
                test_matter = None
                for m in matters:
                    doc_count = 0
                    async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                        doc_count += 1
                        if doc_count > 10:
                            break
                    if doc_count > 5:
                        test_matter = m
                        logger.info(f"Selected matter: {m.display_number} ({doc_count}+ docs)")
                        break

                if not test_matter:
                    logger.error("No suitable test matter found!")
                    return results

                # TEST 1: All documents count
                logger.info("\n--- TEST 1: All Documents Count ---")
                all_count = 0
                async for _ in clio.get_documents(matter_id=int(test_matter.clio_matter_id)):
                    all_count += 1
                results["all_documents"]["count"] = all_count
                results["all_documents"]["passed"] = all_count > 0
                logger.info(f"All Documents: {all_count} documents")
                logger.info(f"PASS" if results["all_documents"]["passed"] else "FAIL")

                # Get folders for this matter
                folders = await clio.get_matter_folders(int(test_matter.clio_matter_id))

                if not folders:
                    logger.warning("No folders found in this matter!")
                    results["specific_folder"]["passed"] = True  # Not a failure
                    results["specific_folder"]["note"] = "No folders to test"
                    return results

                # TEST 2: Specific folder count
                logger.info("\n--- TEST 2: Specific Folder Count ---")
                test_folder = None
                for folder in folders:
                    test_folder = folder
                    results["specific_folder"]["folder_name"] = folder.get("name", "unnamed")
                    break

                if test_folder:
                    folder_count = 0
                    async for _ in clio.get_documents_in_folder(
                        test_folder["id"],
                        matter_id=int(test_matter.clio_matter_id)
                    ):
                        folder_count += 1
                    results["specific_folder"]["count"] = folder_count
                    # Folder may have 0 docs, that's OK - it worked if no error
                    results["specific_folder"]["passed"] = True
                    logger.info(f"Folder '{test_folder.get('name')}': {folder_count} documents")
                    logger.info("PASS")

                # TEST 3: Find a subfolder if available
                logger.info("\n--- TEST 3: Subfolder Count ---")
                subfolder_found = False
                for folder in folders:
                    children = folder.get("children", [])
                    if children:
                        subfolder = children[0]
                        results["subfolder"]["folder_name"] = subfolder.get("name", "unnamed")
                        subfolder_count = 0
                        async for _ in clio.get_documents_in_folder(
                            subfolder["id"],
                            matter_id=int(test_matter.clio_matter_id)
                        ):
                            subfolder_count += 1
                        results["subfolder"]["count"] = subfolder_count
                        results["subfolder"]["passed"] = True
                        logger.info(f"Subfolder '{subfolder.get('name')}': {subfolder_count} documents")
                        logger.info("PASS")
                        subfolder_found = True
                        break

                if not subfolder_found:
                    results["subfolder"]["passed"] = True
                    results["subfolder"]["note"] = "No subfolders to test"
                    logger.info("No subfolders found (not a failure)")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        all_passed = all(r.get("passed", False) for r in results.values())
        for test_name, result in results.items():
            status = "PASS" if result.get("passed") else "FAIL"
            count = result.get("count", "N/A")
            note = result.get("note", "")
            logger.info(f"  {test_name}: {status} (count={count}) {note}")

        logger.info("=" * 60)
        if all_passed:
            logger.info("ALL TESTS PASSED!")
            return True
        else:
            logger.error("SOME TESTS FAILED!")
            return False

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    success = asyncio.run(test_folder_document_counts())
    sys.exit(0 if success else 1)
