#!/usr/bin/env python3
"""Update Findings — Auto-detect and append new data inconsistencies."""
import argparse, json, re, sqlite3, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from unidecode import unidecode
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
FINDINGS_MD = SCRIPT_DIR.parent / "FINDINGS.md"
BEP_DB = SCRIPT_DIR / "bep_index.db"
CONTRACT_INDEX = SCRIPT_DIR / "data" / "contract_index.json"
NIF_MAPPING = SCRIPT_DIR / "data" / "nif_mapping.json"
TOTAL_MUNI = 308

KNOWN_ERRORS = {
    "mealhada": ("Porto", "Aveiro"), "ilhavo": ("Porto", "Aveiro"),
    "aveiro": ("Porto", "Aveiro"), "oliveira do bairro": ("Porto", "Aveiro"),
    "albergaria-a-velha": ("Porto", "Aveiro"), "arouca": ("Porto", "Aveiro"),
    "vagos": ("Porto", "Aveiro"), "mira": ("Porto", "Aveiro"),
    "castelo branco": ("Viseu", "Castelo Branco"),
    "covilha": ("Viseu", "Castelo Branco"), "fundao": ("Viseu", "Castelo Branco"),
    "serta": ("Viseu", "Castelo Branco"), "oleiros": ("Viseu", "Castelo Branco"),
    "aguiar da beira": ("Viseu", "Castelo Branco"),
    "elvas": ("Viseu", "Portalegre"), "marvao": ("Viseu", "Portalegre"),
    "campo maior": ("Viseu", "Portalegre"), "nisa": ("Viseu", "Portalegre"),
    "chaves": ("Guarda", "Vila Real"), "montalegre": ("Guarda", "Vila Real"),
    "sao pedro do sul": ("Porto", "Viseu"), "resende": ("Porto", "Viseu"),
    "vila florz": ("Guarda", "Braganca"),
    "arganil": ("Viseu", "Coimbra"),
    "pampilhosa da serra": ("Viseu", "Coimbra"),
    "vicente": ("Braga", "Viana do Castelo"),
    "pontedeume": ("Braga", "A Coruna"),
}

def load_json(path):
    if not path.exists(): return [] if "mapping" in str(path) else {}
    with open(path, "r") as f: data = json.load(f)
    if isinstance(data, dict) and "mappings" in data: return data["mappings"]
    return data

def load_bep():
    if not BEP_DB.exists(): return []
    conn = db_connect(str(BEP_DB))
    rows = conn.execute("SELECT display_name, nif, listing_count FROM bep_entities WHERE nif IS NOT NULL AND nif != ''").fetchall()
    conn.close()
    return rows

def check_dual_nif():
    index = load_json(CONTRACT_INDEX); mapping = load_json(NIF_MAPPING)
    mapped = {(m.get("camara_nif",""), m.get("municipio_nif","")) for m in mapping if m.get("camara_nif") and m.get("municipio_nif")}
    locs = defaultdict(lambda: {"cam": [], "mun": []})
    cam_p = ["camara municipal de ", "camara municipal do ", "camara municipal da "]
    mun_p = ["municipio de ", "municipio do ", "municipio da "]
    for nif, cs in index.items():
        if not cs: continue
        nl = unidecode(cs[0].get("entity_name","").lower().strip())
        for p in cam_p:
            if nl.startswith(p):
                loc = re.sub(r"\s*\(.*$|,.*$", "", nl[len(p):]).strip()
                if len(loc) >= 2: locs[loc]["cam"].append((nif, len(cs)))
                break
        for p in mun_p:
            if nl.startswith(p):
                loc = re.sub(r"\s*\(.*$|,.*$", "", nl[len(p):]).strip()
                v = sum(c.get("valor",0) or 0 for c in cs)
                if len(loc) >= 2: locs[loc]["mun"].append((nif, len(cs), v))
                break
    unmapped = []
    for loc, g in locs.items():
        if g["cam"] and g["mun"]:
            for cn, cc in g["cam"]:
                for mn, mc, mv in g["mun"]:
                    if (cn, mn) not in mapped:
                        unmapped.append({"loc": loc.title(), "cn": cn, "mn": mn, "contracts": mc, "value": mv})
    unmapped.sort(key=lambda x: -x["value"])
    return {"total": len(unmapped), "entries": unmapped[:30]}

