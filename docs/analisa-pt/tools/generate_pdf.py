#!/usr/bin/env python3
"""PDF Export for Entity Transparency Profiles

Generates a printable PDF report from entity profile data.

Usage:
    python generate_pdf.py "Câmara Municipal de Gaia" -o gaia_report.pdf
    python generate_pdf.py --nif 500014872 -o report.pdf
    python generate_pdf.py "Saúde" --open
"""

import sys
import argparse
import webbrowser
from pathlib import Path

try:
    from fpdf import FPDF
except ImportError:
    print("ERROR: fpdf2 required. Install: pip install fpdf2")
    sys.exit(1)

from entity_profile import (
    search_entities, get_entity_listings, get_entity_contracts,
    get_entity_dre, get_entity_laws, compute_contract_trends,
    compute_hiring_trends,
)


def _safe(text) -> str:
    """Sanitize text for PDF (remove non-Latin-1 chars)."""
    if not text:
        return ""
    return str(text).encode("latin-1", errors="replace").decode("latin-1")


class TransparencyPDF(FPDF):
    """Custom PDF class for transparency reports."""

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Analisa.pt - Entity Transparency Report", align="L")
        self.ln(4)
        self.set_draw_color(59, 130, 246)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def section_title(self, icon: str, title: str, count: int = 0):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 41, 59)
        label = f"{icon}  {_safe(title)}"
        if count:
            label += f"  ({count})"
        self.cell(0, 10, _safe(label), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def key_value(self, key: str, value: str, bold_val: bool = False):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(100, 100, 100)
        self.cell(50, 7, _safe(key) + ":", new_x="END")
        self.set_font("Helvetica", "B" if bold_val else "", 10)
        self.set_text_color(30, 41, 59)
        self.cell(0, 7, _safe(value), new_x="LMARGIN", new_y="NEXT")

    def data_table(self, headers: list[str], rows: list[list[str]], col_widths: list[float] = None):
        if not col_widths:
            w = 190 / len(headers)
            col_widths = [w] * len(headers)

        # Header
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(241, 245, 249)
        self.set_text_color(100, 116, 139)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, _safe(h), border=0, fill=True, new_x="END")
        self.ln(7)

        # Rows
        self.set_font("Helvetica", "", 8)
        self.set_text_color(30, 41, 59)
        for row in rows:
            if self.get_y() > 270:
                self.add_page()
            for i, val in enumerate(row):
                text = _safe(str(val)[:50] if val else "-")
                self.cell(col_widths[i], 6, text, border=0, new_x="END")
            self.ln(6)
            # Subtle row separator
            self.set_draw_color(240, 240, 240)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(1)

    def trend_table(self, data: dict, value_key: str, label: str, currency: bool = True):
        if not data:
            return
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(30, 41, 59)
        total = sum(d.get(value_key, 0) for d in data.values())
        avg = total / len(data) if data else 0
        if currency:
            self.cell(0, 7, f"{label} (Total: EUR {total:,.0f} | Avg: EUR {avg:,.0f}/month)",
                      new_x="LMARGIN", new_y="NEXT")
        else:
            self.cell(0, 7, f"{label} (Total: {total} | Avg: {avg:.1f}/month)",
                      new_x="LMARGIN", new_y="NEXT")

        self.set_font("Helvetica", "", 8)
        for period, d in data.items():
            val = d.get(value_key, 0)
            max_val = max(x.get(value_key, 0) for x in data.values()) or 1
            bar_len = int((val / max_val) * 60) if max_val > 0 else 0
            bar = "#" * bar_len
            if currency and val >= 1000:
                val_str = f"EUR {val:,.0f}"
            elif currency:
                val_str = f"EUR {val:,.2f}"
            else:
                val_str = str(val)
            self.set_text_color(100, 116, 139)
            self.cell(20, 5, period, new_x="END")
            self.set_text_color(59, 130, 246)
            self.cell(65, 5, bar, new_x="END")
            self.set_text_color(30, 41, 59)
            self.cell(0, 5, val_str, new_x="LMARGIN", new_y="NEXT")
        self.ln(4)


