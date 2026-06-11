# Cross-Reference Detectors — 5 New Corruption Pattern Tools

**Date:** 2026-06-07  
**Status:** Design document — approved for implementation  

Builds 5 new tools that cross-reference existing data sources to detect corruption patterns invisible in any single dataset alone.

---

## Tool 1: Multi-Source Entity Profile (`entity_multi_source.py`)

**Purpose:** Single command shows everything known about any entity across all 14 data sources.

**Data Sources:** BAS.E contracts, PRR, BEP jobs, DRE appointments, DRE publications, law projects, TED, anúncios, news articles, anomaly scores, dual-role risk, contract modifications.

**Key Design Decisions:**
- Search by NIF or fuzzy name match
- Single output per entity with sections for each data source
- JSON export for downstream use
- `--compare NIF1 NIF2` for side-by-side comparison (leverage existing `compare_entities.py`)

**Output sections:**
1. **Overview** — Entity name, NIF, risk scores (anomaly, dual-role, composite)
2. **Procurement** — Contracts as buyer, contracts as supplier, inflation, concentration
3. **PRR** — Beneficiary status, contracts, projects, execution rate, cd_base_gov matches
4. **BEP** — Job listings count, hiring trends
5. **DRE** — Appointments (organization, role, dates), publications
6. **News** — Article count, sentiment, sources
7. **Modifications** — Contract amendment count, total value changed
8. **Laws** — Law project mentions

**Risk Score:** Combine all source signals into a single 0-100 multi-source risk score (new, beyond existing individual scores).

---

## Tool 2: Revolving Door Detector (`revolving_door_detector.py`)

**Purpose:** Find people appointed to public positions whose organizations then award contracts to specific companies — detecting conflicts of interest and post-employment influence.

**Data Sources:** DRE appointments (`appointments.organization`, `appointments.role`, `appointments.published_at`) × Procurement contracts (`adjudicante_nome`, `adjudicatarios`, `dataCelebracaoContrato`).

**Detection Logic:**
1. Extract entity name from DRE appointment (e.g., "Câmara Municipal do Fundão")
2. Find all procurement contracts where that entity is the buyer
3. Check if any contractor (adjudicatário) was awarded contracts shortly after the appointment
4. Flag temporal proximity: contract signed within N months of appointment

**Risk Signals:**
- Contract awarded within 3 months of appointment → **Critical** (score +40)
- Same company wins multiple contracts after a single appointment → **High** (+25)
- Company has no prior history with that buyer before appointment → **High** (+20)
- Individual contract winners (not companies) receiving contracts → **Medium** (+15)

**Output:** Table of flagged person→organization→company→contract chains, sorted by risk score. JSON export with full chain details.

---

## Tool 3: Full Money Trail (`money_trail_analyzer.py`)

**Purpose:** Trace public money from EU allocation (PRR) through national budget execution to final procurement contracts — detecting where money "expands" or disappears along the chain.

**Data Sources:** PRR locations (`prr_locations.ds_concelho`, `perc_valor_aprovado`) × Budget execution (`budget.descricao`, `valor_previsto`, `valor_realizado`) × Procurement contracts (`adjudicante_nif`, `NUTs`, `precoContratual`).

**Detection Logic:**
1. Map PRR money to concelho (from `prr_locations`)
2. Map budget execution to similar category/period
3. Map procurement contracts to same concelho (via NUTs code or buyer entity name)
4. Compute ratios: PRR allocated vs budget spent vs procurement signed
5. Flag anomalies where the ratios deviate significantly

**Three-Phase Analysis:**
- **Phase 1:** PRR → Concelho (how much EU money flows where)
- **Phase 2:** Concelho Budget → Actual Spending (planned vs real, per category)
- **Phase 3:** Procurement in Concelho (contracts signed, inflation, concentration)

**Risk Signals:**
- Money "expansion": PRR allocates €5M → procurement shows €7.5M in related contracts (+50%)
- Execution gap: PRR allocates → budget plans → but procurement never happens
- Budget variance: planned vs actual > 50% in categories related to PRR projects
- Geographic mismatch: PRR money flows to concelho X but procurement concentrated in concelho Y

**Output:** Concelho-by-concelho money trail report with chain diagrams. JSON export.

---

## Tool 4: Full Price Chain Analyzer (`price_chain_analyzer.py`)

