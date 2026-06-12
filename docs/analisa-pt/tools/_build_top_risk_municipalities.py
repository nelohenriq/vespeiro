#!/usr/bin/env python3
"""Build top_risk_municipalities.json from a one-shot SQL query.

Composite risk score per concelho:
  - 60% direct-award share (normalized vs 65% national avg)
  - 40% relative contract volume (normalized vs the largest)

This surfaces concelhos with both high non-competitive share AND
high procurement volume — the headline corruption-risk pattern.
"""
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from utils_db import connect

OUT = Path(__file__).parent / "data" / "summary" / "top_risk_municipalities.json"


def main() -> int:
    t0 = time.time()
    conn = connect("data/procurement.db")
    conn.row_factory = sqlite3.Row

    cols = [r[0] for r in conn.execute(
        'SELECT name FROM pragma_table_info("contratos")'
    ).fetchall()]

    # Ensure the index on ine_municipality exists so the GROUP BY is
    # sub-second. Idempotent: the migration runs every time the script
    # is invoked, but only creates the index once. Without this index
    # the full scan against the 1.9GB procurement.db times out.
    if "ine_municipality" in cols:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contratos_ine_municipality "
            "ON contratos(ine_municipality)"
        )
        conn.commit()

    if "ine_municipality" not in cols:
        print(f"  WARN: ine_municipality column not in contratos ({len(cols)} cols).")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_municipalities": 0,
                "by_risk_level": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "municipalities": [],
                "note": "ine_municipality column not yet populated; run municipality_resolver.",
            }, f, indent=2, ensure_ascii=False)
        print(f"  wrote stub {OUT}")
        return 0

    rows = conn.execute("""
        SELECT
            ine_municipality                       AS municipality,
            COUNT(*)                               AS total_contracts,
            SUM(CASE WHEN precoContratual > 0
                     THEN precoContratual ELSE 0 END) AS total_value,
            SUM(CASE WHEN tipoprocedimento LIKE '%ajuste direto%'
                     THEN 1 ELSE 0 END)           AS direct_award_count,
            ROUND(100.0 * SUM(CASE WHEN tipoprocedimento LIKE '%ajuste direto%'
                                   THEN 1 ELSE 0 END) / COUNT(*), 1) AS direct_award_pct
        FROM contratos
        WHERE ine_municipality IS NOT NULL AND ine_municipality != ''
        GROUP BY ine_municipality
        HAVING COUNT(*) >= 100
        ORDER BY total_value DESC
        LIMIT 20
    """).fetchall()
    print(f"  query: {(time.time()-t0)*1000:.0f}ms, {len(rows)} concelhos")

    if not rows:
        return 0

    max_value = max((r["total_value"] or 0) for r in rows) or 1
    results = []
    for r in rows:
        direct_pct = r["direct_award_pct"] or 0
        direct_score = min(direct_pct / 65.0, 1.0)  # 65% national baseline
        volume_score = (r["total_value"] or 0) / max_value
        risk_score = round((direct_score * 0.6 + volume_score * 0.4) * 100, 1)
        if risk_score >= 70:
            level = "critical"
        elif risk_score >= 50:
            level = "high"
        elif risk_score >= 30:
            level = "medium"
        else:
            level = "low"
        results.append({
            "municipality": r["municipality"],
            "total_contracts": int(r["total_contracts"]),
            "total_value": float(r["total_value"] or 0),
            "direct_award_count": int(r["direct_award_count"] or 0),
            "direct_award_pct": float(direct_pct),
            "risk_score": risk_score,
            "risk_level": level,
        })

    results.sort(key=lambda r: -r["risk_score"])

    by_level = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for r in results:
        by_level[r["risk_level"]] += 1

    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_municipalities": len(results),
        "by_risk_level": by_level,
        "municipalities": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"  wrote {OUT} ({len(results)} municipalities)")
    print("  top 5 by risk score:")
    for r in results[:5]:
        print(f"    [{r['risk_level'].upper():8s}] {r['municipality']:30s}"
              f"  score={r['risk_score']:5.1f}  contracts={r['total_contracts']:,}"
              f"  DA%={r['direct_award_pct']:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
