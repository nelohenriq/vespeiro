#!/usr/bin/env python3
"""Enhanced PRR × BASE Corruption Pattern Detector — Goes beyond NIF-level matching.

Detects corruption patterns across 3 match dimensions:
  1. CD_BASE_GOV → nAnuncio: Contract-level PRR ↔ BASE cross-reference
  2. Object-of-contract text similarity: PRR ds_contrato/sumario ↔ BASE objectoContrato
  3. Composite risk: Combined NIF + contract + text + inflation + temporal scoring
  4. Fundão deep-dive: Municipality-specific cross-reference

Requires:
  - transparency.db (PRR data)
  - procurement.db (BASE contracts)

Usage:
    python prr_base_cdgov_detector.py cdgov              # CD_BASE_GOV contract-level matching
    python prr_base_cdgov_detector.py text-match          # Text similarity matching
    python prr_base_cdgov_detector.py composite           # Composite risk (all dimensions)
    python prr_base_cdgov_detector.py fundao              # Fundão deep-dive
    python prr_base_cdgov_detector.py all                 # All analyses
    python prr_base_cdgov_detector.py all --export out.json
"""

import json
import re
import argparse
import sys
import textwrap
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from utils import fmt
from utils_db import connect as db_connect

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
TRANSPARENCY_DB = DATA_DIR / "transparency.db"
PROCUREMENT_DB = DATA_DIR / "procurement.db"


def check_dbs():
    """Verify both databases exist."""
    missing = []
    if not TRANSPARENCY_DB.exists():
        missing.append(f"transparency.db not found at {TRANSPARENCY_DB}")
    if not PROCUREMENT_DB.exists():
        missing.append(f"procurement.db not found at {PROCUREMENT_DB}")
    if missing:
        for m in missing:
            print(f"ERROR: {m}")
        sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
#  MATCH DIMENSION 1 — CD_BASE_GOV → nAnuncio Contract-Level Matching
# ═════════════════════════════════════════════════════════════════════════════

def load_prr_cd_base_gov(conn) -> list[dict]:
    """Load PRR contracts that have cd_base_gov values."""
    rows = conn.execute(
        "SELECT cd_contrato, ds_contrato, sumario, cd_base_gov, "
        "COALESCE(montante, 0) as montante, cd_projeto, ds_projeto, "
        "dt_assinatura "
        "FROM prr_contracts "
        "WHERE cd_base_gov != '' AND cd_base_gov IS NOT NULL "
        "ORDER BY montante DESC"
    ).fetchall()
    return [{
        "cd_contrato": r[0], "ds_contrato": r[1] or "", "sumario": r[2] or "",
        "cd_base_gov": r[3], "montante": r[4], "cd_projeto": r[5] or "",
        "ds_projeto": r[6] or "", "dt_assinatura": r[7] or "",
    } for r in rows]


def load_base_n_anuncio(proc_conn) -> dict:
    """Load BASE contracts with nAnuncio values, indexed by nAnuncio.

    Returns: dict of nAnuncio → list of contract dicts (multi-match possible)
    """
    rows = proc_conn.execute(
        "SELECT idcontrato, nAnuncio, adjudicante_nif, adjudicante_nome, "
        "adjudicatarios, COALESCE(precoContratual, 0), objectoContrato, "
        "tipoprocedimento, dataCelebracaoContrato, "
        "CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        "    THEN 1 ELSE 0 END as is_inflated, "
        "CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
        "    THEN precoContratual - precoBaseProcedimento ELSE 0 END as overrun "
        "FROM contratos WHERE nAnuncio != '' AND nAnuncio IS NOT NULL"
    ).fetchall()

    by_nanuncio = defaultdict(list)
    for r in rows:
        by_nanuncio[r[1]].append({
            "idcontrato": r[0], "adjudicante_nif": r[3] or "",
            "adjudicante_nome": r[4] or "",
            "adjudicatarios": r[5] or "",
            "preco": r[6], "objectoContrato": r[7] or "",
            "tipoprocedimento": r[8] or "", "data": r[9] or "",
            "is_inflated": r[10], "overrun": r[11],
        })
    return dict(by_nanuncio)


def analyze_cdgov_matches() -> dict:
    """Match PRR contracts to BASE contracts via cd_base_gov ↔ nAnuncio."""
    check_dbs()
    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    print("Loading PRR contracts with cd_base_gov...", file=sys.stderr)
    prr_contracts = load_prr_cd_base_gov(conn)

    print("Loading BASE contracts with nAnuncio...", file=sys.stderr)
    base_by_anuncio = load_base_n_anuncio(proc_conn)

    # Also load PRR entity info for context
    prr_entities = conn.execute(
        "SELECT cd_entidade, ds_entidade, nif, papel, valor_contratado "
        "FROM prr_entities WHERE nif != ''"
    ).fetchall()
    entity_by_cd = {}
    for r in prr_entities:
        entity_by_cd[r[0]] = {"name": r[1], "nif": r[2], "papel": r[3], "valor": r[4]}

    # Also load entity-contract links
    ec_rows = conn.execute(
        "SELECT cd_contrato, cd_entidade, ds_papel "
        "FROM prr_entity_contracts"
    ).fetchall()
    ec_by_contrato = defaultdict(list)
    for r in ec_rows:
        ec_by_contrato[r[0]].append({"cd_entidade": r[1], "papel": r[2]})

    print(f"\nAnalyzing {len(prr_contracts)} PRR contracts with cd_base_gov...", file=sys.stderr)

    # Match
    matches = []
    total_base_value_matched = 0
    total_prr_value_matched = 0

    for pc in prr_contracts:
        cdbg = pc["cd_base_gov"].strip()
        base_matches = base_by_anuncio.get(cdbg, [])

        if not base_matches:
            continue

        # Get PRR entity info for this contract
        prr_entities_for_contract = ec_by_contrato.get(pc["cd_contrato"], [])
        entity_details = []
        for ec in prr_entities_for_contract:
            ent = entity_by_cd.get(ec["cd_entidade"])
            if ent:
                entity_details.append({
                    "name": ent["name"], "nif": ent["nif"],
                    "papel": ec["papel"], "papel_ent": ent["papel"],
                })

        for bm in base_matches:
            total_base_value_matched += bm["preco"]
            total_prr_value_matched += pc["montante"]

            # Extract supplier NIFs from adjudicatarios text
            supplier_nifs = set()
            nif_pattern = re.compile(r"\b(\d{9})\b")
            if bm["adjudicatarios"]:
                supplier_nifs = set(nif_pattern.findall(bm["adjudicatarios"]))

            matches.append({
                "prr_contrato": pc["cd_contrato"],
                "prr_descricao": pc["ds_contrato"][:100],
                "prr_montante": pc["montante"],
                "prr_projeto": pc["cd_projeto"],
                "prr_ds_projeto": pc["ds_projeto"][:80],
                "prr_data": pc["dt_assinatura"],
                "cd_base_gov": cdbg,
                "base_idcontrato": bm["idcontrato"],
                "base_preco": bm["preco"],
                "base_adjudicante_nif": bm["adjudicante_nif"],
                "base_adjudicante_nome": bm["adjudicante_nome"],
                "base_objecto": bm["objectoContrato"][:100],
                "base_data": bm["data"],
                "base_inflated": bool(bm["is_inflated"]),
                "base_overrun": bm["overrun"],
                "base_supplier_nifs": list(supplier_nifs),
                "tipoprocedimento": bm["tipoprocedimento"],
                "prr_entities": entity_details,
            })

    matches.sort(key=lambda x: -(x["prr_montante"] + x["base_preco"]))

    # Summary
    entity_nifs_in_matches = set()
    for m in matches:
        if m["base_adjudicante_nif"]:
            entity_nifs_in_matches.add(m["base_adjudicante_nif"])
        for ent in m.get("prr_entities", []):
            if ent.get("nif"):
                entity_nifs_in_matches.add(ent["nif"])
        for snif in m.get("base_supplier_nifs", []):
            entity_nifs_in_matches.add(snif)

    conn.close()
    proc_conn.close()

    return {
        "matches": matches,
        "total_prr_with_cdbg": len(prr_contracts),
        "total_matched": len(matches),
        "total_prr_value_matched": total_prr_value_matched,
        "total_base_value_matched": total_base_value_matched,
        "unique_prr_contratos_matched": len(set(m["prr_contrato"] for m in matches)),
        "unique_entities_involved": len(entity_nifs_in_matches),
        "match_rate_pct": round(len(matches) / len(prr_contracts) * 100, 1) if prr_contracts else 0,
        "inflated_matches": sum(1 for m in matches if m["base_inflated"]),
    }