**Purpose:** Track the complete price evolution of a public contract from initial announcement through signing to post-award modifications — detecting the "lowball → win → inflate" pattern.

**Data Sources:** Anúncios (`anuncios.PrecoBase`, `nAnuncio`) × Contracts (`precoContratual`, `precoBaseProcedimento`, `nAnuncio`) × Modifications (`modificacoes.preco_alterado`, `fundamento`).

**Detection Logic:**
1. Link anúncio → contrato via `(nAnuncio, NIF)`
2. Link contrato → modificações via `idcontrato`
3. Compute chain ratios: Base→Signed, Signed→Modified, Base→Modified
4. Flag contracts where the total price change exceeds thresholds

**Chain Visualisation per Contract:**
```
Anúncio base: €100K
    → Signed: €95K  (-5%)  [competitive bid, looks good]
    → Mod #1: +€30K (fundamento: "trabalhos a mais")
    → Mod #2: +€50K (fundamento: "alteração de preços")
    → Mod #3: +€25K (fundamento: "prorrogação prazo")
    ═══════════════════════════════
    Final: €200K  (+100% vs base)
```

**Risk Signals:**
- Chain total > +50% of base price
- Multiple modifications to same contract
- Modifications justified by vague fundamentos
- Rapid modifications (all within months of signing)
- Contracts without anúncio (no transparency at all)

**Output:** Ranked contracts by total price increase. JSON with full chain details.

---

## Tool 5: News × Procurement Correlator (`news_procurement_correlator.py`)

**Purpose:** Correlate media coverage (or silence) with procurement anomalies — detecting whether high-anomaly entities face media scrutiny or benefit from media silence.

**Data Sources:** Vespeiro articles (`articles.content_text`, `articles.title`, `articles.source_id`, `articles.published_at`) × Anomaly scores × Procurement entities.

**Detection Logic:**
1. Extract entity names from news articles (fuzzy match against entity database)
2. Compute per-entity: article count, sentiment trend, source diversity
3. Correlate with anomaly scores, dual-role risk, price inflation
4. Flag entities with high anomaly but low media coverage (silence)
5. Flag entities with high coverage and negative sentiment (scandal)

**Three Analysis Modes:**
- **silence-scan:** Entities with high anomaly score but zero/low news mentions
- **sentiment-trend:** Sentiment over time for flagged entities around contract award dates
- **source-map:** Which news sources cover which flagged entities (detect media capture)

**Risk Signals:**
- Anomaly score >70 + zero news mentions = **media silence** (score +30)
- Negative sentiment spike correlated with contract award date = **scrutiny triggered by specific event** (+20)
- Only one news source covers a flagged entity = **media concentration** (+15)
- News silence broken by exposé = **prior cover-up** (+25)

**Output:** Ranked entities by silence/anomaly ratio. Per-entity sentiment timelines. Source diversity reports. JSON export.

---

## Unified Architecture

All 5 tools share:
- Same DB connection approach (add `backend/src/db/session.py` import path for Postgres readiness)
- Same entity resolution logic (NIF-based matching with fuzzy name fallback)
- Same output format (console report + JSON export)
- Same risk score normalization (0-100 scale, factors summed and capped)

CLI pattern (consistent across all tools):
```python
python entity_multi_source.py --nif 514288256
python entity_multi_source.py --search "Fundão"
python revolving_door_detector.py --top 50
python revolving_door_detector.py --nif 514288256  # Single entity chain
python money_trail_analyzer.py --concelho "Fundão"
python price_chain_analyzer.py --top 50
python price_chain_analyzer.py --nif 514288256  # All contracts for entity
python news_procurement_correlator.py silence-scan
python news_procurement_correlator.py sentiment-trend --entity "Fundão"
```

---

## Implementation Order

Each tool depends on the previous one's output data but is independently runnable:

1. **Tool 1** — Entity multi-source profile (foundation for all others)
2. **Tool 2** — Revolving door detector (DRE × procurement, highest impact)
3. **Tool 3** — Money trail analyzer (PRR × Budget × Procurement)
4. **Tool 4** — Price chain analyzer (Anúncios × Contratos × Modificações)
5. **Tool 5** — News × Procurement correlator (needs Tool 1's entity resolution)

---

*Implementation plan generated separately for each tool.*
