"""Lusa Dependency Analyzer — measures how dependent Portuguese outlets are on Lusa.

Strategy
--------
For each Portuguese outlet, fetch all articles published in the last N days and
compare them against Lusa articles from the same period using TF-IDF cosine
similarity on (title + content heading). If the best Lusa match exceeds the
``PARAPHRASE`` threshold (0.70), that article is classified as **Lusa-derived**.

This is a fast, embedder-free first pass. In a future iteration, once article
embeddings are persisted in the DB, the :class:`StoryMatcher` can be used
directly for more accurate cross-lingual matching.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from src.db.models import Source, Article
from src.stats.models import LusaDependencyMetrics, OutletDependency

logger = logging.getLogger(__name__)


class LusaDependencyAnalyzer:
    """Measure how dependent each Portuguese outlet is on Lusa content.

    Parameters
    ----------
    db_session:
        Async SQLAlchemy session to query articles and sources.
    window_days:
        How many days back (from now) to look for articles. Default 7.
    match_threshold:
        Minimum TF-IDF cosine similarity to consider an outlet article
        as Lusa-derived. Default 0.70 (same as ``StoryMatcher.PARAPHRASE``).
    """

    def __init__(
        self,
        db_session: object,
        window_days: int = 7,
        match_threshold: float = 0.70,
    ):
        self.db = db_session
        self.window_days = window_days
        self.match_threshold = match_threshold

    # ── Public API ──────────────────────────────────────────────────────────

    async def analyze(self) -> LusaDependencyMetrics:
        """Run the full analysis and return aggregated metrics.

        Returns safe defaults (``global_pct=None``, empty ``per_outlet``) if
        the DB session is unavailable, there are no articles, or an error occurs.
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

            # ── Analyze per outlet ──
            per_outlet: dict[str, OutletDependency] = {}
            total_outlet_articles = 0
            total_derived = 0

            for outlet in outlets:
                outlet_articles = await self._fetch_articles(outlet.id, start, now)
                if not outlet_articles:
                    continue

                derived = self._count_derived(lusa_articles, outlet_articles)
                total_outlet_articles += len(outlet_articles)
                total_derived += derived

                per_outlet[outlet.id] = OutletDependency(
                    pct=round(derived / len(outlet_articles) * 100, 1),
                    stories=len(outlet_articles),
                    lusa_derived=derived,
                )

            global_pct = (
                round(total_derived / total_outlet_articles * 100, 1)
                if total_outlet_articles > 0
                else None
            )

            return LusaDependencyMetrics(
                global_pct=global_pct,
                per_outlet=per_outlet,
                per_topic={},  # Placeholder until topic classification is built
            )

        except Exception as exc:
            logger.warning("Lusa dependency analysis failed: %s", exc)
            return LusaDependencyMetrics()

    # ── Per-day timeline ────────────────────────────────────────────────────

    async def daily_timeline(self, days: int = 7) -> list[float]:
        """Compute Lusa dependency percentage for each of the last *days* days.

        Returns a list of floats (percentages), one per day, most recent last.
        Falls back to an empty list on error.
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

                derived = self._count_derived(lusa_articles, day_outlet_articles)
                daily.append(round(derived / len(day_outlet_articles) * 100, 1))

            return daily

        except Exception as exc:
            logger.warning("Lusa dependency timeline failed: %s", exc)
            return [0.0] * days

    # ── Matching logic ─────────────────────────────────────────────────────

    def _count_derived(
        self, lusa_articles: list[Article], outlet_articles: list[Article]
    ) -> int:
        """Count how many *outlet_articles* are derived from *lusa_articles*.

        Uses TF-IDF vectorisation on ``title + first 500 chars of content``,
        then cosine similarity. Fast and doesn't require pre-computed embeddings.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        # Build text corpus: Lusa texts first, then outlet texts
        lusa_texts = [_article_text(a) for a in lusa_articles]
        outlet_texts = [_article_text(a) for a in outlet_articles]

        if not lusa_texts or not outlet_texts:
            return 0

        try:
            # Fit TF-IDF on all texts, transform separately
            # Adaptive max_df: only filter high-frequency terms when we have
            # enough documents to reliably identify them (20+ docs). For small
            # batches (tests, low-volume periods), keep all terms.
            n_docs = len(lusa_texts) + len(outlet_texts)
            vectorizer = TfidfVectorizer(
                max_features=5000,
                analyzer="word",
                token_pattern=r"(?u)\b\w+\b",
                stop_words=None,  # Keep all words — Portuguese stop words
                # may filter important context
                ngram_range=(1, 2),
                max_df=0.85 if n_docs >= 20 else 1.0,
                min_df=1,
            )
            vectorizer.fit(lusa_texts + outlet_texts)

            lusa_vectors = vectorizer.transform(lusa_texts)
            outlet_vectors = vectorizer.transform(outlet_texts)

            # Compute similarity matrix: outlet x Lusa
            sim_matrix = cosine_similarity(outlet_vectors, lusa_vectors)

            # For each outlet article, find best Lusa match
            derived = 0
            for row in sim_matrix:
                best = row.max()
                if best >= self.match_threshold:
                    derived += 1

            return derived

        except Exception as exc:
            logger.warning("TF-IDF matching failed: %s", exc)
            return 0

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


def _article_text(article: Article) -> str:
    """Build a matching text from an article: title + content heading.

    Uses the full title plus the first 800 characters of content (enough to
    capture the lead/heading paragraph which typically contains the key facts).
    """
    title = (article.title or "").strip()
    content = (article.content_text or "").strip()
    # Use first 800 chars of content (roughly the lead paragraph)
    lead = content[:800]
    return f"{title} {lead}".strip()