def print_cdgov_report(data: dict):
    """Print cd_base_gov matching report."""
    matches = data["matches"]

    print(f"\n{'=' * 110}")
    print(f"  MATCH DIMENSION 1: CD_BASE_GOV → nAnuncio Contract-Level Matching")
    print(f"  Links PRR contracts to specific BASE.gov.pt procurement contracts")
    print(f"{'=' * 110}")

    print(f"\n  📊 Coverage")
    print(f"  {'─' * 50}")
    print(f"  PRR contracts with cd_base_gov: {data['total_prr_with_cdbg']}")
    print(f"  Matched to BASE contracts: {data['total_matched']}")
    print(f"  Match rate: {data['match_rate_pct']}%")
    print(f"  Unique PRR contracts matched: {data['unique_prr_contratos_matched']}")
    print(f"  Unique entities involved: {data['unique_entities_involved']}")
    print(f"  Inflated BASE matches: {data['inflated_matches']}")
    print(f"  Total PRR value matched: {fmt(data['total_prr_value_matched'])}")
    print(f"  Total BASE value matched: {fmt(data['total_base_value_matched'])}")

    if matches:
        print(f"\n  🔴 MATCHES — PRR Contracts Linked to BASE Contracts")
        print(f"  {'─' * 108}")
        print(f"  {'#':<4} {'CD_BASE_GOV':<20} {'PRR Value':>12} {'BASE Value':>12} "
              f"{'PRR Contract':<30} {'Inflation':>9} {'BASE Buyer'}")
        print(f"  {'─' * 4} {'─' * 20} {'─' * 12} {'─' * 12} {'─' * 30} {'─' * 9} {'─' * 20}")

        for i, m in enumerate(matches[:30], 1):
            infl_flag = "💰" if m["base_inflated"] else ("  " if m["base_inflated"] is None else "  ")
            print(f"  {i:<4} {m['cd_base_gov'][:18]:<20} {fmt(m['prr_montante']):>12} "
                  f"{fmt(m['base_preco']):>12} {m['prr_contrato'][:28]:<30} "
                  f"{infl_flag:>9} {m['base_adjudicante_nome'][:18]:<20}")
            # Show entity overlap
            if m.get("prr_entities"):
                for ent in m["prr_entities"]:
                    nif = ent.get("nif", "")
                    print(f"     PRR entity: {ent['name'][:50]:50s} NIF={nif} [{ent.get('papel', '')}]")
            if m["base_supplier_nifs"]:
                print(f"     BASE suppliers: {', '.join(m['base_supplier_nifs'][:5])}")

        if len(matches) > 30:
            print(f"  ... and {len(matches) - 30} more matches")

        # Inflated match detail
        inflated = [m for m in matches if m["base_inflated"]]
        if inflated:
            print(f"\n\n  🚨 INFLATED BASE CONTRACTS LINKED TO PRR")
            print(f"  {'─' * 80}")
            for m in inflated[:10]:
                print(f"  PRR: {m['prr_contrato']} ({fmt(m['prr_montante'])}) → "
                      f"BASE: {m['base_idcontrato']} ({fmt(m['base_preco'])})")
                print(f"       Overrun: {fmt(m['base_overrun'])}  "
                      f"Buyer: {m['base_adjudicante_nome'][:40]}")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  MATCH DIMENSION 2 — Object-of-Contract Text Similarity
# ═════════════════════════════════════════════════════════════════════════════

def tokenize(text: str) -> set:
    """Extract meaningful tokens from text for fuzzy matching."""
    text = text.lower()
    # Remove common stopwords in Portuguese
    stopwords = {
        "a", "o", "e", "de", "da", "do", "em", "para", "com", "no", "na",
        "os", "as", "dos", "das", "um", "uma", "uns", "umas", "ao", "aos",
        "à", "às", "pelo", "pela", "pelos", "pelas", "por", "que", "se",
        "não", "já", "mais", "mas", "como", "ou", "é", "ser", "são",
        "nos", "nas", "num", "numa", "dum", "duma", "duns", "dumas",
        "este", "esta", "estes", "estas", "esse", "essa", "esses", "essas",
        "aquele", "aquela", "aqueles", "aquelas", "seu", "sua", "seus", "suas",
        "entre", "após", "contra", "sem", "sob", "sobre", "até",
        "ltd", "lda", "sa", "s.a", "e", "ou", "unipessoal", "sociedade",
        "contrato", "prestação", "serviços", "aquisição", "empreitada",
        "fornecimento", "bens", "obras", "concurso", "público",
        "ajuste", "direto", "procedimento", "nº", "artigo", "processo",
        "despacho", "deliberação", "autorização", "proposta",
    }
    # Extract alphanumeric tokens of length >= 4
    tokens = set()
    for word in re.findall(r"[a-záéíóúâêôãõçàèìòùäëïöüñ]{4,}", text):
        if word not in stopwords:
            tokens.add(word)
    return tokens


