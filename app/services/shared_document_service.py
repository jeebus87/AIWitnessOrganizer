"""
Shared Document Service for cross-app document sharing.

This service provides access to the FirmDocument table shared between
AIDiscoveryDrafter and AIWitnessFinder. Documents parsed by AIDiscoveryDrafter
can be reused by AIWitnessFinder without re-parsing.
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FirmDocument


class SharedDocumentService:
    """
    Service for accessing shared FirmDocument data.

    Both apps share the same PostgreSQL database with FirmDocument as the
    canonical parsed document store.
    """

    @staticmethod
    async def get_by_clio_document_id(
        db: AsyncSession,
        organization_id: int,
        clio_document_id: str,
    ) -> Optional[FirmDocument]:
        """
        Get a parsed document by its Clio document ID.

        Args:
            db: Database session
            organization_id: Firm/organization ID
            clio_document_id: Clio's document identifier

        Returns:
            FirmDocument if found with extracted text, None otherwise
        """
        result = await db.execute(
            select(FirmDocument).where(
                and_(
                    FirmDocument.organization_id == organization_id,
                    FirmDocument.clio_document_id == clio_document_id,
                )
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_content_hash(
        db: AsyncSession,
        organization_id: int,
        content_hash: str,
    ) -> Optional[FirmDocument]:
        """
        Get a parsed document by its content hash (SHA-256).

        Useful for deduplication - find if this exact content was already parsed.

        Args:
            db: Database session
            organization_id: Firm/organization ID
            content_hash: SHA-256 hash of document content

        Returns:
            FirmDocument if found with extracted text, None otherwise
        """
        result = await db.execute(
            select(FirmDocument).where(
                and_(
                    FirmDocument.organization_id == organization_id,
                    FirmDocument.content_hash == content_hash,
                )
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def compute_content_hash(content: bytes) -> str:
        """
        Compute SHA-256 hash of document content.

        Args:
            content: Raw document bytes

        Returns:
            Hex-encoded SHA-256 hash
        """
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    async def save_parsed_document(
        db: AsyncSession,
        organization_id: int,
        clio_document_id: str,
        clio_matter_id: Optional[str],
        file_name: str,
        content: bytes,
        extracted_text: str,
        extraction_method: str,
        *,
        file_size: Optional[int] = None,
        content_type: Optional[str] = None,
        page_count: Optional[int] = None,
        pages_with_text: Optional[int] = None,
        pages_with_ocr: Optional[int] = None,
    ) -> FirmDocument:
        """
        Save a parsed document to the shared document store.

        If a document with the same organization_id and clio_document_id exists,
        it will be updated. Otherwise, a new record is created.

        Args:
            db: Database session
            organization_id: Firm/organization ID
            clio_document_id: Clio's document identifier
            clio_matter_id: Clio's matter identifier (optional)
            file_name: Original filename
            content: Raw document bytes (for hashing)
            extracted_text: Parsed text content
            extraction_method: How text was extracted

        Returns:
            The saved FirmDocument record
        """
        content_hash = SharedDocumentService.compute_content_hash(content)
        now = datetime.now(timezone.utc)

        # Check if document already exists
        existing = await SharedDocumentService.get_by_clio_document_id(
            db, organization_id, clio_document_id
        )

        if existing:
            # Update existing record
            existing.extracted_text = extracted_text
            existing.extraction_method = extraction_method
            existing.content_hash = content_hash
            existing.file_name = file_name
            existing.file_size = file_size or len(content)
            existing.content_type = content_type
            existing.page_count = page_count
            existing.pages_with_text = pages_with_text
            existing.pages_with_ocr = pages_with_ocr
            existing.clio_matter_id = clio_matter_id
            existing.parsed_at = now

            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            # Create new record
            firm_doc = FirmDocument(
                organization_id=organization_id,
                clio_document_id=clio_document_id,
                clio_matter_id=clio_matter_id,
                file_name=file_name,
                file_size=file_size or len(content),
                content_type=content_type,
                content_hash=content_hash,
                extracted_text=extracted_text,
                extraction_method=extraction_method,
                page_count=page_count,
                pages_with_text=pages_with_text,
                pages_with_ocr=pages_with_ocr,
                parsed_at=now,
            )
            db.add(firm_doc)
            await db.commit()
            await db.refresh(firm_doc)
            return firm_doc

    @staticmethod
    async def get_firm_document_for_witness_extraction(
        db: AsyncSession,
        organization_id: int,
        clio_document_id: str,
        content_hash: Optional[str] = None,
    ) -> Optional[FirmDocument]:
        """
        Get a FirmDocument that has extracted text ready for witness extraction.

        First tries to find by clio_document_id, then by content_hash.
        Only returns documents that have non-empty extracted_text.

        Args:
            db: Database session
            organization_id: Firm/organization ID
            clio_document_id: Clio's document identifier
            content_hash: Optional content hash for fallback lookup

        Returns:
            FirmDocument with extracted text if found, None otherwise
        """
        # First try by Clio document ID
        firm_doc = await SharedDocumentService.get_by_clio_document_id(
            db, organization_id, clio_document_id
        )

        if firm_doc and firm_doc.extracted_text:
            return firm_doc

        # Fallback to content hash if provided
        if content_hash:
            firm_doc = await SharedDocumentService.get_by_content_hash(
                db, organization_id, content_hash
            )
            if firm_doc and firm_doc.extracted_text:
                return firm_doc

        return None
