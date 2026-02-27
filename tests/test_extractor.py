"""Tests for ContentExtractor — HTML to clean text, metadata, and links."""

from __future__ import annotations

import pytest

from iris.config import Settings
from iris.extractor import ContentExtractor
from iris.schemas import PageMetadata


@pytest.fixture
def extractor() -> ContentExtractor:
    settings = Settings(MAX_CONTENT_LENGTH=10000, TESTING_MODE=True)
    return ContentExtractor(settings)


class TestExtractText:
    """Tests for text extraction."""

    def test_extract_text_from_article(
        self, extractor: ContentExtractor, sample_html: str
    ) -> None:
        """Should extract clean text from a standard article page."""
        text = extractor.extract_text(sample_html)
        assert "Test Article Title" in text
        assert "first paragraph" in text
        assert "second paragraph" in text

    def test_extract_text_removes_scripts(
        self, extractor: ContentExtractor, sample_html: str
    ) -> None:
        """Should remove script tags from extracted text."""
        text = extractor.extract_text(sample_html)
        assert "console.log" not in text
        assert "should be removed" not in text

    def test_extract_text_removes_styles(
        self, extractor: ContentExtractor, sample_html: str
    ) -> None:
        """Should remove style tags from extracted text."""
        text = extractor.extract_text(sample_html)
        assert ".hidden" not in text
        assert "display: none" not in text

    def test_extract_text_empty_html(self, extractor: ContentExtractor) -> None:
        """Should return empty string for empty HTML."""
        assert extractor.extract_text("") == ""

    def test_extract_text_minimal_html(self, extractor: ContentExtractor) -> None:
        """Should handle minimal HTML."""
        html = "<html><body><p>Hello World</p></body></html>"
        text = extractor.extract_text(html)
        assert "Hello World" in text

    def test_extract_text_broken_html(self, extractor: ContentExtractor) -> None:
        """Should handle broken/malformed HTML gracefully."""
        html = "<p>Unclosed paragraph<div>Mixed tags</p></div><b>Bold"
        text = extractor.extract_text(html)
        assert "Unclosed paragraph" in text
        assert "Mixed tags" in text

    def test_extract_text_truncation(self) -> None:
        """Should truncate text to MAX_CONTENT_LENGTH."""
        settings = Settings(MAX_CONTENT_LENGTH=50, TESTING_MODE=True)
        extractor = ContentExtractor(settings)
        html = f"<html><body><p>{'A' * 200}</p></body></html>"
        text = extractor.extract_text(html)
        assert len(text) <= 50

    def test_extract_text_spa_like(self, extractor: ContentExtractor) -> None:
        """Should handle SPA-like pages with minimal server HTML."""
        html = """<!DOCTYPE html>
<html><head><title>SPA App</title></head>
<body>
    <div id="root">
        <div class="content">
            <h1>Dynamic Content</h1>
            <p>This was rendered by JavaScript.</p>
        </div>
    </div>
    <script src="/app.js"></script>
</body></html>"""
        text = extractor.extract_text(html)
        assert "Dynamic Content" in text
        assert "rendered by JavaScript" in text

    def test_extract_text_unicode(self, extractor: ContentExtractor) -> None:
        """Should handle Unicode content correctly."""
        html = "<html><body><p>Ünïcödé: 日本語テスト &amp; Ёмоджи 🎉</p></body></html>"
        text = extractor.extract_text(html)
        assert "Ünïcödé" in text
        assert "日本語テスト" in text

    def test_extract_text_with_tables(self, extractor: ContentExtractor) -> None:
        """Should extract text from tables."""
        html = """<html><body>
<table><tr><td>Cell 1</td><td>Cell 2</td></tr>
<tr><td>Cell 3</td><td>Cell 4</td></tr></table>
</body></html>"""
        text = extractor.extract_text(html)
        assert "Cell 1" in text
        assert "Cell 4" in text


