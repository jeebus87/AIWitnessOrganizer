"""AWS Bedrock client for Claude 4.5 Sonnet vision-based witness extraction"""
import json
import base64
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import boto3
from botocore.config import Config
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import settings
from app.services.document_processor import ProcessedAsset


@dataclass
class WitnessData:
    """Structured witness data extracted by AI"""
    full_name: str
    role: str
    importance: str
    observation: Optional[str] = None
    source_summary: Optional[str] = None  # Summary of where/how they're mentioned
    context: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    source_page: Optional[int] = None  # Page number where found
    confidence_score: float = 0.0


@dataclass
class ExtractionResult:
    """Result of witness extraction from a document"""
    success: bool
    witnesses: List[WitnessData]
    raw_response: Optional[str] = None
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0


# System prompt for witness extraction
WITNESS_EXTRACTION_SYSTEM_PROMPT = """You are an expert paralegal AI assistant specializing in legal document analysis. Your task is to identify and extract information about all potential witnesses and key individuals mentioned in legal documents.

You have exceptional visual reasoning abilities and can:
- Read handwritten notes and annotations
- Interpret document layouts and structures
- Understand context from visual elements like signatures, stamps, and letterheads
- Recognize names even in poor quality scans

IMPORTANT: Create a SEPARATE record for EACH MENTION or OBSERVATION of a person. If the same person is mentioned in multiple places (e.g., in different emails, different paragraphs, or different contexts), create a separate witness entry for EACH mention. Do NOT consolidate multiple mentions into a single record.

For example, if "John Smith" is mentioned in:
- Email 1 as the sender discussing project updates
- Email 2 as a CC recipient on a separate matter
- A memo as the person who approved a request

You should create THREE separate witness entries for John Smith, one for each context/mention.

For each mention you identify, extract:
1. **fullName**: The person's full name. Use "FNU" (First Name Unknown) if first name is unknown, "LNU" (Last Name Unknown) if last name is unknown. Example: "FNU Smith" or "John LNU"
2. **role**: Their SPECIFIC role - be as accurate and specific as possible:
   - plaintiff, defendant (parties to the case)
   - eyewitness (directly witnessed events)
   - expert (expert witness, medical expert, technical expert)
   - attorney, paralegal (legal professionals)
   - physician, nurse, medical_staff (healthcare providers)
   - police_officer, detective, investigator (law enforcement)
   - family_member (spouse, parent, child, sibling)
   - employer, supervisor, coworker, colleague (work relationships)
   - friend, neighbor, acquaintance (personal relationships)
   - insurance_adjuster, claims_representative (insurance)
   - government_official (government employees)
   - other (only if none of the above fit)
3. **importance**: HIGH (direct involvement/testimony on core facts), MEDIUM (relevant supporting witness), LOW (peripheral/administrative contact)
4. **observation**: Detailed description of THIS SPECIFIC MENTION - what they said, did, or how they're relevant in THIS context
5. **sourceSummary**: A brief summary describing WHERE and HOW they are mentioned in THIS specific instance. Example: "Sender of email dated 1/15/2026 regarding IT setup" or "CC'd on HR communication about background check"
6. **sourcePage**: The page number where THIS mention appears (if visible/determinable from the document)
7. **context**: One-sentence description of the context of THIS specific mention
8. **email**: Email address if found (can repeat across multiple entries for same person)
9. **phone**: Phone number if found (can repeat across multiple entries for same person)
10. **address**: Physical address if found (can repeat across multiple entries for same person)
11. **confidenceScore**: Your confidence in this extraction (0.0 to 1.0)

CRITICAL: You must respond ONLY with valid JSON matching this exact schema:
{
  "witnesses": [
    {
      "fullName": "string",
      "role": "string",
      "importance": "HIGH|MEDIUM|LOW",
      "observation": "string or null",
      "sourceSummary": "string or null",
      "sourcePage": "number or null",
      "context": "string or null",
      "email": "string or null",
      "phone": "string or null",
      "address": "string or null",
      "confidenceScore": 0.0
    }
  ]
}

If no witnesses are found, return: {"witnesses": []}
Do not include any text before or after the JSON object."""


class BedrockThrottlingError(Exception):
    """Raised when AWS Bedrock throttles requests"""
    pass


