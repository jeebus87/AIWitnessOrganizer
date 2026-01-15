"""Test document processing service"""
import pytest
from PIL import Image
import io

from app.services.document_processor import DocumentProcessor, ProcessedAsset


@pytest.fixture
def processor():
    """Create document processor instance"""
    return DocumentProcessor()


def test_file_hash(processor):
    """Test file hash generation"""
    content = b"test content"
    hash1 = processor.get_file_hash(content)
    hash2 = processor.get_file_hash(content)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex length


def test_detect_file_type_from_content(processor):
    """Test file type detection from magic bytes"""
    # PNG magic bytes
    png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    assert processor.detect_file_type("test.unknown", png_content) == "png"

    # JPEG magic bytes
    jpg_content = b"\xFF\xD8\xFF" + b"\x00" * 100
    assert processor.detect_file_type("test.unknown", jpg_content) == "jpg"

    # PDF magic bytes
    pdf_content = b"%PDF-1.4" + b"\x00" * 100
    assert processor.detect_file_type("test.unknown", pdf_content) == "pdf"


def test_resize_and_compress_image(processor):
    """Test image resizing and compression"""
    # Create a large test image
    img = Image.new('RGB', (10000, 7000), color='blue')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=95)
    original_bytes = buffer.getvalue()

    # Resize
    processed_bytes, media_type = processor._resize_and_compress_image(original_bytes)

    # Check output
    assert media_type == "image/jpeg"
    assert len(processed_bytes) < len(original_bytes)

    # Verify dimensions
    result_img = Image.open(io.BytesIO(processed_bytes))
    assert result_img.width <= processor.MAX_IMAGE_DIMENSION
    assert result_img.height <= processor.MAX_IMAGE_DIMENSION


@pytest.mark.asyncio
async def test_process_image(processor):
    """Test processing an image file"""
    # Create test image
    img = Image.new('RGB', (100, 100), color='red')
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG')
    image_bytes = buffer.getvalue()

    result = await processor.process(image_bytes, "test.jpg")

    assert result.success
    assert len(result.assets) == 1
    assert result.assets[0].asset_type == "image"
    assert result.assets[0].media_type == "image/jpeg"
