# 🐝 Project Vespeiro — Living TODO

> **Este ficheiro é a fonte de verdade para o progresso.**
> **Como usar:** Sempre que uma tarefa for completada, marcar ☐ → ✅ neste ficheiro e fazer commit.
> Cada tarefa com ✅ está feita. Com ☐ está pendente.

---

## 📋 Legenda

| Símbolo | Significado |
|---------|-------------|
| ✅ | Completa |
| ☐ | Pendente |
| ⏳ | Em progresso |
| ❌ | Bloqueada |
| 🔄 | Precisa de revisão |

---

## 🏗️ Fase 0 — Fundação

> **💰 ZERO COST:** Tudo gratuito. Supabase + GitHub Actions + GitHub Pages. Nenhuma API paga.
> **Objetivo:** Infraestrutura de recolha e armazenamento.
> **Dependências:** Nenhuma (ponto de partida)

### 0.1 — Project Scaffolding (no Docker)
- [ ] 0.1.1 Criar `pyproject.toml` com dependências (sem FastAPI, sem Docker, sem APScheduler)
- [ ] 0.1.2 Criar `.env.example` (Supabase, Telegram bot opcional)
- [ ] 0.1.3 Criar `README.md` com visão geral
- [ ] 0.1.4 Commit inicial

### 0.2 — Source Configuration System
- [ ] 0.2.1 Criar `src/config/settings.py` (Pydantic Settings)
- [ ] 0.2.2 Criar `src/config/sources.yaml` (fontes iniciais)
- [ ] 0.2.3 Criar modelos Pydantic (`SourceConfig`, `SourcesConfig`)
- [ ] 0.2.4 Commit

### 0.3 — Database Schema + Supabase Setup
- [ ] 0.3.1 Criar projeto Supabase free tier
- [ ] 0.3.2 Criar `src/db/models.py` (Article, Source, StoryCluster, etc. — SQLAlchemy)
- [ ] 0.3.3 Criar `src/supabase/client.py` (cliente Supabase Python)
- [ ] 0.3.4 Executar migração SQL inicial na Supabase (criar tabelas, índices pgvector)
- [ ] 0.3.5 Semear fontes iniciais na Supabase
- [ ] 0.3.6 Commit

### 0.4 — Lusa Scraper
- [ ] 0.4.1 Criar `src/scrapers/base.py` (classe base abstrata)
- [ ] 0.4.2 Criar `src/scrapers/extractors.py` (trafilatura wrapper)
- [ ] 0.4.3 Criar `src/scrapers/spiders/lusa.py` (Lusa RSS + web)
- [ ] 0.4.4 Criar teste (`tests/test_scrapers.py`)
- [ ] 0.4.5 Testar e commit

### 0.5 — Portuguese Media Spiders
- [ ] 0.5.1 Criar `src/scrapers/spiders/portugal_media.py` (RSS aggregator)
- [ ] 0.5.2 Adicionar teste
- [ ] 0.5.3 Commit

### 0.6 — International Source Spiders
- [ ] 0.6.1 Criar `src/scrapers/spiders/international.py` (com lingua.py)
- [ ] 0.6.2 Adicionar fontes ao `sources.yaml`
- [ ] 0.6.3 Adicionar teste
- [ ] 0.6.4 Commit

### 0.7 — Embedding Pipeline (local CPU, $0)
- [ ] 0.7.1 Criar `src/pipeline/embedder.py` (multilingual-e5-large)
- [ ] 0.7.2 Criar teste (similaridade cross-lingua)
- [ ] 0.7.3 Testar e commit

### 0.8 — Story Matching (cosine similarity + DBSCAN, $0)
- [ ] 0.8.1 Criar `src/pipeline/matcher.py` (cosine similarity + DBSCAN)
- [ ] 0.8.2 Criar teste (clustering, matching)
- [ ] 0.8.3 Testar e commit

### 0.9 — Sentiment Analysis (pysentimiento, local CPU, $0)
- [ ] 0.9.1 Criar `src/pipeline/sentiment.py` (pysentimiento wrapper)
- [ ] 0.9.2 Criar teste (sentiment em PT, ES, EN)
- [ ] 0.9.3 Testar e commit

### 0.10 — GitHub Actions Workflows (substitui APScheduler + servidor)
- [ ] 0.10.1 Criar `src/scrapers/loader.py` (spider registry)
- [ ] 0.10.2 Criar `run_scrape.py` (entrypoint para GHA)
- [ ] 0.10.3 Criar `.github/workflows/scrape.yml` (cron: scraping + embeddings)
- [ ] 0.10.4 Commit

### 0.11 — Data Quality Monitoring (via GHA Summary, sem Grafana)
- [ ] 0.11.1 Criar `src/pipeline/monitor.py` (health checks via Supabase)
- [ ] 0.11.2 Commit

### 0.12 — Testing Suite
- [ ] 0.12.1 Criar `tests/conftest.py` (fixtures)
- [ ] 0.12.2 Criar testes scaffold para Fase 1 (Lusa dependency, silence detector)
- [ ] 0.12.3 Correr suite completa e commit

### 0.13 — Backup & Storage (via Supabase + GitHub, sem S3)
- [ ] 0.13.1 Criar `.github/workflows/backup.yml` (export semanal metadados → GitHub)
- [ ] 0.13.2 Commit

### 0.14 — ERC Publicidade Institucional do Estado
- [ ] 0.14.1 Criar `src/public_sources/__init__.py`
- [ ] 0.14.2 Criar `src/public_sources/erc_advertising.py` (discover PDFs, extract tables)
- [ ] 0.14.3 Criar teste (`tests/test_erc_advertising.py`)
- [ ] 0.14.4 Commit