def text_similarity(text1: str, text2: str) -> float:
    """Compute Jaccard similarity between two texts based on token overlap."""
    tokens1 = tokenize(text1)
    tokens2 = tokenize(text2)
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union) if union else 0.0


def _pretokenize_base_texts(proc_conn, limit: int = 20000) -> list:
    """Load and pre-tokenize BASE contract objects for text matching.

    Returns list of {data, tokens} dicts for fast Jaccard comparison.
    """
    rows = proc_conn.execute(
        "SELECT idcontrato, objectoContrato, COALESCE(precoContratual, 0) as preco, "
        "adjudicante_nif, adjudicante_nome, adjudicatarios "
        "FROM contratos "
        "WHERE objectoContrato != '' AND objectoContrato IS NOT NULL "
        "ORDER BY precoContratual DESC LIMIT ?",
        (limit,)
    ).fetchall()

    results = []
    for r in rows:
        tokens = tokenize(r[1])
        if tokens:
            results.append({
                "data": {
                    "idcontrato": r[0], "text": r[1], "preco": r[2],
                    "adjudicante_nif": r[3] or "",
                    "adjudicante_nome": r[4] or "",
                    "adjudicatarios": r[5] or "",
                },
                "tokens": tokens,
            })
    return results


def _pretokenize_prr_texts(conn) -> list:
    """Load and pre-tokenize PRR contract descriptions for text matching."""
    rows = conn.execute(
        "SELECT cd_contrato, ds_contrato, sumario, COALESCE(montante, 0) as montante "
        "FROM prr_contracts "
        "WHERE (ds_contrato != '' AND ds_contrato IS NOT NULL) "
        "OR (sumario != '' AND sumario IS NOT NULL)"
    ).fetchall()

    results = []
    for r in rows:
        combined = f"{r[1] or ''} {r[2] or ''}".strip()
        if not combined:
            continue
        tokens = tokenize(combined)
        if tokens:
            results.append({
                "cd_contrato": r[0], "text": combined,
                "montante": r[3], "tokens": tokens,
            })
    return results


def analyze_text_matches(min_similarity: float = 0.3) -> dict:
    """Match PRR contracts to BASE contracts via text similarity.

    Compares PRR ds_contrato and sumario against BASE objectoContrato.
    Only reports matches above min_similarity threshold.
    """
    check_dbs()
    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    print("Loading and pre-tokenizing PRR contract descriptions...", file=sys.stderr)
    prr_tokenized = _pretokenize_prr_texts(conn)
    print(f"  Loaded {len(prr_tokenized)} PRR contracts with descriptions", file=sys.stderr)

    print("Loading and pre-tokenizing BASE contract objects (top 20K by value)...", file=sys.stderr)
    base_tokenized = _pretokenize_base_texts(proc_conn, limit=20000)
    print(f"  Loaded {len(base_tokenized)} BASE contracts with objects", file=sys.stderr)

    print(f"  Processing {len(prr_tokenized)} PRR × {len(base_tokenized)} BASE...", file=sys.stderr)

    matches = []
    nif_pattern = re.compile(r"\b(\d{9})\b")

    for prr in prr_tokenized:
        for bt in base_tokenized:
            intersection = prr["tokens"] & bt["tokens"]
            union = prr["tokens"] | bt["tokens"]
            sim = len(intersection) / len(union) if union else 0.0

            if sim >= min_similarity:
                supplier_nifs = set()
                if bt["data"]["adjudicatarios"]:
                    supplier_nifs = set(nif_pattern.findall(bt["data"]["adjudicatarios"]))

                matches.append({
                    "prr_contrato": prr["cd_contrato"],
                    "prr_montante": prr["montante"],
                    "base_idcontrato": bt["data"]["idcontrato"],
                    "base_preco": bt["data"]["preco"],
                    "similarity": round(sim, 3),
                    "common_tokens": len(intersection),
                    "prr_text_preview": prr["text"][:80],
                    "base_text_preview": bt["data"]["text"][:80],
                    "base_adjudicante_nome": bt["data"]["adjudicante_nome"],
                    "base_supplier_nifs": list(supplier_nifs),
                })

    matches.sort(key=lambda x: -x["similarity"])

    # Deduplicate — keep best match per PRR contract
    best_per_prr = {}
    for m in matches:
        pc = m["prr_contrato"]
        if pc not in best_per_prr or m["similarity"] > best_per_prr[pc]["similarity"]:
            best_per_prr[pc] = m
    deduped = list(best_per_prr.values())
    deduped.sort(key=lambda x: (-x["similarity"], -x["prr_montante"]))

    # Also deduplicate per BASE contract (reverse)
    best_per_base = {}
    for m in deduped:
        bc = m["base_idcontrato"]
        if bc not in best_per_base or m["similarity"] > best_per_base[bc]["similarity"]:
            best_per_base[bc] = m
    cross_deduped = list(best_per_base.values())
    cross_deduped.sort(key=lambda x: (-x["similarity"], -x["prr_montante"]))

    conn.close()
    proc_conn.close()

    return {
        "all_matches": deduped[:50],  # Keep top 50 for detail
        "cross_deduped": cross_deduped[:30],
        "total_prr_analyzed": len(prr_texts),
        "total_base_analyzed": len(base_objects),
        "total_matches": len(matches),
        "unique_prr_matched": len(deduped),
        "unique_base_matched": len(cross_deduped),
        "high_similarity_matches": sum(1 for m in deduped if m["similarity"] >= 0.5),
    }


