"""HTML parsing and text / link extraction utilities.

Keeps all BeautifulSoup logic isolated so the crawler stays clean.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Tags whose content is never useful as knowledge
_NOISE_TAGS = {
    "script", "style", "noscript", "head", "meta", "link",
    "nav", "footer", "header", "aside", "form", "button",
    "select", "option", "textarea", "input",
}

# Patterns for URLs we want to skip even if they're HTML
_SKIP_PATTERNS = re.compile(
    r"(mailto:|tel:|javascript:|#|data:)",
    re.IGNORECASE,
)


class ParsedPage:
    """Result of parsing a single HTML document."""

    __slots__ = ("title", "text", "links", "word_count", "content_hash")

    def __init__(
        self,
        title: str | None,
        text: str,
        links: list[str],
    ) -> None:
        self.title = title
        self.text = text
        self.links = links
        self.word_count = len(text.split()) if text else 0
        self.content_hash = hashlib.sha256(text.encode()).hexdigest() if text else None


def parse_html(html: str, base_url: str, skip_extensions: tuple[str, ...] = ()) -> ParsedPage:
    """Parse raw HTML and return extracted text + absolute links.

    Args:
        html: Raw HTML bytes decoded to a string.
        base_url: The URL the HTML was fetched from (used to resolve relative links).
        skip_extensions: File extensions to exclude from outbound links.

    Returns:
        ParsedPage with title, cleaned text, and absolute links.
    """
    soup = BeautifulSoup(html, "html.parser")

    title = _extract_title(soup)
    text = _extract_text(soup)
    links = _extract_links(soup, base_url, skip_extensions)

    return ParsedPage(title=title, text=text, links=links)


def url_id(url: str) -> str:
    """Return a stable SHA-256 hex digest for a URL (used as primary key)."""
    return hashlib.sha256(url.encode()).hexdigest()


def normalise_url(url: str) -> str:
    """Normalise a URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    # Drop fragment
    clean = parsed._replace(fragment="")
    result = urlunparse(clean)
    # Remove trailing slash unless it's the root path
    if result.endswith("/") and urlparse(result).path not in ("", "/"):
        result = result.rstrip("/")
    return result


def is_same_domain(url: str, seed_domain: str) -> bool:
    """Return True if *url* is on *seed_domain* or a subdomain of it."""
    host = urlparse(url).netloc.lower()
    seed = seed_domain.lower()
    return host == seed or host.endswith(f".{seed}")


def domain_of(url: str) -> str:
    """Return the hostname component of a URL."""
    return urlparse(url).netloc.lower()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _extract_title(soup: BeautifulSoup) -> str | None:
    tag = soup.find("title")
    if tag and tag.string:
        return tag.string.strip()

    # Fall back to first <h1>
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return None


def _extract_text(soup: BeautifulSoup) -> str:
    """Extract visible text content, stripping noise tags."""
    # Work on a copy so we don't mutate the original soup
    body = soup.find("body") or soup

    for tag in body.find_all(_NOISE_TAGS):
        tag.decompose()

    # Get text, normalise whitespace
    raw = body.get_text(separator=" ")
    text = re.sub(r"\s+", " ", raw).strip()
    return text


def _extract_links(
    soup: BeautifulSoup,
    base_url: str,
    skip_extensions: tuple[str, ...],
) -> list[str]:
    """Return a de-duplicated list of absolute URLs found on the page."""
    seen: set[str] = set()
    links: list[str] = []

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"].strip()

        # Skip non-navigable links
        if _SKIP_PATTERNS.search(href):
            continue

        # Resolve relative URLs
        absolute = urljoin(base_url, href)

        # Only keep http / https
        scheme = urlparse(absolute).scheme
        if scheme not in ("http", "https"):
            continue

        # Skip binary/asset extensions
        path_lower = urlparse(absolute).path.lower()
        if any(path_lower.endswith(ext) for ext in skip_extensions):
            continue

        normalised = normalise_url(absolute)

        if normalised not in seen:
            seen.add(normalised)
            links.append(normalised)

    return links
