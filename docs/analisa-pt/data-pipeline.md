# Data Pipeline Architecture

> How analisa.pt fetches, processes, and serves data from 10+ government sources through 26 plugins into a unified dataset.

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    RAW SOURCES (10+)                         │
│  INE │ SNS │ IPMA │ PORDATA │ BASE │ ANACOM │ Open-Meteo   │
│  ERSAR │ IEFP │ OSM/GTFS │ SEF │ BdP                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              26 PLUGIN PROCESSORS                           │
│                                                             │
│  Processing Patterns:                                       │
│  • Direct ingestion (PORDATA, INE indicators)               │
│  • Spatial projection (SNS facilities → municipality)        │
│  • Derived computation (affordability, composites)           │
│  • Aggregation (hourly → daily, per-capita)                 │
│  • Normalization (per 10k residents)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│           UNIFIED DATASET (211 layers)                      │
│                                                             │
│  63,492 records │ 2,886 H3 hexes │ 308 municipalities      │
│  Parish-level granularity where available                   │
│  + provenance metadata per indicator per area               │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  API ENDPOINTS                              │
│                                                             │
│  REST: /api/municipality-dataset, /api/history, etc.        │
│  MCP:  30+ tools (search, rank, compare, contracts)         │
│  UI:   Interactive map, rankings, comparisons               │
└─────────────────────────────────────────────────────────────┘
```

## 26 Data Plugins

### Core Data Plugins

| Plugin ID | Name | Layers | Description |
|---|---|---|---|
| `ine-composite` | INE Composite | 42 | Crime, economy, housing from INE |
| `sns-hospital-metrics-catalog` | SNS Hospital Metrics | 4 | Urgency, beds, consults, primary care |
| `sns-primary-care-catalog` | SNS Primary Care | 1 | Family doctor assignment |
| `pordata` | PORDATA Municipal Summary | 47 | Demographics, education, economy, health |
| `iefp-unemployment` | IEFP Unemployment | 7 | Monthly registered unemployment |
| `ersar-agua-segura` | ERSAR Water Safety | 4 | Water quality, sanitation |

### Infrastructure & Environment Plugins

| Plugin ID | Name | Layers | Description |
|---|---|---|---|
| `infrastructure-access` | Hospital Proximity | 2 | Hospital distance, 15km coverage |
| `infrastructure-mobility-access` | Mobility Access | 8 | Airports, highways, rail, major roads |
| `leisure-green-spaces` | Parks & Green Spaces | 2 | Park count, green space presence |
| `leisure-cultural-coastal` | Cultural + Coastal | 7 | Cinemas, theatres, beaches, sports |
| `ipma-climate` | Climate Comfort | 4 | Temperature, comfort days, heat risk |
| `air-quality` | Air Quality | 4 | PM2.5, European AQI |
| `connectivity` | ANACOM Connectivity | 4 | Broadband, speed, mobile coverage |
| `nomad-proxies` | Nomad Proxies | 3 | Timezone, coworking, connectivity |

### Economy & Contracts Plugins

| Plugin ID | Name | Layers | Description |
|---|---|---|---|
| `contractsMomentum` | Contract Momentum | 5 | Rolling 12-month procurement indicators |
| `contractsCpvBreakdown` | CPV Category Breakdown | 16 | Spend by sector (construction, IT, etc.) |
| `contractsModifications` | Contract Modifications | 2 | Modification rate, price increase |
| `expanded-indicators` | Economy & Demographics | 10 | Purchasing power, migration, vacancy |
| `tourism` | Tourism | 9 | Overnight stays, occupancy, intensity |

### Derived & Composite Plugins

| Plugin ID | Name | Layers | Description |
|---|---|---|---|
| `density-variants` | Density Variants | 7 | Per-capita normalized metrics |
| `composite-scores` | Composite Scores | 10 | Resilience, affordability, dynamism |
| `ine-region-composite` | INE Region (NUTS II) | 1 | Regional-level indicators |
| `ine-adhoc` | INE Ad-hoc | 0 | Runtime INE catalog search |
| `education-stats` | Education | 4 | Enrollment, retention, completion |
| `social-protection` | Social Protection | 2 | Pensioners, social security |
| `water-waste` | Water/Sanitation/Waste | 6 | Water quality, waste treatment |

## Processing Patterns

### 1. Direct Ingestion
PORDATA and INE indicators loaded as-is from source databases.

### 2. Spatial Projection
Hospital metrics projected from facility locations to municipalities using NUTS III/NUTS II fallbacks.

### 3. Derived Computation
```
buyEffort = (70m² mortgage burden ÷ monthly income) × 100
rentEffort = (70m² rent burden ÷ monthly income) × 100
foreignResidentsShare = foreign residents ÷ resident population
```

### 4. Aggregation
Open-Meteo hourly forecasts → 24h daily averages for PM2.5 and AQI.

### 5. Normalization
Contract values normalized per 10k residents for fair comparison.

### 6. Composite Scoring
```
compositeMunicipalResilience = f(
  compositeEconomicDynamism,
  compositePopulationMomentum,
  compositeServiceAccess,
  compositeSustainability
)
```

## Spatial Indexing

- **H3 hexagonal grid** (resolution 7) for consistent geographic queries
- **Parish-level identifiers** (`parish:110658`) as primary keys
- **Cross-source joins** via shared municipality/parish codes
- **Map visualization** support through standardized geometry

## Update Frequencies

| Frequency | Indicators | Count |
|---|---|---|
| Daily | Air quality (PM2.5, AQI) | 4 |
| Monthly | SNS health, IEFP unemployment, contracts | ~15 |
| Quarterly | Housing prices, ANACOM connectivity | ~10 |
| Yearly | Crime, demographics, PORDATA, climate | ~180 |
| Static | Infrastructure distances, park counts | ~15 |

## Data Flow for Specific Indicators

### Example: SNS Consult Wait Times

```
SNS Transparência API
  → consultas-em-tempo-real endpoint
  → sns-hospital-metrics-catalog plugin
  → Spatial projection to municipality (NUTS III fallback)
  → Provenance: { granularity: "sub-region", isFallback: true }
  → /api/municipality-dataset response
```

### Example: Air Quality

```
Open-Meteo Air Quality API
  → hourly.pm2_5 endpoint
  → air-quality plugin
  → 24h aggregation → daily average
  → Per-municipality calculation
  → Provenance: { granularity: "municipality", isFallback: true }
  → /api/municipality-dataset response
```

### Example: Public Contract Momentum

```
BASE.gov.pt API
  → public_contracts + public_announcements tables
  → contractsMomentum plugin
  → Rolling 12-month aggregation
  → Normalized per 10k residents
  → Provenance: { granularity: "municipality", isFallback: false }
  → /api/municipality-dataset response
```