def generate_pdf(entity, listings, contracts, dre, laws, output_path: str):
    """Generate a PDF report for an entity."""
    pdf = TransparencyPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    nif = entity.get("nif", "")
    total_value = sum(c.get("valor", 0) for c in contracts)

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 12, _safe(entity["display_name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Entity info
    pdf.key_value("NIF", nif or "N/A", bold_val=True)
    pdf.key_value("Department", _safe(entity.get("entidade", "-")[:70]))
    pdf.key_value("Organization", _safe(entity.get("organismo", "-")[:70]))
    pdf.key_value("BEP Listings", str(entity.get("listing_count", 0)))
    pdf.key_value("BASE Contracts", f"{len(contracts)} (EUR {total_value:,.2f} total)")
    pdf.key_value("DRE Publications", str(len(dre)))
    pdf.key_value("Law Projects", str(len(laws)))
    if nif:
        pdf.key_value("BASE.gov.pt", f"https://www.base.gov.pt/Base4/pt/detalhe/?type=entidades&id={nif}")
    pdf.ln(6)

    # Summary cards
    pdf.set_draw_color(200, 200, 200)
    pdf.rect(10, pdf.get_y(), 190, 20)
    pdf.set_y(pdf.get_y() + 3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(100, 116, 139)
    col_w = 190 / 5
    vals = [
        (str(len(listings)), "Listings"),
        (str(len(contracts)), "Contracts"),
        (f"EUR {total_value:,.0f}", "Value"),
        (str(len(dre)), "DRE"),
        (str(len(laws)), "Laws"),
    ]
    for val, lbl in vals:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(col_w, 8, val, align="C", new_x="END")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(100, 116, 139)
    for _, lbl in vals:
        pdf.cell(col_w, 5, lbl, align="C", new_x="END")
    pdf.ln(12)

    # Contract Trends
    contract_trends = compute_contract_trends(contracts)
    if contract_trends:
        pdf.section_title("=", "Contract Value by Month", len(contracts))
        pdf.trend_table(contract_trends, "value", "Contract Value", currency=True)

    # Hiring Trends
    hiring_trends = compute_hiring_trends(listings)
    if hiring_trends:
        pdf.section_title("=", "BEP Hiring by Month", len(listings))
        pdf.trend_table(hiring_trends, "count", "Listings", currency=False)

    # BEP Job Listings
    if listings:
        pdf.add_page()
        pdf.section_title("=", "BEP Job Listings", len(listings))
        headers = ["Status", "Title", "Category", "Salary", "Positions", "Deadline"]
        rows = []
        for l in listings[:40]:
            status = "Open" if "aberta" in (l.get("estado") or "").lower() else "Closed"
            rows.append([
                status,
                _safe((l.get("titulo") or "-")[:45]),
                _safe((l.get("categoria") or "-")[:20]),
                _safe(f"EUR {l.get('remuneracao', '-')}"),
                str(l.get("total_postos", "1")),
                _safe((l.get("data_limite") or "-")[:10]),
            ])
        pdf.data_table(headers, rows, [18, 60, 35, 30, 20, 27])
        if len(listings) > 40:
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(128, 128, 128)
            pdf.cell(0, 6, f"... and {len(listings) - 40} more listings", new_x="LMARGIN", new_y="NEXT")

    # BASE Contracts
    if contracts:
        pdf.add_page()
        pdf.section_title("=", "BASE.gov.pt Contracts", len(contracts))
        headers = ["Date", "Value", "Type", "Description"]
        rows = []
        for c in contracts[:40]:
            rows.append([
                _safe((c.get("data") or "-")[:10]),
                _safe(f"EUR {c.get('valor', 0):,.2f}"),
                _safe((c.get("tipo") or "-")[:25]),
                _safe((c.get("objeto") or "-")[:55]),
            ])
        pdf.data_table(headers, rows, [25, 35, 45, 85])
        if len(contracts) > 40:
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(128, 128, 128)
            pdf.cell(0, 6, f"... and {len(contracts) - 40} more contracts", new_x="LMARGIN", new_y="NEXT")

    # DRE Publications
    if dre:
        pdf.add_page()
        pdf.section_title("=", "DRE Publications", len(dre))
        headers = ["Serie", "Number", "Year", "Title"]
        rows = []
        for d in dre[:30]:
            title = _safe(d.get("title") or f"Serie {d.get('serie')} #{d.get('numero')}/{d.get('year')}")
            rows.append([
                str(d.get("serie", "-")),
                str(d.get("numero", "-")),
                str(d.get("year", "-")),
                _safe(title[:65]),
            ])
        pdf.data_table(headers, rows, [15, 20, 15, 140])

    # Law Projects
    if laws:
        pdf.add_page()
        pdf.section_title("=", "Law Projects", len(laws))
        headers = ["Type", "Title", "Phase", "Date", "Vote"]
        rows = []
        for l in laws[:30]:
            rows.append([
                _safe((l.get("ini_desc_tipo") or "-")[:20]),
                _safe((l.get("ini_titulo") or "-")[:50]),
                _safe((l.get("latest_fase") or "-")[:15]),
                _safe((l.get("latest_fase_date") or "-")[:10]),
                _safe((l.get("vote_result") or "-")[:15]),
            ])
        pdf.data_table(headers, rows, [25, 70, 25, 25, 45])

    pdf.output(output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate PDF Transparency Report")
    parser.add_argument("query", nargs="?", default="", help="Entity name")
    parser.add_argument("--nif", default="", help="Filter by NIF")
    parser.add_argument("-o", "--output", default="", help="Output PDF file")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")

    args = parser.parse_args()

    if not args.query and not args.nif:
        parser.print_help()
        sys.exit(1)

    entities = search_entities(query=args.query, nif=args.nif, limit=1)
    if not entities:
        print(f"No entity found matching '{args.query or args.nif}'")
        sys.exit(1)

    entity = entities[0]
    print(f"Generating PDF report for {entity['display_name']}...")

    listings = get_entity_listings(entity["id"])
    contracts = get_entity_contracts(entity.get("nif", ""), entity_name=entity.get("display_name", ""), entidade=entity.get("entidade", ""))
    dre = get_entity_dre(entity["display_name"])
    laws = get_entity_laws(entity["display_name"])

    print(f"  BEP: {len(listings)} listings | BASE: {len(contracts)} contracts | DRE: {len(dre)} | Laws: {len(laws)}")

    output = args.output or f"report_{entity.get('nif', 'entity')}.pdf"
    generate_pdf(entity, listings, contracts, dre, laws, output)
    print(f"  ✅ PDF saved to {output}")

    if args.open:
        webbrowser.open(Path(output).resolve().as_uri())


if __name__ == "__main__":
    main()
