#!/usr/bin/env python3
"""Law × Hiring Temporal Correlation Analysis

Correlates Portuguese law project milestones (from api.votoaberto.org)
with BEP public sector hiring spikes by sector. Identifies patterns like:
- Education laws → increased Professor hiring
- Health laws → increased medical staff hiring
- IT/digital laws → increased tech staff hiring

Usage:
    python law_hiring_correlation.py                    # Full analysis
    python law_hiring_correlation.py --sector education # Filter by sector
    python law_hiring_correlation.py --export report.json
"""

import sys
import sqlite3
import json
import re
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent
LAW_DB = SCRIPT_DIR / "law_index.db"
BEP_DB = SCRIPT_DIR / "bep_index.db"

# ---------------------------------------------------------------------------
# Sector mapping: law project keywords → BEP hiring category keywords
# ---------------------------------------------------------------------------

SECTOR_KEYWORDS = {
    "education": {
        "law_keywords": ["educação", "escola", "professor", "ensino", "universidade",
                         "investigação", "ciência", "aluno", "formação", "pedagogia",
                         "ensino superior", "politécnico"],
        "bep_keywords": ["professor", "investigador", "docente", "ensino",
                         "auxiliar", "associado", "adjunto"],
    },
    "health": {
        "law_keywords": ["saúde", "hospital", "médico", "enfermeiro", "farmácia",
                         "doente", "SNS", "urgência", "vacina", "epidemia"],
        "bep_keywords": ["médico", "enfermeiro", "carreira médica", "saúde",
                         "hospital", "diagnóstico", "terapêutica"],
    },
    "justice": {
        "law_keywords": ["justiça", "tribunal", "juiz", "advogado", "magistrado",
                         "penal", "cível", "procurador"],
        "bep_keywords": ["juiz", "magistrado", "procurador", "advogado",
                         "jurista", "fiscal", "secretário judicial"],
    },
    "infrastructure": {
        "law_keywords": ["obra", "infraestrutura", "estrada", "habitação",
                         "construção", "urbanismo", "transporte", "mobilidade"],
        "bep_keywords": ["engenheiro", "arquiteto", "técnico superior",
                         "assistente operacional"],
    },
    "finance": {
        "law_keywords": ["orçamento", "finanças", "fiscal", "imposto", "taxa",
                         "despesa", "receita", "contabilidade"],
        "bep_keywords": ["contabilista", "auditor", "fiscal", "técnico superior",
                         "assistente técnico"],
    },
    "it_digital": {
        "law_keywords": ["digital", "tecnologia", "informática", "dados",
                         "cibersegurança", "inteligência artificial"],
        "bep_keywords": ["sistemas e tecnologias", "informática", "informático",
                         "especialista de sistemas"],
    },
    "environment": {
        "law_keywords": ["ambiente", "energia", "clima", "sustentabilidade",
                         "água", "floresta", "biodiversidade"],
        "bep_keywords": ["engenheiro", "técnico superior", "investigador"],
    },
    "social": {
        "law_keywords": ["segurança social", "apoio social", "criança",
                         "idoso", "deficiência", "inclusão", "rendimento mínimo"],
        "bep_keywords": ["assistente social", "técnico superior",
                         "assistente operacional"],
    },
}


def classify_law(title: str, desc_tipo: str = "") -> list[str]:
    """Classify a law project into sectors based on title keywords."""
    text = f"{title} {desc_tipo}".lower()
    sectors = []
    for sector, kw in SECTOR_KEYWORDS.items():
        for keyword in kw["law_keywords"]:
            if keyword in text:
                sectors.append(sector)
                break
    return sectors or ["other"]


def classify_bep(categoria: str, funcoes: str = "", organismo: str = "") -> list[str]:
    """Classify a BEP listing into sectors based on category keywords."""
    text = f"{categoria} {funcoes} {organismo}".lower()
    sectors = []
    for sector, kw in SECTOR_KEYWORDS.items():
        for keyword in kw["bep_keywords"]:
            if keyword in text:
                sectors.append(sector)
                break
    return sectors or ["other"]


