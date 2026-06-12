// ── API Response Types ──────────────────────────────────────────────────────

export interface DbStatus {
  exists: boolean;
  size_mb: number;
  mtime?: string;
  tables?: string[];
  connectable?: boolean;
}

export interface OverviewResponse {
  generated_at: string;
  _server_ms: number;
  databases: Record<string, DbStatus>;
  justice?: {
    corruption_years: number | null;
    corruption_latest: number | null;
    corruption_latest_year: number | null;
    ml_latest: number | null;
    ml_latest_year: number | null;
    court_pending: number | null;
    court_pending_year: number | null;
    prison_population: number | null;
    prison_year: number | null;
  };
  ine?: {
    pensionistas: number | null;
    pensionistas_year: number | null;
    foreign_residents: number | null;
    foreign_year: number | null;
    crime_rate: number | null;
    crime_year: number | null;
    natural_growth: number | null;
    natural_growth_year: number | null;
  };
  procurement?: {
    total_contracts: number | null;
    years_available: number | null;
    year_min: number | null;
    year_max: number | null;
    total_value: number | null;
  };
  top_findings?: TopFindings;
}

// ── Justice ─────────────────────────────────────────────────────────────────

export interface CorruptionTrend {
  year: number;
  corruption: number | null;
  money_laundering: number | null;
}

export interface CourtMovement {
  year: number;
  entered: number;
  finalized: number;
  pending: number;
  resolution_rate: number;
}

export interface PrisonEntry {
  year: number;
  count: number;
}

export interface JusticeDataset {
  dataset: string;
  category: string;
  records: number;
  year_min: number;
  year_max: number;
}

export interface JusticeResponse {
  corruption_trend: CorruptionTrend[];
  court_movements: CourtMovement[];
  prison_population: PrisonEntry[];
  datasets: JusticeDataset[];
  _server_ms?: number;
}

// ── Procurement ─────────────────────────────────────────────────────────────

export interface ProcurementStats {
  total: number | null;
  total_value: number | null;
  year_min: number | null;
  year_max: number | null;
}

export interface ProcurementYear {
  year: number;
  contracts: number;
  value: number | null;
}

export interface ProcurementProcedure {
  tipoprocedimento: string;
  contracts: number;
  value: number | null;
}

export interface DirectAwards {
  count: number | null;
  pct: number;
}

export interface PriceInflation {
  count: number | null;
  with_base_price: number | null;
}

export interface SelfReferencing {
  count: number;
  sample_size: number;
}

export interface TopBuyer {
  nif: string;
  name: string;
  contracts: number;
  value: number | null;
}

export interface TopSellerHint {
  adjudicatarios: string;
  cnt: number;
  value: number | null;
}

export interface MunicipalityRow {
  municipality: string;
  contracts: number;
  value: number | null;
}

export interface SingleBidderTimelineRow {
  year: number;
  total: number;
  single_bidder: number;
  single_bidder_pct: number;
}

export interface ProcurementResponse {
  stats: ProcurementStats;
  by_year: ProcurementYear[];
  by_procedure: ProcurementProcedure[];
  direct_awards: DirectAwards;
  price_inflation: PriceInflation;
  self_referencing: SelfReferencing;
  top_buyers: TopBuyer[];
  top_sellers_hint: TopSellerHint[];
  by_municipality: MunicipalityRow[];
  single_bidder_timeline: SingleBidderTimelineRow[];
  _server_ms?: number;
}

// ── Social (INE) ────────────────────────────────────────────────────────────

export interface YearValue {
  year: number;
  total: number;
}

export interface CrimeRateYear {
  year: number;
  rate: number;
}

export interface RegionValue {
  region: string;
  value: number;
}

export interface IndicatorMeta {
  indicator_code: string;
  indicator_name: string;
  category: string;
  records: number;
  year_min: number;
  year_max: number;
}

export interface SocialResponse {
  immigration: YearValue[];
  pensionistas: YearValue[];
  avg_pension: YearValue[];
  early_retirement: YearValue[];
  natural_growth: YearValue[];
  crime_rate: CrimeRateYear[];
  immigration_by_region: RegionValue[];
  indicators: IndicatorMeta[];
  _server_ms?: number;
}

// ── Cross-Reference ─────────────────────────────────────────────────────────

export interface TrendPoint {
  year: number;
  value: number;
}

export interface ImmigrationCrimeCorrelation {
  pearson_r: number;
  r_squared: number;
  overlap_years: number[];
  n: number;
  interpretation: string;
}

export interface RiskSignal {
  signal: string;
  severity: "high" | "medium" | "low" | "info";
  detail: string;
}

export interface CrossRefResponse {
  corruption_trend: TrendPoint[];
  ml_trend: TrendPoint[];
  court_pending_trend: TrendPoint[];
  crime_trend: TrendPoint[];
  immigration_trend: TrendPoint[];
  pension_trend: TrendPoint[];
  procurement_signals: { direct_award_pct: number; total_contracts: number; error?: string };
  immigration_crime_correlation: ImmigrationCrimeCorrelation;
  risk_signals: RiskSignal[];
  _server_ms?: number;
}

// ── Top Findings (from run_corruption_scan.py → data/summary/top_findings.json) ──

export type FindingSeverity = "critical" | "high" | "medium" | "low" | "info";

export interface Finding {
  source: string;        // e.g. "justice_xref", "bid_pattern", "anomaly_scanner"
  severity: FindingSeverity;
  category: string;      // e.g. "crossref", "bidding", "anomaly", "temporal", "geographic", "supplier", "procurement", "composite"
  signal: string;        // short machine label, e.g. "money_laundering_rising"
  detail: string;        // human-readable explanation, e.g. "+200% over 3-year trend"
}

export interface TopFindings {
  generated_at: string;
  total_findings: number;
  by_severity: Record<FindingSeverity, number>;
  findings: Finding[];
}

// ── Health ──────────────────────────────────────────────────────────────────

export interface HealthResponse {
  databases: Record<string, DbStatus>;
  timestamp: string;
}

// ── Transparency ────────────────────────────────────────────────────────────

export interface TableInfo {
  rows: number;
  columns: string[];
}

export interface TransparencyResponse {
  tables: string[];
  [key: string]: unknown;
  _server_ms?: number;
}
