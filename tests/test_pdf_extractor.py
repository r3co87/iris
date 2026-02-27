"""Tests for PdfExtractor — PDF text and metadata extraction."""

from __future__ import annotations

import pytest

from iris.pdf_extractor import PdfExtractor


def _create_test_pdf(
    text: str = "Hello World", title: str = "", author: str = ""
) -> bytes:
    """Create a simple test PDF with pymupdf."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    if title or author:
        doc.set_metadata({"title": title, "author": author})
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _create_multipage_pdf(pages: int = 3) -> bytes:
    """Create a multi-page test PDF."""
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1} content")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture
def extractor() -> PdfExtractor:
    return PdfExtractor()


class TestPdfExtractor:
    """Tests for PDF extraction."""

    @pytest.mark.asyncio
    async def test_extract_basic_text(self, extractor: PdfExtractor) -> None:
        """Should extract text from a simple PDF."""
        pdf = _create_test_pdf("Hello World")
        result = await extractor.extract(pdf)
        assert "Hello World" in result.text
        assert result.pages == 1

    @pytest.mark.asyncio
    async def test_extract_metadata_title(self, extractor: PdfExtractor) -> None:
        """Should extract title metadata."""
        pdf = _create_test_pdf("Content", title="My Title")
        result = await extractor.extract(pdf)
        assert result.title == "My Title"

    @pytest.mark.asyncio
    async def test_extract_metadata_author(self, extractor: PdfExtractor) -> None:
        """Should extract author metadata."""
        pdf = _create_test_pdf("Content", author="John Doe")
        result = await extractor.extract(pdf)
        assert result.author == "John Doe"

    @pytest.mark.asyncio
    async def test_extract_multipage(self, extractor: PdfExtractor) -> None:
        """Should extract text from multiple pages."""
        pdf = _create_multipage_pdf(3)
        result = await extractor.extract(pdf)
        assert result.pages == 3
        assert "Page 1" in result.text
        assert "Page 3" in result.text

    @pytest.mark.asyncio
    async def test_extract_empty_pdf(self, extractor: PdfExtractor) -> None:
        """Should handle empty PDF (no text)."""
        import fitz

        doc = fitz.open()
        doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()

        result = await extractor.extract(pdf_bytes)
        assert result.pages == 1
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_extract_invalid_bytes(self, extractor: PdfExtractor) -> None:
        """Should handle invalid PDF bytes gracefully."""
        result = await extractor.extract(b"not a pdf at all")
        assert result.pages == 0
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_extract_empty_bytes(self, extractor: PdfExtractor) -> None:
        """Should handle empty bytes gracefully."""
        result = await extractor.extract(b"")
        assert result.pages == 0
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_extract_no_metadata(self, extractor: PdfExtractor) -> None:
        """Should return None for missing metadata fields."""
        pdf = _create_test_pdf("Just text")
        result = await extractor.extract(pdf)
        assert result.title is None
        assert result.author is None

    @pytest.mark.asyncio
    async def test_extract_created_date_normalization(
        self, extractor: PdfExtractor
    ) -> None:
        """Should normalize D: prefix from creation dates."""
        import fitz

        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"creationDate": "D:20240115100000"})
        pdf_bytes = doc.tobytes()
        doc.close()

        result = await extractor.extract(pdf_bytes)
        if result.created_date:
            assert not result.created_date.startswith("D:")
