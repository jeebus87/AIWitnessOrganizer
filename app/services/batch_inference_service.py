"""
AWS Bedrock Batch Inference Service for processing AI requests at scale.

Batch inference provides:
- Separate quotas from on-demand inference (no daily token limits)
- 50% cost savings compared to on-demand
- No real-time throttling
- Support for Claude Sonnet 4.5

Workflow:
1. Create JSONL input file with all requests
2. Upload to S3
3. Submit batch job to Bedrock
4. Poll for completion
5. Download and parse results from S3
"""

import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import boto3
from botocore.config import Config

from app.core.config import settings

logger = logging.getLogger(__name__)


class BatchInferenceService:
    """
    Service for AWS Bedrock Batch Inference operations.

    Handles the complete workflow for batch processing of AI requests:
    - JSONL input creation
    - S3 upload/download
    - Batch job submission and monitoring
    - Result parsing and extraction
    """

    # Default model for batch inference - Claude 4.5 REQUIRES cross-region inference profile
    DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"

    def __init__(self):
        """Initialize AWS clients for S3 and Bedrock."""
        self._s3_client = None
        self._bedrock_client = None

    @property
    def s3_client(self):
        """Get or create S3 client."""
        if self._s3_client is None:
            config = Config(
                region_name=settings.aws_region,
                retries={"max_attempts": 3, "mode": "adaptive"},
            )
            self._s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                config=config,
            )
        return self._s3_client

    @property
    def bedrock_client(self):
        """Get or create Bedrock client (not runtime - for batch job management)."""
        if self._bedrock_client is None:
            config = Config(
                region_name=settings.aws_region,
                retries={"max_attempts": 3, "mode": "adaptive"},
            )
            self._bedrock_client = boto3.client(
                "bedrock",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                config=config,
            )
        return self._bedrock_client

    @property
    def bucket(self) -> str:
        """Get the S3 bucket name for batch inference."""
        return settings.batch_s3_bucket

    @property
    def input_prefix(self) -> str:
        """Get the S3 prefix for input files."""
        return settings.batch_s3_input_prefix

    @property
    def output_prefix(self) -> str:
        """Get the S3 prefix for output files."""
        return settings.batch_s3_output_prefix

    def create_batch_record(
        self,
        record_id: str,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Dict[str, Any]:
        """
        Create a single batch inference record in JSONL format.

        Args:
            record_id: Unique identifier for this record (e.g., "item-123")
            system_prompt: System instructions for Claude
            user_message: User message/prompt
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            Dict representing one JSONL record for batch inference
        """
        return {
            "recordId": record_id,
            "modelInput": {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [
                    {
                        "role": "user",
                        "content": user_message
                    }
                ]
            }
        }

    def create_jsonl_content(self, records: List[Dict[str, Any]]) -> str:
        """
        Convert a list of batch records to JSONL string.

        Args:
            records: List of record dicts from create_batch_record()

        Returns:
            JSONL string with one record per line
        """
        lines = [json.dumps(record, ensure_ascii=False) for record in records]
        return "\n".join(lines)

    def upload_to_s3(self, content: str, key: str) -> str:
        """
        Upload JSONL content to S3.

        Args:
            content: JSONL string content
            key: S3 key (path within bucket)

        Returns:
            S3 URI (s3://bucket/key)
        """
        logger.info(f"Uploading batch input to s3://{self.bucket}/{key}")

        self.s3_client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode('utf-8'),
            ContentType='application/jsonl'
        )

        s3_uri = f"s3://{self.bucket}/{key}"
        logger.info(f"Upload complete: {s3_uri}")
        return s3_uri

    def submit_batch_job(
        self,
        input_s3_uri: str,
        output_s3_uri: str,
        job_name: str,
        model_id: str = None,
    ) -> Dict[str, Any]:
        """
        Submit a batch inference job to AWS Bedrock.

        Args:
            input_s3_uri: S3 URI for input JSONL file
            output_s3_uri: S3 URI prefix for output
            job_name: Human-readable job name
            model_id: Model to use (defaults to Claude Sonnet 4.5)

        Returns:
            Dict with job_arn and status
        """
        model_id = model_id or self.DEFAULT_MODEL_ID
        role_arn = settings.bedrock_batch_role_arn

        if not role_arn:
            raise ValueError("BEDROCK_BATCH_ROLE_ARN environment variable is not set")

        logger.info(f"Submitting batch job '{job_name}' with model {model_id}")
        logger.info(f"  Input: {input_s3_uri}")
        logger.info(f"  Output: {output_s3_uri}")
        logger.info(f"  Role: {role_arn}")

        try:
            response = self.bedrock_client.create_model_invocation_job(
                jobName=job_name,
                modelId=model_id,
                roleArn=role_arn,
                inputDataConfig={
                    "s3InputDataConfig": {
                        "s3Uri": input_s3_uri
                    }
                },
                outputDataConfig={
                    "s3OutputDataConfig": {
                        "s3Uri": output_s3_uri
                    }
                },
            )

            job_arn = response["jobArn"]
            logger.info(f"Batch job submitted successfully: {job_arn}")

            return {
                "job_arn": job_arn,
                "status": "Submitted",
                "input_uri": input_s3_uri,
                "output_uri": output_s3_uri,
            }

        except Exception as e:
            logger.error(f"Failed to submit batch job: {e}")
            raise

    def check_job_status(self, job_arn: str) -> Dict[str, Any]:
        """
        Check the status of a batch inference job.

        Args:
            job_arn: ARN of the batch job

        Returns:
            Dict with status, message, and output_uri (when completed)
        """
        try:
            response = self.bedrock_client.get_model_invocation_job(
                jobIdentifier=job_arn
            )

            status = response.get("status", "Unknown")
            message = response.get("message", "")

            # Get output URI if available
            output_uri = None
            output_config = response.get("outputDataConfig", {})
            if output_config:
                s3_config = output_config.get("s3OutputDataConfig", {})
                output_uri = s3_config.get("s3Uri")

            # Get statistics if available
            stats = response.get("statistics", {})
            input_tokens = stats.get("inputTokenCount", 0)
            output_tokens = stats.get("outputTokenCount", 0)

            result = {
                "status": status,
                "message": message,
                "output_uri": output_uri,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

            # Add timing info if available
            if "submittedAt" in response:
                result["submitted_at"] = response["submittedAt"]
            if "endTime" in response:
                result["end_time"] = response["endTime"]

            logger.debug(f"Job {job_arn} status: {status}")
            return result

        except Exception as e:
            logger.error(f"Failed to check job status for {job_arn}: {e}")
            raise

    def _parse_s3_uri(self, s3_uri: str) -> Tuple[str, str]:
        """
        Parse an S3 URI into bucket and key.

        Args:
            s3_uri: S3 URI (s3://bucket/key/path)

        Returns:
            Tuple of (bucket, key)
        """
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {s3_uri}")

        path = s3_uri[5:]  # Remove "s3://"
        parts = path.split("/", 1)

        if len(parts) < 2:
            raise ValueError(f"Invalid S3 URI (no key): {s3_uri}")

        return parts[0], parts[1]

    def download_from_s3(self, s3_uri: str) -> str:
        """
        Download content from S3.

        Args:
            s3_uri: S3 URI to download

        Returns:
            File content as string
        """
        bucket, key = self._parse_s3_uri(s3_uri)

        logger.info(f"Downloading from s3://{bucket}/{key}")

        response = self.s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')

        logger.info(f"Downloaded {len(content)} bytes")
        return content

    def list_output_files(self, output_s3_uri: str) -> List[str]:
        """
        List all output files from a batch job.

        Batch jobs create output files with suffixes like .jsonl.out

        Args:
            output_s3_uri: S3 URI prefix for output

        Returns:
            List of full S3 URIs for output files
        """
        bucket, prefix = self._parse_s3_uri(output_s3_uri)

        # Ensure prefix ends with /
        if not prefix.endswith('/'):
            prefix += '/'

        logger.info(f"Listing output files in s3://{bucket}/{prefix}")

        response = self.s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=prefix
        )

        files = []
        for obj in response.get('Contents', []):
            key = obj['Key']
            # Only include JSONL output files
            if key.endswith('.jsonl.out') or key.endswith('.jsonl'):
                files.append(f"s3://{bucket}/{key}")

        logger.info(f"Found {len(files)} output files")
        return files

    def parse_batch_output(self, output_content: str) -> Dict[str, Any]:
        """
        Parse JSONL output from a completed batch job.

        Args:
            output_content: JSONL string content from output file

        Returns:
            Dict mapping recordId to parsed output
        """
        results = {}

        for line in output_content.strip().split('\n'):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
                record_id = record.get("recordId", "unknown")

                # Check for errors
                if record.get("error"):
                    results[record_id] = {
                        "error": True,
                        "error_message": record.get("error", {}).get("message", "Unknown error"),
                        "error_code": record.get("error", {}).get("code", ""),
                    }
                    continue

                # Extract model output
                model_output = record.get("modelOutput", {})
                content_blocks = model_output.get("content", [])

                # Extract text from content blocks
                text = ""
                for block in content_blocks:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        break

                results[record_id] = {
                    "content": text,
                    "stop_reason": model_output.get("stop_reason"),
                    "usage": model_output.get("usage", {}),
                }

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse output line: {e}")
                continue

        logger.info(f"Parsed {len(results)} records from batch output")
        return results

    def download_and_parse_results(self, output_s3_uri: str) -> Dict[str, Any]:
        """
        Download and parse all results from a completed batch job.

        Args:
            output_s3_uri: S3 URI prefix for output

        Returns:
            Dict mapping recordId to parsed output
        """
        # List all output files
        output_files = self.list_output_files(output_s3_uri)

        if not output_files:
            logger.warning(f"No output files found at {output_s3_uri}")
            return {}

        # Download and parse each file
        all_results = {}

        for file_uri in output_files:
            try:
                content = self.download_from_s3(file_uri)
                file_results = self.parse_batch_output(content)
                all_results.update(file_results)
            except Exception as e:
                logger.error(f"Failed to process output file {file_uri}: {e}")

        logger.info(f"Total: {len(all_results)} records parsed from {len(output_files)} files")
        return all_results

    def generate_job_name(self, job_type: str, job_id: int) -> str:
        """
        Generate a unique job name for a batch job.

        Args:
            job_type: Type of job (witness-extraction, legal-research)
            job_id: ID of the processing job

        Returns:
            Job name string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{job_type}-{job_id}-{timestamp}"

    def generate_input_key(self, job_type: str, job_id: int) -> str:
        """
        Generate S3 key for input file.

        Args:
            job_type: Type of job
            job_id: ID of the processing job

        Returns:
            S3 key string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.input_prefix}{job_type}_{job_id}_{timestamp}.jsonl"

    def generate_output_uri(self, job_type: str, job_id: int) -> str:
        """
        Generate S3 URI for output location.

        Args:
            job_type: Type of job
            job_id: ID of the processing job

        Returns:
            S3 URI string
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"s3://{self.bucket}/{self.output_prefix}{job_type}_{job_id}_{timestamp}/"


# Singleton instance
_batch_service: Optional[BatchInferenceService] = None


def get_batch_inference_service() -> BatchInferenceService:
    """Get or create BatchInferenceService singleton."""
    global _batch_service
    if _batch_service is None:
        _batch_service = BatchInferenceService()
    return _batch_service