def print_text_match_report(data: dict):
    """Print text similarity matching report."""
    matches = data.get("cross_deduped", [])
    all_matches = data.get("all_matches", [])

    print(f"\n{'=' * 110}")
    print(f"  MATCH DIMENSION 2: Object-of-Contract Text Similarity")
    print(f"  Fuzzy-matches PRR contract descriptions to BASE object descriptions")
    print(f"{'=' * 110}")

    print(f"\n  📊 Coverage")
    print(f"  {'─' * 50}")
    print(f"  PRR contracts with descriptions: {data['total_prr_analyzed']}")
    print(f"  BASE contracts sampled (top 20K by value): {data['total_base_analyzed']}")
    print(f"  Total cross-matches (raw): {data['total_matches']}")
    print(f"  Unique PRR contracts matched: {data['unique_prr_matched']}")
    print(f"  Unique BASE contracts matched: {data['unique_base_matched']}")
    print(f"  High similarity matches (≥0.5): {data['high_similarity_matches']}")

    if matches:
        print(f"\n  🟠 TOP TEXT-MATCHED PAIRS (deduplicated, best match per contract)")
        print(f"  {'─' * 108}")
        print(f"  {'#':<4} {'Sim':>6} {'Tokens':>7} {'PRR Value':>12} {'BASE Value':>12} "
              f"{'PRR Text':<35} {'BASE Text':<35}")
        print(f"  {'─' * 4} {'─' * 6} {'─' * 7} {'─' * 12} {'─' * 12} {'─' * 35} {'─' * 35}")

        for i, m in enumerate(matches[:20], 1):
            print(f"  {i:<4} {m['similarity']:.2f} {m['common_tokens']:>7} {fmt(m['prr_montante']):>12} "
                  f"{fmt(m['base_preco']):>12} {m['prr_text_preview'][:33]:<35} {m['base_text_preview'][:33]:<35}")

        if len(matches) > 20:
            print(f"  ... and {len(matches) - 20} more cross-deduplicated matches")

        # Show potential duplicates — same object being funded AND procured
        print(f"\n\n  🔴 POTENTIAL DUPLICATES (similar descriptions, different contract IDs)")
        print(f"  Same work funded via PRR AND procured via BASE — possible double-dipping")
        print(f"  {'─' * 90}")
        duplicates_shown = 0
        for m in all_matches[:10]:
            if m["similarity"] >= 0.5:
                print(f"  PRR: {m['prr_contrato']} ({fmt(m['prr_montante'])})  "
                      f"BASE: {m['base_idcontrato']} ({fmt(m['base_preco'])})")
                print(f"    PRR: \"{m['prr_text_preview']}\"")
                print(f"    BASE: \"{m['base_text_preview']}\"")
                duplicates_shown += 1
        if not duplicates_shown:
            print(f"  None found at ≥0.5 threshold")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  MATCH DIMENSION 3 — Composite Risk (all dimensions combined)
# ═════════════════════════════════════════════════════════════════════════════

def analyze_composite_risk() -> dict:
    """Combine all match dimensions into composite risk scoring.

    For each entity:
      - NIF-based dual role (from prr_procurement_crossref)
      - cd_base_gov contract-level matches
      - Text similarity matches
      - Price inflation in BASE linked contracts
      - Temporal proximity of PRR ↔ BASE contracts
    """
    check_dbs()

    # --- Load cd_base_gov matches ---
    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    # Load PRR contracts with cd_base_gov
    prr_cdbg = load_prr_cd_base_gov(conn)
    base_by_anuncio = load_base_n_anuncio(proc_conn)

    # --- Step 1: cd_base_gov matches ---
    cdgov_by_entity = defaultdict(lambda: {
        "cdbg_matches": 0, "cdbg_total_prr_value": 0, "cdbg_total_base_value": 0,
        "cdbg_inflated": 0, "cdbg_overrun": 0,
        "cdbg_contracts": [],
    })

    # Load entity-contract links
    ec_rows = conn.execute(
        "SELECT cd_contrato, cd_entidade, ds_papel, COALESCE(valor_contrato, 0) "
        "FROM prr_entity_contracts"
    ).fetchall()
    entities_by_contrato = defaultdict(list)
    for r in ec_rows:
        entities_by_contrato[r[0]].append({
            "cd_entidade": r[1], "papel": r[2], "valor": r[3],
        })

    # Load entity names from prr_entities
    ent_names = {}
    ent_rows = conn.execute(
        "SELECT cd_entidade, ds_entidade, nif FROM prr_entities"
    ).fetchall()
    for r in ent_rows:
        ent_names[r[0]] = {"name": r[1], "nif": r[2]}

    nif_pattern = re.compile(r"\b(\d{9})\b")

    for pc in prr_cdbg:
        cdbg = pc["cd_base_gov"].strip()
        base_ms = base_by_anuncio.get(cdbg, [])
        if not base_ms:
            continue

        # Find which PRR entities are linked to this contract
        linked_entities = entities_by_contrato.get(pc["cd_contrato"], [])

        # Also extract entity NIFs from BASE supplier side
        for bm in base_ms:
            supplier_nifs = set()
            if bm["adjudicatarios"]:
                supplier_nifs = set(nif_pattern.findall(bm["adjudicatarios"]))

            # Track by each linked PRR entity
            for le in linked_entities:
                ent = ent_names.get(le["cd_entidade"], {})
                nif = ent.get("nif", "")
                if not nif:
                    continue

                g = cdgov_by_entity[nif]
                g["cdbg_matches"] += 1
                g["cdbg_total_prr_value"] += pc["montante"]
                g["cdbg_total_base_value"] += bm["preco"]
                if bm["is_inflated"]:
                    g["cdbg_inflated"] += 1
                    g["cdbg_overrun"] += bm["overrun"]
                g["cdbg_contracts"].append({
                    "prr": pc["cd_contrato"],
                    "base": bm["idcontrato"],
                    "cdbg": cdbg,
                    "prr_value": pc["montante"],
                    "base_value": bm["preco"],
                    "inflated": bool(bm["is_inflated"]),
                    "overrun": bm["overrun"],
                })

            # Also track by BASE buyer NIF
            buyer_nif = bm.get("adjudicante_nif", "")
            if buyer_nif and buyer_nif != "-":
                g = cdgov_by_entity[buyer_nif]
                g["cdbg_matches"] += 1
                g["cdbg_total_prr_value"] += pc["montante"]
                g["cdbg_total_base_value"] += bm["preco"]

            # Track by BASE supplier NIFs
            for snif in supplier_nifs:
                g = cdgov_by_entity[snif]
                g["cdbg_matches"] += 1
                g["cdbg_total_prr_value"] += pc["montante"]
                g["cdbg_total_base_value"] += bm["preco"]

    # --- Step 2: Text similarity matches (reuse pre-tokenized data) ---
    print("Computing text similarity matches for composite risk...", file=sys.stderr)
    prr_tokenized = _pretokenize_prr_texts(conn)
    base_tokenized_txt = _pretokenize_base_texts(proc_conn, limit=10000)

    textmatch_by_nif = defaultdict(lambda: {
        "text_matches": 0, "text_similarity_max": 0.0,
    })

    nif_pattern = re.compile(r"\b(\d{9})\b")
    for prr in prr_tokenized:
        for bt in base_tokenized_txt:
            intersection = prr["tokens"] & bt["tokens"]
            union = prr["tokens"] | bt["tokens"]
            sim = len(intersection) / len(union) if union else 0.0
            if sim >= 0.25:
                bd = bt["data"]
                if bd["adjudicante_nif"]:
                    g = textmatch_by_nif[bd["adjudicante_nif"]]
                    g["text_matches"] += 1
                    g["text_similarity_max"] = max(g["text_similarity_max"], sim)
                snifs = set(nif_pattern.findall(bd["adjudicatarios"]))
                for snif in snifs:
                    g = textmatch_by_nif[snif]
                    g["text_matches"] += 1
                    g["text_similarity_max"] = max(g["text_similarity_max"], sim)

    conn.close()
    proc_conn.close()

    # --- Step 3: Combine all NIF-based risk ---
    all_nifs = set(cdgov_by_entity.keys()) | set(textmatch_by_nif.keys())

    composite_results = []
    for nif in sorted(all_nifs):
        cg = cdgov_by_entity.get(nif, {})
        tg = textmatch_by_nif.get(nif, {})

        # Composite risk score (0-100)
        risk = 0.0
        risk_factors = []

        # Factor 1: cd_base_gov contract-level matches (0-40)
        cdbg_count = cg.get("cdbg_matches", 0)
        if cdbg_count >= 5:
            risk += 40
            risk_factors.append(f"High cd_base_gov match count: {cdbg_count}")
        elif cdbg_count >= 2:
            risk += 25
            risk_factors.append(f"Multiple cd_base_gov matches: {cdbg_count}")
        elif cdbg_count >= 1:
            risk += 15

        # Factor 2: Inflated contracts in cd_base_gov matches (0-25)
        inflated = cg.get("cdbg_inflated", 0)
        overrun = cg.get("cdbg_overrun", 0)
        if overrun > 100_000:
            risk += 25
            risk_factors.append(f"Inflation via cd_base_gov: {fmt(overrun)} overrun")
        elif inflated >= 2:
            risk += 15
            risk_factors.append(f"{inflated} inflated cd_base_gov-linked contracts")
        elif inflated >= 1:
            risk += 10

        # Factor 3: Text similarity matches (0-20)
        text_matches = tg.get("text_matches", 0)
        max_sim = tg.get("text_similarity_max", 0.0)
        if text_matches >= 3 and max_sim >= 0.5:
            risk += 20
            risk_factors.append(f"High text similarity: {text_matches} matches (max {max_sim:.2f})")
        elif text_matches >= 1 and max_sim >= 0.4:
            risk += 10
            risk_factors.append(f"Text similarity: {text_matches} matches (max {max_sim:.2f})")
        elif text_matches >= 1:
            risk += 5

        # Factor 4: Combined value via all dimensions (0-15)
        total_value = cg.get("cdbg_total_prr_value", 0) + cg.get("cdbg_total_base_value", 0)
        if total_value > 10_000_000:
            risk += 15
            risk_factors.append(f"High combined value: {fmt(total_value)}")
        elif total_value > 1_000_000:
            risk += 10
        elif total_value > 100_000:
            risk += 5

        risk = min(100, risk)

        composite_results.append({
            "nif": nif,
            "risk_score": round(risk, 1),
            "risk_factors": risk_factors,
            "cdbg_matches": cdbg_count,
            "cdbg_total_prr_value": cg.get("cdbg_total_prr_value", 0),
            "cdbg_total_base_value": cg.get("cdbg_total_base_value", 0),
            "cdbg_inflated": inflated,
            "cdbg_overrun": overrun,
            "text_matches": text_matches,
            "text_similarity_max": max_sim,
        })

    composite_results.sort(key=lambda x: -x["risk_score"])

    return {
        "entities": composite_results,
        "total_entities_analyzed": len(all_nifs),
        "high_risk_count": sum(1 for e in composite_results if e["risk_score"] >= 50),
        "medium_risk_count": sum(1 for e in composite_results if 20 <= e["risk_score"] < 50),
        "total_cdbg_matches": sum(e["cdbg_matches"] for e in composite_results),
        "total_inflated": sum(e["cdbg_inflated"] for e in composite_results),
        "total_text_matches": sum(e["text_matches"] for e in composite_results),
    }


