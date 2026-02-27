"""PDF text and metadata extraction using pymupdf (fitz)."""

from __future__ import annotations

from iris.logging import get_logger
from iris.schemas import PdfResult

logger = get_logger(__name__)


class PdfExtractor:
    """Extract text and metadata from PDF bytes."""

    async def extract(self, pdf_bytes: bytes) -> PdfResult:
        """Extract text and metadata from PDF bytes.

        Args:
            pdf_bytes: Raw PDF file content.

        Returns:
            PdfResult with extracted text, page count, and metadata.
        """
        import fitz

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.error("Failed to open PDF: %s", e)
            return PdfResult(text="", pages=0)

        try:
            pages = len(doc)
            text_parts: list[str] = []
            for page in doc:
                text_parts.append(page.get_text())

            text = "\n".join(text_parts).strip()

            meta = doc.metadata or {}
            title = meta.get("title") or None
            author = meta.get("author") or None
            created_date = meta.get("creationDate") or None

            # pymupdf dates look like "D:20240115100000" — normalize
            if created_date and created_date.startswith("D:"):
                created_date = created_date[2:]

            return PdfResult(
                text=text,
                pages=pages,
                title=title if title else None,
                author=author if author else None,
                created_date=created_date if created_date else None,
            )
        finally:
            doc.close()