def load_law_timeline(db_path: Path) -> dict:
    """Load law projects and events into a timeline."""
    conn = sqlite3.connect(str(db_path))

    projects = conn.execute(
        "SELECT ini_id, ini_desc_tipo, ini_titulo, latest_fase, latest_fase_date "
        "FROM law_projects WHERE legislatura = 'L17'"
    ).fetchall()

    events = conn.execute(
        "SELECT ini_id, fase, data_fase FROM law_events "
        "WHERE data_fase IS NOT NULL AND data_fase != '' "
        "ORDER BY data_fase"
    ).fetchall()

    conn.close()

    # Build project lookup
    project_map = {}
    for p in projects:
        sectors = classify_law(p[2] or "", p[1] or "")
        project_map[p[0]] = {
            "ini_id": p[0], "tipo": p[1], "titulo": p[2],
            "fase": p[3], "fase_date": p[4], "sectors": sectors,
        }

    # Build event timeline
    timeline = []
    for e in events:
        proj = project_map.get(e[0], {})
        sectors = proj.get("sectors", ["other"])
        try:
            date = e[2][:10]
        except (IndexError, TypeError):
            continue
        timeline.append({
            "date": date,
            "ini_id": e[0],
            "fase": e[1],
            "titulo": proj.get("titulo", "?"),
            "sectors": sectors,
        })

    return {"projects": project_map, "events": timeline}


def load_bep_timeline(db_path: Path) -> dict:
    """Load BEP listings into a daily timeline grouped by sector."""
    conn = sqlite3.connect(str(db_path))

    rows = conn.execute(
        "SELECT data_publicacao, categoria, funcoes, organismo "
        "FROM bep_listings WHERE data_publicacao != ''"
    ).fetchall()

    conn.close()

    # Group by date and sector
    daily = defaultdict(lambda: defaultdict(int))
    total_by_date = defaultdict(int)

    for r in rows:
        date = r[0][:10]
        sectors = classify_bep(r[1] or "", r[2] or "", r[3] or "")
        for sector in sectors:
            daily[date][sector] += 1
        total_by_date[date] += 1

    return {"daily": dict(daily), "totals": dict(total_by_date)}


def analyze_correlation(law_timeline: dict, bep_timeline: dict, window_days: int = 14):
    """Analyze correlation between law milestones and hiring spikes."""
    events = law_timeline["events"]
    daily_bep = bep_timeline["daily"]

    # Collect law milestones by sector
    sector_milestones = defaultdict(list)
    for evt in events:
        for sector in evt["sectors"]:
            sector_milestones[sector].append({
                "date": evt["date"],
                "fase": evt["fase"],
                "ini_id": evt["ini_id"],
                "titulo": evt["titulo"],
            })

    # For each sector, find hiring volume before and after law milestones
    results = {}
    for sector in SECTOR_KEYWORDS:
        milestones = sector_milestones.get(sector, [])
        if not milestones:
            continue

        # Get all BEP dates for this sector
        sector_dates = sorted(daily_bep.keys())

        # For each milestone, compute hiring volume in window before/after
        pre_counts = []
        post_counts = []

        for ms in milestones:
            try:
                ms_date = datetime.strptime(ms["date"], "%Y-%m-%d")
            except ValueError:
                continue

            pre_start = ms_date - timedelta(days=window_days)
            post_end = ms_date + timedelta(days=window_days)

            pre_count = sum(
                daily_bep.get(d, {}).get(sector, 0)
                for d in sector_dates
                if pre_start.strftime("%Y-%m-%d") <= d < ms_date.strftime("%Y-%m-%d")
            )
            post_count = sum(
                daily_bep.get(d, {}).get(sector, 0)
                for d in sector_dates
                if ms_date.strftime("%Y-%m-%d") <= d <= post_end.strftime("%Y-%m-%d")
            )
            pre_counts.append(pre_count)
            post_counts.append(post_count)

        avg_pre = sum(pre_counts) / len(pre_counts) if pre_counts else 0
        avg_post = sum(post_counts) / len(post_counts) if post_counts else 0
        change_pct = ((avg_post - avg_pre) / avg_pre * 100) if avg_pre > 0 else 0

        results[sector] = {
            "milestones": len(milestones),
            "avg_hiring_before": round(avg_pre, 1),
            "avg_hiring_after": round(avg_post, 1),
            "change_pct": round(change_pct, 1),
            "trend": "📈 up" if change_pct > 10 else ("📉 down" if change_pct < -10 else "➡️ stable"),
            "milestone_details": milestones,
        }

    return results


