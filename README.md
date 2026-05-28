# 🐝 Project Vespeiro

[![Deploy Dashboard](https://github.com/nelohenriq/vespeiro/actions/workflows/deploy-dashboard.yml/badge.svg)](https://github.com/nelohenriq/vespeiro/actions/workflows/deploy-dashboard.yml)
[![Scrape Sources](https://github.com/nelohenriq/vespeiro/actions/workflows/scrape.yml/badge.svg)](https://github.com/nelohenriq/vespeiro/actions/workflows/scrape.yml)
[![Narrative Analysis](https://github.com/nelohenriq/vespeiro/actions/workflows/analyze.yml/badge.svg)](https://github.com/nelohenriq/vespeiro/actions/workflows/analyze.yml)
[![Daily Stats](https://github.com/nelohenriq/vespeiro/actions/workflows/stats.yml/badge.svg)](https://github.com/nelohenriq/vespeiro/actions/workflows/stats.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Media Narrative Intelligence Platform — Open-source media monitoring for Portugal**

Monitors, analyzes, and exposes narrative control in Portuguese media — quantifying Lusa's gatekeeping role, detecting international coverage gaps, mapping the state-media personnel network, and measuring advertising-editorial correlation.

> 📊 **[Live Dashboard →](https://nelohenriq.github.io/vespeiro/)** · 📖 **[API Docs →](docs/api.md)** · 🔬 **[Methodology →](https://nelohenriq.github.io/vespeiro/)** (📖 Methodology tab) · 🏷️ **[Releases →](https://github.com/nelohenriq/vespeiro/tags)**

---

## 🎯 Mission

> *"The most powerful propaganda isn't the lie you're told — it's the truth you never see."*

Vespeiro is a public **information asymmetry radar** that makes visible what is being silenced, distorted, or filtered in Portuguese media. We don't claim what's "true" — we show the **gap** between what Portugal sees and what the world sees.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    DATA SOURCES ($0)                           │
│  🇵🇹 15 PT outlets  │  🌍 10 international  │  🏛️ 6 state sites │
└──────────────────────────┬─────────────────────────────────────┘
                           │
     ┌─────────────────────▼──────────────────────┐
     │       GITHUB ACTIONS (scheduled cron)       │
     │  scrape → embed → match → analyze → alert  │
     └─────────────────────┬──────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   SUPABASE (PostgreSQL)  │
              │   articles · embeddings  │
              │   clusters · metrics     │
              └────────────┬────────────┘
                           │
     ┌─────────────────────┼──────────────────────┐
     │                     │                      │
     ▼                     ▼                      ▼
┌─────────┐    ┌──────────────────┐    ┌─────────────────┐
│ GH Pages│    │  Public REST API │    │  Telegram Bot   │
│ React   │    │  (PostgREST)     │    │  daily briefing │
│ D3.js   │    │  RLS policies    │    │  anomaly alerts │
└─────────┘    └──────────────────┘    └─────────────────┘
```

**💰 Total cost: $0/month.** Everything runs on free tiers — GitHub Actions, Supabase, GitHub Pages, Telegram API. No servers, no paid APIs, no Docker in production.

---

## ✨ Features

### Phase 1 — Lusa Dependency
- **Lusa Dependency Score** per outlet — what % of articles trace back to Lusa?
- **Topic Monopoly Analysis** — topics where Lusa has >80% market share
- **Agenda-Setting Metrics** — time lag, gatekeeping ratio
- **Framing Divergence** — how outlets reframe Lusa content

### Phase 2 — The Broken Mirror
- **Silence Detection** — international stories with zero Portuguese coverage
- **Narrative Asymmetry** — sentiment divergence on key political figures
- **Story Clustering** — cross-lingual matching (PT/EN/ES/FR)
- **"Jornal do Contra"** — daily Telegram briefing with silenced stories

### Phase 3 — State Ecosystem
- **Personnel Network Graph** — D3.js force graph of state-media revolving door
- **Parliament-Media Gap** — topics debated in Parliament that never reach the public
- **Advertising-Editorial Correlation** — do outlets that receive more state ads cover government more favorably?
- **Influence Map** — composite dashboard with Capture Score per outlet

### Phase 4 — Public Exposure
- **React Dashboard** — 6 tabs, 13 components, D3.js visualizations
- **Public API** — Supabase PostgREST with Row Level Security
- **Transparency & Methodology** — full disclosure of how every metric is calculated
- **Telegram Alerts** — daily briefings + anomaly detection

---

## 🔧 Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Scraping | Python (httpx + feedparser + trafilatura + pdfplumber) | $0 |
| Embeddings | sentence-transformers (multilingual-e5-large) | $0 (CPU) |
| Sentiment | pysentimiento (PT/ES/EN) | $0 (CPU) |
| Story Matching | cosine similarity + DBSCAN | $0 |
| Database | SQLite (dev) / Supabase Free Tier (prod) | $0 |
| API | Supabase PostgREST + Row Level Security | $0 |
| Dashboard | React 19 + Vite 6 + TypeScript + D3.js | $0 |
| Hosting | GitHub Pages | $0 |
| CI/CD | GitHub Actions (5 workflows) | $0 |
| Alerts | Telegram Bot | $0 |

---

## 📂 Project Structure

```
vespeiro/
├── .github/workflows/        # 5 CI/CD workflows
├── backend/
│   ├── src/
│   │   ├── config/           # sources.yaml + Pydantic settings
│   │   ├── db/               # SQLAlchemy models (async, SQLite + Postgres)
│   │   ├── scrapers/         # 7 spiders → 27+ sources
│   │   ├── pipeline/         # embedder, matcher, sentiment, monitor
│   │   ├── analysis/
│   │   │   ├── dependency/   # Lusa dependency analyzer
│   │   │   ├── silence/      # International coverage gap detector
│   │   │   ├── divergence/   # Narrative divergence (extractor, comparator, reporter)
│   │   │   ├── personnel/    # Personnel network graph builder
│   │   │   ├── gap/          # Parliament-media topic gap analysis
│   │   │   └── correlation/  # Advertising-editorial correlation
│   │   ├── alerts/           # Telegram bot (daily briefings + anomaly alerts)
│   │   ├── stats/            # StatsGenerator → stats.json
│   │   └── supabase/         # Supabase client
│   ├── alembic/              # DB migrations (including RLS policies)
│   ├── tests/                # 258+ tests (pytest + pytest-asyncio)
│   └── run_*.py              # CLI entrypoints
├── frontend/                 # React 19 + Vite 6 + TypeScript
│   ├── src/components/       # 13 dashboard components
│   └── public/               # stats.json + static assets
├── docs/                     # Design docs, implementation plans, API docs
└── data/                     # SQLite database (dev)
```

---

## 🚀 Quick Start

### Prerequisites
- Python ≥3.12
- Node.js ≥20

### Backend

```bash
git clone https://github.com/nelohenriq/vespeiro.git
cd vespeiro

# Python environment
python -m venv .venv
source .venv/bin/activate
pip install -e backend/

# Scrape a source (requires GOOGLE_API_KEY + GOOGLE_CUSTOM_SEARCH_CX for DRE)
cd backend
python run_pipeline.py lusa        # fetch + store Lusa articles
python run_analysis.py             # run divergence analysis
python run_stats.py                # generate stats.json
python run_alert.py --test         # test Telegram alert (needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)

# Run tests
python -m pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # → http://localhost:5173
npm run build      # production build → dist/
```

> The dashboard reads `stats.json` from `public/`. Generate it first with `python run_stats.py --output ../frontend/public/stats.json`.

---

## 🌐 CI/CD Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| [Scrape Sources](.github/workflows/scrape.yml) | Every 30 min – 6h | Fetch articles from 27+ sources |
| [Narrative Analysis](.github/workflows/analyze.yml) | Every 6h | Story matching + divergence scoring |
| [Daily Stats](.github/workflows/stats.yml) | Daily 09:00 UTC | Generate stats.json + send Telegram briefing |
| [Deploy Dashboard](.github/workflows/deploy-dashboard.yml) | On push to `frontend/**` | Build + deploy to GitHub Pages |
| [Backup](.github/workflows/backup.yml) | Weekly | Export metadata snapshots to repo |

---

## 📊 Public API

Vespeiro exposes a free, open-access REST API via Supabase PostgREST. No API key required for read access on:

- **`/sources`** — registered media sources with metadata
- **`/articles`** — article metadata (title, URL, date, summary; full text excluded)
- **`/people`** — public officials extracted from Diário da República
- **`/appointments`** — DRE-extracted appointments to media/communication roles

Full documentation with cURL, Python, and JavaScript examples: **[docs/api.md](docs/api.md)**

---

## 📖 Methodology

Every metric in Vespeiro is transparently documented. See the live **Methodology page** (📖 tab on the dashboard) for:

- **Story matching** — how cosine similarity + DBSCAN clusters articles cross-lingually
- **Silence detection** — how we identify international stories missing from PT media
- **Divergence scoring** — multi-dimensional comparison (quote fidelity, sentiment, headline)
- **Threshold tables** — exact values used for each analysis
- **Known limitations** — what the system can and cannot detect
- **Data sources** — complete list with update frequencies and licenses

---

## 📄 Documentation

- [Design Document](docs/superpowers/specs/2026-05-27-vespeiro-design.md) — full architecture and task specs
- [Implementation Plan](docs/superpowers/plans/2026-05-27-vespeiro-implementation.md) — build order and milestones
- [TODO Tracker](docs/superpowers/plans/vespeiro-todo.md) — 87/87 tasks complete ✅
- [API Documentation](docs/api.md) — REST API reference with client examples
- [Narrative Divergence Spec](docs/superpowers/specs/2026-05-27-narrative-divergence-design.md)
- [Stats Portal Spec](docs/superpowers/specs/2026-05-27-stats-portal-design.md)

---

## ⚠️ Disclaimer

This project is open source and non-partisan. It exposes narrative control from **any** direction — left, right, or center. All data is verifiable by anyone. The project's authority comes from transparency: methodology, code, and data are fully public.

---

*Vespeiro v0.3 — 87/87 tasks complete · [MIT License](LICENSE)*
