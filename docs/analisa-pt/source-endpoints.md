# Source Data Endpoints — Fetch URLs

> The actual URLs and API endpoints that analisa.pt uses to fetch upstream data from government sources.

## Source Endpoints Table

| Source | Layer(s) | Source Code | Fetch URL | Auth | Format |
|---|---|---|---|---|---|
| **INE** | crime, housing, demographics | `0012260`, `0012234`, `0012600`, `0013189`, `0001234`, `0013052`, `0013271`, `0008349` | `https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_api_v2` | No | JSON/CSV |
| **SNS Transparência** | urgency, beds, consults | `atendimentos-em-urgencia-triagem-manchester`, `ocupacao-do-internamento`, `consultas-em-tempo-real`, `utentes-inscritos-em-cuidados-de-saude-primarios` | `https://transparencia.sns.gov.pt/explore/` | No | Opendatasoft API |
| **IPMA** | climate, temperature | — | `https://api.ipma.pt/open-data/` | No | JSON |
| **PORDATA** | 47 municipal summary indicators | — | `https://www.pordata.pt/municipios` | No | Interactive UI / export |
| **ERSAR** | water safety, sanitation | `ersar-agua-segura` | `https://ersar.carto.com/maps` | No | CARTO / reports |
| **IEFP** | registered unemployment | `iefp-desemprego` | PDF reports parsed → `desemprego-pdf` | No | PDF → structured |
| **BASE.gov.pt** | contracts, announcements | `contracts-momentum-12m`, `contracts-12m-per10k`, `contracts-cpv-*` | `https://www.base.gov.pt/Base4/en/` | No | Web scraping |
| **ANACOM** | broadband, speed, mobile | `connectivity_indicators/*` | `https://www.anacom.pt/` (Open Data section) | No | CSV/Excel |
| **Open-Meteo** | climate archive, air quality | `archive-api.open-meteo.com/v1/archive`, `hourly.pm2_5`, `hourly.european_aqi` | `https://archive-api.open-meteo.com/v1/archive`<br>`https://air-quality-api.open-meteo.com/v1/air-quality` | No | JSON |
| **SEF/AIMA** | foreign residents | `0009107+csv-2024` | Periodically published by INE or direct CSV extract | No | CSV |
| **BEP** | public job offers | — | `https://www.bep.gov.pt/pages/oferta/Oferta_Detalhes.aspx?CodOferta={ID}` | No | HTML scraping |

## Detailed URLs by Source

### 1. INE (Instituto Nacional de Estatística)

**API Portal:** `https://www.ine.pt/xportal/xmain?xpid=INE&xpgid=ine_api_v2`

**Known variable codes used by analisa.pt:**

| Variable Code | Description | Frequency |
|---|---|---|
| `0012260` | Crime rate (per 1,000 residents) | Yearly |
| `0012261` | Police reports by type | Yearly |
| `0012234` | House purchase price (€/m²) | Quarterly |
| `0012600` | House rent price (€/m²) | Yearly |
| `0013189` | Population density | Yearly |
| `0001234` | Resident population | Yearly |
| `0001274` | Unemployment rate | Quarterly |
| `0013052` | Housing credit pressure | Yearly |
| `0013271` | Divorce count | Yearly |
| `0008349` | Births (deliveries) | Yearly |
| `0009107` | Foreign residents | Yearly |
| `0013288` | Tourism occupancy rate | Yearly |

**API format:** `https://www.ine.pt/ine/api/metadata/indicators/<varcd>`

---

### 2. SNS Transparência (Health Data)

**Portal:** `https://transparencia.sns.gov.pt/explore/`

Uses **Opendatasoft** platform — each dataset has a built-in API tab.

**Dataset endpoints:**

| Dataset | API Endpoint |
|---|---|
| Urgency episodes (Manchester triage) | `https://transparencia.sns.gov.pt/api/explore/v2.1/catalog/datasets/atendimentos-em-urgencia-triagem-manchester/records` |
| Bed occupancy | `https://transparencia.sns.gov.pt/api/explore/v2.1/catalog/datasets/ocupacao-do-internamento/records` |
| Consult wait times | `https://transparencia.sns.gov.pt/api/explore/v2.1/catalog/datasets/consultas-em-tempo-real/records` |
| Primary care (family doctor) | `https://transparencia.sns.gov.pt/api/explore/v2.1/catalog/datasets/utentes-inscritos-em-cuidados-de-saude-primarios/records` |

---

### 3. IPMA (Weather & Climate)

**API:** `https://api.ipma.pt/open-data/`

