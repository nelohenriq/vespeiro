"""Advertising-Editorial Correlation Analyzer.

Measures the correlation between state institutional advertising spending (from
ERC reports) and the editorial stance/volume of coverage across Portuguese media
outlets.

Strategy:
1. Query ERC advertising articles for spending data.
2. Query media outlet articles for editorial coverage patterns.
3. Compute correlation coefficients (spending vs. coverage volume, sentiment).
4. Return structured correlation data for frontend scatter plot visualization.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class OutletCorrelation(BaseModel):
    """Correlation data for a single outlet."""

    outlet_id: str
    outlet_name: str = ""
    # Advertising
    estimated_ad_spend_eur: float = 0.0
    ad_reports_found: int = 0
    # Editorial
    articles_count: int = 0
    avg_sentiment: float | None = None
    gov_coverage_pct: float = 0.0
    # Correlation metadata
    owner_group: str = ""
    owner: str = ""


class CorrelationReport(BaseModel):
    """Full ad-editorial correlation report."""

    generated_at: datetime
    outlets: list[OutletCorrelation] = []
    correlation_coefficient: float | None = None
    # Pearson's r between ad_spend and articles_count
    r_spend_vs_articles: float | None = None
    # Pearson's r between ad_spend and gov_coverage_pct
    r_spend_vs_gov_coverage: float | None = None
    total_ad_spend_estimated: float = 0.0
    total_articles_analyzed: int = 0


# ── Analyzer ──────────────────────────────────────────────────────────────────


class CorrelationAnalyzer:
    """Analyzes the correlation between state ad spending and editorial patterns."""

    # Known outlets to match in ERC reports
    _OUTLET_PATTERNS: dict[str, list[str]] = {
        "rtp_noticias": ["rtp", "rádio e televisão de portugal"],
        "sic_noticias": ["sic", "sic notícias"],
        "cnn_portugal": ["cnn", "tvi", "media capital"],
        "publico": ["público", "publico"],
        "expresso": ["expresso", "impresa"],
        "cm_jornal": ["correio da manhã", "cm", "cmtv", "cofina"],
        "jn": ["jornal de notícias", "jn", "global media"],
        "dn": ["diário de notícias", "dn", "global media"],
        "tsf": ["tsf", "global media"],
        "observador": ["observador"],
        "renascenca": ["renascença", "rr", "rfm"],
        "eco": ["eco", "trust in news"],
    }

    def __init__(self, db_session: object | None = None):
        self.db = db_session

    async def analyze(self) -> CorrelationReport:
        """Run the full ad-editorial correlation analysis."""
        # Extract ad spending estimates from ERC articles
        ad_spending = await self._extract_ad_spending()

        # Get editorial metrics per outlet
        editorial = await self._get_editorial_metrics()

        # Get ownership info
        ownership = self._load_ownership_map()

        # Merge
        outlets: list[OutletCorrelation] = []
        for outlet_id, patterns in self._OUTLET_PATTERNS.items():
            spend_eur = 0.0
            ad_reports = 0
            for ad_outlet, amount in ad_spending.items():
                for pat in patterns:
                    if pat in ad_outlet.lower():
                        spend_eur += amount
                        ad_reports += 1
                        break

            ed = editorial.get(outlet_id, {})
            owner_info = ownership.get(outlet_id, {})

            outlets.append(OutletCorrelation(
                outlet_id=outlet_id,
                outlet_name=owner_info.get("name", outlet_id),
                estimated_ad_spend_eur=round(spend_eur, 2),
                ad_reports_found=ad_reports,
                articles_count=ed.get("articles", 0),
                avg_sentiment=ed.get("avg_sentiment"),
                gov_coverage_pct=round(ed.get("gov_coverage_pct", 0.0), 3),
                owner_group=owner_info.get("owner_group", ""),
                owner=owner_info.get("owner", ""),
            ))

        # Compute correlation coefficients
        r_articles = self._pearson_r(
            [(o.estimated_ad_spend_eur, o.articles_count) for o in outlets]
        )
        r_gov = self._pearson_r(
            [(o.estimated_ad_spend_eur, o.gov_coverage_pct) for o in outlets]
        )

        total_spend = sum(o.estimated_ad_spend_eur for o in outlets)
        total_articles = sum(o.articles_count for o in outlets)

        return CorrelationReport(
            generated_at=datetime.now(timezone.utc),
            outlets=outlets,
            r_spend_vs_articles=r_articles,
            r_spend_vs_gov_coverage=r_gov,
            total_ad_spend_estimated=round(total_spend, 2),
            total_articles_analyzed=total_articles,
        )

    async def _extract_ad_spending(self) -> dict[str, float]:
        """Extract ad spending estimates from ERC articles.

        Returns a dict mapping outlet names to estimated EUR amounts.
        """
        if self.db is None:
            return {}

        try:
            from sqlalchemy import select
            from src.db.models import Article

            result = await self.db.execute(
                select(Article.content_text, Article.title)
                .where(Article.source_id == "erc_advertising")
                .where(Article.content_text.isnot(None))
                .limit(50)
            )

            spending: dict[str, float] = {}
            for row in result.all():
                text = row[0] or ""
                # Search for EUR amounts near outlet names
                # Patterns like "RTP: 1.234.567,89 €" or "1.234.567,89€"
                amounts = re.findall(
                    r"([\d.,]+)\s*[€E]\s*(?:euros?)?",
                    text, re.IGNORECASE,
                )
                for amt_str in amounts[:50]:  # Cap per document
                    try:
                        # Normalize Portuguese number format
                        cleaned = amt_str.replace(".", "").replace(",", ".")
                        amount = float(cleaned)
                    except ValueError:
                        continue

                    # Find nearest outlet name before this amount
                    idx = text.find(amt_str)
                    before = text[max(0, idx - 200):idx].lower()
                    for outlet_id, patterns in self._OUTLET_PATTERNS.items():
                        for pat in patterns:
                            if pat in before:
                                display = outlet_id.replace("_", " ").title()
                                spending[display] = spending.get(display, 0) + amount
                                break

            return spending
        except Exception as exc:
            logger.warning("Failed to extract ad spending: %s", exc)
            return {}

    async def _get_editorial_metrics(self) -> dict[str, dict]:
        """Get editorial metrics per outlet from the database."""
        if self.db is None:
            return {}

        try:
            from sqlalchemy import select, func
            from src.db.models import Article, Source

            # Fetch media source IDs, then filter articles in Python
            # to avoid SQLite string comparison quirks with IN/joins.
            src_result = await self.db.execute(
                select(Source.id).where(
                    Source.category.in_(["mainstream", "agency"]),
                )
            )
            media_source_ids = {row[0] for row in src_result.all()}

            if not media_source_ids:
                return {}

            # Fetch all article source_id/count pairs (any text), filter in Python.
            # Mainstream RSS scrapers only store summaries, not full content_text.
            from sqlalchemy import or_
            result = await self.db.execute(
                select(
                    Article.source_id,
                    func.count(Article.id).label("count"),
                )
                .where(or_(
                    Article.content_text.isnot(None),
                    Article.summary.isnot(None),
                ))
                .group_by(Article.source_id)
            )

            # Filter to only media outlet sources
            metrics: dict[str, dict] = {}
            for row in result.all():
                source_id = row[0]
                if source_id not in media_source_ids:
                    continue
                count = row[1]

                # Check for government coverage
                gov_count = await self._count_gov_articles(source_id)

                metrics[source_id] = {
                    "articles": count,
                    "gov_coverage_pct": (
                        gov_count / count if count > 0 else 0.0
                    ),
                    "avg_sentiment": None,  # Requires sentiment pipeline
                }

            return metrics
        except Exception as exc:
            logger.warning("Failed to get editorial metrics: %s", exc)
            return {}

    async def _count_gov_articles(self, source_id: str) -> int:
        """Count articles mentioning government-related terms."""
        if self.db is None:
            return 0
        try:
            from sqlalchemy import select, func, or_
            from src.db.models import Article

            gov_terms = ["governo", "ministério", "primeiro-ministro",
                         "presidente", "conselho de ministros"]

            # Check both content_text and summary for gov terms
            conditions = []
            for term in gov_terms:
                conditions.append(func.lower(func.coalesce(Article.content_text, Article.summary, "")).contains(term))

            result = await self.db.execute(
                select(func.count(Article.id))
                .where(Article.source_id == source_id)
                .where(or_(*conditions))
            )
            return result.scalar() or 0
        except Exception:
            return 0

    def _load_ownership_map(self) -> dict[str, dict]:
        """Load ownership info mapped by outlet ID."""
        try:
            from src.config.ownership import load_ownership

            config = load_ownership()
            return {
                o.id: {
                    "name": o.name,
                    "owner": o.owner,
                    "owner_group": o.owner_group,
                }
                for o in config.outlets
            }
        except Exception:
            return {}

    @staticmethod
    def _pearson_r(pairs: list[tuple[float, float]]) -> float | None:
        """Compute Pearson's r correlation coefficient."""
        n = len(pairs)
        if n < 3:
            return None

        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        num = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
        denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))

        if denom_x == 0 or denom_y == 0:
            return None

        return round(num / (denom_x * denom_y), 4)
