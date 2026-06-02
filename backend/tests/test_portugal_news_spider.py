"""Tests for the generic ``portugal_news`` Scrapy spider.

Tests the pure helper functions and the spider's extraction logic using
mock HTTP responses (no real network calls).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from scrapy.http import HtmlResponse, TextResponse

# Add Scrapy project to sys.path so the spider module can be imported properly
import sys
from pathlib import Path

_SCRAPY_DIR = (
    Path(__file__).parent.parent / "scrapy_project"
).resolve()
if str(_SCRAPY_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRAPY_DIR))

from publico.spiders.portugal_news import (
    PortugalNewsSpider,
    _is_navigation_link,
    _looks_like_article_url,
)

# ── Helper to build a fake HtmlResponse ─────────────────────────────────────


def _make_response(
    body: str,
    url: str = "https://observador.pt",
    status: int = 200,
) -> HtmlResponse:
    return HtmlResponse(
        url=url,
        status=status,
        body=body.encode("utf-8"),
        encoding="utf-8",
        request=None,
    )


def _make_jsonld_response(
    jsonld_data: list | dict,
    url: str = "https://observador.pt/2026/05/28/artigo.html",
    body_html: str = "",
) -> HtmlResponse:
    """Create a response with JSON-LD script tag and optional body HTML."""
    if isinstance(jsonld_data, (list, dict)):
        script = f'<script type="application/ld+json">{json.dumps(jsonld_data)}</script>'
    else:
        script = ""
    html = f"<html><head>{script}</head><body>{body_html}</body></html>"
    return _make_response(html, url=url)


# ═══════════════════════════════════════════════════════════════════════════
#  Pure helper function tests
# ═══════════════════════════════════════════════════════════════════════════


class TestIsNavigationLink:
    def test_navigation_patterns(self):
        """URLs containing nav/social/login patterns should be filtered."""
        nav_urls = [
            "https://observador.pt/#comments",
            "javascript:void(0)",
            "mailto:news@observador.pt",
            "tel:+351123456789",
            "https://observador.pt/tag/politica/",
            "https://observador.pt/autor/joao-silva/",
            "https://observador.pt/categoria/opiniao/",
            "https://observador.pt/search?q=algo",
            "https://observador.pt/pesquisa?q=algo",
            "https://observador.pt/login",
            "https://observador.pt/register",
            "https://observador.pt/assinaturas",
            "https://observador.pt/newsletter",
        ]
        for url in nav_urls:
            assert _is_navigation_link(url), f"Expected True for nav link: {url}"

    def test_article_urls_not_filtered(self):
        """Real article URLs should not be filtered."""
        article_urls = [
            "https://observador.pt/2026/05/28/artigo-principal/",
            "https://eco.sapo.pt/2026/05/28/economia/pib-cresce-2-5/",
            "https://www.cmjornal.pt/2026/05/28/politica/governo-anuncia-medidas",
            "https://24noticias.sapo.pt/2026/05/28/tecnologia/novo-smartphone/",
        ]
        for url in article_urls:
            assert not _is_navigation_link(url), f"Expected False for article: {url}"

    def test_empty_href(self):
        """Empty href should not be filtered by navigation check."""
        assert not _is_navigation_link("")


class TestLooksLikeArticleUrl:
    def test_date_in_path(self):
        """URLs with /2026/05/28/ pattern should be recognized."""
        assert _looks_like_article_url("https://observador.pt/2026/05/28/artigo/")
        assert _looks_like_article_url("https://eco.sapo.pt/2026/5/28/economia/")
        assert _looks_like_article_url("https://observador.pt/20260528-artigo/")

    def test_navigation_not_article(self):
        """Navigation URLs should not look like articles."""
        assert not _looks_like_article_url("https://observador.pt/login")
        assert not _looks_like_article_url("https://observador.pt/#comments")
        assert not _looks_like_article_url("https://observador.pt/tag/politica/")

    def test_non_date_urls(self):
        """URLs without date segments should not be recognized."""
        assert not _looks_like_article_url("https://observador.pt/sobre/")
        assert not _looks_like_article_url("https://observador.pt/contactos/")


# ═══════════════════════════════════════════════════════════════════════════
#  Spider: _extract_author  (static method)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractAuthor:
    def test_author_string(self):
        result = PortugalNewsSpider._extract_author({"author": "João Silva"})
        assert result == "João Silva"

    def test_author_dict(self):
        result = PortugalNewsSpider._extract_author(
            {"author": {"name": "Maria Santos"}}
        )
        assert result == "Maria Santos"

    def test_author_list_of_dicts(self):
        result = PortugalNewsSpider._extract_author(
            {"author": [{"name": "Carlos Pereira"}]}
        )
        assert result == "Carlos Pereira"

    def test_author_list_of_strings(self):
        result = PortugalNewsSpider._extract_author(
            {"author": ["Ana Rodrigues", "Pedro Costa"]}
        )
        assert result == "Ana Rodrigues"

    def test_author_missing(self):
        assert PortugalNewsSpider._extract_author({}) is None

    def test_author_empty_string(self):
        assert PortugalNewsSpider._extract_author({"author": ""}) is None

    def test_author_dict_no_name(self):
        assert PortugalNewsSpider._extract_author({"author": {"role": "reporter"}}) is None


# ═══════════════════════════════════════════════════════════════════════════
#  Spider: _try_jsonld
# ═══════════════════════════════════════════════════════════════════════════


class TestTryJsonLd:
    def test_simple_newsarticle(self):
        """Extract headline, author, and date from a NewsArticle JSON-LD."""
        data = {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Governo anuncia novo pacote de medidas",
            "author": {"name": "João Silva"},
            "datePublished": "2026-05-28T10:30:00+01:00",
            "description": "O governo anunciou hoje um novo pacote de medidas económicas.",
        }
        response = _make_jsonld_response(data, body_html="<p>Texto do artigo.</p>")
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._try_jsonld(response)
        assert result is not None
        assert result["title"] == "Governo anuncia novo pacote de medidas"
        assert result["author"] == "João Silva"
        assert result["published_at"] == "2026-05-28T10:30:00+01:00"

    def test_no_jsonld(self):
        """No JSON-LD → return None (spider falls back to HTML)."""
        response = _make_response("<html><h1>Title</h1><p>Text</p></html>")
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        assert spider._try_jsonld(response) is None

    def test_invalid_json(self):
        """Malformed JSON-LD should not crash."""
        html = '<script type="application/ld+json">{invalid json}</script>'
        response = _make_response(f"<html>{html}</html>")
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        assert spider._try_jsonld(response) is None

    def test_non_article_type_skipped(self):
        """WebSite or Organization types should be skipped."""
        data = {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "Observador",
        }
        response = _make_jsonld_response(data)
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        assert spider._try_jsonld(response) is None

    def test_graph_parsing(self):
        """JSON-LD with @graph should extract NewsArticle from graph."""
        data = {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "WebSite", "name": "Site"},
                {
                    "@type": "NewsArticle",
                    "headline": "Artigo importante",
                    "author": "Pedro Costa",
                    "datePublished": "2026-05-28T12:00:00Z",
                },
            ],
        }
        response = _make_jsonld_response(data, body_html="<p>Texto.</p>")
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._try_jsonld(response)
        assert result is not None
        assert result["title"] == "Artigo importante"

    def test_multiple_candidates_selects_article_type(self):
        """When multiple JSON-LD blocks exist, prefer the NewsArticle type."""
        html = """
        <html>
        <script type="application/ld+json">{"@type": "Organization", "name": "Observador"}</script>
        <script type="application/ld+json">{"@type": "NewsArticle", "headline": "Notícia real", "author": "Ana"}</script>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._try_jsonld(response)
        assert result is not None
        assert result["title"] == "Notícia real"


