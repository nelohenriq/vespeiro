"""Parliament-Media Gap Analyzer — measures the gap between what's discussed
in parliament and what's covered by Portuguese media outlets.

Strategy:
1. Query parliament debate articles (source_id = "parlamento") and all PT media articles.
2. Extract key topics/terms from both corpora using TF-IDF.
3. Compute topic overlap and gap metrics.
4. Return structured gap data for frontend visualization.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class TopicGap(BaseModel):
    """A topic discussed in parliament with its media coverage level."""

    topic: str
    parliament_mentions: int = 0
    media_mentions: int = 0
    media_outlets: int = 0
    gap_score: float = 0.0  # 0 = full coverage, 1 = total silence
    top_media_outlets: list[str] = []


class ParliamentGapReport(BaseModel):
    """Full parliament-media gap analysis report."""

    generated_at: datetime
    total_parliament_docs: int = 0
    total_media_articles: int = 0
    overall_gap_score: float = 0.0
    topics: list[TopicGap] = []
    most_discussed_only_parliament: list[str] = []
    most_covered_in_media: list[str] = []


# ── Analyzer ──────────────────────────────────────────────────────────────────


class ParliamentGapAnalyzer:
    """Analyzes the gap between parliamentary debate and media coverage."""

    # Portuguese stopwords + noise words
    _STOPWORDS: set[str] = {
        "de", "a", "o", "que", "e", "do", "da", "em", "um", "para",
        "com", "não", "uma", "os", "no", "se", "na", "por", "mais",
        "as", "dos", "como", "mas", "ao", "ele", "das", "à", "seu",
        "sua", "ou", "quando", "muito", "nos", "já", "eu", "também",
        "só", "pelo", "pela", "até", "isso", "ela", "entre", "depois",
        "sem", "mesmo", "aos", "seus", "quem", "nas", "me", "esse",
        "eles", "estão", "você", "tinha", "foram", "essa", "num",
        "nem", "suas", "meu", "às", "minha", "numa", "pelos", "elas",
        "qual", "nós", "lhe", "deles", "essas", "esses", "pelas",
        "este", "dele", "tu", "te", "vocês", "vos", "lhes", "meus",
        "minhas", "teu", "tua", "teus", "tuas", "nosso", "nossa",
        "nossos", "nossas", "dela", "delas", "este", "esta", "estes",
        "estas", "aquele", "aquela", "aqueles", "aquelas", "isto",
        "aquilo", "estou", "está", "estamos", "estão", "estive",
        "esteve", "estivemos", "estiveram", "estava", "estávamos",
        "estavam", "estivera", "estivéramos", "esteja", "estejamos",
        "estejam", "estivesse", "estivéssemos", "estivessem",
        "estiver", "estivermos", "estiverem", "hei", "há", "havemos",
        "hão", "houve", "houvemos", "houveram", "houvera",
        "houvéramos", "haja", "hajamos", "hajam", "houvesse",
        "houvéssemos", "houvessem", "houver", "houvermos", "houverem",
        "houverei", "houverá", "houveremos", "houverão", "houveria",
        "houveríamos", "houveriam", "sou", "somos", "são", "era",
        "éramos", "eram", "fui", "foi", "fomos", "foram", "fora",
        "fôramos", "seja", "sejamos", "sejam", "fosse", "fôssemos",
        "fossem", "for", "formos", "forem", "serei", "será", "seremos",
        "serão", "seria", "seríamos", "seriam", "tenho", "tem", "temos",
        "têm", "tinha", "tínhamos", "tinham", "tive", "teve", "tivemos",
        "tiveram", "tivera", "tivéramos", "tenha", "tenhamos", "tenham",
        "tivesse", "tivéssemos", "tivessem", "tiver", "tivermos",
        "tiverem", "terei", "terá", "teremos", "terão", "teria",
        "teríamos", "teriam",
    }

    def __init__(self, db_session: object | None = None):
        self.db = db_session

    async def analyze(self) -> ParliamentGapReport:
        """Run the full parliament-media gap analysis."""
        parliament_docs = await self._get_parliament_docs()
        media_docs = await self._get_media_docs()

        if not parliament_docs:
            return ParliamentGapReport(
                generated_at=datetime.now(timezone.utc),
                total_parliament_docs=0,
                total_media_articles=len(media_docs),
            )

        # Extract terms from both corpora
        parliament_terms = self._extract_key_terms(parliament_docs)
        media_terms = self._extract_key_terms(media_docs)

        # Track per-outlet media coverage
        outlet_terms: dict[str, set[str]] = defaultdict(set)
        for doc in media_docs:
            source = doc.get("source_id", "unknown")
            terms = self._extract_terms_from_text(doc.get("content_text", ""))
            outlet_terms[source] |= terms

        # Compute gap per topic
        topics: list[TopicGap] = []
        all_parl_terms = set(parliament_terms.keys())
        all_media_terms = set(media_terms.keys())

        for term, parl_count in sorted(
            parliament_terms.items(), key=lambda x: -x[1]
        )[:30]:
            media_count = media_terms.get(term, 0)
            # Count outlets covering this term
            covering_outlets = [
                src for src, terms in outlet_terms.items()
                if term in terms
            ]

            # Gap score: 0 if well covered, approaches 1 if not covered
            # Uses log scale so even 1 media mention reduces gap from 1 to ~0.3
            if media_count > 0:
                gap_score = max(0.0, 1.0 - (media_count / max(parl_count, 1)))
            else:
                gap_score = 1.0

            topics.append(TopicGap(
                topic=term,
                parliament_mentions=parl_count,
                media_mentions=media_count,
                media_outlets=len(covering_outlets),
                gap_score=round(gap_score, 3),
                top_media_outlets=covering_outlets[:5],
            ))

        # Overall gap score: weighted average
        total_parl_mentions = sum(t.parliament_mentions for t in topics)
        if total_parl_mentions > 0:
            overall_gap = sum(
                t.gap_score * t.parliament_mentions for t in topics
            ) / total_parl_mentions
        else:
            overall_gap = 0.0

        # Most parliament-only topics
        only_parliament = sorted(
            [t for t in topics if t.media_mentions == 0],
            key=lambda t: -t.parliament_mentions,
        )[:10]

        # Most media-covered
        most_covered = sorted(
            [t for t in topics if t.media_mentions > 0],
            key=lambda t: t.media_mentions,
            reverse=True,
        )[:10]

        return ParliamentGapReport(
            generated_at=datetime.now(timezone.utc),
            total_parliament_docs=len(parliament_docs),
            total_media_articles=len(media_docs),
            overall_gap_score=round(overall_gap, 3),
            topics=topics,
            most_discussed_only_parliament=[
                t.topic for t in only_parliament
            ],
            most_covered_in_media=[
                t.topic for t in most_covered
            ],
        )

    def _extract_key_terms(self, docs: list[dict]) -> dict[str, int]:
        """Extract key terms from a corpus of documents and count frequency."""
        from collections import Counter

        counter: Counter[str] = Counter()
        for doc in docs:
            text = doc.get("content_text", "")
            terms = self._extract_terms_from_text(text)
            counter.update(terms)
        return dict(counter.most_common(50))

    def _extract_terms_from_text(self, text: str) -> set[str]:
        """Extract significant 2-3 word terms from Portuguese text."""
        if not text:
            return set()

        # Normalize
        text = text.lower()
        text = re.sub(r"[^a-zà-ú\s]", " ", text)

        words = text.split()
        terms: set[str] = set()

        # Bigrams
        for i in range(len(words) - 1):
            if words[i] not in self._STOPWORDS or words[i + 1] not in self._STOPWORDS:
                bigram = f"{words[i]} {words[i + 1]}"
                if not all(w in self._STOPWORDS for w in bigram.split()):
                    terms.add(bigram)

        # Trigrams
        for i in range(len(words) - 2):
            trigram = f"{words[i]} {words[i + 1]} {words[i + 2]}"
            # At least one non-stopword
            if not all(w in self._STOPWORDS for w in trigram.split()):
                terms.add(trigram)

        return terms

    async def _get_parliament_docs(self) -> list[dict]:
        """Query parliament debate articles from the DB."""
        if self.db is None:
            return []
        try:
            from sqlalchemy import select
            from src.db.models import Article

            result = await self.db.execute(
                select(Article.content_text, Article.title, Article.id)
                .where(Article.source_id == "parlamento_debates")
                .where(Article.content_text.isnot(None))
                .limit(100)
            )
            return [
                {"content_text": row[0], "title": row[1], "id": row[2]}
                for row in result.all()
            ]
        except Exception as exc:
            logger.warning("Failed to query parliament articles: %s", exc)
            return []

    async def _get_media_docs(self) -> list[dict]:
        """Query Portuguese media articles from the DB."""
        if self.db is None:
            return []
        try:
            from sqlalchemy import select
            from src.db.models import Article, Source

            # Fetch media source IDs and all articles in parallel,
            # then filter in Python to avoid SQLite string comparison quirks.
            src_result = await self.db.execute(
                select(Source.id).where(
                    Source.category.in_(["mainstream", "agency", "international"]),
                )
            )
            media_source_ids = {row[0] for row in src_result.all()}

            if not media_source_ids:
                return []

            # Fetch articles with any text content (body or summary)
            # Mainstream RSS scrapers only store summaries, not full text.
            from sqlalchemy import or_
            result = await self.db.execute(
                select(Article.content_text, Article.summary, Article.title, Article.id, Article.source_id)
                .where(or_(
                    Article.content_text.isnot(None),
                    Article.summary.isnot(None),
                ))
                .limit(500)
            )
            return [
                {
                    # Use content_text if available, else fall back to summary
                    "content_text": row[0] or row[1] or "",
                    "title": row[2],
                    "id": row[3],
                    "source_id": row[4],
                }
                for row in result.all()
                if row[4] in media_source_ids  # Python-side filter
            ]
        except Exception as exc:
            logger.warning("Failed to query media articles: %s", exc)
            return []



