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


class PersonnelNode(BaseModel):
    """A node in the personnel network graph."""
    id: str = ""
    label: str = ""
    type: str = ""  # person, organization, government
    group: str = ""  # media, state, regulator, other


class PersonnelEdge(BaseModel):
    """An edge in the personnel network graph."""
    source: str = ""
    target: str = ""
    label: str = ""
    value: int = 1


class PersonnelNetworkMetrics(BaseModel):
    """Personnel / revolving-door network graph metrics."""
    nodes: list[PersonnelNode] = []
    edges: list[PersonnelEdge] = []
    total_people: int = 0
    total_appointments: int = 0


class TopicGapItem(BaseModel):
    """A single topic's parliament-vs-media gap."""
    topic: str = ""
    parliament_mentions: int = 0
    media_mentions: int = 0
    media_outlets: int = 0
    gap_score: float = 0.0
    top_media_outlets: list[str] = []


class ParliamentGapMetrics(BaseModel):
    """Parliament-media coverage gap metrics."""
    overall_gap_score: float = 0.0
    total_parliament_docs: int = 0
    total_media_articles: int = 0
    topics: list[TopicGapItem] = []
    most_discussed_only_parliament: list[str] = []
    most_covered_in_media: list[str] = []


class OutletCorrelationItem(BaseModel):
    """Correlation data for a single outlet."""
    outlet_id: str = ""
    outlet_name: str = ""
    estimated_ad_spend_eur: float = 0.0
    articles_count: int = 0
    avg_sentiment: float | None = None
    gov_coverage_pct: float = 0.0
    owner_group: str = ""
    owner: str = ""


class CorrelationMetrics(BaseModel):
    """Ad-editorial correlation metrics."""
    outlets: list[OutletCorrelationItem] = []
    r_spend_vs_articles: float | None = None
    r_spend_vs_gov_coverage: float | None = None
    total_ad_spend_estimated: float = 0.0
    total_articles_analyzed: int = 0


class InfluenceMapMetrics(BaseModel):
    """Composite Influence Map — a unified capture score."""
    # Composite capture score (0-1, higher = more captured)
    capture_score: float = 0.0
    # Sub-scores
    personnel_density: float = 0.0
    parliament_gap: float = 0.0
    ad_correlation_strength: float = 0.0
    # Narrative
    summary: str = ""


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
    # Phase 3 — Influence Map
    personnel: PersonnelNetworkMetrics = PersonnelNetworkMetrics()
    parliament_gap: ParliamentGapMetrics = ParliamentGapMetrics()
    ad_correlation: CorrelationMetrics = CorrelationMetrics()
    influence: InfluenceMapMetrics = InfluenceMapMetrics()