def print_composite_report(data: dict, top_n: int = 30):
    """Print composite risk report."""
    entities = data["entities"]

    print(f"\n{'=' * 110}")
    print(f"  COMPOSITE RISK — All Match Dimensions Combined")
    print(f"  cd_base_gov + Text Similarity + Inflation + Value Magnitude")
    print(f"{'=' * 110}")

    print(f"\n  📊 Overview")
    print(f"  {'─' * 50}")
    print(f"  Entities analyzed: {data['total_entities_analyzed']}")
    print(f"  High risk (≥50): {data['high_risk_count']}")
    print(f"  Medium risk (20-49): {data['medium_risk_count']}")
    print(f"  Total cd_base_gov contract matches: {data['total_cdbg_matches']}")
    print(f"  Total inflated matches: {data['total_inflated']}")
    print(f"  Total text similarity matches: {data['total_text_matches']}")

    if not entities:
        print(f"\n  No entities found with cross-dimension matches.")
        print(f"  The PRR cd_base_gov field may not contain nAnuncio values.")
        print(f"  Try revealing cd_base_gov format with: transparency_scraper.py query")
        print(f"  Or: sqlite3 data/transparency.db 'SELECT cd_base_gov FROM prr_contracts WHERE cd_base_gov != \"\" LIMIT 10'")
    else:
        print(f"\n  🔴 TOP {min(top_n, len(entities))} ENTITIES BY COMPOSITE RISK")
        print(f"  {'─' * 108}")
        print(f"  {'#':<4} {'Score':>6} {'NIF':<12} {'cdbg':>5} {'Infl':>5} {'Text':>5} "
              f"{'PRR Value':>12} {'BASE Value':>12} {'Risk Factors'}")
        print(f"  {'─' * 4} {'─' * 6} {'─' * 12} {'─' * 5} {'─' * 5} {'─' * 5} "
              f"{'─' * 12} {'─' * 12} {'─' * 40}")

        for i, e in enumerate(entities[:top_n], 1):
            factors = "; ".join(e["risk_factors"][:2])
            icon = "🔴" if e["risk_score"] >= 50 else ("🟡" if e["risk_score"] >= 20 else "🟢")
            print(f"  {i:<4} {icon}{e['risk_score']:>5.0f}  {e['nif']:<12} "
                  f"{e['cdbg_matches']:>5} {e['cdbg_inflated']:>5} {e['text_matches']:>5} "
                  f"{fmt(e['cdbg_total_prr_value']):>12} {fmt(e['cdbg_total_base_value']):>12} "
                  f"{factors[:38]:<40}")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  FUNDÃO DEEP-DIVE
# ═════════════════════════════════════════════════════════════════════════════

