"""StatsGenerator — collects all Vespeiro platform metrics into a single StatsPayload.

Usage inside a GHA step or CLI script::

    from src.stats.generator import StatsGenerator

    async def main():
        generator = StatsGenerator(db_session=session)
        payload = await generator.collect()
        print(payload.model_dump_json(indent=2))
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import select, func

from src.db.models import Source, Article
from src.stats.models import (
    CategoryStats,
    OutletDivergence,
    OmittedFact,
    SourceMetrics,
    LusaDependencyMetrics,
    DivergenceMetrics,
    SilenceMetrics,
    Timelines,
    SystemMetrics,
    StatsPayload,
    PersonnelNetworkMetrics,
    PersonnelNode,
    PersonnelEdge,
    ParliamentGapMetrics,
    TopicGapItem,
    CorrelationMetrics,
    OutletCorrelationItem,
    InfluenceMapMetrics,
)

logger = logging.getLogger(__name__)


class StatsGenerator:
    """Aggregates all platform metrics into a single :class:`StatsPayload`.

    Each ``_*_metrics()`` method is self-contained and returns safe defaults
    (zeros, empty lists, ``None``) if the data source is unavailable.

    Parameters
    ----------
    db_session:
        Optional async SQLAlchemy session for DB-backed metrics
        (source counts, article counts, system health).
        If ``None``, DB-dependent methods return defaults.
    reports_dir:
        Path to the directory containing divergence report JSON files
        (output by ``run_analysis.py --output``). Defaults to
        ``reports/divergence/`` relative to the current working directory.
    """

    def __init__(
        self,
        db_session: object | None = None,
        reports_dir: str | Path | None = None,
    ):
        self.db = db_session
        self.reports_dir = Path(reports_dir or "reports/divergence")

    # ── Public API ──────────────────────────────────────────────────────────

    async def collect(self) -> StatsPayload:
        """Run all metric collectors and return the aggregated payload."""
        # Run all collectors in parallel where possible
        sources = await self._source_metrics()
        lusa = await self._lusa_metrics()
        divergence = self._divergence_metrics()
        silence = await self._silence_metrics()
        timelines = await self._timelines()
        system = await self._system_health()

        # Phase 3 collectors
        personnel = await self._personnel_metrics()
        parliament_gap = await self._parliament_gap_metrics()
        ad_correlation = await self._correlation_metrics()
        influence = self._influence_metrics(personnel, parliament_gap, ad_correlation)

        return StatsPayload(
            generated_at=datetime.now(timezone.utc),
            sources=sources,
            lusa_dependency=lusa,
            divergence=divergence,
            silence=silence,
            timelines=timelines,
            system=system,
            personnel=personnel,
            parliament_gap=parliament_gap,
            ad_correlation=ad_correlation,
            influence=influence,
        )

    # ── Phase 3: Influence Map ───────────────────────────────────────────────

    async def _personnel_metrics(self) -> PersonnelNetworkMetrics:
        """Build the personnel/revolving-door network graph.

        Delegates to :class:`PersonnelNetworkBuilder` which queries DRE
        articles and extracts person-organization connections.

        Returns empty defaults if no DB session or no DRE data.
        """
        if self.db is None:
            return PersonnelNetworkMetrics()

        try:
            from src.analysis.personnel import PersonnelNetworkBuilder

            builder = PersonnelNetworkBuilder(db_session=self.db)
            network = await builder.build()

            return PersonnelNetworkMetrics(
                nodes=[
                    PersonnelNode(
                        id=n.id, label=n.label, type=n.type, group=n.group,
                    )
                    for n in network.nodes
                ],
                edges=[
                    PersonnelEdge(
                        source=e.source, target=e.target,
                        label=e.label, value=e.value,
                    )
                    for e in network.edges
                ],
                total_people=network.total_people,
                total_appointments=network.total_appointments,
            )
        except Exception as exc:
            logger.warning("Failed to build personnel network: %s", exc)
            return PersonnelNetworkMetrics()

    async def _parliament_gap_metrics(self) -> ParliamentGapMetrics:
        """Analyze the gap between parliamentary debate and media coverage.

        Delegates to :class:`ParliamentGapAnalyzer` which compares
        parliament docs to media outlet articles.

        Returns empty defaults if no DB session.
        """
        if self.db is None:
            return ParliamentGapMetrics()

        try:
            from src.analysis.gap import ParliamentGapAnalyzer

            analyzer = ParliamentGapAnalyzer(db_session=self.db)
            report = await analyzer.analyze()

            return ParliamentGapMetrics(
                overall_gap_score=report.overall_gap_score,
                total_parliament_docs=report.total_parliament_docs,
                total_media_articles=report.total_media_articles,
                topics=[
                    TopicGapItem(
                        topic=t.topic,
                        parliament_mentions=t.parliament_mentions,
                        media_mentions=t.media_mentions,
                        media_outlets=t.media_outlets,
                        gap_score=t.gap_score,
                        top_media_outlets=t.top_media_outlets,
                    )
                    for t in report.topics
                ],
                most_discussed_only_parliament=report.most_discussed_only_parliament,
                most_covered_in_media=report.most_covered_in_media,
            )
        except Exception as exc:
            logger.warning("Failed to analyze parliament gap: %s", exc)
            return ParliamentGapMetrics()

    async def _correlation_metrics(self) -> CorrelationMetrics:
        """Analyze advertising-editorial correlation.

        Delegates to :class:`CorrelationAnalyzer` which compares ERC ad
        spending data with outlet editorial coverage patterns.

        Returns empty defaults if no DB session.
        """
        if self.db is None:
            return CorrelationMetrics()

        try:
            from src.analysis.correlation import CorrelationAnalyzer

            analyzer = CorrelationAnalyzer(db_session=self.db)
            report = await analyzer.analyze()

            return CorrelationMetrics(
                outlets=[
                    OutletCorrelationItem(
                        outlet_id=o.outlet_id,
                        outlet_name=o.outlet_name,
                        estimated_ad_spend_eur=o.estimated_ad_spend_eur,
                        articles_count=o.articles_count,
                        avg_sentiment=o.avg_sentiment,
                        gov_coverage_pct=o.gov_coverage_pct,
                        owner_group=o.owner_group,
                        owner=o.owner,
                    )
                    for o in report.outlets
                ],
                r_spend_vs_articles=report.r_spend_vs_articles,
                r_spend_vs_gov_coverage=report.r_spend_vs_gov_coverage,
                total_ad_spend_estimated=report.total_ad_spend_estimated,
                total_articles_analyzed=report.total_articles_analyzed,
            )
        except Exception as exc:
            logger.warning("Failed to analyze ad correlation: %s", exc)
            return CorrelationMetrics()

    def _influence_metrics(
        self,
        personnel: PersonnelNetworkMetrics,
        parliament_gap: ParliamentGapMetrics,
        ad_correlation: CorrelationMetrics,
    ) -> InfluenceMapMetrics:
        """Compute a composite Influence Map Capture Score.

        Combines:
        - Personnel density: normalized count of appointments/people
        - Parliament gap: 1 - overall_gap_score (higher = more gap detected)
        - Ad correlation: absolute value of Pearson's r (higher = stronger correlation)

        Each sub-score is 0-1; capture_score is the weighted average.
        """
        # Personnel density (0-1 scale, capped at 50 people)
        personnel_density = min(personnel.total_people / 50.0, 1.0) if personnel.total_people > 0 else 0.0

        # Parliament gap (already 0-1, higher = bigger gap = more capture)
        parliament_gap_score = parliament_gap.overall_gap_score

        # Ad correlation strength (absolute Pearson's r, 0-1)
        r_val = ad_correlation.r_spend_vs_gov_coverage
        ad_corr_strength = abs(r_val) if r_val is not None else 0.0

        # Composite capture score (weighted average)
        capture_score = round(
            (personnel_density * 0.3) +
            (parliament_gap_score * 0.4) +
            (ad_corr_strength * 0.3),
            3,
        )

        # Narrative summary
        if capture_score > 0.7:
            summary = "Alta captura: fortes conexões pessoais, grande fosso parlamento-media, e correlação publicidade-cobertura significativa."
        elif capture_score > 0.4:
            summary = "Captura moderada: existem conexões entre Estado e media que merecem atenção."
        elif capture_score > 0.2:
            summary = "Baixa captura: alguns sinais de influência mas sem evidência forte de captura sistémica."
        else:
            summary = "Captura mínima: não foi detetada evidência significativa de captura do ecossistema mediático."

        return InfluenceMapMetrics(
            capture_score=capture_score,
            personnel_density=round(personnel_density, 3),
            parliament_gap=round(parliament_gap_score, 3),
            ad_correlation_strength=round(ad_corr_strength, 3),
            summary=summary,
        )

    # ── Source metrics ──────────────────────────────────────────────────────

    async def _source_metrics(self) -> SourceMetrics:
        """Query the database for source and article counts.

        Returns safe defaults if no DB session is available or the query fails.
        """
        if self.db is None:
            return SourceMetrics()

        try:
            # ── Total sources ──
            result = await self.db.execute(select(func.count(Source.id)))
            total = result.scalar() or 0

            # ── Active sources ──
            result = await self.db.execute(
                select(func.count(Source.id)).where(Source.is_active.is_(True))
            )
            active = result.scalar() or 0

            # ── Total articles ──
            result = await self.db.execute(select(func.count(Article.id)))
            articles_total = result.scalar() or 0

            # ── Articles today ──
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            result = await self.db.execute(
                select(func.count(Article.id)).where(
                    Article.collected_at >= today_start
                )
            )
            articles_today = result.scalar() or 0

            # ── Articles per source ──
            result = await self.db.execute(
                select(Article.source_id, func.count(Article.id))
                .group_by(Article.source_id)
            )
            per_source: dict[str, int] = {}
            for row in result.all():
                per_source[row[0]] = row[1]

            # ── Articles per category ──
            result = await self.db.execute(
                select(
                    Source.category,
                    func.count(Source.id.distinct()).label("sources_in_cat"),
                    func.count(Article.id).label("articles_in_cat"),
                    func.count(Article.id).filter(
                        Article.collected_at >= today_start
                    ).label("articles_today_in_cat"),
                )
                .outerjoin(Article, Source.id == Article.source_id)
                .group_by(Source.category)
            )
            per_category: dict[str, CategoryStats] = {}
            for row in result.all():
                per_category[row.category] = CategoryStats(
                    sources=row.sources_in_cat,
                    articles=row.articles_in_cat,
                    articles_today=row.articles_today_in_cat,
                )

            return SourceMetrics(
                total=total,
                active=active,
                articles_total=articles_total,
                articles_today=articles_today,
                articles_per_source=per_source,
                per_category=per_category,
            )

        except Exception as exc:
            logger.warning("Failed to query source metrics: %s", exc)
            return SourceMetrics()

    # ── Lusa dependency ─────────────────────────────────────────────────────

    async def _lusa_metrics(self) -> LusaDependencyMetrics:
        """Analyze dependency of Portuguese outlets on Lusa news agency.

        Delegates to :class:`LusaDependencyAnalyzer` which compares outlet
        articles to Lusa articles using TF-IDF cosine similarity.

        Returns empty/default values if no DB session is available.
        """
        if self.db is None:
            return LusaDependencyMetrics()

        from src.analysis.dependency import LusaDependencyAnalyzer

        analyzer = LusaDependencyAnalyzer(db_session=self.db)
        return await analyzer.analyze()

    # ── Divergence metrics ──────────────────────────────────────────────────

    def _divergence_metrics(self) -> DivergenceMetrics:
        """Read divergence reports from JSON files and aggregate per outlet.

        Reads all ``*.json`` files from ``self.reports_dir``, parses each into
        a :class:`DivergenceReport`, groups by ``portuguese_outlet_id``, and
        delegates to :func:`aggregate_summary` for each group.

        Returns safe defaults if the directory is missing, empty, or parsing fails.
        """
        from src.analysis.divergence.models import (
            DivergenceReport,
            Fact,
            FactCategory,
        )
        from src.analysis.divergence.reporter import aggregate_summary

        reports = self._load_divergence_reports()
        if not reports:
            return DivergenceMetrics()

        # Group by outlet
        per_outlet: dict[str, list[DivergenceReport]] = {}
        for r in reports:
            per_outlet.setdefault(r.portuguese_outlet_id, []).append(r)

        # Aggregate per outlet
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        outlet_metrics: dict[str, OutletDivergence] = {}

        for outlet_id, reps in per_outlet.items():
            summary = aggregate_summary(reps, outlet_id, week_ago, now)

            # Overall global average for this outlet
            scores = [
                r.overall_divergence_score for r in reps
                if r.overall_divergence_score is not None
            ]
            avg = sum(scores) / len(scores) if scores else 0.0

            outlet_metrics[outlet_id] = OutletDivergence(
                avg=avg,
                stories=summary.stories_analyzed,
                avg_omission=summary.avg_omission,
                avg_sentiment_shift=summary.avg_sentiment_shift,
                avg_quote_fidelity=summary.avg_quote_fidelity,
                avg_headline_divergence=summary.avg_headline_divergence,
            )

        # Global average across all outlets
        all_scores = [
            r.overall_divergence_score for r in reports
            if r.overall_divergence_score is not None
        ]
        global_avg = sum(all_scores) / len(all_scores) if all_scores else None

        # Top omitted facts
        fact_counter: dict[str, int] = {}
        fact_category: dict[str, str] = {}
        for r in reports:
            for f in r.omitted_facts:
                fact_counter[f.text] = fact_counter.get(f.text, 0) + 1
                if f.text not in fact_category:
                    fact_category[f.text] = (
                        f.category.value if isinstance(f.category, FactCategory)
                        else str(f.category)
                    )

        top_facts = [
            OmittedFact(text=txt, count=cnt, category=fact_category.get(txt, ""))
            for txt, cnt in sorted(fact_counter.items(), key=lambda x: -x[1])[:10]
        ]

        return DivergenceMetrics(
            global_avg=global_avg,
            per_outlet=outlet_metrics,
            top_omitted_facts=top_facts,
        )

    def _load_divergence_reports(self) -> list:
        """Load all divergence report JSON files from ``self.reports_dir``.

        Returns an empty list if the directory doesn't exist, is empty,
        or files fail to parse.
        """
        from src.analysis.divergence.models import DivergenceReport

        if not self.reports_dir.is_dir():
            logger.debug("Divergence reports directory not found: %s", self.reports_dir)
            return []

        reports: list[DivergenceReport] = []
        for path in sorted(self.reports_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Handle datetime fields that arrive as ISO strings
                if "analyzed_at" in data and isinstance(data["analyzed_at"], str):
                    data["analyzed_at"] = datetime.fromisoformat(data["analyzed_at"])
                reports.append(DivergenceReport(**data))
            except Exception as exc:
                logger.warning("Failed to parse divergence report %s: %s", path.name, exc)

        return reports

    # ── Silence metrics ──────────────────────────────────────────────────────

    async def _silence_metrics(self) -> SilenceMetrics:
        """Detect stories covered internationally but not in Portuguese outlets.

        Delegates to :class:`SilenceAnalyzer` which compares international
        articles to Portuguese outlet articles using TF-IDF cosine similarity.

        Returns empty/default values if no DB session is available.
        """
        if self.db is None:
            return SilenceMetrics()

        from src.analysis.silence import SilenceAnalyzer

        analyzer = SilenceAnalyzer(db_session=self.db)
        return await analyzer.analyze()

    # ── Timelines ────────────────────────────────────────────────────────────

    async def _timelines(self) -> Timelines:
        """Build 7-day historical timelines.

        Sources:
        - Article counts are queried from the DB (if available).
        - Divergence and silence timelines fall back to empty arrays.
        - Lusa dependency timeline is a placeholder.

        Falls back to empty arrays if insufficient data.
        """
        today = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        dates: list[str] = []
        articles_daily: list[int] = []

        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            dates.append(day.strftime("%Y-%m-%d"))

            if self.db is not None:
                articles_daily.append(
                    await self._get_article_count_for_day(day)
                )
            else:
                articles_daily.append(0)

        # Divergence timeline: compute per-day averages from loaded reports
        reports = self._load_divergence_reports()
        div_avg_7d: list[float] = []
        for i in range(7):
            day_start = today - timedelta(days=6 - i)
            day_end = day_start + timedelta(days=1)
            day_reports = [
                r for r in reports
                if day_start <= r.analyzed_at < day_end
            ]
            scores = [
                r.overall_divergence_score for r in day_reports
                if r.overall_divergence_score is not None
            ]
            div_avg_7d.append(
                sum(scores) / len(scores) if scores else 0.0
            )

        # Lusa dependency timeline: per-day averages
        lusa_dep_7d: list[float] = []
        if self.db is not None:
            from src.analysis.dependency import LusaDependencyAnalyzer

            dep_analyzer = LusaDependencyAnalyzer(db_session=self.db)
            lusa_dep_7d = await dep_analyzer.daily_timeline(days=7)
        else:
            lusa_dep_7d = [0.0] * 7

        # Silence timeline: per-day silenced story counts
        silence_daily_7d: list[int] = []
        if self.db is not None:
            from src.analysis.silence import SilenceAnalyzer

            sil_analyzer = SilenceAnalyzer(db_session=self.db)
            silence_daily_7d = await sil_analyzer.daily_timeline(days=7)
        else:
            silence_daily_7d = [0] * 7

        return Timelines(
            lusa_dependency_7d=lusa_dep_7d,
            divergence_avg_7d=div_avg_7d,
            articles_daily_7d=articles_daily,
            silence_daily_7d=silence_daily_7d,
            dates_7d=dates,
        )

    async def _get_article_count_for_day(self, day: datetime) -> int:
        """Query article count for a specific calendar day."""
        if self.db is None:
            return 0
        try:
            day_start = day
            day_end = day + timedelta(days=1)
            result = await self.db.execute(
                select(func.count(Article.id)).where(
                    Article.collected_at >= day_start,
                    Article.collected_at < day_end,
                )
            )
            return result.scalar() or 0
        except Exception as exc:
            logger.warning("Failed to query article count for %s: %s", day.date(), exc)
            return 0

    # ── System health ───────────────────────────────────────────────────────

    async def _system_health(self) -> SystemMetrics:
        """Check source health and return system metrics.

        Currently returns defaults with a best-effort check of
        source counts vs activity. Full health monitoring is planned
        for the pipeline monitor module.
        """
        if self.db is None:
            return SystemMetrics()

        try:
            # Count active and total sources
            result = await self.db.execute(select(func.count(Source.id)))
            total = result.scalar() or 0

            result = await self.db.execute(
                select(func.count(Source.id)).where(Source.is_active.is_(True))
            )
            active = result.scalar() or 0

            # Find most recent article scrape
            result = await self.db.execute(
                select(func.max(Article.collected_at))
            )
            last_scrape: datetime | None = result.scalar()

            return SystemMetrics(
                uptime_pct=100.0 if total > 0 else 0.0,
                sources_healthy=active,
                sources_failing=total - active,
                last_scrape=last_scrape,
                last_error=None,
            )

        except Exception as exc:
            logger.warning("Failed to query system health: %s", exc)
            return SystemMetrics()


