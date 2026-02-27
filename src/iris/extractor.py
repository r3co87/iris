"""Content extraction from HTML — clean text, metadata, and links."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from iris.config import Settings
from iris.logging import get_logger
from iris.schemas import ExtractedLink, PageMetadata

logger = get_logger(__name__)


class ContentExtractor:
    """Extracts clean text, metadata, and links from HTML."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract_text(self, html: str) -> str:
        """Extract clean text from HTML.

        Removes scripts, styles, nav, footer, and other non-content elements.
        Uses trafilatura for best-in-class extraction with BS4 as fallback.

        Args:
            html: Raw HTML content.

        Returns:
            Clean text content, truncated to MAX_CONTENT_LENGTH.
        """
        if not html:
            return ""

        # Try trafilatura first for best content extraction
        try:
            import trafilatura

            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
                favor_recall=True,
            )
            if text:
                return self._truncate(text)
        except Exception:
            logger.debug("trafilatura extraction failed, using BS4 fallback")

        # Fallback: BeautifulSoup
        return self._extract_text_bs4(html)

    def _extract_text_bs4(self, html: str) -> str:
        """Fallback text extraction using BeautifulSoup."""
        soup = BeautifulSoup(html, "lxml")

        # Remove non-content elements
        for tag_name in [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
            "noscript",
            "iframe",
            "svg",
        ]:
            for element in soup.find_all(tag_name):
                element.decompose()

        # Get text with newlines between blocks
        text = soup.get_text(separator="\n", strip=True)

        # Clean up excessive whitespace
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(line for line in lines if line)

        return self._truncate(text)

    def extract_metadata(self, html: str, url: str) -> PageMetadata:
        """Extract metadata from HTML.

        Args:
            html: Raw HTML content.
            url: Page URL for resolving relative URLs.

        Returns:
            PageMetadata with title, description, OG tags, etc.
        """
        if not html:
            return PageMetadata()

        soup = BeautifulSoup(html, "lxml")

        return PageMetadata(
            title=self._get_title(soup),
            description=self._get_meta_content(soup, "description"),
            og_title=self._get_og_tag(soup, "og:title"),
            og_description=self._get_og_tag(soup, "og:description"),
            og_image=self._resolve_url(self._get_og_tag(soup, "og:image"), url),
            language=self._get_language(soup),
            canonical_url=self._get_canonical(soup, url),
            author=self._get_meta_content(soup, "author"),
            published_date=self._get_published_date(soup),
        )

    def extract_links(self, html: str, url: str) -> list[ExtractedLink]:
        """Extract all links from HTML.

        Args:
            html: Raw HTML content.
            url: Page URL for resolving relative URLs and classifying links.

        Returns:
            List of extracted links with text and external classification.
        """
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(url).netloc
        links: list[ExtractedLink] = []
        seen_urls: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            if not isinstance(anchor, Tag):
                continue

            href = str(anchor.get("href", ""))
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue

            absolute_url = urljoin(url, href)
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)

            link_text = anchor.get_text(strip=True) or ""
            link_domain = urlparse(absolute_url).netloc
            is_external = link_domain != base_domain

            links.append(
                ExtractedLink(
                    url=absolute_url,
                    text=link_text[:200],  # Truncate long link text
                    is_external=is_external,
                )
            )

        return links

    def _truncate(self, text: str) -> str:
        """Truncate text to MAX_CONTENT_LENGTH."""
        if len(text) > self.settings.MAX_CONTENT_LENGTH:
            return text[: self.settings.MAX_CONTENT_LENGTH]
        return text

    @staticmethod
    def _get_title(soup: BeautifulSoup) -> str | None:
        """Get page title."""
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        return None

    @staticmethod
    def _get_meta_content(soup: BeautifulSoup, name: str) -> str | None:
        """Get content of a meta tag by name."""
        meta = soup.find("meta", attrs={"name": name})
        if meta and isinstance(meta, Tag):
            content = meta.get("content")
            if content:
                return str(content).strip()
        return None

    @staticmethod
    def _get_og_tag(soup: BeautifulSoup, prop: str) -> str | None:
        """Get content of an Open Graph meta tag."""
        meta = soup.find("meta", attrs={"property": prop})
        if meta and isinstance(meta, Tag):
            content = meta.get("content")
            if content:
                return str(content).strip()
        return None

    @staticmethod
    def _get_language(soup: BeautifulSoup) -> str | None:
        """Get page language from html tag."""
        html_tag = soup.find("html")
        if html_tag and isinstance(html_tag, Tag):
            lang = html_tag.get("lang")
            if lang:
                return str(lang).strip()
        return None

    @staticmethod
    def _get_canonical(soup: BeautifulSoup, url: str) -> str | None:
        """Get canonical URL."""
        link = soup.find("link", attrs={"rel": "canonical"})
        if link and isinstance(link, Tag):
            href = link.get("href")
            if href:
                return urljoin(url, str(href))
        return None

    @staticmethod
    def _get_published_date(soup: BeautifulSoup) -> str | None:
        """Get published date from various meta tags."""
        for attr_name, attr_val in [
            ("property", "article:published_time"),
            ("name", "date"),
            ("name", "pubdate"),
            ("name", "publishdate"),
            ("itemprop", "datePublished"),
        ]:
            meta = soup.find("meta", attrs={attr_name: attr_val})
            if meta and isinstance(meta, Tag):
                content = meta.get("content")
                if content:
                    return str(content).strip()

        # Check time tag
        time_tag = soup.find("time", attrs={"datetime": True})
        if time_tag and isinstance(time_tag, Tag):
            dt = time_tag.get("datetime")
            if dt:
                return str(dt).strip()

        return None

    @staticmethod
    def _resolve_url(url: str | None, base_url: str) -> str | None:
        """Resolve a possibly relative URL."""
        if not url:
            return None
        return urljoin(base_url, url)
