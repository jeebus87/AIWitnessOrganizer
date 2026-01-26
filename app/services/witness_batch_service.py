"""
Batch Witness Extraction Service for AWS Bedrock Batch Inference.

Converts the real-time witness extraction workflow to batch processing:
- Collects all documents in a processing job
- Creates batch inference requests for all documents
- Submits to Bedrock batch API
- Processes results when complete

Benefits:
- 50% cost savings vs on-demand
- No rate limits (separate quota)
- No daily token limits (separate quota)
"""

import json
import base64
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ProcessingJob, Document, BatchJob, BatchJobType,
    Witness, User, ClioMatter
)
from app.services.batch_inference_service import get_batch_inference_service
from app.services.document_processor import ProcessedAsset, DocumentProcessor
from app.services.bedrock_client import (
    WITNESS_EXTRACTION_SYSTEM_PROMPT,
    WitnessData,
    ClaimLinkData,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class WitnessBatchService:
    """
    Service for batch witness extraction using AWS Bedrock Batch Inference.

    Replaces real-time BedrockClient calls with batch job submission.
    """

    def __init__(self):
        self.batch_service = get_batch_inference_service()
        self.document_processor = DocumentProcessor()

    def _build_extraction_prompt(
        self,
        assets: List[ProcessedAsset],
        legal_context: Optional[str] = None
    ) -> str:
        """
        Build the user message for witness extraction.

        For batch inference, we can't send images directly - we need to
        include text content or describe what we're analyzing.
        """
        parts = []

        if legal_context:
            parts.append(f"LEGAL CONTEXT:\n{legal_context}\n")

        # Add text content from assets
        for asset in assets:
            if asset.asset_type in ("text", "email_body"):
                try:
                    text = asset.content.decode("utf-8", errors="replace")
                    parts.append(f"[Document: {asset.filename}]\n{text}\n")
                except Exception:
                    pass

        parts.append(
            "\nAnalyze the provided document(s) and extract information about "
            "ALL witnesses and key individuals mentioned. "
            "Respond with valid JSON only."
        )

        return "\n".join(parts)

    def _build_extraction_prompt_with_images(
        self,
        assets: List[ProcessedAsset],
        legal_context: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Build content array with images for batch inference.

        Batch inference supports the same format as real-time, including images.
        """
        content = []

        if legal_context:
            content.append({
                "type": "text",
                "text": f"LEGAL CONTEXT:\n{legal_context}"
            })

        # Add images and text
        for asset in assets:
            if asset.asset_type == "image":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": asset.media_type,
                        "data": base64.b64encode(asset.content).decode("utf-8")
                    }
                })
            elif asset.asset_type in ("text", "email_body"):
                try:
                    text = asset.content.decode("utf-8", errors="replace")
                    content.append({
                        "type": "text",
                        "text": f"[Document: {asset.filename}]\n{text}"
                    })
                except Exception:
                    pass

        # Add extraction instruction
        content.append({
            "type": "text",
            "text": (
                "Analyze the provided document(s) and extract information about "
                "ALL witnesses and key individuals mentioned. "
                "Respond with valid JSON only."
            )
        })

        return content

    def create_witness_extraction_record(
        self,
        record_id: str,
        assets: List[ProcessedAsset],
        legal_context: Optional[str] = None,
        max_tokens: int = 8192,
    ) -> Dict[str, Any]:
        """
        Create a batch record for witness extraction with image support.

        Args:
            record_id: Unique ID for this record (e.g., "extract-job-123-doc-456")
            assets: List of ProcessedAsset objects
            legal_context: Optional legal standards context
            max_tokens: Maximum response tokens

        Returns:
            Dict representing one JSONL record for batch inference
        """
        # Build content array with images
        content = self._build_extraction_prompt_with_images(assets, legal_context)

        return {
            "recordId": record_id,
            "modelInput": {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "system": WITNESS_EXTRACTION_SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            }
        }

    async def submit_witness_extraction_batch(
        self,
        db: AsyncSession,
        job: ProcessingJob,
        documents_with_assets: Dict[int, List[ProcessedAsset]],
        legal_context: Optional[str] = None,
    ) -> BatchJob:
        """
        Submit all documents in a processing job for batch witness extraction.

        Args:
            db: Database session
            job: ProcessingJob to process
            documents_with_assets: Dict mapping document ID to parsed assets
            legal_context: Optional legal standards context from RAG

        Returns:
            BatchJob record for tracking
        """
        logger.info(f"Preparing batch witness extraction for job {job.id} with {len(documents_with_assets)} documents")

        # Create batch records for each document
        records = []

        for doc_id, assets in documents_with_assets.items():
            if not assets:
                logger.warning(f"No assets for document {doc_id}, skipping")
                continue

            # Create extraction record
            record = self.create_witness_extraction_record(
                record_id=f"extract-{job.id}-{doc_id}",
                assets=assets,
                legal_context=legal_context,
            )
            records.append(record)
            logger.debug(f"Created extraction record for document {doc_id}")

        if not records:
            raise ValueError("No valid documents to process")

        # Generate job identifiers
        job_name = self.batch_service.generate_job_name("witness-extraction", job.id)
        input_key = self.batch_service.generate_input_key("witness-extraction", job.id)
        output_uri = self.batch_service.generate_output_uri("witness-extraction", job.id)

        # Create JSONL content
        jsonl_content = self.batch_service.create_jsonl_content(records)

        # Upload to S3
        input_s3_uri = self.batch_service.upload_to_s3(jsonl_content, input_key)

        # Submit batch job
        result = self.batch_service.submit_batch_job(
            input_s3_uri=input_s3_uri,
            output_s3_uri=output_uri,
            job_name=job_name,
        )

        # Create BatchJob record for tracking
        batch_job = BatchJob(
            user_id=job.user_id,
            processing_job_id=job.id,
            aws_job_arn=result["job_arn"],
            job_type=BatchJobType.WITNESS_EXTRACTION,
            status="Submitted",
            input_s3_uri=result["input_uri"],
            output_s3_uri=result["output_uri"],
            total_records=len(records),
        )

        db.add(batch_job)
        await db.commit()
        await db.refresh(batch_job)

        logger.info(f"Batch job submitted: {batch_job.aws_job_arn} with {len(records)} records")

        return batch_job

    def parse_witness_extraction_results(
        self,
        batch_results: Dict[str, Any],
    ) -> Dict[int, List[WitnessData]]:
        """
        Parse batch output into WitnessData objects per document.

        Args:
            batch_results: Dict mapping record_id to parsed output from batch service

        Returns:
            Dict mapping document_id to list of WitnessData
        """
        results_by_doc = {}

        for record_id, result in batch_results.items():
            # Parse record_id: "extract-{job_id}-{doc_id}"
            try:
                parts = record_id.split("-")
                if len(parts) >= 3 and parts[0] == "extract":
                    doc_id = int(parts[-1])
                else:
                    logger.warning(f"Unexpected record_id format: {record_id}")
                    continue
            except (ValueError, IndexError):
                logger.warning(f"Failed to parse record_id: {record_id}")
                continue

            # Check for errors
            if result.get("error"):
                logger.error(f"Error in batch result for doc {doc_id}: {result.get('error_message')}")
                results_by_doc[doc_id] = []
                continue

            # Parse the AI response content
            content = result.get("content", "")
            witnesses = self._parse_witness_json(content)
            results_by_doc[doc_id] = witnesses

            logger.info(f"Parsed {len(witnesses)} witnesses for document {doc_id}")

        return results_by_doc

    def _parse_witness_json(self, content: str) -> List[WitnessData]:
        """
        Parse JSON response into WitnessData objects.

        Handles various JSON formats and error recovery.
        """
        import re

        if not content:
            return []

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from text
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError as e:
                    # Try to recover partial data
                    try:
                        witnesses_match = re.search(r'"witnesses"\s*:\s*\[([\s\S]*)', json_match.group())
                        if witnesses_match:
                            complete_witnesses = re.findall(r'\{[^{}]*\}', witnesses_match.group(1))
                            if complete_witnesses:
                                fixed_json = '{"witnesses": [' + ','.join(complete_witnesses) + ']}'
                                data = json.loads(fixed_json)
                            else:
                                logger.warning(f"Could not recover witnesses from malformed JSON")
                                return []
                        else:
                            return []
                    except Exception:
                        logger.warning(f"Failed to parse witness JSON: {e}")
                        return []
            else:
                logger.warning(f"No JSON found in content")
                return []

        # Convert to WitnessData objects
        witnesses = []
        for w in data.get("witnesses", []):
            # Map relevance to importance for backwards compatibility
            relevance = w.get("relevance", "RELEVANT").upper().replace(" ", "_")
            importance = w.get("importance", "MEDIUM").upper()
            if importance not in ("HIGH", "MEDIUM", "LOW"):
                importance_map = {
                    "HIGHLY_RELEVANT": "HIGH",
                    "RELEVANT": "MEDIUM",
                    "SOMEWHAT_RELEVANT": "LOW",
                    "NOT_RELEVANT": "LOW"
                }
                importance = importance_map.get(relevance, "MEDIUM")

            # Parse claim links if present
            claim_links = []
            for link in w.get("claimLinks", []):
                claim_links.append(ClaimLinkData(
                    claim_ref=link.get("claimRef", ""),
                    relationship=link.get("relationship", "neutral"),
                    explanation=link.get("explanation", "")
                ))

            witnesses.append(WitnessData(
                full_name=w.get("fullName", "Unknown"),
                role=w.get("role", "other").lower(),
                importance=importance,
                observation=w.get("observation"),
                source_summary=w.get("sourceSummary") or w.get("sourceQuote"),
                context=w.get("context"),
                email=w.get("email"),
                phone=w.get("phone"),
                address=w.get("address"),
                source_page=w.get("sourcePage"),
                confidence_score=float(w.get("confidenceScore", 0.5)),
                relevance=relevance,
                relevance_reason=w.get("relevanceReason"),
                document_relevance=w.get("documentRelevance", "RELEVANT").upper().replace(" ", "_"),
                document_relevance_reason=w.get("documentRelevanceReason"),
                claim_links=claim_links
            ))

        return witnesses

    async def process_completed_batch(
        self,
        db: AsyncSession,
        batch_job: BatchJob,
    ) -> int:
        """
        Process a completed batch job and save witnesses to database.

        Args:
            db: Database session
            batch_job: Completed BatchJob with results

        Returns:
            Number of witnesses saved
        """
        logger.info(f"Processing completed batch job {batch_job.id} for processing job {batch_job.processing_job_id}")

        # Get results from BatchJob (already downloaded by polling worker)
        if not batch_job.results_json:
            logger.warning(f"No results_json in batch job {batch_job.id}")
            return 0

        # Parse results
        results_by_doc = self.parse_witness_extraction_results(batch_job.results_json)

        # Get processing job
        result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == batch_job.processing_job_id)
        )
        processing_job = result.scalar_one_or_none()

        if not processing_job:
            logger.error(f"Processing job {batch_job.processing_job_id} not found")
            return 0

        # Get documents in the job
        result = await db.execute(
            select(Document).where(Document.processing_job_id == processing_job.id)
        )
        documents = {doc.id: doc for doc in result.scalars().all()}

        # Save witnesses
        total_saved = 0

        for doc_id, witnesses in results_by_doc.items():
            document = documents.get(doc_id)
            if not document:
                logger.warning(f"Document {doc_id} not found in processing job")
                continue

            for witness_data in witnesses:
                witness = Witness(
                    document_id=doc_id,
                    full_name=witness_data.full_name,
                    role=witness_data.role,
                    importance=witness_data.importance,
                    observation=witness_data.observation,
                    source_summary=witness_data.source_summary,
                    context=witness_data.context,
                    email=witness_data.email,
                    phone=witness_data.phone,
                    address=witness_data.address,
                    source_page=witness_data.source_page,
                    confidence_score=witness_data.confidence_score,
                    relevance=witness_data.relevance,
                    relevance_reason=witness_data.relevance_reason,
                    document_relevance=witness_data.document_relevance,
                    document_relevance_reason=witness_data.document_relevance_reason,
                )
                db.add(witness)
                total_saved += 1

        await db.commit()
        logger.info(f"Saved {total_saved} witnesses from batch job {batch_job.id}")

        return total_saved


# Singleton instance
_witness_batch_service: Optional[WitnessBatchService] = None


def get_witness_batch_service() -> WitnessBatchService:
    """Get or create WitnessBatchService singleton."""
    global _witness_batch_service
    if _witness_batch_service is None:
        _witness_batch_service = WitnessBatchService()
    return _witness_batch_service
