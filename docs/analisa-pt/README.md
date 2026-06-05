# analisa.pt — API Reference & Data Platform

> Interactive quality-of-life explorer for all 308 municipalities in Portugal. Free, open-data platform with maps, rankings, and 230+ indicators.

## Quick Start

**Base URL:** `https://analisa.pt`

### REST API (no auth required)

```bash
# Get full municipality dataset (GeoJSON, 63K+ records)
curl 'https://analisa.pt/api/municipality-dataset'

# Search for a municipality
curl 'https://analisa.pt/api/ine-search?q=Lisboa'

# Get historical time series
curl 'https://analisa.pt/api/history?code=1106&indicator=crime'

# Get hospital overview
curl 'https://analisa.pt/api/hospitals/overview?code=1106'

# Get latest dataset updates
curl 'https://analisa.pt/api/datasets/latest-news'
```

### MCP API (JSON-RPC 2.0, no auth required)

```bash
# Initialize MCP session
curl -X POST https://analisa.pt/api/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"my-app","version":"1.0"}}}'

# Call a tool
curl -X POST https://analisa.pt/api/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_municipalities","arguments":{"query":"Lisboa","limit":5}}}'
```

## Documentation Files

| File | Description |
|---|---|
| [api-endpoints.md](api-endpoints.md) | All REST API endpoints with parameters |
| [mcp-tools.md](mcp-tools.md) | Complete MCP tool catalog (30+ tools) |
| [provenance-metadata.md](provenance-metadata.md) | Data sources, provenance tracking, and quality metadata |
| [data-pipeline.md](data-pipeline.md) | How data flows from raw sources to API |
| [llms-full.txt](llms-full.txt) | Original platform documentation for LLMs |

## Examples

| File | Description |
|---|---|
| [examples/search-municipalities.json](examples/search-municipalities.json) | MCP search_municipalities response |
| [examples/rank-crime.json](examples/rank-crime.json) | MCP rank_municipalities response (crime) |
| [examples/municipality-indicators.json](examples/municipality-indicators.json) | MCP get_municipality_indicators response |
| [examples/contract-sankey.json](examples/contract-sankey.json) | MCP get_contract_sankey response |
| [examples/contract-momentum.json](examples/contract-momentum.json) | MCP get_contract_momentum response |
| [examples/contract-concentration.json](examples/contract-concentration.json) | MCP get_contract_concentration response |
| [examples/feature-detail.json](examples/feature-detail.json) | MCP get_dataset_feature_detail response |
| [examples/layer-detail.json](examples/layer-detail.json) | MCP get_dataset_layer_detail response |

## Data Sources

| Source | Data | Frequency |
|---|---|---|
| INE | Crime, demographics, housing, population | Yearly/Quarterly |
| SNS Transparência | Health metrics (urgency, beds, consults) | Monthly |
| IPMA | Climate, temperature, rainfall | Daily/Yearly |
| PORDATA | 47 municipal summary indicators | Yearly |
| ERSAR | Water safety, sanitation | Yearly |
| IEFP | Registered unemployment | Monthly |
| BASE.gov.pt | Public contracts & procurement | Daily |
| ANACOM | Broadband, mobile coverage | Quarterly |
| Open-Meteo | Air quality (PM2.5, AQI) | Daily |
| OSM/GTFS | Infrastructure distances | Yearly |

## Municipality Codes

All municipalities use 4-digit INE codes:
- `1106` = Lisboa
- `1312` = Porto
- `0303` = Braga
- `0603` = Coimbra
- `0805` = Faro

## Tech Stack

- **Frontend:** Next.js (App Router, React Server Components)
- **Geospatial:** H3 hexagonal grid (resolution 7)
- **Languages:** Portuguese (pt-PT) and English (en)
- **CDN:** Cloudflare
