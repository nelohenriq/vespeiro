#!/usr/bin/env python3
"""Data Quality Report — NIF Coverage & Scraping Gap Analysis."""
import argparse, json, os, sqlite3, sys
from collections import defaultdict
from pathlib import Path
from unidecode import unidecode

from utils import fmt

SCRIPT_DIR = Path(__file__).parent
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
NIF_MAPPING_FILE = SCRIPT_DIR / "data" / "nif_mapping.json"
XLSX_FILE = SCRIPT_DIR / "data" / "contratos2025.xlsx"

def audit_contract_index():
    with open(CONTRACT_INDEX, "r") as f:
        index = json.load(f)
    tc = sum(len(cs) for cs in index.values())
    tv = sum(c.get("valor", 0) or 0 for cs in index.values() for c in cs)
    et = defaultdict(lambda: {"count": 0, "value": 0.0, "nifs": set()})
    mn, cn = set(), set()
    for nif, contracts in index.items():
        for c in contracts:
            nl = unidecode(c.get("entity_name", "").lower())
            v = c.get("valor", 0) or 0
            if "municipio" in nl: k = "municipio"; mn.add(nif)
            elif "camara" in nl: k = "camara"; cn.add(nif)
            elif "junta" in nl or "freguesia" in nl: k = "freguesia"
            elif "hospital" in nl or "unidade local" in nl: k = "health"
            elif "escola" in nl or "agrupamento" in nl: k = "education"
            elif "associacao" in nl: k = "association"
            elif "empresa municipal" in nl: k = "empresa_municipal"
            else: k = "other"
            et[k]["count"] += 1; et[k]["value"] += v; et[k]["nifs"].add(nif)
    return {"total_nifs": len(index), "total_contracts": tc, "total_value": tv,
            "entity_types": {k: {"count": v["count"], "value": v["value"], "unique_nifs": len(v["nifs"])} for k, v in et.items()},
            "municipio_nifs": mn, "camara_nifs": cn}

def audit_nif_mapping():
    if not NIF_MAPPING_FILE.exists(): return {"total": 0, "camara_nifs": set(), "municipio_nifs": set()}
    with open(NIF_MAPPING_FILE, "r") as f: data = json.load(f)
    ms = data.get("mappings", []) if isinstance(data, dict) else data
    return {"total": len(ms), "camara_nifs": {m["camara_nif"] for m in ms if m.get("camara_nif")}, "municipio_nifs": {m["municipio_nif"] for m in ms if m.get("municipio_nif")}}

def audit_bep():
    if not BEP_DB.exists(): return {"error": "not found"}
    try:
        conn = sqlite3.connect(str(BEP_DB))
        t = conn.execute("SELECT COUNT(*) FROM bep_entities WHERE nif IS NOT NULL AND nif != ''").fetchone()[0]
        c = conn.execute("SELECT COUNT(DISTINCT nif) FROM bep_entities WHERE nif IS NOT NULL AND nif != '' AND (lower(display_name) LIKE 'camara municipal%' OR lower(display_name) LIKE 'municipio%')").fetchone()[0]
        conn.close()
        return {"total_entities": t, "camara_municipal": c}
    except Exception as e: return {"error": str(e)}

def audit_demographics():
    try:
        import municipality_demographics as md
        return {"total": len(md.MUNICIPALITY_DEMOGRAPHICS)}
    except ImportError: return {"error": "not found"}

def audit_xlsx():
    if not XLSX_FILE.exists(): return {"available": False}
    return {"available": True, "size_mb": round(os.path.getsize(XLSX_FILE) / (1024*1024), 1)}

def generate_gaps(ca, ma):
    un_mn = ca["municipio_nifs"] - ma.get("municipio_nifs", set())
    un_cn = ca["camara_nifs"] - ma.get("camara_nifs", set())
    with open(CONTRACT_INDEX, "r") as f: index = json.load(f)
    gaps = []
    for nif in un_mn:
        cs = index.get(nif, [])
        if not cs: continue
        v = sum(c.get("valor", 0) or 0 for c in cs)
        gaps.append({"nif": nif, "name": cs[0].get("entity_name", ""), "type": "municipio", "contracts": len(cs), "value": v, "gap": "missing_camara_nif", "priority": v + len(cs) * 1000})
    for nif in un_cn:
        cs = index.get(nif, [])
        if not cs: continue
        v = sum(c.get("valor", 0) or 0 for c in cs)
        gaps.append({"nif": nif, "name": cs[0].get("entity_name", ""), "type": "camara", "contracts": len(cs), "value": v, "gap": "missing_municipio_nif", "priority": v + len(cs) * 1000})
    gaps.sort(key=lambda x: -x["priority"])
    return gaps

