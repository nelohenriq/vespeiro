# 🐝 Vespeiro Public API

> **Free, open-access REST API for media narrative intelligence data.**
> Built on Supabase PostgREST. No API key required for read access.

**Base URL:** `https://<project>.supabase.co/rest/v1`

---

## 🔑 Authentication

| Key Type | Access | Rate Limit |
|----------|--------|------------|
| `anon` (public) | Read-only on whitelisted tables | 100 req/min per IP |
| `service_role` (private) | Full CRUD | Unlimited (CI/CD only) |

**Public access uses the Supabase `anon` key.** Include it in requests:

```bash
curl "https://<project>.supabase.co/rest/v1/sources" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

> **Researchers:** For higher rate limits, contact us. The `anon` key is available in the Supabase project settings → API.

---

## 📊 Endpoints

### Sources

```
GET /rest/v1/sources
```

Registered media sources with metadata.

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | `eq.{slug}` | Filter by source slug (e.g., `lusa`, `publico`) |
| `category` | `eq.{category}` | Filter by category (`agency`, `mainstream`, `international`, `government`, `parliament`, `regulator`) |
| `language` | `eq.{lang}` | Filter by language (`pt`, `en`, `es`, `fr`) |
| `is_active` | `is.true` / `is.false` | Only active/inactive sources |

**Example — All Portuguese sources:**
```bash
curl "https://<project>.supabase.co/rest/v1/sources?language=eq.pt&is_active=is.true&order=name" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

**Example — Count by category:**
```bash
curl "https://<project>.supabase.co/rest/v1/sources?select=category,id&order=category" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

---

### Articles

```
GET /rest/v1/articles
```

Collected articles with metadata. **Full text (`content_text`) is excluded from public API** (available only via `service_role` key for internal analysis).

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_id` | `eq.{slug}` | Filter by source |
| `published_at` | `gte.{iso}` / `lte.{iso}` | Date range |
| `language` | `eq.{lang}` | Filter by detected language |
| `order` | `published_at.desc` / `published_at.asc` | Sort order |
| `limit` | `{n}` | Max results (default: 1000, max: 5000) |
| `offset` | `{n}` | Pagination offset |

**Example — Last 100 articles from Lusa:**
```bash
curl "https://<project>.supabase.co/rest/v1/articles?source_id=eq.lusa&order=published_at.desc&limit=100&select=id,url,title,summary,author,published_at" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

**Example — Articles from last 7 days:**
```bash
curl "https://<project>.supabase.co/rest/v1/articles?published_at=gte.$(date -v-7d +%Y-%m-%d)&order=published_at.desc&limit=100&select=id,source_id,url,title,summary,published_at" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

**Example — Count articles per source (PostgREST computed columns):**
```bash
# PostgREST doesn't support GROUP BY; use the Supabase JS client or SQL for aggregation
# Alternative: fetch all and count client-side, or use stats.json for pre-computed metrics
```

---

### People

```
GET /rest/v1/people
```

Public officials and appointees extracted from Diário da República.

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `ilike.*{pattern}*` | Case-insensitive name search |
| `normalized_name` | `ilike.*{pattern}*` | Normalized name search |
| `select` | `*,appointments(*)` | Include nested appointments |

**Example — Find a person and their appointments:**
```bash
curl "https://<project>.supabase.co/rest/v1/people?select=name,appointments(organization,role,appointment_type,published_at)&name=ilike.*silva*&limit=10" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

---

### Appointments

```
GET /rest/v1/appointments
```

DRE-extracted appointments to media and communication roles.

| Parameter | Type | Description |
|-----------|------|-------------|
| `organization` | `ilike.*{pattern}*` | Case-insensitive org search |
| `appointment_type` | `eq.{type}` | Filter by type (`nomeação`, `exoneração`, `designação`) |
| `published_at` | `gte.{iso}` / `lte.{iso}` | Date range |
| `select` | `*,person(name)` | Include person data |

**Example — All RTP and Lusa appointments:**
```bash
curl "https://<project>.supabase.co/rest/v1/appointments?select=*,person(name)&organization=ilike.*(RTP|Lusa).*&order=published_at.desc&limit=50" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

