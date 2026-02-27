"""Tests for structured data extraction — JSON-LD and Schema.org."""

from __future__ import annotations

import pytest

from iris.config import Settings
from iris.extractor import ContentExtractor


@pytest.fixture
def extractor() -> ContentExtractor:
    settings = Settings(MAX_CONTENT_LENGTH=10000, TESTING_MODE=True)
    return ContentExtractor(settings)


HTML_WITH_JSON_LD = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "Test Article",
    "author": {"@type": "Person", "name": "John Doe"}
}
</script>
</head><body><p>Content</p></body></html>"""

HTML_WITH_MULTIPLE_JSON_LD = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Article", "headline": "Test"}
</script>
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": []}
</script>
</head><body><p>Content</p></body></html>"""

HTML_WITH_JSON_LD_ARRAY = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
[
    {"@context": "https://schema.org", "@type": "Article", "headline": "Test"},
    {"@context": "https://schema.org", "@type": "WebPage", "name": "Page"}
]
</script>
</head><body><p>Content</p></body></html>"""

HTML_WITH_MICRODATA = """<!DOCTYPE html>
<html><body>
<div itemscope itemtype="https://schema.org/Product">
    <span itemprop="name">Widget</span>
    <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
        <span itemprop="price">9.99</span>
    </div>
</div>
</body></html>"""

HTML_WITH_INVALID_JSON_LD = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{invalid json here}
</script>
<script type="application/ld+json">
{"@type": "Article", "headline": "Valid"}
</script>
</head><body></body></html>"""

HTML_NO_STRUCTURED_DATA = """<!DOCTYPE html>
<html><body><p>Just plain content</p></body></html>"""

HTML_MULTI_TYPE_JSON_LD = """<!DOCTYPE html>
<html><head>
<script type="application/ld+json">
{
    "@context": "https://schema.org",
    "@type": ["Article", "NewsArticle"],
    "headline": "Multi"
}
</script>
</head><body></body></html>"""


class TestStructuredDataExtraction:
    """Tests for JSON-LD and Schema.org extraction."""

    def test_extract_json_ld_article(self, extractor: ContentExtractor) -> None:
        """Should extract JSON-LD Article data."""
        result = extractor.extract_structured_data(HTML_WITH_JSON_LD)
        assert result is not None
        assert result.json_ld is not None
        assert len(result.json_ld) == 1
        assert result.json_ld[0]["@type"] == "Article"
        assert result.json_ld[0]["headline"] == "Test Article"

    def test_extract_multiple_json_ld(self, extractor: ContentExtractor) -> None:
        """Should extract multiple JSON-LD blocks."""
        result = extractor.extract_structured_data(HTML_WITH_MULTIPLE_JSON_LD)
        assert result is not None
        assert result.json_ld is not None
        assert len(result.json_ld) == 2
        types = [item["@type"] for item in result.json_ld]
        assert "Article" in types
        assert "BreadcrumbList" in types

    def test_extract_json_ld_array(self, extractor: ContentExtractor) -> None:
        """Should handle JSON-LD arrays."""
        result = extractor.extract_structured_data(HTML_WITH_JSON_LD_ARRAY)
        assert result is not None
        assert result.json_ld is not None
        assert len(result.json_ld) == 2

    def test_extract_schema_org_types(self, extractor: ContentExtractor) -> None:
        """Should extract @type from JSON-LD."""
        result = extractor.extract_structured_data(HTML_WITH_JSON_LD)
        assert result is not None
        assert result.schema_org_types is not None
        assert "Article" in result.schema_org_types

    def test_extract_microdata(self, extractor: ContentExtractor) -> None:
        """Should extract Schema.org types from microdata."""
        result = extractor.extract_structured_data(HTML_WITH_MICRODATA)
        assert result is not None
        assert result.schema_org_types is not None
        assert "Product" in result.schema_org_types
        assert "Offer" in result.schema_org_types

    def test_invalid_json_ld_skipped(self, extractor: ContentExtractor) -> None:
        """Should skip invalid JSON-LD and extract valid ones."""
        result = extractor.extract_structured_data(HTML_WITH_INVALID_JSON_LD)
        assert result is not None
        assert result.json_ld is not None
        assert len(result.json_ld) == 1
        assert result.json_ld[0]["headline"] == "Valid"

    def test_no_structured_data(self, extractor: ContentExtractor) -> None:
        """Should return None when no structured data found."""
        result = extractor.extract_structured_data(HTML_NO_STRUCTURED_DATA)
        assert result is None

    def test_empty_html(self, extractor: ContentExtractor) -> None:
        """Should return None for empty HTML."""
        result = extractor.extract_structured_data("")
        assert result is None

    def test_multi_type_json_ld(self, extractor: ContentExtractor) -> None:
        """Should handle @type as array."""
        result = extractor.extract_structured_data(HTML_MULTI_TYPE_JSON_LD)
        assert result is not None
        assert result.schema_org_types is not None
        assert "Article" in result.schema_org_types
        assert "NewsArticle" in result.schema_org_types

    def test_schema_org_types_sorted(self, extractor: ContentExtractor) -> None:
        """Schema.org types should be sorted."""
        result = extractor.extract_structured_data(HTML_WITH_MICRODATA)
        assert result is not None
        assert result.schema_org_types is not None
        assert result.schema_org_types == sorted(result.schema_org_types)
