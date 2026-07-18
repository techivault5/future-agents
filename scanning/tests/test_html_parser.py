"""Tests for the HTML parser and link extractor."""

from __future__ import annotations

import pytest

from scanning.html_parser import (
    ParsedPage,
    domain_of,
    is_same_domain,
    normalise_url,
    parse_html,
    url_id,
)

SIMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Test Page</title></head>
<body>
  <h1>Hello World</h1>
  <p>This is a test paragraph with some words.</p>
  <nav><a href="/about">About</a></nav>
  <a href="https://example.com/page1">Page 1</a>
  <a href="/page2">Page 2</a>
  <a href="https://other.com/stuff">External</a>
  <a href="mailto:hi@example.com">Email</a>
  <a href="#section">Anchor</a>
  <script>var x = 1;</script>
  <style>body { color: red; }</style>
</body>
</html>
"""


class TestParseHtml:
    def test_extracts_title(self):
        result = parse_html(SIMPLE_HTML, "https://example.com/")
        assert result.title == "Test Page"

    def test_extracts_text_without_scripts(self):
        result = parse_html(SIMPLE_HTML, "https://example.com/")
        assert "Hello World" in result.text
        assert "test paragraph" in result.text
        # Script/style content should be stripped
        assert "var x = 1" not in result.text
        assert "color: red" not in result.text

    def test_word_count_positive(self):
        result = parse_html(SIMPLE_HTML, "https://example.com/")
        assert result.word_count > 0

    def test_content_hash_set(self):
        result = parse_html(SIMPLE_HTML, "https://example.com/")
        assert result.content_hash is not None
        assert len(result.content_hash) == 64  # SHA-256 hex

    def test_extracts_absolute_links(self):
        result = parse_html(SIMPLE_HTML, "https://example.com/")
        assert "https://example.com/page1" in result.links
        assert "https://example.com/page2" in result.links

    def test_skips_mailto_and_anchors(self):
        result = parse_html(SIMPLE_HTML, "https://example.com/")
        urls = result.links
        assert not any("mailto:" in u for u in urls)
        assert not any(u.endswith("#section") for u in urls)

    def test_skips_binary_extensions(self):
        html = """
        <html><body>
          <a href="/doc.pdf">PDF</a>
          <a href="/image.png">Image</a>
          <a href="/page.html">Page</a>
        </body></html>
        """
        result = parse_html(html, "https://example.com/", skip_extensions=(".pdf", ".png"))
        urls = result.links
        assert not any(u.endswith(".pdf") for u in urls)
        assert not any(u.endswith(".png") for u in urls)
        assert any(u.endswith(".html") for u in urls)

    def test_deduplicates_links(self):
        html = """
        <html><body>
          <a href="/page">Link 1</a>
          <a href="/page">Link 2</a>
          <a href="/page/">Link 3</a>
        </body></html>
        """
        result = parse_html(html, "https://example.com/")
        page_links = [u for u in result.links if "/page" in u]
        assert len(page_links) == 1

    def test_empty_html(self):
        result = parse_html("", "https://example.com/")
        assert result.title is None
        assert result.word_count == 0
        assert result.links == []


class TestHelpers:
    def test_url_id_stable(self):
        uid1 = url_id("https://example.com/")
        uid2 = url_id("https://example.com/")
        assert uid1 == uid2
        assert len(uid1) == 64

    def test_url_id_different_urls(self):
        assert url_id("https://a.com/") != url_id("https://b.com/")

    def test_normalise_removes_fragment(self):
        assert normalise_url("https://example.com/page#section") == "https://example.com/page"

    def test_normalise_removes_trailing_slash(self):
        assert normalise_url("https://example.com/page/") == "https://example.com/page"

    def test_normalise_keeps_root_slash(self):
        result = normalise_url("https://example.com/")
        # Root should remain navigable
        assert "example.com" in result

    def test_domain_of(self):
        assert domain_of("https://docs.python.org/3/") == "docs.python.org"
        assert domain_of("https://EXAMPLE.COM/") == "example.com"

    def test_is_same_domain_exact(self):
        assert is_same_domain("https://example.com/page", "example.com")

    def test_is_same_domain_subdomain(self):
        assert is_same_domain("https://docs.example.com/api", "example.com")

    def test_is_same_domain_different(self):
        assert not is_same_domain("https://other.com/", "example.com")

    def test_is_same_domain_case_insensitive(self):
        assert is_same_domain("https://EXAMPLE.COM/", "example.com")
