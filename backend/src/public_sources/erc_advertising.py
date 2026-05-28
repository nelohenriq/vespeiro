"""
Scraper for ERC Institutional Advertising Reports.

Source: https://www.erc.pt/pt/estudos/publicidade--/relatorio-sobre-publicidade-institucional-do-estado-/

These monthly PDF reports contain:
- Which government entities bought advertising
- Which media outlets received the spending
- Amount spent per campaign

Strategy:
1. Fetch the listing page to discover PDF URLs
2. Download new PDFs (skip already-downloaded)
3. Extract tables from PDFs using pdfplumber
4. Return structured data (entity, outlet, amount, date)
"""

import re
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class AdvertisingRecord:
    entity: str          # e.g. "Repartição do Estado"
    media_outlet: str    # e.g. "RTP1", "Público", "Facebook"
    campaign: str        # e.g. "Campanha de Vacinação"
    amount_cents: int    # Amount in euro cents (avoid float precision)
    month: str           # ISO month: "2026-05"
    source_url: str      # PDF URL for audit trail


ERC_BASE_URL = "https://www.erc.pt"
ERC_REPORTS_PAGE = "/pt/estudos/publicidade--/relatorio-sobre-publicidade-institucional-do-estado-/"
PDFS_DIR = Path("data/erc_pdfs")


# ── Discovery ───────────────────────────────────────────────────────────────


def discover_monthly_reports() -> list[dict]:
    """Fetch the ERC page and extract all PDF report links."""
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(f"{ERC_BASE_URL}{ERC_REPORTS_PAGE}")
        resp.raise_for_status()

    pdf_links: list[dict] = []
    pattern = r'href=["\']([^"\']+\.pdf)["\']'
    for match in re.finditer(pattern, resp.text):
        pdf_url = match.group(1)
        if pdf_url.startswith("/"):
            pdf_url = f"{ERC_BASE_URL}{pdf_url}"
        pdf_links.append({
            "url": pdf_url,
            "filename": Path(pdf_url).name,
        })

    return pdf_links


# ── Download ────────────────────────────────────────────────────────────────


def download_pdf(url: str, filename: str) -> Path | None:
    """Download a PDF report if not already cached."""
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    local_path = PDFS_DIR / filename

    if local_path.exists():
        return local_path

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            return None
        local_path.write_bytes(resp.content)

    return local_path


# ── Extraction ──────────────────────────────────────────────────────────────


def _extract_month_from_filename(filename: str) -> str:
    """Extract ISO month from filename like 'PIE_2025_04.pdf' -> '2025-04'."""
    match = re.search(r"(\d{4})[_-]?(\d{2})", filename)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return filename


def extract_advertising_data(
    pdf_path: Path, original_url: str = ""
) -> list[AdvertisingRecord]:
    """Extract structured advertising data from a PDF report.

    Uses ``pdfplumber`` to extract tables.
    Expected columns: Entity, Media Outlet, Campaign, Amount (€).
    """
    import pdfplumber

    records: list[AdvertisingRecord] = []
    month = _extract_month_from_filename(pdf_path.name)

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    for row in table[1:]:  # Skip header row
                        if not row or len(row) < 4:
                            continue
                        entity = (row[0] or "").strip()
                        outlet = (row[1] or "").strip()
                        campaign = (row[2] or "").strip()
                        amount_str = (row[3] or "0").strip()

                        if not entity or not outlet:
                            continue

                        # Parse amount (e.g. "1 234,56 €" -> 123456 cents)
                        amount_clean = (
                            amount_str.replace("€", "")
                            .replace(" ", "")
                            .replace(".", "")
                            .replace(",", ".")
                        )
                        try:
                            amount_cents = int(float(amount_clean) * 100)
                        except (ValueError, TypeError):
                            amount_cents = 0

                        records.append(AdvertisingRecord(
                            entity=entity,
                            media_outlet=outlet,
                            campaign=campaign,
                            amount_cents=amount_cents,
                            month=month,
                            source_url=original_url or str(pdf_path),
                        ))
    except Exception as exc:
        print(f"  ⚠️ Failed to extract {pdf_path.name}: {exc}")

    return records


# ── Full pipeline ───────────────────────────────────────────────────────────


def get_all_advertising() -> list[AdvertisingRecord]:
    """Full pipeline: discover -> download -> extract all available reports."""
    reports = discover_monthly_reports()
    all_records: list[AdvertisingRecord] = []

    for report in reports[:3]:  # Limit to 3 most recent to avoid overload
        try:
            local_path = download_pdf(report["url"], report["filename"])
            if local_path:
                records = extract_advertising_data(
                    local_path, original_url=report["url"]
                )
                print(f"  Extracted {len(records)} records from {report['filename']}")
                all_records.extend(records)
        except Exception as exc:
            print(f"  ⚠️ Failed to process {report['filename']}: {exc}")

    return all_records
