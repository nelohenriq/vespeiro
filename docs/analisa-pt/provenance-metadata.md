# Provenance Metadata & Data Sources

> How analisa.pt tracks where each data point comes from and its quality/reliability.

## Overview

Every indicator value in analisa.pt includes **provenance metadata** that tracks:
- Where the data actually came from (granularity)
- Whether it was projected/fallback from another geography
- What fallback strategy was used
- The chain of resolution

## Provenance Structure

```json
{
  "granularity": "sub-region",
  "isFallback": true,
  "fallbackType": "derived",
  "chain": {
    "resolvedAt": "district-or-sub-region"
  }
}
```

### Fields

| Field | Description |
|---|---|
| `granularity` | Actual geographic level: `municipality`, `sub-region`, `district`, `parish` |
| `isFallback` | `true` if data was projected from a different geography |
| `fallbackType` | Type of fallback: `derived`, `source-missing`, `other` |
| `chain.resolvedAt` | Where the data actually came from |

## Data Sources

### Government Sources

| Source | Code | Data | Frequency | Granularity |
|---|---|---|---|---|
| **INE** (Instituto Nacional de Estatística) | `0012260` | Crime rates | Yearly | Municipality |
| **INE** | `0012261` | Police reports | Yearly | Municipality |
| **INE** | `0012234` | House purchase price | Quarterly | Municipality |
| **INE** | `0012600` | House rent price | Yearly | Municipality |
| **INE** | `0013189` | Population density | Yearly | Municipality |
| **INE** | `0001234` | Resident population | Yearly | Municipality |
| **INE** | `0001274` | Unemployment rate | Quarterly | Municipality |
| **INE** | `0013052` | Housing credit | Yearly | Municipality |
| **INE** | `0013271` | Divorce | Yearly | Municipality |
| **INE** | `0008349` | Births | Yearly | Municipality |
| **INE** | `0009107+csv-2024` | Foreign residents | Yearly | Municipality |

### Health Sources

| Source | Code | Data | Frequency | Granularity |
|---|---|---|---|---|
| **SNS Transparência** | `atendimentos-em-urgencia-triagem-manchester` | Urgency episodes | Monthly | Sub-region |
| **SNS Transparência** | `ocupacao-do-internamento` | Bed occupancy | Monthly | Sub-region |
| **SNS Transparência** | `consultas-em-tempo-real` | Consult wait times | Monthly | Sub-region |
| **SNS Transparência** | `utentes-inscritos-em-cuidados-de-saude-primarios` | Primary care | Monthly | Sub-region |

### Environmental Sources

| Source | Code | Data | Frequency | Granularity |
|---|---|---|---|---|
| **Open-Meteo Archive** | `archive-api.open-meteo.com/v1/archive` | Climate data | Yearly | Municipality |
| **Open-Meteo Air Quality** | `hourly.pm2_5` | PM2.5 | Daily | Municipality |
| **Open-Meteo Air Quality** | `hourly.european_aqi` | European AQI | Daily | Municipality |

### Infrastructure Sources

| Source | Code | Data | Frequency | Granularity |
|---|---|---|---|---|
| **ANACOM NET.mede** | `connectivity_indicators/download_mbps_median` | Download speed | Quarterly | Municipality |
| **ANACOM NET.mede** | `connectivity_indicators/upload_mbps_median` | Upload speed | Quarterly | Municipality |
| **ANACOM NET.mede** | `connectivity_indicators/mobile_4g_pct` | Mobile coverage | Quarterly | Municipality |
| **ANACOM** | `connectivity_indicators/broadband_coverage_pct` | Broadband | Quarterly | Municipality |

### Economic Sources

| Source | Code | Data | Frequency | Granularity |
|---|---|---|---|---|
| **BASE.gov.pt** | `contracts-momentum-12m` | Contract momentum | Monthly | Municipality |
| **BASE.gov.pt** | `contracts-12m-per10k` | Contracts per 10k | Monthly | Municipality |
| **BASE.gov.pt** | `contracts-award-value-12m-per-resident` | Award value | Monthly | Municipality |
| **BASE.gov.pt** | `contracts-cpv-*` | CPV breakdowns | Yearly | Municipality |

### Other Sources

| Source | Data | Frequency | Granularity |
|---|---|---|---|
| **PORDATA** | 47 municipal summary indicators | Yearly | Municipality |
| **ERSAR** | Water safety, sanitation | Yearly | Municipality |
| **IEFP** | Registered unemployment | Monthly | Municipality |
| **SEF/Immigration** | Foreign residents | Yearly | Municipality |

## Missing Data Strategies

| Strategy | Description | Example |
|---|---|---|
| `null` | Return null if no data available | Some SNS metrics |
| `national-mean` | Fill with national average | Climate, air quality |
| Fallback to district | Use district-level data | SNS hospital metrics |
| Fallback to NUTS region | Use NUTS II/III data | Some INE indicators |

## Provenance Examples

### Municipality-level data (no fallback)
```json
{
  "crime": {
    "granularity": "municipality",
    "isFallback": false,
    "fallbackType": null,
    "chain": null
  }
}
```

### Sub-region fallback (SNS data projected to municipality)
```json
{
  "snsConsultAdequatePct": {
    "granularity": "sub-region",
    "isFallback": true,
    "fallbackType": "derived",
    "chain": {
      "resolvedAt": "district-or-sub-region"
    }
  }
}
```

### Source missing
```json
{
  "tourismDensity": {
    "granularity": "municipality",
    "isFallback": true,
    "fallbackType": "source-missing",
    "chain": {
      "resolvedAt": null
    }
  }
}
```

## Data Quality Indicators

- **Provenance metadata** tracks reliability of each data point
- **Fallback chains** show how data was projected when not available at parish level
- **Update timestamps** (`generatedAt`) show when data was last refreshed
- **Year metadata** shows the reference period for each indicator