class TestExtractMetadata:
    """Tests for metadata extraction."""

    def test_extract_metadata_full(
        self, extractor: ContentExtractor, sample_html: str
    ) -> None:
        """Should extract all metadata fields from a complete page."""
        meta = extractor.extract_metadata(sample_html, "https://example.com/article")
        assert meta.title == "Test Article Title"
        assert meta.description == "A test article description"
        assert meta.og_title == "OG Test Title"
        assert meta.og_description == "OG test description"
        assert meta.og_image == "https://example.com/images/og.png"
        assert meta.language == "en"
        assert meta.canonical_url == "https://example.com/article"
        assert meta.author == "Test Author"
        assert meta.published_date == "2024-01-15T10:00:00Z"

    def test_extract_metadata_empty_html(self, extractor: ContentExtractor) -> None:
        """Should return empty metadata for empty HTML."""
        meta = extractor.extract_metadata("", "https://example.com")
        assert meta == PageMetadata()

    def test_extract_metadata_minimal(self, extractor: ContentExtractor) -> None:
        """Should handle pages with minimal metadata."""
        html = "<html><head><title>Only Title</title></head><body></body></html>"
        meta = extractor.extract_metadata(html, "https://example.com")
        assert meta.title == "Only Title"
        assert meta.description is None
        assert meta.og_title is None

    def test_extract_metadata_relative_og_image(
        self, extractor: ContentExtractor
    ) -> None:
        """Should resolve relative OG image URLs."""
        html = """<html><head>
        <meta property="og:image" content="/img/test.jpg">
        </head><body></body></html>"""
        meta = extractor.extract_metadata(html, "https://example.com/page")
        assert meta.og_image == "https://example.com/img/test.jpg"

    def test_extract_metadata_published_date_time_tag(
        self, extractor: ContentExtractor
    ) -> None:
        """Should extract published date from <time> tag."""
        html = """<html><body>
        <time datetime="2024-06-15T08:00:00Z">June 15, 2024</time>
        </body></html>"""
        meta = extractor.extract_metadata(html, "https://example.com")
        assert meta.published_date == "2024-06-15T08:00:00Z"


class TestExtractLinks:
    """Tests for link extraction."""

    def test_extract_links_basic(
        self, extractor: ContentExtractor, sample_html: str
    ) -> None:
        """Should extract all links from a page."""
        links = extractor.extract_links(sample_html, "https://example.com/article")
        assert len(links) >= 3

    def test_extract_links_internal_external(
        self, extractor: ContentExtractor, sample_html: str
    ) -> None:
        """Should classify links as internal or external."""
        links = extractor.extract_links(sample_html, "https://example.com/article")
        urls = {link.url: link for link in links}

        # Internal link
        internal = urls.get("https://example.com/internal-page")
        assert internal is not None
        assert internal.is_external is False

        # External link
        external = urls.get("https://external.com/page")
        assert external is not None
        assert external.is_external is True

    def test_extract_links_absolute_resolution(
        self, extractor: ContentExtractor
    ) -> None:
        """Should resolve relative URLs to absolute."""
        html = '<html><body><a href="/about">About</a></body></html>'
        links = extractor.extract_links(html, "https://example.com/page")
        assert links[0].url == "https://example.com/about"

    def test_extract_links_skip_special(self, extractor: ContentExtractor) -> None:
        """Should skip javascript:, mailto:, tel: and anchor links."""
        html = """<html><body>
        <a href="javascript:void(0)">JS Link</a>
        <a href="mailto:test@example.com">Email</a>
        <a href="tel:+1234567890">Phone</a>
        <a href="#section">Anchor</a>
        <a href="https://real.com/page">Real Link</a>
        </body></html>"""
        links = extractor.extract_links(html, "https://example.com")
        assert len(links) == 1
        assert links[0].url == "https://real.com/page"

    def test_extract_links_empty_html(self, extractor: ContentExtractor) -> None:
        """Should return empty list for empty HTML."""
        links = extractor.extract_links("", "https://example.com")
        assert links == []

    def test_extract_links_deduplication(self, extractor: ContentExtractor) -> None:
        """Should deduplicate links with the same URL."""
        html = """<html><body>
        <a href="https://example.com/page">First</a>
        <a href="https://example.com/page">Second</a>
        </body></html>"""
        links = extractor.extract_links(html, "https://example.com")
        assert len(links) == 1

    def test_extract_links_text_truncation(self, extractor: ContentExtractor) -> None:
        """Should truncate very long link text."""
        long_text = "A" * 300
        html = (
            f'<html><body><a href="https://example.com">{long_text}</a></body></html>'
        )
        links = extractor.extract_links(html, "https://example.com")
        assert len(links[0].text) <= 200
