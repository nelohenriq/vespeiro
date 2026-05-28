"""Tests for the LusaDependencyAnalyzer — matching logic, helper, and graceful degradation."""

import uuid
import pytest
from src.analysis.dependency.analyzer import LusaDependencyAnalyzer, _article_text
from src.db.models import Article
from src.stats.models import LusaDependencyMetrics


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_article(
    title: str,
    content: str,
    source_id: str = "lusa",
) -> Article:
    """Create a minimal Article instance for testing."""
    return Article(
        id=str(uuid.uuid4()),
        source_id=source_id,
        url="https://example.com/article",
        title=title,
        content_text=content,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  _article_text helper
# ═══════════════════════════════════════════════════════════════════════════════


class TestArticleText:
    """The _article_text helper concatenates title + content heading."""

    def test_full_content(self):
        """Title + content heading should be concatenated, truncated to ~800 chars."""
        article = _make_article(
            "Governo anuncia 2.3M€ para a saúde",
            "O governo português anunciou um pacote de 2.3 milhões de euros. "
            * 200,  # well over 800 chars
        )
        text = _article_text(article)
        assert "Governo anuncia 2.3M€" in text
        assert "pacote" in text
        # Should be truncated to roughly title_len + 800 + space
        assert len(text) < 900

    def test_no_content(self):
        """When content_text is None, only the title is used."""
        article = Article(
            id="no-content",
            source_id="lusa",
            url="https://example.com",
            title="Apenas título sem corpo",
            content_text=None,
        )
        assert _article_text(article) == "Apenas título sem corpo"

    def test_empty_strings(self):
        """When both title and content are empty, return empty string."""
        article = Article(
            id="empty",
            source_id="lusa",
            url="https://example.com",
            title="",
            content_text="",
        )
        assert _article_text(article) == ""

    def test_very_short_text(self):
        """Very short articles should still produce a valid string."""
        article = _make_article("Título", "Corpo curto.")
        text = _article_text(article)
        assert "Título" in text
        assert "Corpo curto" in text


# ═══════════════════════════════════════════════════════════════════════════════
#  _count_derived — TF-IDF matching logic
# ═══════════════════════════════════════════════════════════════════════════════


class TestCountDerived:
    """Core matching: TF-IDF cosine similarity between Lusa and outlet articles."""

    def test_exact_match(self):
        """Identical texts should be counted as derived (above 0.70)."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        text = (
            "O governo português anunciou um investimento de 2.3 milhões de euros "
            "no setor da saúde. O primeiro-ministro confirmou a decisão após uma "
            "reunião em Lisboa com representantes da União Europeia."
        )
        lusa = [_make_article("Governo anuncia 2.3M€ para saúde", text)]
        outlet = [_make_article("Governo anuncia 2.3M€ para saúde", text, source_id="publico")]
        assert analyzer._count_derived(lusa, outlet) == 1

    def test_paraphrase_match(self):
        """Close paraphrase (same facts, different wording) should still match."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        lusa_text = (
            "O governo português anunciou um investimento de 2.3 milhões de euros "
            "no setor da saúde. O primeiro-ministro António Costa confirmou a "
            "decisão após uma reunião em Lisboa com a União Europeia. Serão "
            "contratados 500 enfermeiros e adquiridos novos equipamentos "
            "para o Serviço Nacional de Saúde."
        )
        # Paraphrase: minimal changes — locale synonym ("no setor da" → "na área da")
        # and omits peripheral detail ("com a União Europeia"). Same facts, same
        # key vocabulary — realistic of a journalist rewriting from the same source.
        outlet_text = (
            "O governo português anunciou um investimento de 2.3 milhões de euros "
            "na área da saúde. O primeiro-ministro António Costa confirmou a "
            "decisão após uma reunião em Lisboa. Serão contratados 500 enfermeiros "
            "e adquiridos novos equipamentos para o Serviço Nacional de Saúde."
        )
        lusa = [_make_article("Governo investe 2.3 milhões em saúde", lusa_text)]
        outlet = [_make_article("Governo investe 2.3 milhões na área da saúde", outlet_text, source_id="publico")]
        assert analyzer._count_derived(lusa, outlet) == 1

    def test_no_match_different_topics(self):
        """Completely different topics should NOT be counted as derived."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        lusa = [_make_article(
            "Governo investe 2.3 milhões em saúde",
            "O governo português anunciou investimento de 2.3 milhões de euros "
            "no setor da saúde para contratar enfermeiros.",
        )]
        outlet = [_make_article(
            "Benfica vence clássico por 3-1",
            "O Benfica venceu o FC Porto por 3-1 no Estádio da Luz num jogo "
            "emocionante com casa cheia.",
            source_id="publico",
        )]
        assert analyzer._count_derived(lusa, outlet) == 0

    def test_empty_lusa_articles(self):
        """No Lusa articles → count is 0 (nothing to match against)."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        outlet = [_make_article("Notícia qualquer", "Conteúdo qualquer.", source_id="publico")]
        assert analyzer._count_derived([], outlet) == 0

    def test_empty_outlet_articles(self):
        """No outlet articles → count is 0 (nothing to evaluate)."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        lusa = [_make_article("Notícia Lusa", "Conteúdo da Lusa.")]
        assert analyzer._count_derived(lusa, []) == 0

    def test_mixed_results(self):
        """With multiple outlet articles, only those above threshold are counted."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        lusa = [_make_article(
            "Governo investe 2.3 milhões em saúde",
            "O governo português anunciou um investimento de 2.3 milhões de "
            "euros no setor da saúde. O primeiro-ministro António Costa "
            "confirmou a decisão após uma reunião em Lisboa com a União "
            "Europeia. Serão contratados 500 enfermeiros e adquiridos novos "
            "equipamentos para o Serviço Nacional de Saúde.",
        )]
        outlets = [
            # Should match — close paraphrase of the same story
            _make_article(
                "Governo investe 2.3 milhões na área da saúde",
                "O governo português anunciou um investimento de 2.3 milhões de euros "
                "na área da saúde. O primeiro-ministro António Costa confirmou a "
                "decisão após uma reunião em Lisboa. Serão contratados 500 enfermeiros "
                "e adquiridos novos equipamentos para o Serviço Nacional de Saúde.",
                source_id="publico",
            ),
            # Should NOT match — different story entirely
            _make_article(
                "Tragédia na estrada: 5 mortos",
                "Um grave acidente na A1 provocou cinco mortos e vários feridos. "
                "A estrada esteve cortada durante várias horas.",
                source_id="expresso",
            ),
        ]
        assert analyzer._count_derived(lusa, outlets) == 1

    def test_same_topic_different_angles(self):
        """Same broad topic but different angles → may or may not match.

        This tests the threshold boundary — articles about the same political
        event but focusing on different aspects.
        """
        analyzer = LusaDependencyAnalyzer(db_session=None)
        lusa = [_make_article(
            "Orçamento do Estado aprovado no parlamento",
            "O Orçamento do Estado para 2026 foi aprovado no parlamento com "
            "os votos favoráveis do PS e a abstenção do PSD. O documento "
            "prevê um crescimento de 2.5% do PIB.",
        )]
        outlet = [_make_article(
            "OE2026: oposição critica falta de diálogo",
            "A oposição criticou hoje a falta de diálogo do governo na "
            "preparação do Orçamento do Estado para 2026. O PSD anunciou "
            "que se vai abster na votação.",
            source_id="publico",
        )]
        # These share key terms (Orçamento do Estado, 2026, parlamento)
        # but have different emphasis. We don't assert a specific result,
        # just that it doesn't crash.
        count = analyzer._count_derived(lusa, outlet)
        assert isinstance(count, int)
        assert 0 <= count <= 1

    def test_multiple_lusa_articles(self):
        """With multiple Lusa articles, best match determines derivation."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        lusa = [
            _make_article(
                "Crise política: primeiro-ministro demite-se",
                "O primeiro-ministro apresentou a sua demissão ao Presidente "
                "da República após uma crise política sem precedentes no "
                "parlamento português com repercussões internacionais.",
            ),
            _make_article(
                "Saúde: governo investe 2.3 milhões",
                "O governo português anunciou um investimento de 2.3 milhões "
                "de euros no setor da saúde. O primeiro-ministro António Costa "
                "confirmou a decisão após uma reunião em Lisboa com a União "
                "Europeia. Serão contratados 500 enfermeiros e adquiridos novos "
                "equipamentos para o Serviço Nacional de Saúde.",
            ),
        ]
        outlet = [_make_article(
            "Governo investe 2.3 milhões na área da saúde",
            "O governo português anunciou um investimento de 2.3 milhões de euros "
            "na área da saúde. O primeiro-ministro António Costa confirmou a "
            "decisão após uma reunião em Lisboa. Serão contratados 500 enfermeiros "
            "e adquiridos novos equipamentos para o Serviço Nacional de Saúde.",
            source_id="publico",
        )]
        # Should match the second Lusa article (saúde), not the first (political crisis)
        assert analyzer._count_derived(lusa, outlet) == 1

    def test_custom_threshold(self):
        """Lower threshold should count more articles as derived."""
        analyzer_low = LusaDependencyAnalyzer(db_session=None, match_threshold=0.10)
        analyzer_high = LusaDependencyAnalyzer(db_session=None, match_threshold=0.99)

        # Very loosely related articles
        lusa = [_make_article("Saúde", "Artigos sobre saúde em Portugal.")]
        outlet = [_make_article(
            "Hospital",
            "Notícias sobre hospitais portugueses.",
            source_id="publico",
        )]

        low_count = analyzer_low._count_derived(lusa, outlet)
        high_count = analyzer_high._count_derived(lusa, outlet)
        assert low_count >= high_count


# ═══════════════════════════════════════════════════════════════════════════════
#  Graceful degradation — no DB session
# ═══════════════════════════════════════════════════════════════════════════════


class TestAnalyzeNoDb:
    """Without a DB session, all methods return safe defaults."""

    @pytest.mark.asyncio
    async def test_analyze_returns_defaults(self):
        """analyze() should return LusaDependencyMetrics with all defaults."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        result = await analyzer.analyze()
        assert isinstance(result, LusaDependencyMetrics)
        assert result.global_pct is None
        assert result.per_outlet == {}
        assert result.per_topic == {}

    @pytest.mark.asyncio
    async def test_daily_timeline_returns_empty_list(self):
        """daily_timeline() should return an empty list."""
        analyzer = LusaDependencyAnalyzer(db_session=None)
        result = await analyzer.daily_timeline(days=7)
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
#  Constructor defaults
# ═══════════════════════════════════════════════════════════════════════════════


def test_constructor_defaults():
    """Default window_days and match_threshold should be sensible."""
    analyzer = LusaDependencyAnalyzer(db_session=object())
    assert analyzer.window_days == 7
    assert analyzer.match_threshold == 0.70


def test_constructor_custom_values():
    """Custom parameters should be reflected in the instance."""
    analyzer = LusaDependencyAnalyzer(
        db_session=object(),
        window_days=14,
        match_threshold=0.80,
    )
    assert analyzer.window_days == 14
    assert analyzer.match_threshold == 0.80
