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
}