class BedrockClient:
    """
    AWS Bedrock client for Claude 4.5 Sonnet vision-based witness extraction.

    Handles image analysis, structured JSON output, and retry logic.
    """

    def __init__(
        self,
        model_id: Optional[str] = None,
        region: Optional[str] = None
    ):
        self.model_id = model_id or settings.bedrock_model_id
        self.region = region or settings.aws_region

        # Configure boto3 client with retries and extended timeout
        # Large PDFs with 40+ pages can take several minutes to process
        config = Config(
            region_name=self.region,
            retries={
                "max_attempts": 3,
                "mode": "adaptive"
            },
            read_timeout=600,  # 10 minutes for large document processing
            connect_timeout=30
        )

        self.client = boto3.client(
            service_name="bedrock-runtime",
            config=config,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

    def _build_messages(
        self,
        assets: List[ProcessedAsset],
        search_targets: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Build the messages array for Claude API"""
        content = []

        # Add images
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
                # Add text content for context
                content.append({
                    "type": "text",
                    "text": f"[Document: {asset.filename}]\n\n{asset.content.decode('utf-8', errors='replace')}"
                })

        # Add the extraction prompt
        if search_targets:
            targets_str = ", ".join(search_targets)
            prompt = f"""Analyze the provided document(s) and extract information about witnesses.

SPECIFIC TARGETS: Focus your analysis on these specific individuals: {targets_str}

If these target individuals are mentioned or depicted:
- Extract their full details (role, observations, contact info)
- Mark their importance as HIGH unless they are merely mentioned in passing

For other individuals present in the document:
- Only include them if they directly interact with the target individuals
- Mark their importance as LOW unless they provide significant testimony

Respond with valid JSON only."""
        else:
            prompt = """Analyze the provided document(s) and extract information about ALL witnesses and key individuals mentioned.

For each person identified:
- Extract their name, role, and relevance to the case
- Rate their importance (HIGH, MEDIUM, LOW) based on their testimony or involvement
- Include any contact information found

Respond with valid JSON only."""

        content.append({
            "type": "text",
            "text": prompt
        })

        return [{"role": "user", "content": content}]

    @retry(
        retry=retry_if_exception_type(BedrockThrottlingError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, min=4, max=120)
    )
    def _invoke_model(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Invoke the Bedrock model with retry logic"""
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 8192,
            "system": WITNESS_EXTRACTION_SYSTEM_PROMPT,
            "messages": messages
        }

        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body)
            )

            response_body = json.loads(response["body"].read())
            return response_body

        except self.client.exceptions.ThrottlingException as e:
            raise BedrockThrottlingError(str(e))

    def _parse_response(self, response: Dict[str, Any]) -> ExtractionResult:
        """Parse the Claude response into structured WitnessData"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Extract text content from response
            text_content = ""
            for block in response.get("content", []):
                if block.get("type") == "text":
                    text_content = block.get("text", "")
                    break

            # Log raw response length for debugging
            logger.info(f"Raw response length: {len(text_content)} chars")

            # Parse JSON
            try:
                data = json.loads(text_content)
            except json.JSONDecodeError as e:
                logger.warning(f"Initial JSON parse failed: {e}")

                # Try to extract JSON from the text
                import re
                json_match = re.search(r'\{[\s\S]*\}', text_content)
                if json_match:
                    json_text = json_match.group()
                    try:
                        data = json.loads(json_text)
                    except json.JSONDecodeError as e2:
                        # Try to fix common JSON errors
                        logger.warning(f"Regex JSON parse failed: {e2}, attempting repairs")

                        # Try to fix truncated JSON by finding last complete witness entry
                        # Look for the last complete "}" before the error
                        try:
                            # Find witnesses array and extract complete entries
                            witnesses_match = re.search(r'"witnesses"\s*:\s*\[([\s\S]*)', json_text)
                            if witnesses_match:
                                witnesses_content = witnesses_match.group(1)
                                # Find all complete witness objects
                                complete_witnesses = re.findall(r'\{[^{}]*\}', witnesses_content)
                                if complete_witnesses:
                                    fixed_json = '{"witnesses": [' + ','.join(complete_witnesses) + ']}'
                                    data = json.loads(fixed_json)
                                    logger.info(f"Recovered {len(complete_witnesses)} witnesses from malformed JSON")
                                else:
                                    raise e2
                            else:
                                raise e2
                        except Exception:
                            # Log a sample of the problematic JSON for debugging
                            logger.error(f"JSON repair failed. Sample (first 1000 chars): {json_text[:1000]}")
                            logger.error(f"JSON repair failed. Sample (last 500 chars): {json_text[-500:]}")
                            return ExtractionResult(
                                success=False,
                                witnesses=[],
                                raw_response=text_content[:2000],
                                error=f"Failed to parse JSON: {e2}"
                            )
                else:
                    logger.error(f"No JSON found in response. Sample: {text_content[:500]}")
                    return ExtractionResult(
                        success=False,
                        witnesses=[],
                        raw_response=text_content,
                        error="Failed to parse JSON from response"
                    )

            # Convert to WitnessData objects
            witnesses = []
            for w in data.get("witnesses", []):
                witnesses.append(WitnessData(
                    full_name=w.get("fullName", "Unknown"),
                    role=w.get("role", "other").lower(),
                    importance=w.get("importance", "LOW").upper(),
                    observation=w.get("observation"),
                    source_summary=w.get("sourceSummary") or w.get("sourceQuote"),  # Fallback for backwards compat
                    context=w.get("context"),
                    email=w.get("email"),
                    phone=w.get("phone"),
                    address=w.get("address"),
                    source_page=w.get("sourcePage"),
                    confidence_score=float(w.get("confidenceScore", 0.5))
                ))

            # Get token usage
            usage = response.get("usage", {})

            return ExtractionResult(
                success=True,
                witnesses=witnesses,
                raw_response=text_content,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0)
            )

        except Exception as e:
            return ExtractionResult(
                success=False,
                witnesses=[],
                raw_response=str(response),
                error=str(e)
            )

    async def extract_witnesses(
        self,
        assets: List[ProcessedAsset],
        search_targets: Optional[List[str]] = None
    ) -> ExtractionResult:
        """
        Extract witnesses from document assets using Claude vision.

        Args:
            assets: List of ProcessedAsset objects (images and text)
            search_targets: Optional list of specific names to search for

        Returns:
            ExtractionResult with list of WitnessData
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"extract_witnesses called with {len(assets)} assets, types: {[a.asset_type for a in assets]}")
        
        if not assets:
            logger.warning("No assets provided to extract_witnesses")
            return ExtractionResult(
                success=True,
                witnesses=[],
                error="No assets to process"
            )

        # Filter to only include image and text assets
        valid_assets = [
            a for a in assets
            if a.asset_type in ("image", "text", "email_body")
        ]

        if not valid_assets:
            return ExtractionResult(
                success=True,
                witnesses=[],
                error="No valid assets to process"
            )

        # Build messages
        messages = self._build_messages(valid_assets, search_targets)

        # Invoke model
        try:
            logger.info(f"Calling Bedrock model {self.model_id}...")
            response = self._invoke_model(messages)
            result = self._parse_response(response)
            logger.info(f"Bedrock returned {len(result.witnesses)} witnesses, success={result.success}, tokens={result.input_tokens}+{result.output_tokens}")
            return result
        except BedrockThrottlingError as e:
            return ExtractionResult(
                success=False,
                witnesses=[],
                error=f"Rate limited: {e}"
            )
        except Exception as e:
            return ExtractionResult(
                success=False,
                witnesses=[],
                error=str(e)
            )

    async def extract_witnesses_batched(
        self,
        assets: List[ProcessedAsset],
        search_targets: Optional[List[str]] = None,
        batch_size: int = 10
    ) -> List[ExtractionResult]:
        """
        Extract witnesses from a large set of assets in batches.

        Useful for multi-page PDFs or documents with many attachments.

        Args:
            assets: List of ProcessedAsset objects
            search_targets: Optional list of specific names to search for
            batch_size: Number of assets per batch (max images per request)

        Returns:
            List of ExtractionResult, one per batch
        """
        results = []

        # Group assets into batches
        for i in range(0, len(assets), batch_size):
            batch = assets[i:i + batch_size]
            result = await self.extract_witnesses(batch, search_targets)
            results.append(result)

        return results

    async def verify_witnesses(
        self,
        witnesses: List[WitnessData],
        document_filename: str
    ) -> List[WitnessData]:
        """
        Run a second AI pass to verify and improve witness data accuracy.

        Args:
            witnesses: List of extracted WitnessData to verify
            document_filename: Name of the source document

        Returns:
            List of verified/improved WitnessData
        """
        import logging
        logger = logging.getLogger(__name__)

        if not witnesses:
            return witnesses

        logger.info(f"Running verification pass on {len(witnesses)} witnesses")

        # Build verification prompt
        witness_json = json.dumps([{
            "fullName": w.full_name,
            "role": w.role,
            "importance": w.importance,
            "observation": w.observation,
            "sourceSummary": w.source_summary,
            "sourcePage": w.source_page,
            "email": w.email,
            "phone": w.phone,
            "address": w.address,
            "confidenceScore": w.confidence_score
        } for w in witnesses], indent=2)

        verification_prompt = f"""You are verifying and improving witness extraction accuracy. Review the following extracted witness data from document "{document_filename}" and improve it:

EXTRACTED DATA:
{witness_json}

Please verify and improve each witness entry:
1. **Names**: If a name appears incomplete, use "FNU" (First Name Unknown) or "LNU" (Last Name Unknown) appropriately
2. **Roles**: Verify the role is the most accurate and specific classification:
   - plaintiff, defendant, eyewitness, expert, attorney, paralegal
   - physician, nurse, medical_staff, police_officer, detective, investigator
   - family_member, employer, supervisor, coworker, colleague
   - friend, neighbor, acquaintance, insurance_adjuster, claims_representative
   - government_official, other
3. **Importance**: Verify HIGH/MEDIUM/LOW is accurate based on their involvement
4. **Duplicates**: If the same person appears multiple times with slight variations, consolidate into one entry with the most complete information
5. **Confidence**: Adjust confidence scores based on how certain the information is

Return the verified/improved list in the same JSON format.

CRITICAL: Respond ONLY with valid JSON:
{{"witnesses": [...]}}"""

        messages = [{
            "role": "user",
            "content": [{"type": "text", "text": verification_prompt}]
        }]

        try:
            response = self._invoke_model(messages)
            result = self._parse_response(response)

            if result.success and result.witnesses:
                logger.info(f"Verification complete: {len(result.witnesses)} witnesses after deduplication/improvement")
                return result.witnesses
            else:
                logger.warning(f"Verification failed, returning original witnesses: {result.error}")
                return witnesses

        except Exception as e:
            logger.error(f"Verification error: {e}, returning original witnesses")
            return witnesses
