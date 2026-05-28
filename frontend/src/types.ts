export interface CategoryStats {
  sources: number;
  articles: number;
  articles_today: number;
}

export interface OutletDependency {
  pct: number;
  stories: number;
  lusa_derived: number;
}

export interface OutletDivergence {
  avg: number;
  stories: number;
  avg_omission: number;
  avg_sentiment_shift: number;
  avg_quote_fidelity: number;
  avg_headline_divergence: number;
}

export interface SilencedStory {
  title: string;
  international_sources: number;
  pt_coverage: number;
  gap_pct: number;
  sources: string[];
}

export interface OmittedFact {
  text: string;
  count: number;
  category: string;
}

export interface SourceMetrics {
  total: number;
  active: number;
  articles_total: number;
  articles_today: number;
  articles_per_source: Record<string, number>;
  per_category: Record<string, CategoryStats>;
}

export interface LusaDependencyMetrics {
  global_pct: number | null;
  per_outlet: Record<string, OutletDependency>;
  per_topic: Record<string, number>;
}

export interface DivergenceMetrics {
  global_avg: number | null;
  per_outlet: Record<string, OutletDivergence>;
  top_omitted_facts: OmittedFact[];
}

export interface SilenceMetrics {
  today: number;
  avg_7d: number;
  top_silenced: SilencedStory[];
}

export interface Timelines {
  lusa_dependency_7d: number[];
  divergence_avg_7d: number[];
  articles_daily_7d: number[];
  silence_daily_7d: number[];
  dates_7d: string[];
}

export interface SystemMetrics {
  uptime_pct: number;
  sources_healthy: number;
  sources_failing: number;
  last_scrape: string | null;
  last_error: string | null;
}

export interface StatsPayload {
  generated_at: string;
  version: string;
  sources: SourceMetrics;
  lusa_dependency: LusaDependencyMetrics;
  divergence: DivergenceMetrics;
  silence: SilenceMetrics;
  timelines: Timelines;
  system: SystemMetrics;
  // Phase 3 — Influence Map
  personnel: PersonnelNetworkMetrics;
  parliament_gap: ParliamentGapMetrics;
  ad_correlation: CorrelationMetrics;
  influence: InfluenceMapMetrics;
}

// ── Phase 3: Personnel Network ───────────────────────────────────────────

export interface PersonnelNode {
  id: string;
  label: string;
  type: string;
  group: string;
}

export interface PersonnelEdge {
  source: string;
  target: string;
  label: string;
  value: number;
}

export interface PersonnelNetworkMetrics {
  nodes: PersonnelNode[];
  edges: PersonnelEdge[];
  total_people: number;
  total_appointments: number;
}

// ── Phase 3: Parliament-Media Gap ────────────────────────────────────────

export interface TopicGapItem {
  topic: string;
  parliament_mentions: number;
  media_mentions: number;
  media_outlets: number;
  gap_score: number;
  top_media_outlets: string[];
}

export interface ParliamentGapMetrics {
  overall_gap_score: number;
  total_parliament_docs: number;
  total_media_articles: number;
  topics: TopicGapItem[];
  most_discussed_only_parliament: string[];
  most_covered_in_media: string[];
}

// ── Phase 3: Ad-Editorial Correlation ────────────────────────────────────

export interface OutletCorrelationItem {
  outlet_id: string;
  outlet_name: string;
  estimated_ad_spend_eur: number;
  articles_count: number;
  avg_sentiment: number | null;
  gov_coverage_pct: number;
  owner_group: string;
  owner: string;
}

export interface CorrelationMetrics {
  outlets: OutletCorrelationItem[];
  r_spend_vs_articles: number | null;
  r_spend_vs_gov_coverage: number | null;
  total_ad_spend_estimated: number;
  total_articles_analyzed: number;
}

// ── Phase 3: Influence Map ───────────────────────────────────────────────

export interface InfluenceMapMetrics {
  capture_score: number;
  personnel_density: number;
  parliament_gap: number;
  ad_correlation_strength: number;
  summary: string;
}
