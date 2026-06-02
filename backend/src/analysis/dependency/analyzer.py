"""Lusa Dependency Analyzer — measures how dependent Portuguese outlets are on Lusa.

Strategy
--------
For each Portuguese outlet, fetch all articles published in the last N days and
compare them against Lusa articles from the same period using multilingual
sentence embeddings (``intfloat/multilingual-e5-large``) + cosine similarity.
The embedding model captures semantic similarity across short RSS summary texts
(200-500 chars) where TF-IDF sparse vectors produce near-zero overlap.

If the best Lusa match exceeds ``match_threshold`` (default 0.50, calibrated
for embedding cosine similarity on short texts), that article is classified as
**Lusa-derived**.

Falls back gracefully to zero matches if the sentence-transformers model
cannot be loaded (e.g. first-run download not yet complete).

Topic Classification
--------------------
After computing per-outlet dependency, the analyzer classifies each outlet
article into a topic category using a keyword-based approach (TF-IDF-like
term matching against curated keyword sets for 12 Portuguese news topics).
Per-topic dependency percentages are computed and returned in
``LusaDependencyMetrics.per_topic``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape

from sqlalchemy import select, func

from src.db.models import Source, Article
from src.stats.models import LusaDependencyMetrics, OutletDependency

logger = logging.getLogger(__name__)


# ── Topic classification keywords ───────────────────────────────────────────
# Each topic maps to a set of Portuguese-language keywords.  Classification
# is done by counting keyword matches in the article text (title + lead).
# The topic with the most matches wins; ``"outros"`` is the fallback.
# These sets are curated for Portuguese news coverage and can be extended.

_CLASSIFY_TOPIC_KEYWORDS: dict[str, set[str]] = {
    "política": {
        "governo", "primeiro-ministro", "presidente da república", "parlamento",
        "assembleia da república", "partido", "ps", "psd", "chega",
        "bloco de esquerda", "pcp", "livre", "pan", "deputado",
        "ministro", "ministra", "eleições", "votação", "orçamento do estado",
        "coligação", "maioria absoluta", "moção", "censura", "demissão",
        "crise política", "liderança", "campanha eleitoral", "sondagem",
        "poder político", "primeiro ministro", "presidente da republica",
        "assembleia da republica", "autarquias", "municipio", "câmara municipal",
        "presidencia", "cds", "il", "iniciativa liberal",
    },
    "economia": {
        "economia", "pib", "inflação", "taxa de juro", "banco de portugal",
        "banco central", "orçamento", "finanças", "fiscal", "irs", "irc", "iva",
        "imposto", "receita fiscal", "despesa pública", "dívida pública",
        "défice", "excedente", "crescimento económico", "recessão",
        "mercado", "bolsa", "psix", "empresa", "negócios", "startup",
        "investimento", "exportação", "importação", "turismo",
        "desemprego", "emprego", "salário", "pensão", "segurança social",
        "prr", "plano de recuperação", "fundos europeus", "bancos",
        "finanças públicas", "contenção orçamental", "poupança",
        "crise económica", "recuperação económica", "pacote",
    },
    "saúde": {
        "saúde", "sns", "serviço nacional de saúde", "hospital", "centro de saúde",
        "médico", "enfermeiro", "urgência", "consulta", "vacina", "medicamento",
        "doença", "pandemia", "epidemia", "covid", "internamento",
        "ministério da saúde", "direção geral da saúde", "dgs",
        "ordem dos médicos", "cuidados intensivos", "cirurgia",
        "transplante", "saúde mental", "doente", "utente",
    },
    "educação": {
        "educação", "escola", "universidade", "faculdade", "politécnico",
        "professor", "aluno", "estudante", "ensino", "curso", "licenciatura",
        "mestrado", "doutoramento", "bolsa de estudo", "ação social escolar",
        "ministério da educação", "provas de aferição", "exames nacionais",
        "manuais escolares", "abandono escolar", "sucesso escolar",
        "greve", "sindicato", "avaliação de professores",
    },
    "justiça": {
        "justiça", "tribunal", "juiz", "procurador", "advogado", "magistrado",
        "ministério público", "supremo tribunal", "conselho superior",
        "crime", "processo crime", "investigação criminal",
        "julgamento", "sentença", "condenação", "absolvição",
        "recurso", "prisão", "estabelecimento prisional",
        "corrupção", "fraude", "branqueamento", "suborno",
        "operação", "busca", "apreensão", "arguido",
    },
    "desporto": {
        "desporto", "futebol", "benfica", "porto", "sporting", "braga",
        "seleção nacional", "liga", "campeonato", "taça",
        "jogador", "treinador", "golo", "vitória", "derrota", "estádio",
        "olimpíadas", "jogos olímpicos", "atletismo", "natação", "ténis",
        "ciclismo", "modalidade", "federação", "clube",
    },
    "cultura": {
        "cultura", "cinema", "teatro", "música", "dança", "literatura",
        "livro", "autor", "escritor", "poesia", "romance", "ensaio",
        "exposição", "museu", "galeria", "arte", "artista", "pintura",
        "escultura", "arquitetura", "património", "unesco", "fado",
        "festival", "espetáculo", "concerto", "série", "documentário",
        "netflix", "streaming", "cinema português",
    },
    "ambiente": {
        "ambiente", "clima", "alterações climáticas", "aquecimento global",
        "sustentabilidade", "carbono", "pegada ecológica", "energia renovável",
        "energia solar", "energia eólica", "transição energética",
        "poluição", "qualidade do ar", "emissões", "co2", "lixo", "resíduos",
        "reciclagem", "economia circular", "biodiversidade", "espécie",
        "floresta", "incêndio florestal", "água", "seca", "oceanos",
        "sustentável", "carbono neutro",
    },
    "internacional": {
        "internacional", "europa", "união europeia", "ue", "otan", "nato",
        "estados unidos", "eua", "china", "rússia", "ucrânia", "guerra",
        "conflito internacional", "sanções", "diplomacia", "embaixador",
        "nações unidas", "onu", "fmi", "banco mundial",
        "comércio internacional", "migração", "refugiado", "fronteira",
        "médio oriente", "israel", "palestina", "síria", "afeganistão",
        "brasil", "palop", "cplp", "comunidade dos países de língua portuguesa",
        "áfrica", "ásia", "américa latina", "g7", "g20",
    },
    "crime": {
        "crime", "assalto", "roubo", "homicídio", "assassinato", "morte violenta",
        "violência doméstica", "violação", "abuso", "tráfico", "droga",
        "toxicodependência", "polícia", "psp", "gnr", "pj",
        "polícia judiciária", "segurança pública", "violência",
        "agressão", "sequestro", "incêndio criminoso", "arma",
    },
    "sociedade": {
        "sociedade", "população", "demografia", "natalidade", "envelhecimento",
        "família", "criança", "jovem", "idoso", "deficiência", "inclusão",
        "igualdade de género", "discriminação", "racismo", "xenofobia",
        "lgbt", "direitos humanos", "associativismo", "voluntariado",
        "igreja", "religião", "católica", "fátima", "papa",
        "consumo", "direitos do consumidor", "habitação", "renda", "casa",
        "transportes", "mobilidade", "metro", "comboio", "cp", "carris",
    },
    "ciência": {
        "ciência", "tecnologia", "investigação científica", "inovação",
        "inteligência artificial", "ia", "digital", "transformação digital",
        "internet", "dados", "software", "aplicação", "app",
        "startup", "espaço", "satélite", "nasa", "esa",
        "agência espacial", "biologia", "genética", "dna",
        "investigador", "laboratório", "artigo científico", "estudo",
        "centro de investigação", "física", "química", "matemática",
        "engenharia", "computação", "algoritmo",
    },
}


class LusaDependencyAnalyzer:
    """Measure how dependent each Portuguese outlet is on Lusa content.

    Parameters
    ----------
    db_session:
        Async SQLAlchemy session to query articles and sources.
    window_days:
        How many days back (from now) to look for articles. Default 7.
    match_threshold:
        Minimum embedding cosine similarity to consider an outlet article
        as Lusa-derived. Default 0.50 — calibrated for multilingual
        sentence embeddings (1024-dim, L2-normalised). Higher than the
        old TF-IDF threshold (0.35) because embeddings produce richer
        semantic representations even for short 200-500 char summaries.
    """

    def __init__(
        self,
        db_session: object,
        window_days: int = 7,
        match_threshold: float = 0.50,
    ):
        self.db = db_session
        self.window_days = window_days
        self.match_threshold = match_threshold

    # ── Public API ──────────────────────────────────────────────────────────

    async def analyze(self) -> LusaDependencyMetrics:
        """Run the full analysis and return aggregated metrics.

        Returns safe defaults (``global_pct=None``, empty ``per_outlet``) if
        the DB session is unavailable, there are no articles, or an error occurs.

        Performance note: Lusa embeddings are computed once and reused across
        all outlets (50 Lusa + N×30 outlet = ~530 total embeddings, ~3 min on
        CPU). Without this batching, each outlet would re-embed Lusa texts,
        totalling ~1280 embeddings.
        """
        if self.db is None:
            logger.debug("No DB session — returning defaults")
            return LusaDependencyMetrics()

        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=self.window_days)

            # ── Fetch Lusa articles ──
            lusa_articles = await self._fetch_articles("lusa", start, now)
            if not lusa_articles:
                logger.info("No Lusa articles found in the last %d days", self.window_days)
                return LusaDependencyMetrics(global_pct=0.0)

            # ── Identify Portuguese-language outlets (exclude Lusa itself) ──
            outlets = await self._fetch_portuguese_outlets()

            # ── Pre-compute Lusa embeddings once ──
            lusa_vecs = self._embed_articles(lusa_articles)
            if lusa_vecs is None:
                return LusaDependencyMetrics(global_pct=0.0)

            # ── Analyze per outlet ──
            per_outlet: dict[str, OutletDependency] = {}
            total_outlet_articles = 0
            total_derived = 0
            per_topic_counts: dict[str, list[int]] = {}  # topic -> [total, derived]

            for outlet in outlets:
                outlet_articles = await self._fetch_articles(outlet.id, start, now)
                if not outlet_articles:
                    continue

                outlet_vecs = self._embed_articles(outlet_articles)
                if outlet_vecs is None:
                    continue

                derived_mask = self._derived_mask_from_vecs(lusa_vecs, outlet_vecs)
                derived = sum(derived_mask)
                total_outlet_articles += len(outlet_articles)
                total_derived += derived

                per_outlet[outlet.id] = OutletDependency(
                    pct=round(derived / len(outlet_articles) * 100, 1),
                    stories=len(outlet_articles),
                    lusa_derived=derived,
                )

                # Accumulate per-topic counts
                for i, article in enumerate(outlet_articles):
                    text = _article_text(article)
                    topic = self._classify_topic(text)
                    if topic not in per_topic_counts:
                        per_topic_counts[topic] = [0, 0]
                    per_topic_counts[topic][0] += 1
                    if derived_mask[i]:
                        per_topic_counts[topic][1] += 1

            global_pct = (
                round(total_derived / total_outlet_articles * 100, 1)
                if total_outlet_articles > 0
                else None
            )

            # Compute per-topic percentages
            per_topic: dict[str, float] = {}
            for topic, (total, derived_count) in per_topic_counts.items():
                if total > 0:
                    per_topic[topic] = round(derived_count / total * 100, 1)

            return LusaDependencyMetrics(
                global_pct=global_pct,
                per_outlet=per_outlet,
                per_topic=per_topic,
            )

        except Exception as exc:
            logger.warning("Lusa dependency analysis failed: %s", exc)
            return LusaDependencyMetrics()

    # ── Per-day timeline ────────────────────────────────────────────────────

    async def daily_timeline(self, days: int = 7) -> list[float]:
        """Compute Lusa dependency percentage for each of the last *days* days.

        Returns a list of floats (percentages), one per day, most recent last.
        Falls back to an empty list on error.

        Performance note: Lusa embeddings are pre-computed once and reused
        across all 7 days.
        """
        if self.db is None:
            return []

        try:
            now = datetime.now(timezone.utc)
            lusa_articles = await self._fetch_articles(
                "lusa", now - timedelta(days=days), now
            )
            if not lusa_articles:
                return [0.0] * days

            lusa_vecs = self._embed_articles(lusa_articles)
            if lusa_vecs is None:
                return [0.0] * days

            outlets = await self._fetch_portuguese_outlets()
            daily: list[float] = []

            for i in range(days - 1, -1, -1):
                day_start = (now - timedelta(days=i)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                day_end = day_start + timedelta(days=1)

                day_outlet_articles: list[Article] = []
                for outlet in outlets:
                    batch = await self._fetch_articles(outlet.id, day_start, day_end)
                    day_outlet_articles.extend(batch)

                if not day_outlet_articles:
                    daily.append(0.0)
                    continue

                day_vecs = self._embed_articles(day_outlet_articles)
                if day_vecs is None:
                    daily.append(0.0)
                    continue

                derived = self._count_derived_from_vecs(lusa_vecs, day_vecs)
                daily.append(round(derived / len(day_outlet_articles) * 100, 1))

            return daily

        except Exception as exc:
            logger.warning("Lusa dependency timeline failed: %s", exc)
            return [0.0] * days

    # ── Matching logic ─────────────────────────────────────────────────────

    # ── Topic classification ────────────────────────────────────────────────

    @staticmethod
    def _classify_topic(text: str) -> str:
        """Classify article text into a topic category using keyword matching.

        Returns the best-matching topic key from ``_CLASSIFY_TOPIC_KEYWORDS``
        or ``"outros"`` if no keywords match.

        **Tie-breaking:** When two topics have the same keyword count, the
        topic with the longer combined keyword string wins (more specific
        = longer total keyword length).  This prevents tie-dependent
        results from dict insertion order (e.g. ``"crime"`` vs ``"justiça"``
        for criminal court cases).
        """
        if not text:
            return "outros"
        text_lower = text.lower()
        best_topic = "outros"
        best_score = 0
        best_keyword_len = 0

        # Pre-compute total keyword lengths for tie-breaking
        _total_keyword_len: dict[str, int] = {
            topic: sum(len(kw) for kw in keywords)
            for topic, keywords in _CLASSIFY_TOPIC_KEYWORDS.items()
        }

        for topic, keywords in _CLASSIFY_TOPIC_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > best_score:
                best_score = score
                best_topic = topic
                best_keyword_len = _total_keyword_len[topic]
            elif score == best_score and score > 0:
                # Tie: prefer the topic with longer combined keyword length
                # (more specific vocabulary → more discriminating topic)
                kw_len = _total_keyword_len[topic]
                if kw_len > best_keyword_len:
                    best_topic = topic
                    best_keyword_len = kw_len
        return best_topic

    @staticmethod
    def _embed_articles(articles: list[Article]) -> "np.ndarray | None":  # type: ignore[valid-type]
        """Embed a list of articles into a (N, 1024) numpy array.

        Returns ``None`` if the embedding model is unavailable.
        """
        from src.pipeline.embedder import EmbeddingService, _get_model

        import numpy as np

        texts = [_article_text(a) for a in articles]
        if not texts:
            return None

        if _get_model() is None:
            logger.warning(
                "Embedding model not available. "
                "Install sentence-transformers to enable embedding-based matching."
            )
            return None

        embedder = EmbeddingService()
        embeddings = embedder.embed_batch(texts)
        return np.array(embeddings, dtype=np.float64)

    def _count_derived_from_vecs(
        self,
        lusa_vecs: "np.ndarray",  # type: ignore[valid-type]
        outlet_vecs: "np.ndarray",  # type: ignore[valid-type]
    ) -> int:
        """Count derived articles from pre-computed embedding matrices.

        Args:
            lusa_vecs: (N_lusa, 1024) L2-normalised Lusa embeddings.
            outlet_vecs: (N_outlet, 1024) L2-normalised outlet embeddings.

        Returns:
            Number of outlet articles whose best Lusa similarity ≥ threshold.
        """
        import numpy as np

        if lusa_vecs.size == 0 or outlet_vecs.size == 0:
            return 0

        # Cosine similarity via dot product (embeddings are L2-normalised)
        # Shape: (n_outlet, n_lusa)
        sim_matrix: np.ndarray = outlet_vecs @ lusa_vecs.T

        derived = 0
        for row in sim_matrix:
            if float(row.max()) >= self.match_threshold:
                derived += 1

        return derived

    def _derived_mask_from_vecs(
        self,
        lusa_vecs: "np.ndarray",  # type: ignore[valid-type]
        outlet_vecs: "np.ndarray",  # type: ignore[valid-type]
    ) -> list[bool]:
        """Return a boolean mask indicating which outlet articles are Lusa-derived.

        Like :meth:`_count_derived_from_vecs` but returns per-article booleans
        instead of a count, enabling per-article analysis (e.g. topic breakdown).
        """
        import numpy as np

        if lusa_vecs.size == 0 or outlet_vecs.size == 0:
            return [False] * outlet_vecs.shape[0]

        sim_matrix: np.ndarray = outlet_vecs @ lusa_vecs.T
        return [float(row.max()) >= self.match_threshold for row in sim_matrix]

    def _count_derived(
        self, lusa_articles: list[Article], outlet_articles: list[Article]
    ) -> int:
        """Count how many *outlet_articles* are derived from *lusa_articles*.

        Convenience wrapper that embeds both article sets then delegates to
        :meth:`_count_derived_from_vecs`. Prefer calling :meth:`_embed_articles`
        followed by :meth:`_count_derived_from_vecs` directly when Lusa
        embeddings can be reused across multiple outlets (the common case).
        """
        lusa_vecs = self._embed_articles(lusa_articles)
        if lusa_vecs is None:
            return 0
        outlet_vecs = self._embed_articles(outlet_articles)
        if outlet_vecs is None:
            return 0
        return self._count_derived_from_vecs(lusa_vecs, outlet_vecs)

    # ── DB helpers ──────────────────────────────────────────────────────────

    async def _fetch_articles(
        self, source_id: str, start: datetime, end: datetime
    ) -> list[Article]:
        """Fetch all articles from *source_id* in the given time window."""
        result = await self.db.execute(
            select(Article)
            .where(Article.source_id == source_id)
            .where(Article.collected_at >= start)
            .where(Article.collected_at < end)
            .order_by(Article.collected_at)
        )
        return list(result.scalars().all())

    async def _fetch_portuguese_outlets(self) -> list[Source]:
        """Fetch all Portuguese-language sources except Lusa itself."""
        result = await self.db.execute(
            select(Source)
            .where(Source.language == "pt")
            .where(Source.id != "lusa")
            .where(Source.is_active.is_(True))
            .order_by(Source.id)
        )
        return list(result.scalars().all())


# Known Portuguese news source suffixes commonly appended to RSS titles
_TITLE_SUFFIX_RE = re.compile(r"\s[-|]\s([A-ZÀ-Ú][\wÀ-ú. ]+|[A-ZÀ-Ú]{2,})$")

# Google News RSS sometimes generates placeholder titles when it can't extract
# the real article title (e.g. "www.lusa.pt - LUSA", "Fotogalerias - LUSA").
# These pollute matching, so we detect them and skip the title entirely.
# We match known garbage patterns rather than broad heuristics to avoid false
# positives on legitimate article titles.
_AUTO_TITLE_RE = re.compile(
    r"""
    ^(?:                                         # Start of string, non-capturing group:
        www\.[a-z]+\.[a-z]+                     #   Domain pattern: www.lusa.pt
        | Fotogalerias                           #   Gallery section page
        | Galeria\sde\s(?:Vídeos|Imagens|Fotos)  #   Gallery section page (pt)
        | Adenda\s                               #   Agenda appendix
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _article_text(article: Article) -> str:
    """Build a matching text from an article: title + content heading.

    Uses the full title plus the first 800 characters of content (enough to
    capture the lead/heading paragraph which typically contains the key facts).
    Falls back to ``summary`` when ``content_text`` is empty (mainstream RSS
    scrapers only store summaries, not full body text). HTML tags and entities
    are stripped from the summary since they typically contain RSS link wrappers.

    When a Google News RSS article has an auto-generated placeholder title
    (e.g. "www.lusa.pt - LUSA"), the title is discarded entirely so it doesn't
    pollute embedding-based matching.
    """
    raw_title = (article.title or "").strip()

    content = (article.content_text or "").strip()
    if not content:
        # Fall back to summary — strip HTML tags and decode HTML entities
        summary = (article.summary or "").strip()
        summary = re.sub(r"<[^>]+>", " ", summary)  # Remove HTML tags
        summary = unescape(summary)  # Decode &nbsp; &amp; etc.
        content = summary.strip()

    # Use first 800 chars of content (roughly the lead paragraph)
    lead = content[:800]

    # Detect auto-generated Google News titles — if found, skip title entirely
    if _AUTO_TITLE_RE.match(raw_title):
        return lead.strip()

    # Strip common RSS title suffixes: "- SourceName" or "| Section"
    # Only strips if suffix looks like a proper name (capitalized) or acronym
    title = _TITLE_SUFFIX_RE.sub("", raw_title).strip()

    return f"{title} {lead}".strip()