def print_report(correlations: dict, law_timeline: dict, bep_timeline: dict):
    """Print the correlation report."""
    print(f"\n{'='*80}")
    print(f"  Law × Hiring Temporal Correlation — L17 Legislature")
    print(f"{'='*80}")
    print(f"  Law projects: {len(law_timeline['projects'])}")
    print(f"  Law events:   {len(law_timeline['events'])}")
    print(f"  BEP dates:    {len(bep_timeline['totals'])}")
    print(f"  Total BEP:    {sum(bep_timeline['totals'].values())} listings")
    print(f"{'='*80}\n")

    if not correlations:
        print("  No sector correlations found (need more law events or BEP data)")
        return

    # Summary table
    print(f"  {'Sector':<15} {'Milestones':>10} {'Hires Before':>14} {'Hires After':>14} {'Change':>10} {'Trend':>10}")
    print(f"  {'-'*15} {'-'*10} {'-'*14} {'-'*14} {'-'*10} {'-'*10}")

    for sector, data in sorted(correlations.items(), key=lambda x: abs(x[1]["change_pct"]), reverse=True):
        print(f"  {sector:<15} {data['milestones']:>10} {data['avg_hiring_before']:>14.1f} "
              f"{data['avg_hiring_after']:>14.1f} {data['change_pct']:>9.1f}% {data['trend']:>10}")

    # Detailed breakdown
    print(f"\n{'='*80}")
    print(f"  Detailed Sector Analysis")
    print(f"{'='*80}\n")

    for sector, data in sorted(correlations.items(), key=lambda x: abs(x[1]["change_pct"]), reverse=True):
        print(f"  📊 {sector.upper()}")
        print(f"     Milestones: {data['milestones']} | "
              f"Avg hiring before: {data['avg_hiring_before']:.1f} | "
              f"Avg after: {data['avg_hiring_after']:.1f} | "
              f"Change: {data['change_pct']:+.1f}% {data['trend']}")

        for ms in data["milestone_details"][:3]:
            print(f"       [{ms['date']}] {ms['fase']} — {ms['titulo'][:55]}")
        if len(data["milestone_details"]) > 3:
            print(f"       ... and {len(data['milestone_details']) - 3} more milestones")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Law × Hiring Temporal Correlation Analysis",
    )
    parser.add_argument("--sector", default="", help="Filter by sector")
    parser.add_argument("--window", type=int, default=14, help="Days window around milestones")
    parser.add_argument("--export", help="Export to JSON")
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    if not LAW_DB.exists():
        print(f"ERROR: Law database not found at {LAW_DB}")
        sys.exit(1)
    if not BEP_DB.exists():
        print(f"ERROR: BEP database not found at {BEP_DB}")
        sys.exit(1)

    print("Loading law timeline...")
    law_timeline = load_law_timeline(LAW_DB)

    print("Loading BEP timeline...")
    bep_timeline = load_bep_timeline(BEP_DB)

    print("Analyzing correlations...")
    correlations = analyze_correlation(law_timeline, bep_timeline, args.window)

    if args.sector:
        sector = args.sector.lower()
        if sector in correlations:
            correlations = {sector: correlations[sector]}
        else:
            print(f"No data for sector '{sector}'")
            return

    print_report(correlations, law_timeline, bep_timeline)

    if args.export:
        output = {
            "summary": {
                "law_projects": len(law_timeline["projects"]),
                "law_events": len(law_timeline["events"]),
                "bep_dates": len(bep_timeline["totals"]),
                "bep_total": sum(bep_timeline["totals"].values()),
            },
            "correlations": correlations,
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nExported to {args.export}")


if __name__ == "__main__":
    main()