### 0.15 — dados.gov.pt CKAN Data Portal
- [ ] 0.15.1 Criar `src/public_sources/dados_gov_pt.py` (REST API client)
- [ ] 0.15.2 Criar teste (`tests/test_dados_gov_pt.py`)
- [ ] 0.15.3 Commit

### 0.16 — Media Ownership Reference Dataset
- [ ] 0.16.1 Criar `src/config/ownership.yaml` (11 outlets mapeados)
- [ ] 0.16.2 Criar `src/config/ownership.py` (Pydantic models)
- [ ] 0.16.3 Criar teste (`tests/test_ownership.py`)
- [ ] 0.16.4 Commit

---

## 🎯 Fase 1 — Análise Lusa (7 tarefas)

> **Objetivo:** Quantificar o peso da Lusa nos media portugueses.
> **Dependências:** Fase 0 completa (precisa de dados coletados)

- [ ] 1.1 Tagging de fontes Lusa + deteção de atribuição
- [ ] 1.2 Pipeline de content matching (Lusa → outlets, thresholds 0.85/0.70/0.55)
- [ ] 1.3 Lusa Dependency Score (por outlet, por tópico)
- [ ] 1.4 Topic Monopoly Analysis (tópicos com >80% Lusa)
- [ ] 1.5 Agenda-Setting Metrics (time lag, gatekeeping)
- [ ] 1.6 Lusa Framing Divergence (pysentimiento em vez de Claude API)
- [ ] 1.7 Lusa Influence Report (template Jinja2, sem LLM)

---

## 🪞 Fase 2 — O Espelho Partido (8 tarefas)

> **Objetivo:** Detetar silêncios e assimetrias na cobertura internacional em Portugal.
> **Dependências:** Fases 0 + 1 completas

- [ ] 2.1 Verificação da saúde das fontes internacionais
- [ ] 2.2 Multi-Source Story Clustering (PT + internacional)
- [ ] 2.3 Coverage Comparison Matrix (cobertura por país)
- [ ] 2.4 Silence Detection (Buracos Negros — algoritmo + lista diária)
- [ ] 2.5 Narrative Asymmetry by Figure (Trump, Milei, etc.)
- [ ] 2.6 Topic-Specific Narrative Divergence (Ucrânia, Venezuela, etc.)
- [ ] 2.7 "Jornal do Contra" Generator (template Jinja2, sem LLM)
- [ ] 2.8 Historical Baseline & Anomaly Detection (30+ dias, ±2σ)

---

## 🏛️ Fase 3 — Ecossistema do Estado (9 tarefas)

> **Objetivo:** Mapear toda a rede de comunicação do Estado português.
> **Dependências:** Fases 0 + 1 completas

- [ ] 3.1 Government Communication Collector (portugal.gov.pt, 17 ministérios)
- [ ] 3.2a Diário da República — Taxonomy Mapping
- [ ] 3.2b Diário da República — Scraper Implementation
- [ ] 3.3 Parliamentary Debate Collector (parlamento.pt)
- [ ] 3.4 Institutional Advertising Data (relatórios ERC, camelot-py)
- [ ] 3.5 Personnel Network Graph (Porta Giratória visual — D3.js)
- [ ] 3.6 Parliament-Media Gap Analysis
- [ ] 3.7 Advertising-Editorial Correlation
- [ ] 3.8 Complete Influence Map Dashboard

---

## 🌐 Fase 4 — Exposição Pública (5 tarefas)

> **Objetivo:** Disponibilizar todas as descobertas ao público.
> **Dependências:** Fases 0-3 (pelo menos parcialmente)

- [ ] 4.1 Public Dashboard (React + D3.js, GitHub Pages, lê dados da Supabase)
- [ ] 4.2 Alert System (Telegram Bot via GHA, sem servidor)
- [ ] 4.3 Public API (Supabase REST API + Row Level Security, sem FastAPI)
- [ ] 4.4 Transparency & Methodology (site público)
- [ ] 4.5 Archival & Data Integrity (backup imutável no GitHub)

---

## 📊 Progresso Resumido

| Fase | Total | ✅ Feitas | Progresso |
|------|-------|-----------|-----------|
| Fase 0 — Fundação | 57 | 0 | 0% |
| Fase 1 — Análise Lusa | 7 | 0 | 0% |
| Fase 2 — Espelho Partido | 8 | 0 | 0% |
| Fase 3 — Ecossistema Estado | 9 | 0 | 0% |
| Fase 4 — Exposição Pública | 5 | 0 | 0% |
| **Total** | **86** | **0** | **0%** |

---

## 🚧 Bloqueios Atuais

| Tarefa | Bloqueada por | Motivo |
|--------|---------------|--------|
| — | — | Nenhum bloqueio ativo |

---

## 📝 Notas

- **💰 ZERO COST:** Tudo $0/mês. Ver design doc Appendix C para detalhes.
- **Thresholds de story matching:** Os valores iniciais (0.85/0.70/0.55) precisam de calibração com dataset de ~100 pares manualmente verificados.
- **Acesso Lusa:** Pendente de investigação. O scraper usa RSS público (lusa.pt/rss). Se houver API privada disponível, atualizar.
- **Fontes internacionais:** Serão adicionadas depois da pipeline portuguesa estar estável.
- **GitHub Actions:** Para evitar custos, o repositório deve ser público (minutos ilimitados).
- **Supabase:** 500MB free. Texto completo retido ~1 mês. Depois, apenas metadados + embeddings.
- **Sentiment analysis:** `pysentimiento` corre em CPU local. Suporta PT, ES, EN. Sem API costs.
- **Relatórios:** Gerados com templates Jinja2, não LLM. $0.

---

*Atualizado: 2026-05-27 — Migrado para zero-cost architecture*