def print_report(ca, ma, ba, da, xa, gaps):
    nm, nc, nmap = len(ca["municipio_nifs"]), len(ca["camara_nifs"]), ma["total"]
    print(f"\n{'='*100}\nDATA QUALITY REPORT — Analisa.pt\n{'='*100}")
    print(f"\n📊 DATA SOURCE OVERVIEW\n{'─'*80}")
    print(f"  {'Source':<35}{'Status':<15}{'Coverage':>15}")
    print(f"  {'─'*35}{'─'*15}{'─'*15}")
    print(f"  {'BASE.gov.pt (contracts)':<35}{'✅ Active':<15}{ca['total_contracts']:>10,} contracts")
    print(f"  {'BEP (hiring)':<35}{'✅ Active':<15}{ba.get('total_entities', 0):>10,} entities")
    print(f"  {'NIF Mapping':<35}{'⚠️ Partial':<15}{nmap:>10}/308 pairs")
    print(f"  {'Population Data':<35}{'⚠️ Partial':<15}{da.get('total', 0):>10}/308 municipalities")
    if xa.get('available'): print(f"  {'XLSX (adjudicatário)':<35}{'✅ Active':<15}{xa.get('size_mb', 0):>10} MB")
    else: print(f"  {'XLSX (adjudicatário)':<35}{'❌ Missing':<15}")
    print(f"\n📋 ENTITY TYPE DISTRIBUTION\n{'─'*80}")
    print(f"  {'Type':<25}{'Contracts':>12}{'Value':>18}{'NIFs':>10}")
    for et, d in sorted(ca["entity_types"].items(), key=lambda x: -x[1]["value"]):
        print(f"  {et:<25}{d['count']:>12,}{fmt(d['value']):>18}{d['unique_nifs']:>10}")
    print(f"\n🔗 NIF COVERAGE\n{'─'*80}")
    print(f"  Município NIFs in index:   {nm}")
    print(f"  Câmara NIFs in index:      {nc}")
    print(f"  NIF mapping pairs:         {nmap}")
    mi = ma.get("camara_nifs", set()) & set(ca["camara_nifs"])
    print(f"  Mapped Câmara in index:    {len(mi)}")
    print(f"\n⚠️  SCRAPING PRIORITIES (Top 20)\n{'─'*100}")
    print(f"  {'#':<4}{'Name':<40}{'Type':<12}{'Contracts':>10}{'Value':>14}{'Gap'}")
    for i, g in enumerate(gaps[:20], 1):
        print(f"  {i:<4}{g['name'][:40]:<40}{g['type']:<12}{g['contracts']:>10}{fmt(g['value']):>14}{g['gap']}")
    print(f"\n{'='*100}\nSUMMARY\n{'='*100}")
    print(f"  Municipalities with data:     {nm + nc}")
    print(f"  Needing NIF mapping:          {len(gaps)}")
    print(f"  Needing population data:      {308 - da.get('total', 0)}")
    print(f"  Total contract value:         {fmt(ca['total_value'])}")

def main():
    p = argparse.ArgumentParser(description="Data Quality Report")
    p.add_argument("--gaps", action="store_true")
    p.add_argument("--priorities", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    ca, ma, ba, da, xa = audit_contract_index(), audit_nif_mapping(), audit_bep(), audit_demographics(), audit_xlsx()
    gaps = generate_gaps(ca, ma)
    if a.json:
        print(json.dumps({"contract_index": {k: v for k, v in ca.items() if k not in ("municipio_nifs", "camara_nifs")}, "nif_mapping": {"total": ma["total"]}, "bep": ba, "demographics": da, "xlsx": xa, "gaps": gaps}, indent=2, ensure_ascii=False))
        return
    if a.priorities:
        print(f"\nSCRAPING PRIORITIES (by contract value)")
        for i, g in enumerate(gaps[:30], 1): print(f"  {i:>3}. {g['name'][:40]:<40} {g['type']:<12} {g['contracts']:>6} contracts  {fmt(g['value']):>12}")
        return
    if a.gaps:
        print(f"\nGAP ANALYSIS — {len(gaps)} municipalities need NIF mapping")
        for g in gaps[:30]: print(f"  [{g['nif']}] {g['name'][:45]:<45} {g['contracts']:>5} contracts  {fmt(g['value']):>12}")
        return
    print_report(ca, ma, ba, da, xa, gaps)

if __name__ == "__main__": main()
