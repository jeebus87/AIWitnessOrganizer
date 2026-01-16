"""Document processing service for PDFs, images, and Outlook emails"""
import os
import io
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
import hashlib

from PIL import Image
import extract_msg

try:
    from pdf2image import convert_from_bytes
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False


@dataclass
class ProcessedAsset:
    """Represents a processed document asset ready for AI analysis"""
    asset_type: str  # "image", "text", "email_body"
    content: bytes  # Image bytes or text encoded as bytes
    media_type: str  # "image/jpeg", "image/png", "text/plain"
    filename: str
    original_filename: str
    parent_filename: Optional[str] = None
    context: str = ""  # Additional context (e.g., "Attachment to email from X")
    page_number: Optional[int] = None  # For multi-page PDFs


@dataclass
class ProcessingResult:
    """Result of processing a document"""
    success: bool
    assets: List[ProcessedAsset] = field(default_factory=list)
    error: Optional[str] = None
    file_hash: Optional[str] = None


class DocumentProcessor:
    """
    Processes various document types into assets ready for AI analysis.
    Supports PDFs, images, and Outlook .msg/.eml files with recursive extraction.
    """

    # Image constraints for AWS Bedrock
    MAX_IMAGE_SIZE_MB = 3.75
    MAX_IMAGE_DIMENSION = 8000
    SUPPORTED_IMAGE_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    SUPPORTED_DOC_FORMATS = {".pdf", ".msg", ".eml"}

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or tempfile.gettempdir()

    def get_file_hash(self, content: bytes) -> str:
        """Calculate SHA-256 hash of file content for caching"""
        return hashlib.sha256(content).hexdigest()

    def detect_file_type(self, filename: str, content: bytes) -> str:
        """Detect file type from extension and content"""
        ext = Path(filename).suffix.lower()

        # Check magic bytes for common formats
        if content[:4] == b"%PDF":
            return "pdf"
        elif content[:8] == b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1":  # OLE compound
            return "msg"
        elif content[:4] == b"\x89PNG":
            return "png"
        elif content[:2] == b"\xFF\xD8":
            return "jpg"
        elif ext in self.SUPPORTED_IMAGE_FORMATS:
            return ext.lstrip(".")

        return ext.lstrip(".") or "unknown"

    async def process(
        self,
        content: bytes,
        filename: str,
        context: str = ""
    ) -> ProcessingResult:
        """
        Process a document and return assets ready for AI analysis.

        Args:
            content: Raw file bytes
            filename: Original filename
            context: Additional context for nested files

        Returns:
            ProcessingResult with list of ProcessedAssets
        """
        file_hash = self.get_file_hash(content)
        file_type = self.detect_file_type(filename, content)

        try:
            if file_type in ("jpg", "jpeg", "png", "gif", "webp"):
                assets = await self._process_image(content, filename, context)
            elif file_type == "pdf":
                assets = await self._process_pdf(content, filename, context)
            elif file_type == "msg":
                assets = await self._process_msg(content, filename, context)
            elif file_type == "eml":
                assets = await self._process_eml(content, filename, context)
            else:
                return ProcessingResult(
                    success=False,
                    error=f"Unsupported file type: {file_type}",
                    file_hash=file_hash
                )

            return ProcessingResult(
                success=True,
                assets=assets,
                file_hash=file_hash
            )

        except Exception as e:
            return ProcessingResult(
                success=False,
                error=str(e),
                file_hash=file_hash
            )

    async def _process_image(
        self,
        content: bytes,
        filename: str,
        context: str = ""
    ) -> List[ProcessedAsset]:
        """Process an image file, resizing if necessary"""
        processed_bytes, media_type = self._resize_and_compress_image(content)

        return [ProcessedAsset(
            asset_type="image",
            content=processed_bytes,
            media_type=media_type,
            filename=filename,
            original_filename=filename,
            context=context
        )]

    async def _process_pdf(
        self,
        content: bytes,
        filename: str,
        context: str = ""
    ) -> List[ProcessedAsset]:
        """Convert PDF pages to images - processes one page at a time to save memory"""
        if not PDF2IMAGE_AVAILABLE:
            raise ImportError("pdf2image not available. Install poppler.")

        import gc

        assets = []
        page_number = 1

        # Process one page at a time to avoid memory exhaustion
        # first_page and last_page are 1-indexed in pdf2image
        while True:
            try:
                # Convert single page at lower DPI to reduce memory usage
                images = convert_from_bytes(
                    content,
                    dpi=100,  # Reduced from 150 to save memory
                    first_page=page_number,
                    last_page=page_number
                )

                if not images:
                    break

                image = images[0]

                # Convert PIL Image to bytes
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=80, optimize=True)
                image_bytes = buffer.getvalue()

                # Explicitly close and delete image to free memory
                image.close()
                del image
                del images
                buffer.close()

                # Resize if needed
                processed_bytes, media_type = self._resize_and_compress_image(image_bytes)
                del image_bytes

                assets.append(ProcessedAsset(
                    asset_type="image",
                    content=processed_bytes,
                    media_type=media_type,
                    filename=f"{filename}_page_{page_number}.jpg",
                    original_filename=filename,
                    context=context,
                    page_number=page_number
                ))

                page_number += 1

                # Force garbage collection every few pages
                if page_number % 5 == 0:
                    gc.collect()

            except Exception as e:
                # If we get an error (e.g., page out of range), we're done
                if "page" in str(e).lower() or page_number > 1:
                    break
                raise

        # Final garbage collection
        gc.collect()

        return assets

    async def _process_msg(
        self,
        content: bytes,
        filename: str,
        context: str = ""
    ) -> List[ProcessedAsset]:
        """
        Process Outlook .msg file recursively.
        Extracts email body and all attachments (including nested emails).
        """
        assets = []

        # Save to temp file (extract-msg requires file path)
        with tempfile.NamedTemporaryFile(
            suffix=".msg",
            dir=self.temp_dir,
            delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            msg = extract_msg.Message(tmp_path)

            # Extract email metadata and body
            email_text = self._format_email_body(msg)
            assets.append(ProcessedAsset(
                asset_type="email_body",
                content=email_text.encode("utf-8"),
                media_type="text/plain",
                filename=f"{filename}.txt",
                original_filename=filename,
                context=context
            ))

            # Process attachments
            for attachment in msg.attachments:
                try:
                    att_filename = attachment.longFilename or attachment.shortFilename or "unknown"
                    att_content = attachment.data

                    if att_content is None:
                        continue

                    # Determine attachment context
                    att_context = f"Attachment to email: {msg.subject or filename}"
                    if context:
                        att_context = f"{context} > {att_context}"

                    # Recursive processing for nested emails
                    att_ext = Path(att_filename).suffix.lower()
                    if att_ext in (".msg", ".eml"):
                        nested_result = await self.process(
                            att_content,
                            att_filename,
                            att_context
                        )
                        if nested_result.success:
                            for asset in nested_result.assets:
                                asset.parent_filename = filename
                            assets.extend(nested_result.assets)
                    elif att_ext in self.SUPPORTED_IMAGE_FORMATS or att_ext == ".pdf":
                        nested_result = await self.process(
                            att_content,
                            att_filename,
                            att_context
                        )
                        if nested_result.success:
                            for asset in nested_result.assets:
                                asset.parent_filename = filename
                            assets.extend(nested_result.assets)

                except Exception as e:
                    # Log but don't fail entire processing
                    print(f"Failed to process attachment {att_filename}: {e}")
                    continue

            msg.close()

        finally:
            # Clean up temp file
            os.unlink(tmp_path)

        return assets

    async def _process_eml(
        self,
        content: bytes,
        filename: str,
        context: str = ""
    ) -> List[ProcessedAsset]:
        """Process .eml email file"""
        import email
        from email import policy

        assets = []
        msg = email.message_from_bytes(content, policy=policy.default)

        # Extract email body
        email_text = self._format_email_body_from_eml(msg)
        assets.append(ProcessedAsset(
            asset_type="email_body",
            content=email_text.encode("utf-8"),
            media_type="text/plain",
            filename=f"{filename}.txt",
            original_filename=filename,
            context=context
        ))

        # Process attachments
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue

            att_filename = part.get_filename()
            if not att_filename:
                continue

            att_content = part.get_payload(decode=True)
            if not att_content:
                continue

            att_context = f"Attachment to email: {msg.get('subject', filename)}"
            if context:
                att_context = f"{context} > {att_context}"

            att_ext = Path(att_filename).suffix.lower()
            if att_ext in (".msg", ".eml") or att_ext in self.SUPPORTED_IMAGE_FORMATS or att_ext == ".pdf":
                nested_result = await self.process(att_content, att_filename, att_context)
                if nested_result.success:
                    for asset in nested_result.assets:
                        asset.parent_filename = filename
                    assets.extend(nested_result.assets)

        return assets

    def _format_email_body(self, msg) -> str:
        """Format extract-msg Message into text"""
        parts = [
            f"From: {msg.sender or 'Unknown'}",
            f"To: {msg.to or 'Unknown'}",
            f"CC: {msg.cc or ''}" if msg.cc else None,
            f"Date: {msg.date or 'Unknown'}",
            f"Subject: {msg.subject or 'No Subject'}",
            "",
            msg.body or ""
        ]
        return "\n".join(p for p in parts if p is not None)

    def _format_email_body_from_eml(self, msg) -> str:
        """Format email.message.Message into text"""
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

        parts = [
            f"From: {msg.get('from', 'Unknown')}",
            f"To: {msg.get('to', 'Unknown')}",
            f"CC: {msg.get('cc', '')}" if msg.get("cc") else None,
            f"Date: {msg.get('date', 'Unknown')}",
            f"Subject: {msg.get('subject', 'No Subject')}",
            "",
            body
        ]
        return "\n".join(p for p in parts if p is not None)

    def _resize_and_compress_image(
        self,
        image_bytes: bytes,
        max_size_mb: float = None,
        max_dimension: int = None
    ) -> Tuple[bytes, str]:
        """
        Resize and compress image to meet AWS Bedrock constraints.

        Args:
            image_bytes: Raw image bytes
            max_size_mb: Maximum file size in MB
            max_dimension: Maximum width or height

        Returns:
            Tuple of (processed bytes, media type)
        """
        max_size_mb = max_size_mb or self.MAX_IMAGE_SIZE_MB
        max_dimension = max_dimension or self.MAX_IMAGE_DIMENSION
        max_size_bytes = int(max_size_mb * 1024 * 1024)

        img = Image.open(io.BytesIO(image_bytes))

        # Resize if dimensions exceed limit
        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

        # Determine format
        original_format = img.format or "JPEG"
        if original_format.upper() in ("JPEG", "JPG"):
            media_type = "image/jpeg"
            save_format = "JPEG"
        elif original_format.upper() == "PNG":
            media_type = "image/png"
            save_format = "PNG"
        elif original_format.upper() == "WEBP":
            media_type = "image/webp"
            save_format = "WEBP"
        else:
            media_type = "image/jpeg"
            save_format = "JPEG"
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

        # Compress if needed
        buffer = io.BytesIO()

        if save_format in ("JPEG", "WEBP"):
            quality = 95
            while quality > 10:
                buffer.seek(0)
                buffer.truncate()
                img.save(buffer, format=save_format, quality=quality, optimize=True)
                if buffer.tell() <= max_size_bytes:
                    break
                quality -= 5
        else:
            img.save(buffer, format=save_format, optimize=True)

        return buffer.getvalue(), media_type