**Example — Appointments in the last year:**
```bash
curl "https://<project>.supabase.co/rest/v1/appointments?select=*,person(name)&published_at=gte.2025-05-28&order=published_at.desc" \
  -H "apikey: <anon-key>" \
  -H "Authorization: Bearer <anon-key>"
```

---

## 📈 Pre-Computed Metrics (stats.json)

For aggregate metrics (dependency scores, silence counts, divergence rates, personnel networks), use the static `stats.json` endpoint served by GitHub Pages:

```
GET /vespeiro/stats.json
```

This file is regenerated daily by GitHub Actions (`run_stats.py`) and contains all dashboard metrics in a single JSON payload. See `frontend/src/types.ts` for the schema.

---

## 🔗 PostgREST Advanced Features

Supabase exposes the full PostgREST API. Advanced queries:

| Feature | Syntax | Example |
|---------|--------|---------|
| **Select columns** | `?select=col1,col2` | `?select=id,url,title` |
| **Nested resources** | `?select=*,child(*)` | `?select=*,appointments(*)` |
| **Filter equals** | `?col=eq.value` | `?source_id=eq.lusa` |
| **Filter like** | `?col=ilike.*pattern*` | `?name=ilike.*silva*` |
| **Filter in** | `?col=in.(a,b,c)` | `?source_id=in.(lusa,rtp,publico)` |
| **Filter range** | `?col=gte.val&col=lte.val` | `?published_at=gte.2026-01-01` |
| **Order** | `?order=col.desc` | `?order=published_at.desc` |
| **Limit/Offset** | `?limit=50&offset=100` | Pagination |
| **Count** | `?select=count` or `Prefer: count=exact` | Total row count |

Full reference: [postgrest.org/en/stable/references/api.html](https://postgrest.org/en/stable/references/api.html)

---

## 📦 Client Libraries

### JavaScript / TypeScript

```typescript
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(
  "https://<project>.supabase.co",
  "<anon-key>"
);

const { data, error } = await supabase
  .from("articles")
  .select("id, url, title, summary, published_at, source_id")
  .eq("source_id", "lusa")
  .order("published_at", { ascending: false })
  .limit(100);
```

### Python

```python
import httpx

async def fetch_articles(source_id: str, limit: int = 100):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://<project>.supabase.co/rest/v1/articles",
            headers={
                "apikey": "<anon-key>",
                "Authorization": f"Bearer <anon-key>",
            },
            params={
                "source_id": f"eq.{source_id}",
                "order": "published_at.desc",
                "limit": str(limit),
                "select": "id,url,title,summary,author,published_at",
            },
        )
        return resp.json()
```

### cURL

```bash
export SUPABASE_URL="https://<project>.supabase.co"
export ANON_KEY="<anon-key>"

# Get active Portuguese sources
curl "$SUPABASE_URL/rest/v1/sources?language=eq.pt&is_active=is.true" \
  -H "apikey: $ANON_KEY" \
  -H "Authorization: Bearer $ANON_KEY"
```

---

## ⚠️ Rate Limits & Fair Use

| Tier | Requests/min | Requests/day |
|------|-------------|--------------|
| **Public (anon)** | 100 | 10,000 |
| **Researcher** | On request | On request |

- **Be respectful:** Use `limit` and `offset` for pagination. Don't scrape entire tables in one request.
- **Cache responses:** Stats change daily; article data is append-only. Cache aggressively.
- **Prefer stats.json:** For dashboard metrics, use the pre-computed stats file — it's faster and doesn't count against rate limits.
- **Need more?** Open an issue on GitHub requesting researcher access.

---

## 📜 Open Data License

Data exposed via this API is derived from publicly available sources (RSS feeds, public government websites). Attribution appreciated but not required.

- **Article metadata** (title, URL, date, source): Public domain / fair use
- **Article full text**: Available only via `service_role` for internal analysis; not publicly exposed (respects copyright)
- **DRE appointments**: Public government data — freely redistributable
- **Derived metrics** (dependency scores, silence counts): CC-BY 4.0

---

## 🐛 Issues & Contributions

- **GitHub:** [github.com/nelohenriq/vespeiro](https://github.com/nelohenriq/vespeiro)
- **Bug reports:** Open an issue
- **Feature requests:** Open a discussion
- **API questions:** Open an issue with label `api`

---

*Last updated: 2026-05-28 — Vespeiro v1.0*
