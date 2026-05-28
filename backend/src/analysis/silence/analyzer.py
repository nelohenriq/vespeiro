"""Silence Detector — detects stories covered internationally but not in Portuguese outlets.

Strategy
--------
For each international source article (Reuters, BBC, Guardian, AP, El País) in
the last N days, check whether any Portuguese-language outlet (excluding Lusa)
published a similar article using TF-IDF cosine similarity on
(title + content heading). If no Portuguese outlet matches above the
``PARAPHRASE`` threshold (0.70), the story is classified as **silenced in
Portugal**.

Near-duplicate international articles are then deduplicated into story clusters
so that one story covered by multiple international sources counts as *one*
silenced story.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.db.models import Source, Article
from src.stats.models import SilenceMetrics, SilencedStory

logger = logging.getLogger(__name__)


class SilenceAnalyzer:
    """Detect stories covered internationally but absent from Portuguese outlets.

    Parameters
    ----------
    db_session:
        Async SQLAlchemy session to query articles and sources.
    window_days:
        How many days back (from now) to look for articles. Default 7.
    match_threshold:
        Minimum TF-IDF cosine similarity to consider a Portuguese article as
        covering an international story. Default 0.70
        (same as ``StoryMatcher.PARAPHRASE``).
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

    async def analyze(self) -> SilenceMetrics:
        """Run the full silence analysis and return aggregated metrics.

        Returns safe defaults (zeros, empty list) if the DB session is
        unavailable, there are no articles, or an error occurs.
        """
        if self.db is None:
            logger.debug("No DB session — returning defaults")
            return SilenceMetrics()

        try:
            now = datetime.now(timezone.utc)
            start = now - timedelta(days=self.window_days)

            # ── Fetch international articles ──
            intl_sources = await self._fetch_international_sources()
            if not intl_sources:
                logger.info("No international sources found — returning defaults")
                return SilenceMetrics()

            intl_ids = [s.id for s in intl_sources]
            intl_articles = await self._fetch_articles_bulk(intl_ids, start, now)
            if not intl_articles:
                logger.info("No international articles in the last %d days", self.window_days)
                return SilenceMetrics()

            # ── Fetch Portuguese outlet articles ──
            pt_outlets = await self._fetch_portuguese_outlets()
            pt_ids = [s.id for s in pt_outlets]
            pt_articles = await self._fetch_articles_bulk(pt_ids, start, now)

            # ── Compute today and avg_7d from daily timeline ──
            daily_counts = await self.daily_timeline(days=7)
            today = daily_counts[-1] if daily_counts else 0
            avg_7d = (
                round(sum(daily_counts) / len(daily_counts), 1)
                if daily_counts else 0.0
            )

            # ── Find silenced stories for the top_silenced list ──
            silenced_stories = self._find_silenced(
                intl_articles, pt_articles, intl_sources,
            )

            return SilenceMetrics(
                today=today,
                avg_7d=avg_7d,
                top_silenced=sorted(
                    silenced_stories,
                    key=lambda s: (-s.international_sources, s.gap_pct),
                )[:10],
            )

        except Exception as exc:
            logger.warning("Silence analysis failed: %s", exc)
            return SilenceMetrics()

    # ── Per-day timeline ────────────────────────────────────────────────────

    async def daily_timeline(self, days: int = 7) -> list[int]:
        """Compute number of silenced stories for each of the last *days* days.

        Returns a list of integers (counts), one per day, most recent last.
        Falls back to an empty list on error or no DB.
        """
        if self.db is None:
            return []

        try:
            now = datetime.now(timezone.utc)
            intl_sources = await self._fetch_international_sources()
            if not intl_sources:
                return [0] * days

            intl_ids = [s.id for s in intl_sources]
            pt_outlets = await self._fetch_portuguese_outlets()
            pt_ids = [s.id for s in pt_outlets]

            daily: list[int] = []

            for i in range(days - 1, -1, -1):
                day_start = (now - timedelta(days=i)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                day_end = day_start + timedelta(days=1)

                day_intl = await self._fetch_articles_bulk(intl_ids, day_start, day_end)
                if not day_intl:
                    daily.append(0)
                    continue

                day_pt = await self._fetch_articles_bulk(pt_ids, day_start, day_end)
                silenced = self._find_silenced(day_intl, day_pt, intl_sources)
                daily.append(len(silenced))

            return daily

        except Exception as exc:
            logger.warning("Silence timeline failed: %s", exc)
            return [0] * days

    # ── Core logic ─────────────────────────────────────────────────────────

    def _find_silenced(
        self,
        intl_articles: list[Article],
        pt_articles: list[Article],
        intl_sources: list[Source],
    ) -> list[SilencedStory]:
        """Find international stories not covered by Portuguese outlets.

        1. For each international article, check similarity against all PT articles.
        2. If no match above threshold, mark as silence candidate.
        3. Deduplicate silence candidates by checking similarity among themselves.

        Returns deduplicated list of :class:`SilencedStory` objects.
        """
        if not intl_articles:
            return []
        if not pt_articles:
            # No PT articles at all → every international story is silenced
            # Deduplicate and return
            return self._deduplicate_stories(intl_articles, intl_sources)

        # Build texts for all articles
        intl_texts = [_article_text(a) for a in intl_articles]
        pt_texts = [_article_text(a) for a in pt_articles]

        # Fit TF-IDF on all texts combined for consistent vocabulary
        all_texts = intl_texts + pt_texts
        n_docs = len(all_texts)

        try:
            vectorizer = TfidfVectorizer(
                max_features=5000,
                analyzer="word",
                token_pattern=r"(?u)\b\w+\b",
                ngram_range=(1, 2),
                max_df=0.85 if n_docs >= 20 else 1.0,
                min_df=1,
            )
            vectorizer.fit(all_texts)

            intl_vec = vectorizer.transform(intl_texts)
            pt_vec = vectorizer.transform(pt_texts)

            # Similarity matrix: international articles x PT articles
            sim_matrix = cosine_similarity(intl_vec, pt_vec)

            # Find silenced articles: no PT match above threshold
            silenced_articles: list[Article] = []
            for i, row in enumerate(sim_matrix):
                best = row.max()
                if best < self.match_threshold:
                    silenced_articles.append(intl_articles[i])

            if not silenced_articles:
                return []

            return self._deduplicate_stories(silenced_articles, intl_sources)

        except Exception as exc:
            logger.warning("TF-IDF silencing check failed: %s", exc)
            return []

    def _deduplicate_stories(
        self,
        articles: list[Article],
        intl_sources: list[Source],
    ) -> list[SilencedStory]:
        """Remove near-duplicate silenced articles by clustering by similarity.

        Groups articles that describe the same story (similarity >= 0.70)
        into a single :class:`SilencedStory`.

        Builds a source name lookup for reporting.
        """
        if not articles:
            return []

        source_name_map: dict[str, str] = {s.id: s.name for s in intl_sources}

        # Deduplicate: cluster by TF-IDF similarity
        texts = [_article_text(a) for a in articles]
        if len(articles) <= 1:
            single = articles[0]
            return [SilencedStory(
                title=single.title or "Untitled",
                international_sources=1,
                pt_coverage=0,
                gap_pct=100.0,
                sources=[source_name_map.get(single.source_id, single.source_id)],
            )]

        try:
            vectorizer = TfidfVectorizer(
                max_features=5000,
                analyzer="word",
                token_pattern=r"(?u)\b\w+\b",
                ngram_range=(1, 2),
                max_df=0.85 if len(texts) >= 20 else 1.0,
                min_df=1,
            )
            vectors = vectorizer.fit_transform(texts)
            sim_matrix = cosine_similarity(vectors)

            # Greedy clustering: group articles with similarity >= threshold
            assigned: set[int] = set()
            clusters: list[list[int]] = []

            for i in range(len(articles)):
                if i in assigned:
                    continue
                cluster = [i]
                assigned.add(i)
                for j in range(i + 1, len(articles)):
                    if j in assigned:
                        continue
                    if sim_matrix[i][j] >= self.match_threshold:
                        cluster.append(j)
                        assigned.add(j)
                clusters.append(cluster)

            # Build SilencedStory for each cluster
            stories: list[SilencedStory] = []
            for cluster in clusters:
                cluster_articles = [articles[idx] for idx in cluster]
                # Pick the best title (prefer the longest non-empty one)
                best_title = max(
                    (a.title or "Untitled" for a in cluster_articles),
                    key=lambda t: len(t),
                )
                # Collect unique source names
                source_ids_in_cluster: set[str] = set()
                for a in cluster_articles:
                    source_ids_in_cluster.add(a.source_id)

                sources_list = sorted(
                    source_name_map.get(sid, sid)
                    for sid in source_ids_in_cluster
                )

                stories.append(SilencedStory(
                    title=best_title,
                    international_sources=len(source_ids_in_cluster),
                    pt_coverage=0,
                    gap_pct=100.0,
                    sources=sources_list,
                ))

            return stories

        except Exception as exc:
            logger.warning("Story deduplication failed: %s", exc)
            # Fallback: return each article as a separate silenced story
            return [
                SilencedStory(
                    title=a.title or "Untitled",
                    international_sources=1,
                    pt_coverage=0,
                    gap_pct=100.0,
                    sources=[source_name_map.get(a.source_id, a.source_id)],
                )
                for a in articles
            ]



    # ── DB helpers ──────────────────────────────────────────────────────────

    async def _fetch_international_sources(self) -> list[Source]:
        """Fetch all international (non-Portuguese) active sources."""
        result = await self.db.execute(
            select(Source)
            .where(Source.language != "pt")
            .where(Source.is_active.is_(True))
            .order_by(Source.id)
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

    async def _fetch_articles_bulk(
        self, source_ids: list[str], start: datetime, end: datetime,
    ) -> list[Article]:
        """Fetch all articles from *source_ids* in the given time window."""
        if not source_ids:
            return []
        result = await self.db.execute(
            select(Article)
            .where(Article.source_id.in_(source_ids))
            .where(Article.collected_at >= start)
            .where(Article.collected_at < end)
            .order_by(Article.collected_at)
        )
        return list(result.scalars().all())


def _article_text(article: Article) -> str:
    """Build a matching text from an article: title + content heading.

    Uses the full title plus the first 800 characters of content (enough to
    capture the lead/heading paragraph which typically contains the key facts).
    """
    title = (article.title or "").strip()
    content = (article.content_text or "").strip()
    lead = content[:800]
    return f"{title} {lead}".strip()
