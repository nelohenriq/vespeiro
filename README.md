# 🐝 Project Vespeiro

**Media Narrative Intelligence Platform**

Monitoriza, analisa e expõe o controlo narrativo nos media portugueses — com foco no papel da Lusa como gatekeeper da informação e na assimetria entre o que Portugal vê e o que o mundo vê.

## 🎯 Missão

> *"A propaganda mais poderosa não é a mentira que te contam — é a verdade que nunca vês."*

Construir um radar público de **assimetria informativa** que torna visível o que está a ser silenciado, distorcido ou filtrado nos media portugueses.

## 🔧 Stack

| Componente | Tecnologia | Custo |
|------------|-----------|-------|
| Scraping | Python (httpx + feedparser + trafilatura) | $0 |
| Embeddings | sentence-transformers (multilingual-e5-large) | $0 (CPU) |
| Sentiment | pysentimiento (PT/ES/EN) | $0 (CPU) |
| Database | Supabase Free Tier (PostgreSQL + pgvector) | $0 |
| Dashboard | React + Vite + D3.js (GitHub Pages) | $0 |
| CI/CD | GitHub Actions | $0 (public repo) |
| Alertas | Telegram Bot (via GHA) | $0 |

**💰 Total: $0/mês operacionais.**

## 📂 Estrutura

```
vespeiro/
├── .github/workflows/     # GitHub Actions (scraping, análise, deploy)
├── backend/
│   ├── src/
│   │   ├── config/         # Sources.yaml + settings
│   │   ├── db/             # SQLAlchemy models + session
│   │   ├── scrapers/       # Spiders (Lusa, media PT, internacional)
│   │   ├── pipeline/       # Embeddings, story matching, sentiment
│   │   ├── analysis/       # Lusa dependency, silence detection
│   │   └── supabase/       # Supabase client
│   └── tests/
├── frontend/               # React dashboard (Fase 4)
├── docs/                   # Design docs + plans
└── data/                   # SQLite local dev
```

## 🏗️ Fases

| Fase | O quê | Estado |
|------|-------|--------|
| 0 | Fundação — scraping, DB, embeddings | ⏳ Em implementação |
| 1 | Análise Lusa — peso da agência nos media | ☐ Planeado |
| 2 | Espelho Partido — silêncios internacionais | ☐ Planeado |
| 3 | Ecossistema do Estado — gov, DR, publicidade | ☐ Planeado |
| 4 | Exposição Pública — dashboard, API, bot | ☐ Planeado |

## 🚀 Começar

```bash
cd vespeiro
python -m venv .venv
source .venv/bin/activate
pip install -e backend/
```

## 📄 Documentação

- [Design Doc](docs/superpowers/specs/2026-05-27-vespeiro-design.md)
- [Plano de Implementação](docs/superpowers/plans/2026-05-27-vespeiro-implementation.md)
- [TODO Tracker](docs/superpowers/plans/vespeiro-todo.md)

## ⚠️ Nota

Este projeto é open source e apartidário. Expõe controlo narrativo de QUALQUER direção — esquerda, direita ou centro. Os dados são verificáveis por qualquer pessoa.
