# 🐝 Project Vespeiro

[![Deploy Dashboard](https://github.com/USER/REPO/actions/workflows/deploy-dashboard.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/deploy-dashboard.yml)
[![Scrape Sources](https://github.com/USER/REPO/actions/workflows/scrape.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/scrape.yml)
[![Narrative Analysis](https://github.com/USER/REPO/actions/workflows/analyze.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/analyze.yml)
[![Daily Stats](https://github.com/USER/REPO/actions/workflows/stats.yml/badge.svg)](https://github.com/USER/REPO/actions/workflows/stats.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Media Narrative Intelligence Platform**

Monitoriza, analisa e expõe o controlo narrativo nos media portugueses — com foco no papel da Lusa como gatekeeper da informação e na assimetria entre o que Portugal vê e o que o mundo vê.

> 📊 **[Live Dashboard →](https://USER.github.io/REPO/)** — deployed daily via GitHub Pages

## 🎯 Missão

> *"A propaganda mais poderosa não é a mentira que te contam — é a verdade que nunca vês."*

Construir um radar público de **assimetria informativa** que torna visível o que está a ser silenciado, distorcido ou filtrado nos media portugueses.

## 🔧 Stack

| Componente | Tecnologia | Custo |
|------------|-----------|-------|
| Scraping | Python (httpx + feedparser + trafilatura + pdfplumber) | $0 |
| Embeddings | sentence-transformers (multilingual-e5-large) | $0 (CPU) |
| Sentiment | pysentimiento (PT/ES/EN) | $0 (CPU) |
| Database | SQLite (dev) / Supabase Free Tier (prod) | $0 |
| Dashboard | React 19 + Vite 6 + TypeScript 5.8 (GitHub Pages) | $0 |
| CI/CD | GitHub Actions (scrape, analyze, stats, deploy) | $0 |
| Alertas | Telegram Bot (via GitHub Actions) | $0 |

**💰 Total: $0/mês operacionais.**

## 📂 Estrutura

```
vespeiro/
├── .github/workflows/     # 5 workflows: scrape, analyze, stats, deploy, alerts
├── backend/
│   ├── src/
│   │   ├── config/         # Sources.yaml + Pydantic settings
│   │   ├── db/             # SQLAlchemy models + async session
│   │   ├── scrapers/       # 8 spiders → 27 sources (RSS, Google News, PDF)
│   │   ├── pipeline/       # Embeddings, story matching, sentiment, monitor
│   │   ├── analysis/       # Divergence, Lusa dependency, silence detection
│   │   ├── alerts/         # Telegram bot (daily briefing + anomaly alerts)
│   │   └── supabase/       # Supabase client
│   ├── tests/              # 200+ tests (pytest)
│   └── run_*.py           # CLI entrypoints (scrape, analysis, stats, alert)
├── frontend/               # React 19 + Vite 6 + TypeScript dashboard
│   ├── src/components/     # 10 dashboard components
│   ├── public/             # stats.json, favicon, OG image, PWA manifest
│   └── dist/               # Built output (deployed to GitHub Pages)
├── docs/                   # Design docs + implementation plans
└── data/                   # SQLite database (local dev + GHA cache)
```

## 🏗️ Fases

| Fase | O quê | Estado |
|------|-------|--------|
| 0 | Fundação — 8 spiders, 27 sources, SQLite storage | ✅ Implementado |
| 1 | Pipeline — embeddings, story matching, sentiment | ✅ Implementado |
| 2 | Divergência — extractor, comparator, reporter | ✅ Implementado |
| 3 | Ecossistema — DRE, Parlamento, ERC, dependência Lusa | ✅ Implementado |
| 4 | Exposição — dashboard, Telegram bot, stats portal | ✅ Implementado |

## 🌐 Workflows

| Workflow | Schedule | Description |
|----------|----------|-------------|
| [Scrape Sources](.github/workflows/scrape.yml) | Every 30 min — 6h | Fetch articles from 27 sources across 5 cadence groups |
| [Narrative Analysis](.github/workflows/analyze.yml) | Every 6h | Compare Lusa vs Portuguese outlets for divergence scoring |
| [Daily Stats](.github/workflows/stats.yml) | Daily 09:00 UTC | Generate stats.json, commit to repo, send Telegram briefing |
| [Deploy Dashboard](.github/workflows/deploy-dashboard.yml) | Daily 09:30 UTC | Build React app and deploy to GitHub Pages |

## 🚀 Começar

```bash
git clone https://github.com/USER/REPO.git
cd vespeiro
python -m venv .venv
source .venv/bin/activate
pip install -e backend/

# Scrape a source
cd backend && python run_pipeline.py lusa

# Run analysis
python run_analysis.py

# Generate stats
python run_stats.py
```

## 📊 Dashboard Preview

Run locally:
```bash
cd frontend
npm install
npm run dev     # → http://localhost:3000
```

## 🚀 GitHub Pages Deployment

The dashboard is automatically built and deployed to GitHub Pages every day at 09:30 UTC via the [Deploy Dashboard](.github/workflows/deploy-dashboard.yml) workflow.

### Prerequisites

1. **Enable GitHub Pages** — Go to your repo **Settings → Pages → Source** and select **"GitHub Actions"**.
2. **Approve the environment (if prompted)** — The first time the workflow runs, you may see a pending approval for the `github-pages` environment. Go to **Settings → Environments → github-pages** and approve it. To skip this step on future runs, set **Required reviewers** to _none_.
3. **Update placeholder URLs** — Replace `USER/REPO` in the badges at the top of this README with your actual GitHub username and repository name (e.g., `myuser/vespeiro`).

After these steps, the workflow triggers on:
- **Push** to `main` that changes files in `frontend/`, workflow files, or `stats.json`
- **Schedule** daily at 09:30 UTC (30 min after stats generation)
- **Manual** via `Actions → Deploy Dashboard → Run workflow` (supports `build_only` mode)

> The live dashboard will be available at `https://USER.github.io/REPO/` once deployed.

## 📄 Documentação

- [Design Doc](docs/superpowers/specs/2026-05-27-vespeiro-design.md)
- [Plano de Implementação](docs/superpowers/plans/2026-05-27-vespeiro-implementation.md)
- [TODO Tracker](docs/superpowers/plans/vespeiro-todo.md)
- [Narrative Divergence Spec](docs/superpowers/specs/2026-05-27-narrative-divergence-design.md)
- [Stats Portal Spec](docs/superpowers/specs/2026-05-27-stats-portal-design.md)

## ⚠️ Nota

Este projeto é open source e apartidário. Expõe controlo narrativo de QUALQUER direção — esquerda, direita ou centro. Os dados são verificáveis por qualquer pessoa.

---

> 🔧 Substitui `USER/REPO` nos badges e links pelo teu repositório GitHub real.