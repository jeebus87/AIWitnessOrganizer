"""Legal Authority Service for RAG with pgvector"""
import hashlib
import json
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

import boto3
import httpx
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
                    # Insert chunk with embedding as JSON text (fallback for no pgvector)
                    embedding_json = json.dumps(embedding)
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
                            "embedding": embedding_json
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

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors"""
        import math
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

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
            # Fallback: Load all chunks and compute similarity in Python
            # (Since pgvector is not available on Railway)
            result = await db.execute(
                text("""
                    SELECT
                        lac.id,
                        lac.chunk_text,
                        lac.chunk_index,
                        la.filename,
                        lac.embedding
                    FROM legal_authority_chunks lac
                    JOIN legal_authorities la ON lac.legal_authority_id = la.id
                    WHERE la.matter_id = :matter_id
                        AND la.is_processed = true
                        AND lac.embedding IS NOT NULL
                """),
                {"matter_id": matter_id}
            )

            rows = result.fetchall()

            # Compute similarities in Python
            chunks_with_similarity = []
            for row in rows:
                try:
                    chunk_embedding = json.loads(row[4]) if row[4] else None
                    if chunk_embedding:
                        similarity = self._cosine_similarity(query_embedding, chunk_embedding)
                        chunks_with_similarity.append({
                            "id": row[0],
                            "text": row[1],
                            "chunk_index": row[2],
                            "filename": row[3],
                            "similarity": similarity
                        })
                except (json.JSONDecodeError, TypeError):
                    continue

            # Sort by similarity and return top results
            chunks_with_similarity.sort(key=lambda x: x["similarity"], reverse=True)
            return chunks_with_similarity[:limit]

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

    # =========================================================================
    # Online Search Fallback with Privacy Guardrails
    # =========================================================================

    async def _extract_privacy_safe_query(self, matter_context: str) -> Optional[str]:
        """
        Use AI to extract ONLY abstract legal concepts from matter context.
        CRITICAL: This ensures no PII is sent to external search APIs.
        """
        if not self.bedrock_client:
            logger.error("Bedrock client not initialized for privacy extraction")
            return None

        try:
            # Privacy-focused prompt that extracts only legal concepts
            privacy_prompt = """You are a legal privacy filter. Your task is to extract ONLY abstract legal principles and topics from the provided context.

STRICT RULES:
1. NEVER include: names, dates, locations, company names, case numbers, addresses, phone numbers, emails, or any identifying information
2. ONLY output: legal concepts, causes of action, legal standards, jurisdictions, and areas of law
3. Output should be suitable as a Google search query for legal research
4. Maximum 10 words

Examples of GOOD outputs:
- "California hostile work environment employment law standard"
- "FMLA retaliation burden of proof elements"
- "Texas breach of fiduciary duty damages"

Examples of BAD outputs (contain PII):
- "John Smith v. Acme Corp hostile work environment" (has names)
- "2023 San Francisco employment discrimination" (has date and location)

CONTEXT TO ANALYZE:
"""
            response = self.bedrock_client.invoke_model(
                modelId=settings.bedrock_model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 100,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"{privacy_prompt}\n{matter_context[:2000]}"
                        }
                    ]
                })
            )

            result = json.loads(response["body"].read())
            safe_query = result.get("content", [{}])[0].get("text", "").strip()

            # Additional validation: check for common PII patterns
            pii_patterns = [
                r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b',  # Phone numbers
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Emails
                r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',  # Dates
                r'\b\d{5}(-\d{4})?\b',  # ZIP codes
                r'\b(Mr\.|Mrs\.|Ms\.|Dr\.)\s+[A-Z][a-z]+\b',  # Titles with names
                r'\bv\.\s+[A-Z]',  # Case citation pattern
            ]

            for pattern in pii_patterns:
                if re.search(pattern, safe_query, re.IGNORECASE):
                    logger.warning(f"PII detected in extracted query, rejecting: {safe_query[:50]}...")
                    return None

            logger.info(f"Privacy-safe query extracted: {safe_query}")
            return safe_query

        except Exception as e:
            logger.error(f"Failed to extract privacy-safe query: {e}")
            return None

    async def search_online_legal_sources(
        self,
        matter_context: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search online legal sources using privacy-safe queries.
        Returns list of search results with titles, snippets, and URLs.

        PRIVACY CRITICAL: All queries are sanitized to remove PII before searching.
        """
        # Check if Google Custom Search is configured
        if not settings.google_custom_search_api_key or not settings.google_custom_search_cx:
            logger.warning("Google Custom Search not configured, skipping online search")
            return []

        # Extract privacy-safe query
        safe_query = await self._extract_privacy_safe_query(matter_context)
        if not safe_query:
            logger.warning("Could not extract privacy-safe query, skipping online search")
            return []

        try:
            # Call Google Custom Search API
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": settings.google_custom_search_api_key,
                        "cx": settings.google_custom_search_cx,
                        "q": safe_query,
                        "num": min(limit, 10),  # Max 10 per request
                    },
                    timeout=30.0
                )

                if response.status_code != 200:
                    logger.error(f"Google Custom Search failed: {response.status_code} - {response.text}")
                    return []

                data = response.json()
                results = []

                for item in data.get("items", []):
                    results.append({
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "url": item.get("link", ""),
                        "display_url": item.get("displayLink", ""),
                        "source": "google_search"
                    })

                logger.info(f"Found {len(results)} online legal sources for query: {safe_query}")
                return results

        except httpx.TimeoutException:
            logger.error("Google Custom Search request timed out")
            return []
        except Exception as e:
            logger.error(f"Failed to search online legal sources: {e}")
            return []

    async def get_legal_context_with_fallback(
        self,
        db: AsyncSession,
        matter_id: int,
        document_summary: str
    ) -> str:
        """
        Get legal context for AI extraction, with online search fallback.

        Priority:
        1. Use RAG from Legal Authority folder if available
        2. Fall back to online search with privacy guardrails
        """
        # First try RAG from uploaded Legal Authorities
        contexts = await self.get_relevant_legal_context(
            db=db,
            query=document_summary,
            matter_id=matter_id,
            limit=5
        )

        if contexts:
            # Format RAG results
            legal_context = "LEGAL STANDARDS AND CASE LAW FOR THIS MATTER:\n\n"
            for i, ctx in enumerate(contexts, 1):
                legal_context += f"[Source {i}: {ctx['filename']}]\n"
                legal_context += f"{ctx['text']}\n\n"
            legal_context += "---\nUse the above legal standards to determine witness relevance.\n"
            return legal_context

        # Fallback: Search online with privacy guardrails
        logger.info(f"No Legal Authority documents for matter {matter_id}, trying online search")
        online_results = await self.search_online_legal_sources(document_summary, limit=3)

        if online_results:
            legal_context = "RELEVANT LEGAL INFORMATION (from online sources):\n\n"
            for i, result in enumerate(online_results, 1):
                legal_context += f"[Source {i}: {result['display_url']}]\n"
                legal_context += f"Title: {result['title']}\n"
                legal_context += f"{result['snippet']}\n\n"
            legal_context += "---\nNote: These are search snippets. Full case law should be reviewed.\n"
            return legal_context

        # No legal context available
        return ""