def fundao_deep_dive() -> dict:
    """Cross-reference Fundão PRR projects with their BASE contracts.

    Returns:
      - Fundão PRR entities and contracts
      - cd_base_gov matches for Fundão contracts
      - Fundão BASE contracts (buyer NIF match)
      - VectorPlano-specific: PRR housing context
      - Price inflation comparison
      - Execution gap analysis
    """
    check_dbs()
    conn = db_connect(str(TRANSPARENCY_DB))
    proc_conn = db_connect(str(PROCUREMENT_DB))

    # --- Find Fundão PRR entities ---
    fundao_entities = conn.execute(
        "SELECT cd_entidade, ds_entidade, nif, papel, atividade_economica, "
        "localizacao, COALESCE(valor_contratado, 0), COALESCE(valor_pago, 0) "
        "FROM prr_entities "
        "WHERE ds_entidade LIKE '%Fundão%' OR ds_entidade LIKE '%Fundao%' "
        "OR localizacao LIKE '%Fundão%' OR localizacao LIKE '%Fundao%'"
    ).fetchall()

    # Also search for Fundão-related entities (municipio de fundao)
    fundao_entities_extra = conn.execute(
        "SELECT cd_entidade, ds_entidade, nif, papel, atividade_economica, "
        "localizacao, COALESCE(valor_contratado, 0), COALESCE(valor_pago, 0) "
        "FROM prr_entities "
        "WHERE cd_entidade IN ("
        "  SELECT cd_entidade FROM prr_entity_contracts WHERE cd_contrato IN ("
        "    SELECT cd_contrato FROM prr_contracts WHERE cd_projeto IN ("
        "      SELECT cd_projeto FROM prr_locations WHERE ds_concelho LIKE '%Fundão%'"
        "    )"
        "  )"
        ")"
    ).fetchall()

    all_fundao = {r[0]: {
        "cd_entidade": r[0], "name": r[1], "nif": r[2],
        "papel": r[3] or "", "atividade": r[4] or "",
        "localizacao": r[5] or "", "prr_value": r[6], "prr_paid": r[7],
    } for r in list(fundao_entities) + list(fundao_entities_extra)}

    # --- Get Fundão contract details ---
    fundao_contracts = []
    for cd_ent in all_fundao:
        rows = conn.execute(
            "SELECT ec.cd_contrato, ec.ds_contrato, ec.ds_papel, ec.valor_contrato, "
            "c.cd_base_gov, c.dt_assinatura, c.montante, c.cd_projeto, c.ds_projeto "
            "FROM prr_entity_contracts ec "
            "LEFT JOIN prr_contracts c ON ec.cd_contrato = c.cd_contrato "
            "WHERE ec.cd_entidade = ? AND ec.valor_contrato > 0 "
            "ORDER BY ec.valor_contrato DESC",
            (cd_ent,)
        ).fetchall()
        for r in rows:
            fundao_contracts.append({
                "cd_contrato": r[0], "ds_contrato": r[1] or "",
                "papel": r[2] or "", "valor_contrato": r[3] or 0,
                "cd_base_gov": r[4] or "", "dt_assinatura": r[5] or "",
                "montante": r[6] or 0, "cd_projeto": r[7] or "",
                "ds_projeto": r[8] or "",
                "cd_entidade": cd_ent,
                "entity_name": all_fundao[cd_ent]["name"],
            })

    # --- cd_base_gov matches for Fundão ---
    nif_pattern = re.compile(r"\b(\d{9})\b")
    base_by_anuncio = load_base_n_anuncio(proc_conn)

    fundao_cdbg_matches = []
    for fc in fundao_contracts:
        cdbg = fc.get("cd_base_gov", "").strip()
        if not cdbg:
            continue
        bms = base_by_anuncio.get(cdbg, [])
        for bm in bms:
            supplier_nifs = set()
            if bm["adjudicatarios"]:
                supplier_nifs = set(nif_pattern.findall(bm["adjudicatarios"]))
            fundao_cdbg_matches.append({
                "prr_contrato": fc["cd_contrato"],
                "prr_descricao": fc["ds_contrato"][:80],
                "prr_value": fc["montante"],
                "entity": fc["entity_name"],
                "cdbg": cdbg,
                "base_idcontrato": bm["idcontrato"],
                "base_preco": bm["preco"],
                "base_adjudicante": bm["adjudicante_nome"],
                "base_objecto": bm["objectoContrato"][:80],
                "inflated": bool(bm["is_inflated"]),
                "overrun": bm["overrun"],
                "base_suppliers": list(supplier_nifs),
            })

    # --- Fundão BASE contracts (buyer side) ---
    fundao_buyer_nifs = set()
    for fe in all_fundao.values():
        if fe["nif"]:
            fundao_buyer_nifs.add(fe["nif"])

    fundao_base_contracts = {}
    for nif in fundao_buyer_nifs:
        rows = proc_conn.execute(
            "SELECT idcontrato, adjudicante_nif, adjudicante_nome, "
            "COALESCE(precoContratual, 0), objectoContrato, tipoprocedimento, "
            "dataCelebracaoContrato, NUTs, "
            "CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
            "    THEN 1 ELSE 0 END as is_inflated, "
            "CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
            "    THEN precoContratual - precoBaseProcedimento ELSE 0 END as overrun "
            "FROM contratos WHERE adjudicante_nif = ? "
            "ORDER BY precoContratual DESC LIMIT 100",
            (nif,)
        ).fetchall()
        if rows:
            fundao_base_contracts[nif] = [{
                "idcontrato": r[0], "adjudicante_nif": r[1],
                "adjudicante_nome": r[2], "preco": r[3],
                "objectoContrato": (r[4] or "")[:80],
                "tipoprocedimento": r[5] or "", "data": r[6] or "",
                "nuts": r[7] or "", "inflated": bool(r[8]),
                "overrun": r[9],
            } for r in rows]

    # --- Fundão supplier side: find contracts where Fundão entities won ---
    fundao_base_supplier = {}
    for nif in fundao_buyer_nifs:
        rows = proc_conn.execute(
            "SELECT idcontrato, adjudicante_nif, adjudicante_nome, "
            "COALESCE(precoContratual, 0), objectoContrato, "
            "adjudicatarios, dataCelebracaoContrato "
            "FROM contratos "
            "WHERE adjudicatarios LIKE ? "
            "ORDER BY precoContratual DESC LIMIT 50",
            (f"%{nif}%",)
        ).fetchall()
        if rows:
            fundao_base_supplier[nif] = [{
                "idcontrato": r[0], "adjudicante_nif": r[1],
                "adjudicante_nome": r[2], "preco": r[3],
                "objectoContrato": (r[4] or "")[:80],
                "data": r[6] or "",
            } for r in rows]

    # --- VectorPlano specific ---
    vectorplano_nif = "513913157"  # Known from FINDINGS.md
    vectorplano_info = conn.execute(
        "SELECT ds_entidade, nif, papel, valor_contratado, valor_pago "
        "FROM prr_entities WHERE nif = ?",
        (vectorplano_nif,)
    ).fetchone()

    vectorplano = {}
    if vectorplano_info:
        vectorplano["prr"] = {
            "name": vectorplano_info[0],
            "nif": vectorplano_info[1],
            "contratado": vectorplano_info[3],
            "pago": vectorplano_info[4],
        }
        # VectorPlano contracts
        vp_contracts = conn.execute(
            "SELECT ec.cd_contrato, ec.ds_contrato, ec.ds_papel, ec.valor_contrato, "
            "c.cd_base_gov, c.dt_assinatura, c.cd_projeto "
            "FROM prr_entity_contracts ec "
            "LEFT JOIN prr_contracts c ON ec.cd_contrato = c.cd_contrato "
            "WHERE ec.cd_entidade IN ("
            "  SELECT cd_entidade FROM prr_entities WHERE nif = ?"
            ") ORDER BY ec.valor_contrato DESC",
            (vectorplano_nif,)
        ).fetchall()
        vectorplano["contracts"] = [{
            "cd_contrato": r[0], "descricao": (r[1] or "")[:60],
            "papel": r[2] or "", "valor": r[3] or 0,
            "cd_base_gov": r[4] or "", "data": r[5] or "",
            "cd_projeto": r[6] or "",
        } for r in vp_contracts]

        # VectorPlano BASE contracts
        vp_base = proc_conn.execute(
            "SELECT idcontrato, adjudicante_nif, adjudicante_nome, "
            "COALESCE(precoContratual, 0), objectoContrato, tipoprocedimento, "
            "CASE WHEN precoBaseProcedimento > 0 AND precoContratual > precoBaseProcedimento "
            "    THEN precoContratual - precoBaseProcedimento ELSE 0 END as overrun "
            "FROM contratos WHERE adjudicatarios LIKE ? "
            "ORDER BY precoContratual DESC",
            (f"%{vectorplano_nif}%",)
        ).fetchall()
        vectorplano["base_contracts"] = [{
            "idcontrato": r[0], "buyer_nif": r[1], "buyer_name": r[2],
            "preco": r[3], "objecto": (r[4] or "")[:60],
            "tipoprocedimento": r[5] or "", "overrun": r[6],
        } for r in vp_base]

    conn.close()
    proc_conn.close()

    # --- Compute stats ---
    total_prr = sum(fc["montante"] for fc in fundao_contracts)
    exec_gap = total_prr - sum(ef["prr_paid"] for ef in all_fundao.values())

    fundao_base_total = sum(
        bc["preco"]
        for nif_contracts in fundao_base_contracts.values()
        for bc in nif_contracts
    )
    fundao_base_buyer_count = sum(
        len(contracts)
        for contracts in fundao_base_contracts.values()
    )
    fundao_inflated = [
        bc for nif_contracts in fundao_base_contracts.values()
        for bc in nif_contracts if bc["inflated"]
    ]

    return {
        "fundao_entities": list(all_fundao.values()),
        "fundao_contracts": fundao_contracts,
        "fundao_cdbg_matches": fundao_cdbg_matches,
        "fundao_base_as_buyer": fundao_base_contracts,
        "fundao_base_as_supplier": fundao_base_supplier,
        "vectorplano": vectorplano,
        "summary": {
            "total_fundao_entities": len(all_fundao),
            "total_fundao_prr_contracts": len(fundao_contracts),
            "total_fundao_prr_value": total_prr,
            "total_fundao_prr_paid": sum(ef["prr_paid"] for ef in all_fundao.values()),
            "execution_gap": exec_gap,
            "fundao_base_buyer_count": fundao_base_buyer_count,
            "fundao_base_buyer_value": fundao_base_total,
            "fundao_inflated_contracts": len(fundao_inflated),
            "fundao_inflated_total_overrun": sum(bc["overrun"] for bc in fundao_inflated),
            "fundao_cdbg_match_count": len(fundao_cdbg_matches),
        },
    }