def check_districts():
    f = SCRIPT_DIR / "municipality_demographics.py"
    if not f.exists(): return {"error": "not found"}
    src = f.read_text()
    entries = {}
    for m in re.finditer(r'"([^"]+)"\s*:\s*\{"population"\s*:\s*(\d+),\s*"area_km2"\s*:\s*([\d.]+),\s*"district"\s*:\s*"([^"]+)"', src):
        entries[m.group(1)] = {"pop": int(m.group(2)), "district": m.group(4)}
    errors = [(n, w, c, entries[n]["pop"]) for n, (w, c) in KNOWN_ERRORS.items() if n in entries and entries[n]["district"] == w and w != c]
    # Simpler duplicate detection
    dup_count = 0
    dup_names = []
    name_counts = defaultdict(int)
    for n in entries: name_counts[n] += 1
    for n, c in name_counts.items():
        if c > 1: dup_count += 1; dup_names.append(n)
    return {"total": len(entries), "errors": len(errors), "error_list": [(n, w, c, p) for n, w, c, p in errors[:10]], "dupes": dup_count, "dupe_names": dup_names[:10]}

def check_bep():
    bep = load_bep(); index = load_json(CONTRACT_INDEX)
    bep_locs = set()
    for name, nif, c in bep:
        nl = unidecode(name.lower())
        for p in ["camara municipal de ", "camara municipal do ", "camara municipal da "]:
            if nl.startswith(p):
                bep_locs.add(re.sub(r"\s*\(.*$|,.*$", "", nl[len(p):]).strip())
                break
    base_locs = set()
    for nif, cs in index.items():
        if not cs: continue
        nl = unidecode(cs[0].get("entity_name","").lower())
        for p in ["municipio de ", "municipio do ", "municipio da "]:
            if nl.startswith(p):
                base_locs.add(re.sub(r"\s*\(.*$|,.*$", "", nl[len(p):]).strip())
                break
    common = bep_locs & base_locs
    return {"bep": len(bep_locs), "base": len(base_locs), "common": len(common), "pct": round(len(common)/TOTAL_MUNI*100,1)}

def check_pop():
    f = SCRIPT_DIR / "municipality_directory.py"
    if not f.exists(): return {"total": 0, "missing": TOTAL_MUNI}
    src = f.read_text()
    count = len(re.findall(r'"[^"]+"\s*:\s*\d{4,}', src))
    return {"total": count, "missing": TOTAL_MUNI - count, "pct": round(count/TOTAL_MUNI*100,1)}

def check_ambiguity():
    index = load_json(CONTRACT_INDEX)
    loc_nifs = defaultdict(set)
    for nif, cs in index.items():
        if not cs: continue
        nl = unidecode(cs[0].get("entity_name","").lower().strip())
        for p in ["municipio de ", "municipio do ", "municipio da "]:
            if nl.startswith(p):
                loc = re.sub(r"\s*\(.*$|,.*$", "", nl[len(p):]).strip()
                if len(loc) >= 2: loc_nifs[loc].add(nif)
                break
    amb = {loc: sorted(nifs) for loc, nifs in loc_nifs.items() if len(nifs) > 1}
    return {"total": len(amb), "list": [(loc.title(), nifs) for loc, nifs in sorted(amb.items())]}