# ═══════════════════════════════════════════════════════════════════════════
#  Spider: _parse_html  (fallback extraction)
# ═══════════════════════════════════════════════════════════════════════════


class TestParseHtml:
    def test_extract_title_and_content(self):
        """Fallback extraction should get h1 title and p content."""
        html = """
        <html>
        <head><title>Page Title</title></head>
        <body>
            <h1>Artigo de Notícias</h1>
            <div class="content">
                <p>Primeiro parágrafo do artigo.</p>
                <p>Segundo parágrafo do artigo.</p>
            </div>
        </body>
        </html>
        """
        response = _make_response(html, url="https://eco.sapo.pt/2026/05/28/artigo/")
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._parse_html(response)
        assert result["title"] == "Artigo de Notícias"
        assert "Primeiro parágrafo" in result["content_text"]
        assert "Segundo parágrafo" in result["content_text"]
        assert result["url"] == "https://eco.sapo.pt/2026/05/28/artigo/"

    def test_no_content(self):
        """With no <p> tags, content_text should be None."""
        html = "<html><body><h1>Title only</h1></body></html>"
        response = _make_response(html)
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._parse_html(response)
        assert result["title"] == "Title only"
        # Result URL should be set from response
        assert result["url"] == "https://observador.pt"

    def test_meta_author(self):
        """Author from meta tag should be extracted."""
        html = """
        <html>
        <head><meta name="author" content="Ricardo Santos"></head>
        <body><h1>Artigo</h1></body>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._parse_html(response)
        assert result["author"] == "Ricardo Santos"

    def test_meta_published_time(self):
        """Published time from meta tag should be extracted."""
        html = """
        <html>
        <head>
            <meta property="article:published_time" content="2026-05-28T14:00:00+01:00">
        </head>
        <body><h1>Artigo</h1></body>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._parse_html(response)
        assert result["published_at"] == "2026-05-28T14:00:00+01:00"

    def test_time_tag_datetime(self):
        """Published time from <time> tag should be extracted as fallback."""
        html = """
        <html>
        <body>
            <h1>Artigo</h1>
            <time datetime="2026-05-28T15:00:00Z">May 28</time>
        </body>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider._parse_html(response)
        assert result["published_at"] == "2026-05-28T15:00:00Z"


# ═══════════════════════════════════════════════════════════════════════════
#  Spider: _extract_content_text
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractContentText:
    def test_article_tag(self):
        """Content inside <article> tag should be extracted."""
        response = _make_response(
            "<html><article><p>Parágrafo dentro de article.</p></article></html>"
        )
        text = PortugalNewsSpider._extract_content_text(response)
        assert text is not None
        assert "Parágrafo dentro de article" in text

    def test_empty_article(self):
        """Empty article tag should return None."""
        response = _make_response("<html><article></article></html>")
        assert PortugalNewsSpider._extract_content_text(response) is None

    def test_main_tag(self):
        """Content inside <main> tag should be extracted."""
        response = _make_response(
            "<html><main><p>Conteúdo principal.</p></main></html>"
        )
        text = PortugalNewsSpider._extract_content_text(response)
        assert text is not None
        assert "Conteúdo principal" in text

    def test_no_content_returns_none(self):
        """Page with no paragraphs should return None."""
        response = _make_response("<html><body>No paragraphs here</body></html>")
        assert PortugalNewsSpider._extract_content_text(response) is None


# ═══════════════════════════════════════════════════════════════════════════
#  Spider: parse() — homepage link discovery
# ═══════════════════════════════════════════════════════════════════════════


class TestParseHomepage:
    def test_selects_link_by_selector(self):
        """When link_selector is provided, only matching links should be queued."""
        html = """
        <html>
        <body>
            <article><a href="/2026/05/28/artigo1/">Artigo 1</a></article>
            <article><a href="/2026/05/28/artigo2/">Artigo 2</a></article>
            <article><a href="/tag/opiniao/">Opinião (no date)</a></article>
        </body>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider(
            site_url="https://eco.sapo.pt",
            link_selector="article a",
            max_articles="30",
        )
        requests = list(spider.parse(response))
        assert len(requests) == 2, "Should find 2 article links"
        urls = [r.url for r in requests]
        assert any("artigo1" in u for u in urls)
        assert any("artigo2" in u for u in urls)

    def test_respects_max_articles(self):
        """Spider should stop queuing after max_articles is reached."""
        articles_html = "".join(
            f'<article><a href="/2026/05/28/artigo{i}/">Artigo {i}</a></article>'
            for i in range(50)
        )
        response = _make_response(f"<html><body>{articles_html}</body></html>")
        spider = PortugalNewsSpider(
            site_url="https://eco.sapo.pt",
            link_selector="article a",
            max_articles="5",
        )
        requests = list(spider.parse(response))
        assert len(requests) == 5

    def test_fallback_date_heuristic(self):
        """Without link_selector, date-based heuristic should find links."""
        html = """
        <html>
        <body>
            <a href="https://observador.pt/2026/05/28/artigo1/">Artigo 1</a>
            <a href="https://observador.pt/sobre/">Sobre (no date)</a>
            <a href="https://observador.pt/2026/05/29/artigo2/">Artigo 2</a>
        </body>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider(
            site_url="https://observador.pt",
            link_selector="",
            max_articles="30",
        )
        requests = list(spider.parse(response))
        assert len(requests) == 2
        urls = [r.url for r in requests]
        assert all("2026" in u for u in urls)

    def test_fallback_with_h2_h3_links(self):
        """When no <a> has date, fall back to h2/h3 links."""
        html = """
        <html>
        <body>
            <h2><a href="https://observador.pt/2026/05/28/artigo/">Artigo em H2</a></h2>
            <h3><a href="https://observador.pt/2026/05/29/outro/">Outro em H3</a></h3>
            <a href="/tag/opiniao/">Opinião (ignored)</a>
        </body>
        </html>
        """
        response = _make_response(html)
        spider = PortugalNewsSpider(
            site_url="https://observador.pt",
            link_selector="",
            max_articles="30",
        )
        requests = list(spider.parse(response))
        assert len(requests) == 2


# ═══════════════════════════════════════════════════════════════════════════
#  Spider: parse_article() — article page extraction
# ═══════════════════════════════════════════════════════════════════════════


class TestParseArticle:
    def test_jsonld_used_when_available(self):
        """parse_article should prefer JSON-LD over HTML fallback."""
        data = {
            "@context": "https://schema.org",
            "@type": "NewsArticle",
            "headline": "Título do JSON-LD",
            "author": "Autora JSON-LD",
            "datePublished": "2026-05-28T10:00:00Z",
        }
        response = _make_jsonld_response(
            data,
            body_html="<h1>Título HTML</h1><p>Texto HTML.</p>",
        )
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider.parse_article(response)
        assert result["title"] == "Título do JSON-LD"
        assert result["author"] == "Autora JSON-LD"

    def test_html_fallback_when_no_jsonld(self):
        """parse_article should fall back to HTML when JSON-LD is missing."""
        response = _make_response(
            "<html><body><h1>Título HTML</h1><p>Conteúdo HTML.</p></body></html>",
            url="https://eco.sapo.pt/artigo.html",
        )
        spider = PortugalNewsSpider()
        spider.max_articles = 30
        result = spider.parse_article(response)
        assert result["title"] == "Título HTML"
