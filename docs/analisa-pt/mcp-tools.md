# MCP Tools — Complete Catalog

> Server: `portugal-stats v1.0.0` | Protocol: `2024-11-05` | Endpoint: `POST https://analisa.pt/api/mcp`

## Authentication

None required. Required headers:
```
Content-Type: application/json
Accept: application/json, text/event-stream
```

## Available Tools (30+)

### Municipal & Indicator Tools

#### `search_municipalities`
Search Portuguese municipalities by name.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | Search query |
| `limit` | number | No | 10 | Max results (1-50) |

**Example Call:**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_municipalities","arguments":{"query":"Lisboa","limit":5}}}
```

---

#### `get_municipality_indicators`
Get all quality-of-life indicators for a municipality.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code (e.g., `1106`) |

**Returns:** 361 indicators with values, periods, and provenance

---

#### `rank_municipalities`
Rank municipalities by indicator (top/bottom N).

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `indicatorKey` | string | Yes | — | Indicator key (e.g., `crime`) |
| `order` | string | No | `desc` | `asc` or `desc` |
| `limit` | number | No | 10 | Max results (1-50) |

---

#### `get_municipality_history`
Get historical time series for a municipality.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code |
| `indicatorKey` | string | No | Specific indicator (returns all if omitted) |

---

#### `compare_municipalities`
Compare 2-5 municipalities side by side.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCodes` | string[] | Yes | Array of 2-5 INE codes |
| `indicatorKeys` | string[] | No | Specific indicators (returns all if omitted) |

---

### Dataset Tools

#### `get_dataset_overview`
Get unified dataset overview (no arguments).

**Returns:** Plugin count (26), layer count (211), record count (63,492), hex count (2,886)

---

#### `list_dataset_plugins`
List all registered dataset plugins.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `q` | string | No | — | Filter by name |
| `limit` | number | No | 50 | Max results (1-100) |

---

#### `list_dataset_layers`
List dataset layers/indicators.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `pluginId` | string | No | — | Filter by plugin |
| `source` | string | No | — | Filter by source |
| `q` | string | No | — | Search by name |
| `limit` | number | No | 50 | Max results (1-100) |
| `page` | number | No | 1 | Page number |

---

#### `get_dataset_layer_detail`
Get full metadata for a single dataset layer.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `key` | string | Yes | Layer key (e.g., `crime`, `houseBuyPrice`) |

**Returns:** Key, label, unit, direction, weight, frequency, source, source code, plugin info

---

#### `search_dataset_features`
Search unified dataset feature collection.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `municipalityCode` | string | No | — | Filter by municipality |
| `parishCode` | string | No | — | Filter by parish |
| `layerKeys` | string[] | No | — | Specific layers (max 12) |
| `includeProvenance` | boolean | No | — | Include provenance metadata |
| `limit` | number | No | 25 | Max results (1-100) |
| `page` | number | No | 1 | Page number |

---

#### `get_dataset_feature_detail`
Get full unified dataset payload for a single feature/area.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `areaCode` | string | Yes | Area identifier (e.g., `parish:110658`) |

**Returns:** Complete indicator values, provenance metadata, regional labels, coordinates

---

### Public Contract & Procurement Tools

#### `search_contracts`
Search public contracts.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `q` | string | No | — | Search query |
| `municipalityCode` | string | No | — | Filter by municipality |
| `publishedFrom` | string | No | — | Start date (ISO) |
| `publishedTo` | string | No | — | End date (ISO) |
| `valueMin` | number | No | — | Min contract value |
| `valueMax` | number | No | — | Max contract value |
| `status` | string | No | — | Contract status |
| `procedureType` | string | No | — | Procedure type |
| `limit` | number | No | 10 | Max results (1-100) |
| `page` | number | No | 1 | Page number |

---

#### `search_announcements`
Search public procurement announcements.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `q` | string | No | — | Search query |
| `municipalityCode` | string | No | — | Filter by municipality |
| `publishedFrom` | string | No | — | Start date |
| `publishedTo` | string | No | — | End date |
| `actType` | string | No | — | Announcement type |
| `unmatchedOnly` | boolean | No | — | Only unmatched announcements |
| `limit` | number | No | 10 | Max results (1-100) |