def print_fundao_report(data: dict):
    """Print Fundão deep-dive report."""
    summary = data["summary"]

    print(f"\n{'=' * 110}")
    print(f"  FUNDÃO DEEP-DIVE — PRR × Procurement Cross-Reference")
    print("  24-anomaly municipality with 87/100 risk score")
    print(f"{'=' * 110}")

    print(f"\n  📊 Summary")
    print(f"  {'─' * 60}")
    print(f"  PRR entities in Fundão: {summary['total_fundao_entities']}")
    print(f"  PRR contracts: {summary['total_fundao_prr_contracts']}")
    print(f"  PRR value: {fmt(summary['total_fundao_prr_value'])}")
    print(f"  PRR paid: {fmt(summary['total_fundao_prr_paid'])}")
    print(f"  Execution gap: {fmt(summary['execution_gap'])} "
          f"({summary['execution_gap']/summary['total_fundao_prr_value']*100:.1f}% unpaid)"
          if summary['total_fundao_prr_value'] > 0 else "")
    print(f"  BASE buyer contracts: {summary['fundao_base_buyer_count']} "
          f"({fmt(summary['fundao_base_buyer_value'])})")
    print(f"  cd_base_gov matches: {summary['fundao_cdbg_match_count']}")
    print(f"  Inflated BASE contracts: {summary['fundao_inflated_contracts']} "
          f"(+{fmt(summary['fundao_inflated_total_overrun'])})")

    # Fundão PRR Entities
    entities = data.get("fundao_entities", [])
    if entities:
        print(f"\n  🏛️  FUNDÃO PRR ENTITIES")
        print(f"  {'─' * 90}")
        print(f"  {'Entity':<45} {'NIF':<12} {'Papel':<20} {'PRR Value':>14}")
        print(f"  {'─' * 45} {'─' * 12} {'─' * 20} {'─' * 14}")
        for e in entities:
            print(f"  {e['name'][:43]:<45} {e['nif']:<12} {e['papel'][:18]:<20} {fmt(e['prr_value']):>14}")

    # cd_base_gov matches
    cdbg_matches = data.get("fundao_cdbg_matches", [])
    if cdbg_matches:
        print(f"\n  🔗 CD_BASE_GOV MATCHES — Fundão PRR → BASE Contract Links")
        print(f"  {'─' * 100}")
        for m in cdbg_matches:
            infl_flag = "💰 INFLATED" if m["inflated"] else "       "
            print(f"  PRR: {m['prr_contrato']} ({fmt(m['prr_value'])}) → "
                  f"BASE: {m['base_idcontrato']} ({fmt(m['base_preco'])} {infl_flag})")
            print(f"       Entity: {m['entity'][:40]}  cd_base_gov: {m['cdbg']}")
            if m["overrun"] > 0:
                print(f"       Overrun: {fmt(m['overrun'])}  Buyer: {m['base_adjudicante'][:40]}")
            print()

    # Inflated Fundão BASE contracts
    inflated_all = [
        {"nif": nif, "c": bc}
        for nif, contracts in data.get("fundao_base_as_buyer", {}).items()
        for bc in contracts if bc["inflated"]
    ]
    if inflated_all:
        print(f"\n  🚨 INFLATED BASE CONTRACTS — Fundão as Buyer")
        print(f"  {'─' * 90}")
        for item in inflated_all[:15]:
            bc = item["c"]
            print(f"  {bc['idcontrato']}  {fmt(bc['preco']):>14}  "
                  f"+{fmt(bc['overrun'])} overrun  {bc['adjudicante_nome'][:30]:30s}")
            print(f"       {bc['tipoprocedimento']}  {bc['objectoContrato'][:60]}")

    # VectorPlano detail
    vp = data.get("vectorplano", {})
    if vp:
        prr_info = vp.get("prr", {})
        print(f"\n  🏢 VECTORPLANO DEEP-DIVE")
        print(f"  {'─' * 90}")
        if prr_info:
            exec_pct = (prr_info["pago"] / prr_info["contratado"] * 100) if prr_info["contratado"] > 0 else 0
            print(f"  PRR: {prr_info['name']} (NIF: {prr_info['nif']})")
            print(f"  Contracted: {fmt(prr_info['contratado'])}  "
                  f"Paid: {fmt(prr_info['pago'])}  Execution: {exec_pct:.1f}%")

        vp_contracts = vp.get("contracts", [])
        if vp_contracts:
            print(f"\n  PRR Contracts:")
            for c in vp_contracts[:5]:
                print(f"    [{c['cd_contrato']}] {fmt(c['valor']):>12}  {c['papel']:<20}  "
                      f"{c['descricao'][:40]}")
                if c["cd_base_gov"]:
                    print(f"      cd_base_gov: {c['cd_base_gov']}  Date: {c['data']}")

        vp_base = vp.get("base_contracts", [])
        if vp_base:
            print(f"\n  BASE Contracts (as supplier):")
            print(f"  {'ID':<10} {'Value':>12} {'Overrun':>10} {'Buyer':<30} {'Procedure':<20}")
            print(f"  {'─' * 10} {'─' * 12} {'─' * 10} {'─' * 30} {'─' * 20}")
            for c in vp_base[:5]:
                print(f"  {c['idcontrato']:<10} {fmt(c['preco']):>12} "
                      f"{fmt(c['overrun']):>10} {c['buyer_name'][:28]:<30} {c['tipoprocedimento'][:18]:<20}")

        if not prr_info and not vp_contracts and not vp_base:
            print(f"  No VectorPlano data found in current datasets.")

    print(f"\n{'=' * 110}\n")