def check_assoc():
    index = load_json(CONTRACT_INDEX)
    result = []
    for nif, cs in index.items():
        if not cs: continue
        nl = unidecode(cs[0].get("entity_name","").lower())
        if "associacao" in nl and "municipio" in nl:
            result.append({"nif": nif, "name": cs[0]["entity_name"], "contracts": len(cs), "value": sum(c.get("valor",0) or 0 for c in cs)})
    return {"total": len(result), "entries": sorted(result, key=lambda x: -x["value"])[:10]}

def fv(v):
    if v >= 1e9: return f"{v/1e9:.2f}B"
    elif v >= 1e6: return f"{v/1e6:.1f}M"
    elif v >= 1e3: return f"{v/1e3:.0f}K"
    return f"{v:.0f}"

def main():
    p = argparse.ArgumentParser(description="Auto-detect data inconsistencies")
    p.add_argument("--check", action="store_true", help="Check only (no file changes)")
    p.add_argument("--add", help="Manually add a finding")
    a = p.parse_args()

    if a.add:
        if not FINDINGS_MD.exists(): print("Error: FINDINGS.md not found"); sys.exit(1)
        content = FINDINGS_MD.read_text()
        ts = datetime.now().strftime("%Y-%m-%d")
        n = len(re.findall(r"^## Finding #", content, re.MULTILINE)) + 1
        content += f"\n---\n\n## Finding #{n} (Manual): {a.add}\n\n### Status: 🔴 ACTIVE\n\n### Description\n{a.add}\n\n### Evidence\nManual entry added on {ts}.\n"
        FINDINGS_MD.write_text(content)
        print(f"Appended Finding #{n} to {FINDINGS_MD}")
        return

    dn = check_dual_nif(); dc = check_districts(); bc = check_bep(); pg = check_pop()
    am = check_ambiguity(); ac = check_assoc()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n{'='*90}\nFINDINGS UPDATE REPORT — {ts}\n{'='*90}")
    print(f"\n🔍 DUAL NIF\n{'─'*60}\n  Unmapped pairs: {dn['total']}")
    for e in dn["entries"][:5]: print(f"    {e['loc']:30s} C={e['cn']} M={e['mn']} ({e['contracts']} contracts)")
    print(f"\n🗺️  DISTRICTS\n{'─'*60}\n  Entries: {dc['total']}  Errors: {dc['errors']}  Dupes: {dc['dupes']}")
    for n, w, c, p in dc["error_list"]: print(f"    {n:25s} {w:12s} → {c} (pop {p:,})")
    dupes = ', '.join(dc['dupe_names'][:5])
    if dc['dupe_names']: print(f'  Duplicates: {dupes}')
    print(f"\n📊 BEP COVERAGE\n{'─'*60}\n  BEP: {bc['bep']}  BASE: {bc['base']}  Common: {bc['common']}  Coverage: {bc['pct']}%")
    print(f"\n👥 POPULATION\n{'─'*60}\n  Entries: {pg['total']}  Missing: {pg['missing']}  Coverage: {pg['pct']}%")
    print(f"\n🔎 AMBIGUITY\n{'─'*60}\n  Multi-NIF locations: {am['total']}")
    for loc, nifs in am["list"]: print(f"    {loc}: {', '.join(nifs)}")
    print(f"\n🏢 ASSOCIAÇÕES\n{'─'*60}\n  Shared entities: {ac['total']}")
    for e in ac["entries"][:5]: print(f"    [{e['nif']}] {e['name'][:50]} ({e['contracts']} contracts, {fv(e['value'])})")

    total = dn["total"] + dc["errors"] + dc["dupes"] + pg["missing"] + am["total"] + ac["total"]
    print(f"\n{'='*90}\n  Total issues: {total}\n{'='*90}")

    if not a.check and FINDINGS_MD.exists():
        content = FINDINGS_MD.read_text()
        content = re.sub(r"\*\*Last updated:.*?\*\*", f"**Last updated:** {datetime.now().strftime('%Y-%m-%d')}", content)
        FINDINGS_MD.write_text(content)
        print(f"Updated timestamp in {FINDINGS_MD}")

if __name__ == "__main__": main()
