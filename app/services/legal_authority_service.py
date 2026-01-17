"""Legal Authority Service for RAG with pgvector"""
import hashlib
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import boto3
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, delete

from app.core.config import settings
from app.db.models import LegalAuthority, LegalAuthorityChunk, Matter

logger = logging.getLogger(__name__)

# Chunk settings
CHUNK_SIZE = 1000  # Characters per chunk
CHUNK_OVERLAP = 200  # Overlap between chunks


class LegalAuthorityService:
    """Service for processing legal authority documents and RAG retrieval"""

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

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks"""
        if not text:
            return []

        chunks = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = start + CHUNK_SIZE

            # Try to break at sentence boundary
            if end < text_len:
                # Look for sentence endings
                for sep in ['. ', '.\n', '? ', '?\n', '! ', '!\n']:
                    last_sep = text.rfind(sep, start, end)
                    if last_sep > start + CHUNK_SIZE // 2:
                        end = last_sep + len(sep)
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # Move start with overlap
            start = end - CHUNK_OVERLAP
            if start >= text_len:
                break

        return chunks

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding vector from Amazon Titan"""
        if not self.bedrock_client:
            logger.error("Bedrock client not initialized")
            return None

        try:
            # Use Amazon Titan Text Embeddings V2
            response = self.bedrock_client.invoke_model(
                modelId="amazon.titan-embed-text-v2:0",
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "inputText": text[:8000],  # Titan limit
                    "dimensions": 1536,
                    "normalize": True
                })
            )

            result = json.loads(response["body"].read())
            return result.get("embedding")

        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            return None

    async def process_legal_authority_document(
        self,
        db: AsyncSession,
        matter_id: int,
        document_text: str,
        filename: str,
        clio_document_id: Optional[str] = None,
        clio_folder_id: Optional[str] = None
    ) -> Optional[LegalAuthority]:
        """Process a legal authority document: chunk, embed, and store"""

        # Calculate content hash
        content_hash = hashlib.sha256(document_text.encode()).hexdigest()

        # Check if already processed (by hash)
        existing = await db.execute(
            select(LegalAuthority).where(
                LegalAuthority.matter_id == matter_id,
                LegalAuthority.content_hash == content_hash
            )
        )
        if existing.scalar_one_or_none():
            logger.info(f"Document already processed: {filename}")
            return None

        # Create legal authority record
        legal_auth = LegalAuthority(
            matter_id=matter_id,
            clio_document_id=clio_document_id,
            clio_folder_id=clio_folder_id,
            filename=filename,
            content_hash=content_hash,
            is_processed=False
        )
        db.add(legal_auth)
        await db.flush()  # Get the ID

        try:
            # Chunk the document
            chunks = self._chunk_text(document_text)
            logger.info(f"Processing {len(chunks)} chunks for {filename}")

            # Process each chunk
            for idx, chunk_text in enumerate(chunks):
                # Get embedding
                embedding = await self._get_embedding(chunk_text)

                if embedding:
                    # Insert chunk with embedding using raw SQL (pgvector)
                    await db.execute(
                        text("""
                            INSERT INTO legal_authority_chunks
                            (legal_authority_id, chunk_index, chunk_text, embedding, created_at)
                            VALUES (:legal_authority_id, :chunk_index, :chunk_text, :embedding, NOW())
                        """),
                        {
                            "legal_authority_id": legal_auth.id,
                            "chunk_index": idx,
                            "chunk_text": chunk_text,
                            "embedding": f"[{','.join(map(str, embedding))}]"
                        }
                    )

            # Update legal authority record
            legal_auth.total_chunks = len(chunks)
            legal_auth.is_processed = True

            await db.commit()
            logger.info(f"Successfully processed legal authority: {filename}")
            return legal_auth

        except Exception as e:
            logger.error(f"Failed to process legal authority {filename}: {e}")
            legal_auth.is_processed = False
            legal_auth.processing_error = str(e)
            await db.commit()
            return None

    async def get_relevant_legal_context(
        self,
        db: AsyncSession,
        query: str,
        matter_id: int,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Retrieve most relevant legal text chunks via similarity search"""

        # Get query embedding
        query_embedding = await self._get_embedding(query)
        if not query_embedding:
            logger.error("Failed to get query embedding")
            return []

        try:
            # Similarity search using pgvector
            # Uses cosine distance (1 - cosine_similarity)
            result = await db.execute(
                text("""
                    SELECT
                        lac.id,
                        lac.chunk_text,
                        lac.chunk_index,
                        la.filename,
                        1 - (lac.embedding <=> :query_embedding::vector) as similarity
                    FROM legal_authority_chunks lac
                    JOIN legal_authorities la ON lac.legal_authority_id = la.id
                    WHERE la.matter_id = :matter_id
                        AND la.is_processed = true
                    ORDER BY lac.embedding <=> :query_embedding::vector
                    LIMIT :limit
                """),
                {
                    "query_embedding": f"[{','.join(map(str, query_embedding))}]",
                    "matter_id": matter_id,
                    "limit": limit
                }
            )

            rows = result.fetchall()

            return [
                {
                    "id": row[0],
                    "text": row[1],
                    "chunk_index": row[2],
                    "filename": row[3],
                    "similarity": float(row[4]) if row[4] else 0.0
                }
                for row in rows
            ]

        except Exception as e:
            logger.error(f"Failed to search legal context: {e}")
            return []

    async def get_legal_context_for_witness_extraction(
        self,
        db: AsyncSession,
        matter_id: int,
        document_summary: str
    ) -> str:
        """Get formatted legal context for AI witness extraction prompt"""

        # Search for relevant legal standards
        contexts = await self.get_relevant_legal_context(
            db=db,
            query=document_summary,
            matter_id=matter_id,
            limit=5
        )

        if not contexts:
            return ""

        # Format for prompt injection
        legal_context = "LEGAL STANDARDS AND CASE LAW FOR THIS MATTER:\n\n"

        for i, ctx in enumerate(contexts, 1):
            legal_context += f"[Source {i}: {ctx['filename']}]\n"
            legal_context += f"{ctx['text']}\n\n"

        legal_context += "---\nUse the above legal standards to determine witness relevance.\n"

        return legal_context

    async def delete_legal_authorities_for_matter(
        self,
        db: AsyncSession,
        matter_id: int
    ) -> int:
        """Delete all legal authorities for a matter"""
        result = await db.execute(
            delete(LegalAuthority).where(LegalAuthority.matter_id == matter_id)
        )
        await db.commit()
        return result.rowcount

    async def get_legal_authority_stats(
        self,
        db: AsyncSession,
        matter_id: int
    ) -> Dict[str, Any]:
        """Get statistics about legal authorities for a matter"""
        result = await db.execute(
            select(LegalAuthority).where(LegalAuthority.matter_id == matter_id)
        )
        authorities = result.scalars().all()

        total_documents = len(authorities)
        total_chunks = sum(a.total_chunks for a in authorities)
        processed = sum(1 for a in authorities if a.is_processed)

        return {
            "total_documents": total_documents,
            "processed_documents": processed,
            "total_chunks": total_chunks,
            "filenames": [a.filename for a in authorities]
        }
