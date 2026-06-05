# REST API Endpoints

> All endpoints are public, no authentication required. Base URL: `https://analisa.pt`

## Endpoints

### GET `/api/municipality-dataset`

Returns the complete unified municipality dataset as GeoJSON.

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `code` | string | Filter by INE municipality code (e.g., `1106`) |
| `municipality` | string | Filter by municipality name |
| `region` | string | Filter by region name |

**Response:** GeoJSON FeatureCollection with 63,492 records, 2,886 H3 hexes, 211 layers

**Example:**
```bash
curl 'https://analisa.pt/api/municipality-dataset?code=1106'
```

---

### GET `/api/history`

Returns historical time-series data for a municipality.

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `code` | string | INE municipality code (required) |
| `indicator` | string | Indicator key (e.g., `crime`, `houseBuyPrice`) |

**Response:** JSON with indicator time series

**Example:**
```bash
curl 'https://analisa.pt/api/history?code=1106&indicator=crime'
```

---

### GET `/api/hospitals/overview`

Returns hospital facility data with metrics.

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `code` | string | INE municipality code |

**Response:** JSON with 50 hospital facilities, urgency episodes, bed occupancy, consult timing

**Example:**
```bash
curl 'https://analisa.pt/api/hospitals/overview?code=1106'
```

---

### GET `/api/datasets/latest-news`

Returns latest dataset updates and news.

**Response:** JSON with recent dataset changes

**Example:**
```bash
curl 'https://analisa.pt/api/datasets/latest-news'
```

---

### GET `/api/ine-search`

Search INE (national statistics institute) data.

**Query Parameters:**
| Param | Type | Description |
|---|---|---|
| `q` | string | Search query |

**Response:** JSON with search results

**Example:**
```bash
curl 'https://analisa.pt/api/ine-search?q=Lisboa'
```

---

## Response Headers

All endpoints return:
- `Content-Type: application/json`
- `Cache-Control: public, max-age=14400, s-maxage=86400` (4h browser, 24h CDN)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: strict-origin-when-cross-origin`

## Municipality Codes (4-digit INE)

| Code | Municipality |
|---|---|
| 1106 | Lisboa |
| 1312 | Porto |
| 0303 | Braga |
| 0603 | Coimbra |
| 0805 | Faro |
| 1503 | Almada |
| 1115 | Amadora |
| 1302 | Vila Nova de Gaia |
| 0105 | Aveiro |
| 1823 | Viseu |