| Endpoint | Description |
|---|---|
| `https://api.ipma.pt/open-data/forecast/meteorology/ww/hp-daily-forecast-day0.json` | Daily forecast |
| `https://api.ipma.pt/open-data/forecast/meteorology/ww/hp-daily-forecast-day1.json` | Day+1 forecast |
| `https://api.ipma.pt/open-data/observation/se498/hp-daily-se498-d0.json` | Daily observations |
| `https://api.ipma.pt/open-data/observation/climatology/hp-daily-climatology.json` | Historical climate data |
| `https://api.ipma.pt/open-data/distrits-islands.json` | District/island metadata |

---

### 4. PORDATA

**Portal:** `https://www.pordata.pt/`

No public API. Data accessed through:
- Interactive UI at `https://www.pordata.pt/municipios`
- Spreadsheet exports
- Community scrapers

---

### 5. ERSAR (Water & Sanitation)

**Portal:** `https://ersar.pt/`

| Resource | URL |
|---|---|
| Água Segura 2024 results | `https://ersar.pt/site/AguaSegura/Resultados.aspx` |
| CARTO visualizations | `https://ersar.carto.com/maps` |

---

### 6. IEFP (Employment)

**Portal:** `https://www.iefp.pt/`

Unemployment data published as PDF reports, parsed into structured data:
- Monthly PDFs with registered unemployment by municipality
- Source code in analisa.pt: `desemprego-pdf`

---

### 7. BASE.gov.pt (Public Contracts)

**Portal:** `https://www.base.gov.pt/Base4/en/`

No official public API. Analisa.pt scrapes the portal.

| Data | Portal URL |
|---|---|
| Contracts search | `https://www.base.gov.pt/Base4/en/Consulta/Contratos` |
| Announcements | `https://www.base.gov.pt/Base4/en/Consulta/Anuncios` |
| Entities | `https://www.base.gov.pt/Base4/en/Consulta/Entidades` |

---

### 8. ANACOM (Telecom)

**Portal:** `https://www.anacom.pt/`

Open Data section provides connectivity indicators:
- Broadband coverage
- Download/upload speeds
- Mobile 4G coverage

---

### 9. Open-Meteo (Air Quality & Climate)

**Free API, no auth required.**

| Endpoint | URL Format |
|---|---|
| Air Quality | `https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lng}&hourly=pm2_5,european_aqi` |
| Climate Archive | `https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lng}&start_date={start}&end_date={end}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum` |

---

### 10. SEF/AIMA (Immigration)

**Former SEF, now AIMA (Agência para a Integração, Migrações e Asilo)**

No public API. Foreign resident data:
- Periodically published by INE as CSV
- Analisa.pt source code: `0009107+csv-2024`

---

### 11. BEP (Bolsa de Emprego Público — Public Job Offers)

**Portal:** `https://www.bep.gov.pt/`

**No formal REST API**, but individual job listings are accessible via URL pattern:

```
https://www.bep.gov.pt/pages/oferta/Oferta_Detalhes.aspx?CodOferta={ID}
```

**Scraping Details:**

| Feature | Details |
|---|---|
| URL Pattern | `https://www.bep.gov.pt/pages/oferta/Oferta_Detalhes.aspx?CodOferta={ID}` |
| Format | HTML (ASP.NET WebForms) |
| Authentication | None required |
| ID Range | Sequential (e.g., 148309, 148310, ...) |

**HTML Field Selectors (ASP.NET span IDs):**

| Field | Selector ID |
|---|---|
| Offer Code | `lblNOCodigo` |
| Status | `lblNOEstado` |
| Organization | `lblNONivelOrganico` |
| Career/Category | `lblNOCarreira`, `lblNOCategoria` |
| Compensation | `lblNORemuneracao` |
| Publication Date | `lblNODataPub` |
| Deadline | `lblNODataLim` |
| Qualifications | `lblNOHabLit` |

**Data Available per Listing:**
- Entity (organization)
- Job title
- Number of vacancies
- Publication date / deadline
- Work location
- Scientific area / job description
- Contract type and duration
- Requirements (education, experience)
- Salary / compensation
- Application instructions
- Selection process details
- Jury composition

**Example Listing (CodOferta=148309):**
- Entity: Laboratório Nacional de Engenharia Civil (LNEC)
- Title: Investigador(a) Auxiliar (R3)
- Vacancies: 1
- Salary: €3,576.56/month (exclusive dedication)
- Deadline: 2026-06-24

**Notes:**
- Site uses ASP.NET `__doPostBack` for search (session state required)
- Detail pages with `CodOferta` parameter are directly accessible
- No RSS/Atom feeds, no robots.txt, no sitemap.xml
- Managed by DGAEP (Direção-Geral da Administração e do Emprego Público)
- Also managed by SGU (Serviço Partilhado de Gestão de Recursos Humanos)

---

### 12. dados.gov.pt (National Open Data Portal)

**Portal:** `https://dados.gov.pt/`

Central repository where government agencies publish datasets. Can be used to discover additional data sources.