---

#### `search_entities`
Search entities (buyers/suppliers) by name or NIF.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `q` | string | No | — | Search by name |
| `nif` | string | No | — | Search by NIF |
| `limit` | number | No | 20 | Max results (1-50) |

---

#### `search_modifications`
Search contract modifications.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `q` | string | No | — | Search query |
| `municipalityCode` | string | No | — | Filter by municipality |
| `publishedFrom` | string | No | — | Start date |
| `publishedTo` | string | No | — | End date |
| `actType` | string | No | — | Modification type |
| `limit` | number | No | 10 | Max results (1-100) |

---

#### `get_contract_detail`
Get full details for a single contract.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Contract ID |

---

#### `get_entity_detail`
Get full details for an entity.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Entity ID |

---

#### `get_announcement_detail`
Get full details for a procurement announcement.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | Announcement ID |

---

#### `get_area_contract_rankings`
Get contract rankings by municipality/parish.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `dataset` | string | No | `contracts` | `contracts`, `announcements`, or `entities` |
| `metric` | string | No | `amount` | `amount` or `count` |
| `scope` | string | No | `municipality` | `country`, `municipality`, or `parish` |
| `limit` | number | No | 10 | Max results (1-50) |

---

#### `get_contract_filters`
List municipality and parish filters.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `municipalityCode` | string | No | — | Filter parishes by municipality |
| `limitParishes` | number | No | 500 | Max parishes (1-5000) |

---

#### `get_contract_latest_activity`
Get latest activity for a municipality/parish.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code |
| `parishCode` | string | No | Parish code |

---

#### `get_contract_momentum`
Get 30-day contract momentum metrics.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code |
| `parishCode` | string | No | Parish code |

**Returns:** contractsLast1m, contractsTrendPct, awardValueLast1mEur, announcementsPer10kResidents, etc.

---

#### `get_contract_monthly_spending`
Get monthly contract spending time series (24 months).

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code |
| `parishCode` | string | No | Parish code |

---

#### `get_contract_map_aggregates`
Get map aggregate values for visualization.

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `dataset` | string | Yes | — | `contracts`, `announcements`, `entities` |
| `metric` | string | Yes | — | `amount`, `count`, `unmatched_announcements` |
| `scope` | string | No | `parish` | `municipality` or `parish` |
| `municipalityCode` | string | No | — | Filter by municipality |
| `limit` | number | No | 25 | Max results (1-100) |
| `page` | number | No | 1 | Page number |

---

#### `get_contract_sankey`
Get Sankey flow data for visualization.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code |
| `mode` | string | Yes | `buyersSuppliers` or `contractTypes` |

---

#### `get_contract_concentration`
Get supplier concentration (HHI index).

**Arguments:**
| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `municipalityCode` | string | No | — | Filter by municipality |
| `cpvCode` | string | No | — | Filter by CPV category |
| `n` | number | No | 10 | Top N suppliers (1-20) |

---

#### `get_contract_modification_analytics`
Get contract modification analytics.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | No | 4-digit INE code |

⚠️ **Note:** Returns BigInt values that may cause serialization issues in some clients.

---

#### `get_contract_outcome_overlay`
Correlate contract spend with municipality indicators.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `cpvPrefix` | string | Yes | CPV category prefix (e.g., `45` for construction) |
| `indicatorKey` | string | Yes | Indicator to correlate with |

**Returns:** Correlation coefficient and scatter data across all 308 municipalities

---

#### `get_municipality_contract_insights`
Get comprehensive contract insights for a municipality.

**Arguments:**
| Param | Type | Required | Description |
|---|---|---|---|
| `municipalityCode` | string | Yes | 4-digit INE code |

---

## MCP Resources

| URI | Type | Description |
|---|---|---|
| `ui://widget/data-table.v2.html` | `text/html;profile=mcp-app` | Sortable HTML data table for rendering results |

---

## Error Handling

| Error | Meaning |
|---|---|
| `Not Acceptable: Client must accept both application/json and text/event-stream` | Missing required Accept header |
| `-32000` | Server-side error (check message) |
| `Do not know how to serialize a BigInt` | Known bug in `get_contract_modification_analytics` |
