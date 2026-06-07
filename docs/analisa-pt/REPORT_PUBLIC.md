# Portuguese Public Procurement — Anomaly Investigation Report

**Date:** June 2026  
**Data:** 244,897 public contracts analyzed from BASE.gov.pt  
**Scope:** All municipalities and public entities with construction/works contracts

---

## Key Findings

### 1. Price Inflation in Public Works

**24 municipalities** show an unusual combination of limited competition and contracts that cost more than originally budgeted.

**Most affected:**

| Municipality | Issue | Amount at stake |
|--------------|-------|-----------------|
| Município do Fundão | 10 contracts went over budget by an average of 15.6% | €1.45 million overrun |
| Município de Ponte de Sor | 8 contracts with 86.5% concentration among top 3 suppliers | €1.1 million overrun |
| Estado-Maior do Exército | 6 contracts with 21.2% average price increase | €1.6 million overrun |

**Context:** Nationally, only 0.5% of construction contracts show price inflation. Fundão's rate of 2.3% is **4.6 times higher** than the national average.

### 2. Closed Procurement Ecosystems

In **79% of municipalities**, just 3 companies receive more than 60% of construction contract value. While this is common in smaller markets, it raises questions about competitive bidding.

**Fundão example:** Three companies — NOW XXI, Constrobi, and VectorPlano — dominate construction procurement. One of them, Constrobi, has **never won a contract outside Fundão** in our dataset (11 contracts, €3 million total).

### 3. Missing Competition Data

**57% of all contracts** (140,000+) have no information about competing bidders. Without knowing who competed, it's impossible to assess whether procurement processes are genuinely competitive.

### 4. Self-Referencing Entities

**495 public entities** appear as both the buyer and the seller in contracts — meaning they awarded contracts to themselves. This is a red flag that warrants investigation in each case.

---

## Case Study: Fundão

Fundão ranks as the highest-risk municipality in our analysis for several overlapping reasons:

- **10 contracts** where the final price exceeded the originally stated maximum by an average of 15.6%
- All 10 contracts were signed in **2025**, during a change in municipal leadership
- **Constrobi**, a construction company based in Fundão, has won 11 contracts worth €3 million — exclusively from Fundão
- The other two major contractors (NOW XXI and VectorPlano) also showed price inflation on Fundão contracts

**What we don't know:** Whether the initial budget prices were set artificially low, or whether contracts were modified after award. The public procurement database does not track contract changes.

**What we found:** No direct links between Fundão council members and the three construction companies in official records (DRE publications, parliamentary law projects). Two individuals — Olga Maria Leitão Ramos Alves and Mariana Brito Páscoa — received contracts from Fundão and may warrant further investigation.

---

## National Picture

| Finding | Scope |
|---------|-------|
| Contracts analyzed | 244,897 |
| Municipalities with limited competition + price inflation | 24 |
| Public entities self-awarding contracts | 495 |
| Contracts with no competition data | 140,000+ (57%) |
| Total price overrun across all contracts | €56.5 million |

---

## Data Limitations

This analysis is based on publicly available procurement data from BASE.gov.pt. Key limitations:

1. **No contract modification data** — We cannot distinguish between low initial budgets and post-award price increases
2. **No company ownership data** — We cannot determine whether officials have financial connections to contractors
3. **No bid-level data** — We cannot detect coordinated pricing or bid rigging
4. **Incomplete competition records** — Most contracts lack information about competing bidders

---

## Recommendations

1. **Mandatory competition disclosure** — Require all contracts above €50,000 to list competing bidders
2. **Contract modification tracking** — Add amendment/addendum records to the public procurement database
3. **Automated monitoring** — Implement regular scans for price inflation and self-referencing patterns
4. **Cross-referencing** — Link procurement data with company registries to detect conflicts of interest
5. **Investigate the 24 dual-anomaly municipalities** — Prioritize those with both high concentration and price inflation

---

## Methodology

This report is based on automated analysis of Portuguese public procurement data. We used:

- **Price analysis:** Comparing contract base prices (precoBaseProcedimento) against final prices (precoContratual)
- **Concentration analysis:** Measuring Herfindahl-Hirschman Index (HHI) and top-3 supplier share
- **Cross-referencing:** Matching entities across procurement, employment (BEP), official gazette (DRE), and parliamentary databases
- **Statistical comparison:** Benchmarking individual municipalities against national averages

All data and analysis tools are available for review. The methodology can be replicated by third parties.

---

## About This Investigation

This analysis was conducted using publicly available data from Portuguese government databases. It is not an audit or legal investigation. Findings indicate patterns that warrant further investigation by appropriate oversight bodies.

**Contact:** [Insert contact information]

**Data sources:**
- BASE.gov.pt — Public procurement contracts
- BEP (Bolsa de Emprego Público) — Public employment listings
- Diário da República Eletrónico (DRE) — Official gazette
- Portuguese Parliament — Law projects and parliamentary questions

---

*Report generated June 2026. Data reflects contracts published through the analysis date.*
