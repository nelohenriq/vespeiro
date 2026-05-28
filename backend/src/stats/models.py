"""Pydantic models for the Vespeiro stats.json schema."""

from datetime import datetime
from pydantic import BaseModel


class CategoryStats(BaseModel):
    """Article and source counts grouped by category."""
    sources: int = 0
    articles: int = 0
    articles_today: int = 0


class OutletDependency(BaseModel):
    """Lusa dependency metrics for a single outlet."""
    pct: float = 0.0
    stories: int = 0
    lusa_derived: int = 0


class OutletDivergence(BaseModel):
    """Aggregated divergence metrics per outlet.

    Mapped from the actual :class:`src.analysis.divergence.models.OutletDivergenceSummary`
    via :func:`src.analysis.divergence.reporter.aggregate_summary`.
    """
    avg: float = 0.0
    stories: int = 0
    avg_omission: float = 0.0
    avg_sentiment_shift: float = 0.0
    avg_quote_fidelity: float = 0.0
    avg_headline_divergence: float = 0.0


class SilencedStory(BaseModel):
    """A story covered internationally but not in Portugal."""
    title: str = ""
    international_sources: int = 0
    pt_coverage: int = 0
    gap_pct: float = 0.0
    sources: list[str] = []


class OmittedFact(BaseModel):
    """A fact that was frequently omitted across multiple analyses."""
    text: str = ""
    count: int = 0
    category: str = ""


class SourceMetrics(BaseModel):
    """Aggregated source and article counts."""
    total: int = 0
    active: int = 0
    articles_total: int = 0
    articles_today: int = 0
    articles_per_source: dict[str, int] = {}
    per_category: dict[str, CategoryStats] = {}


class LusaDependencyMetrics(BaseModel):
    """Lusa dependency metrics — placeholder until Phase 1 is built."""
    global_pct: float | None = None
    per_outlet: dict[str, OutletDependency] = {}
    per_topic: dict[str, float] = {}


class DivergenceMetrics(BaseModel):
    """Aggregated divergence metrics across all outlets.

    Populated by :meth:`StatsGenerator._divergence_metrics` which reads
    JSON reports from the divergence analysis pipeline and delegates to
    :func:`src.analysis.divergence.reporter.aggregate_summary`.
    """
    global_avg: float | None = None
    per_outlet: dict[str, OutletDivergence] = {}
    top_omitted_facts: list[OmittedFact] = []


class SilenceMetrics(BaseModel):
    """Silence detection metrics — placeholder until Phase 2 is built."""
    today: int = 0
    avg_7d: float = 0.0
    top_silenced: list[SilencedStory] = []


class Timelines(BaseModel):
    """7-day historical timelines for key metrics."""
    lusa_dependency_7d: list[float] = []
    divergence_avg_7d: list[float] = []
    articles_daily_7d: list[int] = []
    silence_daily_7d: list[int] = []
    dates_7d: list[str] = []


class SystemMetrics(BaseModel):
    """System health metrics."""
    uptime_pct: float = 0.0
    sources_healthy: int = 0
    sources_failing: int = 0
    last_scrape: datetime | None = None
    last_error: str | None = None


class StatsPayload(BaseModel):
    """Top-level stats.json payload — the single source of truth for the dashboard."""
    generated_at: datetime
    version: str = "1.0"
    sources: SourceMetrics = SourceMetrics()
    lusa_dependency: LusaDependencyMetrics = LusaDependencyMetrics()
    divergence: DivergenceMetrics = DivergenceMetrics()
    silence: SilenceMetrics = SilenceMetrics()
    timelines: Timelines = Timelines()
    system: SystemMetrics = SystemMetrics()