# ═════════════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════════════

def cmd_cdgov(args):
    """Run cd_base_gov contract-level matching."""
    data = analyze_cdgov_matches()
    print_cdgov_report(data)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported cd_base_gov data to {args.export}")


def cmd_text_match(args):
    """Run text similarity matching."""
    data = analyze_text_matches(min_similarity=args.min_sim)
    print_text_match_report(data)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported text match data to {args.export}")


def cmd_composite(args):
    """Run composite risk analysis."""
    data = analyze_composite_risk()
    print_composite_report(data, top_n=args.top)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported composite risk data to {args.export}")


def cmd_fundao(args):
    """Run Fundão deep-dive."""
    data = fundao_deep_dive()
    print_fundao_report(data)
    if args.export:
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported Fundão deep-dive data to {args.export}")


def cmd_all(args):
    """Run all analyses sequentially."""
    print("\n" + "=" * 110)
    print("  ENHANCED PRR × BASE CORRUPTION PATTERN DETECTOR")
    print("  Running all analyses...")
    print("=" * 110)

    # 1. CD_BASE_GOV matching
    print("\n\n" + "=" * 110)
    print("  ANALYSIS 1: CD_BASE_GOV Contract-Level Matching")
    print("=" * 110)
    cdgov_data = analyze_cdgov_matches()
    print_cdgov_report(cdgov_data)

    # 2. Text similarity
    print("\n\n" + "=" * 110)
    print("  ANALYSIS 2: Text Similarity Matching")
    print("=" * 110)
    text_data = analyze_text_matches(min_similarity=0.25)
    print_text_match_report(text_data)

    # 3. Composite risk
    print("\n\n" + "=" * 110)
    print("  ANALYSIS 3: Composite Risk (All Dimensions)")
    print("=" * 110)
    comp_data = analyze_composite_risk()
    print_composite_report(comp_data, top_n=args.top)

    # 4. Fundão deep-dive
    print("\n\n" + "=" * 110)
    print("  ANALYSIS 4: Fundão Deep-Dive")
    print("=" * 110)
    fundao_data = fundao_deep_dive()
    print_fundao_report(fundao_data)

    # Export combined
    if args.export:
        combined = {
            "cd_base_gov": cdgov_data,
            "text_similarity": text_data,
            "composite_risk": comp_data,
            "fundao_deep_dive": fundao_data,
        }
        with open(args.export, "w", encoding="utf-8") as f:
            json.dump(combined, f, ensure_ascii=False, indent=2, default=str)
        print(f"  Exported all data to {args.export}")


def main():
    parser = argparse.ArgumentParser(
        description="Enhanced PRR × BASE Corruption Pattern Detector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(f"""\
            Subcommands:
              cdgov           CD_BASE_GOV → nAnuncio contract-level matching
              text-match      Object-of-contract text similarity matching
              composite       Composite risk (all dimensions combined)
              fundao          Fundão deep-dive
              all             Run all analyses sequentially

            Examples:
              python prr_base_cdgov_detector.py cdgov
              python prr_base_cdgov_detector.py text-match --min-sim 0.3
              python prr_base_cdgov_detector.py composite --top 50
              python prr_base_cdgov_detector.py fundao
              python prr_base_cdgov_detector.py all --export data/summary/enhanced_scan.json
        """),
    )

    parser.add_argument("--top", type=int, default=30, help="Top N results (composite)")
    parser.add_argument("--min-sim", type=float, default=0.25, help="Min text similarity (text-match)")
    parser.add_argument("--export", help="Export to JSON")

    sub = parser.add_subparsers(dest="subcommand", metavar="")

    p_cdgov = sub.add_parser("cdgov", help="CD_BASE_GOV contract-level matching")
    p_cdgov.add_argument("--export", help="Export to JSON")

    p_text = sub.add_parser("text-match", help="Text similarity matching")
    p_text.add_argument("--min-sim", type=float, default=0.25, help="Min similarity (0-1)")
    p_text.add_argument("--export", help="Export to JSON")

    p_comp = sub.add_parser("composite", help="Composite risk analysis")
    p_comp.add_argument("--top", type=int, default=30, help="Top N entities")
    p_comp.add_argument("--export", help="Export to JSON")

    p_fundao = sub.add_parser("fundao", help="Fundão deep-dive")
    p_fundao.add_argument("--export", help="Export to JSON")

    p_all = sub.add_parser("all", help="Run all analyses")
    p_all.add_argument("--top", type=int, default=30)
    p_all.add_argument("--export", help="Export all data to JSON")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(1)

    routers = {
        "cdgov": cmd_cdgov,
        "text-match": cmd_text_match,
        "composite": cmd_composite,
        "fundao": cmd_fundao,
        "all": cmd_all,
    }

    routers[args.subcommand](args)


if __name__ == "__main__":
    main()
