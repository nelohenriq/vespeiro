#!/usr/bin/env python3
"""Unified Dashboard Generator — Renders consolidated.json as an interactive HTML dashboard.

Reads the consolidated JSON from consolidate.py and generates a standalone
HTML file with tab-based navigation across all 8 data categories.

Usage:
    python generate_dashboard.py                                          # Default input/output
    python generate_dashboard.py --in consolidated.json -o dashboard.html # Custom paths
    python generate_dashboard.py --open                                   # Generate and open in browser
"""

import json
import argparse
import webbrowser
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
SUMMARY_DIR = DATA_DIR / "summary"
DEFAULT_INPUT = SUMMARY_DIR / "consolidated.json"
DEFAULT_OUTPUT = DATA_DIR / "dashboard.html"


def esc(text):
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def fmt(v):
    if v is None or v == 0:
        return "€0"
    v = float(v)
    if v >= 1_000_000_000:
        return f"€{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"€{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"€{v / 1_000:.0f}K"
    return f"€{v:.0f}"


def fmt_num(v):
    if v is None:
        return "0"
    return f"{int(v):,}"


def safe_get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        elif isinstance(d, list) and isinstance(k, int):
            try:
                d = d[k]
            except (IndexError, TypeError):
                return default
        else:
            return default
        if d is None:
            return default
    return d


# ═════════════════════════════════════════════════════════════════════════════
#  CATEGORY CONTENT BUILDERS
# ═════════════════════════════════════════════════════════════════════════════


def build_risk_anomalies(tools_data):
    html = []
    # Anomaly scanner
    anomaly = tools_data.get("anomaly_scanner", {}).get("data", {})
    entities = anomaly.get("top_entities", [])
    critical = anomaly.get("critical", 0)
    flagged = anomaly.get("total_flagged", 0)

    if flagged > 0:
        html.append(f'<div class="info-bar">🚨 {flagged} entities flagged ({critical} critical)</div>')
        html.append('<div class="scroll-table"><table><thead><tr>')
        html.append('<th>#</th><th>Score</th><th>Entity</th><th>NIF</th><th>Signals</th><th>Critical</th><th>Details</th>')
        html.append('</tr></thead><tbody>')
        for i, e in enumerate(entities[:30], 1):
            sc = e.get("composite_score", 0)
            color = "#ef4444" if sc >= 70 else "#f59e0b" if sc >= 40 else "#22c55e"
            signals = e.get("signals", [])
            signal_str = ", ".join(f'{s.get("type", "")}' for s in signals[:3])
            html.append(f'<tr><td>{i}</td><td><span class="score-badge" style="background:{color}">{sc:.0f}</span></td>')
            html.append(f'<td class="entity-name">{esc(e.get("name", "")[:50])}</td>')
            html.append(f'<td class="nif">{esc(e.get("nif", ""))}</td>')
            html.append(f'<td>{e.get("signal_count", 0)}</td><td>{e.get("critical_count", 0)}</td>')
            html.append(f'<td class="detail-text">{esc(signal_str[:60])}</td></tr>')
        html.append('</tbody></table></div>')
    else:
        html.append('<div class="empty-state">No anomaly data available. Run anomaly_scanner.py --export first.</div>')

    # Municipality risk
    muni = tools_data.get("municipality_risk", {}).get("data", {})
    muni_list = muni.get("top_municipalities", [])
    if muni_list:
        high = muni.get("high_risk", 0)
        medium = muni.get("medium_risk", 0)
        html.append(f'<div class="info-bar">🏛️ {len(muni_list)} municipalities scanned — {high} high risk, {medium} medium risk</div>')
        html.append('<div class="scroll-table"><table><thead><tr>')
        html.append('<th>#</th><th>Risk</th><th>Municipality</th><th>Contracts</th><th>Value</th><th>Top3%</th><th>Inflation%</th><th>Direct%</th>')
        html.append('</tr></thead><tbody>')
        for i, m in enumerate(muni_list[:25], 1):
            risk = m.get("risk", 0)
            color = "#ef4444" if risk > 60 else "#f59e0b" if risk > 40 else "#22c55e"
            html.append(f'<tr><td>{i}</td><td><span class="score-badge" style="background:{color}">{risk:.0f}</span></td>')
            html.append(f'<td class="entity-name">{esc(m.get("name", "")[:45])}</td>')
            html.append(f'<td>{m.get("total_contracts", 0)}</td>')
            html.append(f'<td class="value">{fmt(m.get("total_value", 0))}</td>')
            html.append(f'<td>{m.get("top3_share", 0):.0f}%</td>')
            html.append(f'<td>{m.get("inflation_rate", 0):.0f}%</td>')
            html.append(f'<td>{m.get("direct_rate", 0):.0f}%</td></tr>')
        html.append('</tbody></table></div>')

    return "\n".join(html) if html else '<div class="empty-state">Run anomaly tools with --export to populate this tab.</div>'


def build_financial(tools_data):
    html = []

    # Money trail
    trail = tools_data.get("money_trail", {}).get("data", {})
    if trail.get("concelho"):
        chain = trail.get("chain_analysis", {})
        prr = trail.get("prr_allocation", {})
        proc = trail.get("procurement", {})

        html.append(f'<div class="info-bar">💶 Money Trail — {esc(trail.get("concelho", ""))}</div>')
        html.append('<div class="metric-row">')
        html.append(f'<div class="metric"><div class="metric-value">{fmt(prr.get("total_approved", 0))}</div><div class="metric-label">PRR Approved</div></div>')
        html.append(f'<div class="metric"><div class="metric-value">{fmt(prr.get("total_paid", 0))}</div><div class="metric-label">PRR Paid ({prr.get("execution_rate", 0):.0f}%)</div></div>')
        html.append(f'<div class="metric"><div class="metric-value">{fmt_num(proc.get("total_contracts", 0))}</div><div class="metric-label">Procurement Contracts</div></div>')
        html.append(f'<div class="metric"><div class="metric-value">{fmt(proc.get("total_value", 0))}</div><div class="metric-label">Procurement Value</div></div>')
        html.append(f'<div class="metric"><div class="metric-value">{chain.get("total_anomalies", 0)}</div><div class="metric-label">Chain Anomalies</div></div>')
        html.append('</div>')

        anomalies = chain.get("anomalies", [])
        if anomalies:
            html.append('<div class="scroll-table"><table><thead><tr><th>Severity</th><th>Type</th><th>Detail</th></tr></thead><tbody>')
            for a in anomalies:
                sev = a.get("severity", "info")
                icon = "🔴" if sev == "critical" else "🟡"
                html.append(f'<tr><td>{icon} {sev}</td><td>{esc(a.get("type", ""))}</td><td>{esc(a.get("detail", "")[:80])}</td></tr>')
            html.append('</tbody></table></div>')

        top_winners = proc.get("top_winners", [])
        if top_winners:
            html.append('<h4>Top Suppliers</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Name</th><th>Value</th><th>Share</th></tr></thead><tbody>')
            for i, w in enumerate(top_winners[:10], 1):
                html.append(f'<tr><td>{i}</td><td>{esc(w.get("name", "")[:45])}</td><td class="value">{fmt(w.get("value", 0))}</td><td>{w.get("share_pct", 0):.1f}%</td></tr>')
            html.append('</tbody></table></div>')
    else:
        html.append('<div class="empty-state">Run money_trail_analyzer.py --concelho "Fundão" --export first.</div>')

    return "\n".join(html) if html else '<div class="empty-state">No financial data available.</div>'


def build_temporal(tools_data):
    html = []
    temp = tools_data.get("temporal_clusters", {}).get("data", {})
    if not temp or temp.get("error"):
        return '<div class="empty-state">Run temporal_clustering.py --export to populate this tab.</div>'

    daily = temp.get("daily_bursts", [])
    year_end = temp.get("year_end")
    buyer_bursts = temp.get("buyer_bursts", [])
    price_patterns = temp.get("price_patterns", [])
    counts = temp.get("counts", {})

    html.append(f'<div class="info-bar">📅 {temp.get("total_contracts", 0):,} contracts analyzed — {counts.get("daily_bursts", 0)} daily bursts, {counts.get("buyer_bursts", 0)} buyer bursts</div>')

    if year_end:
        surge = "🚨 SURGE DETECTED" if year_end.get("is_surge") else "✅ Normal"
        ratio = year_end.get("dec_value_ratio", 0)
        html.append(f'<div class="metric-row"><div class="metric"><div class="metric-value">{ratio:.1f}x</div><div class="metric-label">December Ratio {surge}</div></div>')
        html.append(f'<div class="metric"><div class="metric-value">{year_end.get("dec_late_count", 0)}</div><div class="metric-label">Last Week Dec Contracts</div></div></div>')

    if daily:
        html.append('<h4>Daily Contract Bursts</h4><div class="scroll-table"><table><thead><tr><th>Date</th><th>Contracts</th><th>Value</th><th>Buyers</th><th>Year-End?</th><th>Election</th></tr></thead><tbody>')
        for b in daily[:20]:
            yend = "⚠️" if b.get("is_year_end") else ""
            election = f'{b.get("days_to_election", "")}d' if b.get("days_to_election") and b.get("days_to_election", 9999) <= 30 else ""
            html.append(f'<tr><td>{esc(b.get("date", ""))}</td><td>{b.get("contracts", 0)}</td><td class="value">{fmt(b.get("total_value", 0))}</td><td>{b.get("unique_buyers", 0)}</td><td>{yend}</td><td>{election}</td></tr>')
        html.append('</tbody></table></div>')

    if buyer_bursts:
        html.append('<h4>Per-Buyer Spending Bursts</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Period</th><th>Contracts</th><th>Value</th></tr></thead><tbody>')
        for i, b in enumerate(buyer_bursts[:15], 1):
            period = f'{b.get("start_date", "")} → {b.get("end_date", "")}'
            html.append(f'<tr><td>{i}</td><td class="entity-name">{esc(b.get("buyer_name", "")[:45])}</td><td>{period}</td><td>{b.get("contracts", 0)}</td><td class="value">{fmt(b.get("total_value", 0))}</td></tr>')
        html.append('</tbody></table></div>')

    if price_patterns:
        html.append('<h4>Suspicious Price Patterns</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Cluster</th><th>Price</th><th>Total</th></tr></thead><tbody>')
        for i, p in enumerate(price_patterns[:15], 1):
            html.append(f'<tr><td>{i}</td><td class="entity-name">{esc(p.get("buyer_name", "")[:45])}</td><td>{p.get("cluster_size", 0)}</td><td class="value">{fmt(p.get("price_range", 0))}</td><td class="value">{fmt(p.get("total_value", 0))}</td></tr>')
        html.append('</tbody></table></div>')

    return "\n".join(html)


def build_procurement_patterns(tools_data):
    html = []
    bp = tools_data.get("bid_patterns", {}).get("data", {})
    if not bp or bp.get("error"):
        return '<div class="empty-state">Run bid_pattern_analyzer.py --export to populate this tab.</div>'

    counts = bp.get("counts", {})
    html.append(f'<div class="info-bar">🔄 {counts.get("rotating_winners", 0)} rotating patterns, {counts.get("closed_groups", 0)} closed groups, {counts.get("bid_suppression", 0)} suppression cases, {counts.get("similar_pricing", 0)} suspicious pricing</div>')

    rotating = bp.get("rotating_winners", [])
    if rotating:
        html.append('<h4>Rotating Winners</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Winners</th><th>Contracts</th><th>Value</th><th>Rotation</th></tr></thead><tbody>')
        for i, r in enumerate(rotating[:15], 1):
            html.append(f'<tr><td>{i}</td><td class="entity-name">{esc(r.get("buyer_name", "")[:45])}</td><td>{r.get("unique_winners", 0)}</td><td>{r.get("total_contracts", 0)}</td><td class="value">{fmt(r.get("total_value", 0))}</td><td>{r.get("rotation_ratio", 0):.0%}</td></tr>')
        html.append('</tbody></table></div>')

    suppression = bp.get("bid_suppression", [])
    if suppression:
        html.append('<h4>Bid Suppression</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Dominant Winner</th><th>Win Rate</th><th>Contracts</th><th>Decoys</th></tr></thead><tbody>')
        for i, s in enumerate(suppression[:15], 1):
            html.append(f'<tr><td>{i}</td><td class="entity-name">{esc(s.get("buyer_name", "")[:45])}</td><td>{esc(s.get("dominant_winner_name", "")[:40])}</td><td><span class="score-badge" style="background:#ef4444">{s.get("win_rate", 0):.0%}</span></td><td>{s.get("total_contracts", 0)}</td><td>{len(s.get("decoys", []))}</td></tr>')
        html.append('</tbody></table></div>')

    closed = bp.get("closed_bidder_groups", [])
    if closed:
        html.append('<h4>Closed Bidder Groups</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Buyer</th><th>Group Size</th><th>Co-occurrence</th><th>Bidders</th></tr></thead><tbody>')
        for i, g in enumerate(closed[:15], 1):
            bidders = ", ".join(b.get("name", "")[:30] for b in g.get("bidders", [])[:5])
            html.append(f'<tr><td>{i}</td><td class="entity-name">{esc(g.get("buyer_name", "")[:45])}</td><td>{g.get("group_size", 0)}</td><td>{g.get("cooccurrence_rate", 0):.0f}%</td><td class="detail-text">{esc(bidders[:80])}</td></tr>')
        html.append('</tbody></table></div>')

    return "\n".join(html) if html else '<div class="empty-state">No bid pattern data available.</div>'


def build_entities_networks(tools_data):
    html = []
    dr = tools_data.get("prr_dual_role", {}).get("data", {})
    if not dr or dr.get("error") or dr.get("total", 0) == 0:
        return '<div class="empty-state">Run prr_procurement_crossref.py --export to populate this tab.</div>'

    html.append(f'<div class="info-bar">🏛️ {dr.get("total", 0)} dual-role entities — {dr.get("triple_role", 0)} triple role, {dr.get("high_risk", 0)} high risk</div>')
    html.append(f'<div class="metric-row"><div class="metric"><div class="metric-value">{fmt(dr.get("total_prr_value", 0))}</div><div class="metric-label">Total PRR Value</div></div>')
    html.append(f'<div class="metric"><div class="metric-value">{fmt(dr.get("total_base_value", 0))}</div><div class="metric-label">Total BASE Value</div></div></div>')

    entities = dr.get("top_entities", [])
    if entities:
        html.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Score</th><th>Entity</th><th>NIF</th><th>Role Type</th><th>PRR Value</th><th>BASE Value</th><th>PRR Exec%</th><th>Risk Factors</th></tr></thead><tbody>')
        for i, e in enumerate(entities[:30], 1):
            sc = e.get("risk_score", 0)
            color = "#ef4444" if sc >= 70 else "#f59e0b" if sc >= 40 else "#22c55e"
            base_val = (e.get("base_as_buyer", {}) or {}).get("value", 0) + (e.get("base_as_supplier", {}) or {}).get("value", 0)
            factors = "; ".join(e.get("risk_factors", [])[:2])
            html.append(f'<tr><td>{i}</td><td><span class="score-badge" style="background:{color}">{sc:.0f}</span></td>')
            html.append(f'<td class="entity-name">{esc(e.get("name", "")[:50])}</td>')
            html.append(f'<td class="nif">{esc(e.get("nif", ""))}</td>')
            html.append(f'<td>{esc(e.get("role_type", "")[:25])}</td>')
            html.append(f'<td class="value">{fmt(e.get("prr_value", 0))}</td>')
            html.append(f'<td class="value">{fmt(base_val)}</td>')
            html.append(f'<td>{e.get("prr_execution_pct", 0):.0f}%</td>')
            html.append(f'<td class="detail-text">{esc(factors[:60])}</td></tr>')
        html.append('</tbody></table></div>')

    return "\n".join(html)


def build_cross_references(tools_data):
    html = []

    enhanced = tools_data.get("prr_enhanced", {}).get("data", {})
    if enhanced and not enhanced.get("error"):
        cdg = enhanced.get("cd_base_gov_matches", [])
        text_sim = enhanced.get("text_similarity_matches", [])
        html.append(f'<div class="info-bar">🔗 PRR Enhanced — {len(cdg)} cd_base_gov matches, {len(text_sim)} text similarity matches</div>')

        if cdg:
            html.append('<h4>cd_base_gov Matches</h4><div class="scroll-table"><table><thead><tr><th>#</th><th>Entity</th><th>PRR Value</th><th>Match Score</th></tr></thead><tbody>')
            for i, m in enumerate(cdg[:20], 1):
                html.append(f'<tr><td>{i}</td><td class="entity-name">{esc(str(m.get("entity", m.get("name", "")))[:50])}</td><td class="value">{fmt(m.get("prr_value", 0))}</td><td>{m.get("score", m.get("match_score", 0))}</td></tr>')
            html.append('</tbody></table></div>')

    ted = tools_data.get("ted_crossref", {}).get("data", {})
    if ted and not ted.get("error"):
        html.append(f'<div class="info-bar">🇪🇺 TED Cross-Reference — {ted.get("total_matches", 0)} threshold crosses</div>')

    bep = tools_data.get("bep_crossref", {}).get("data", {})
    if bep and not bep.get("error"):
        html.append(f'<div class="info-bar">📋 BEP × Procurement — {bep.get("total_matched", 0)} matched entities</div>')

    law = tools_data.get("law_hiring", {}).get("data", {})
    if law and not law.get("error"):
        html.append(f'<div class="info-bar">📜 Laws × BEP Hiring — {law.get("total_correlations", 0)} correlations</div>')

    return "\n".join(html) if html else '<div class="empty-state">Run cross-reference tools (prr_base_cdgov_detector.py, ted_crossref.py, bep_procurement_crossref.py, law_hiring_correlation.py) with --export to populate this tab.</div>'


def build_personnel(tools_data):
    html = []
    doors = tools_data.get("revolving_doors", {}).get("data", {})
    if not doors or doors.get("error") or doors.get("total_chains", 0) == 0:
        return '<div class="empty-state">Run revolving_door_detector.py --export to populate this tab.</div>'

    html.append(f'<div class="info-bar">👤 {doors.get("total_appointments_matched", 0)} appointments matched, {doors.get("total_chains", 0)} revolving door chains detected</div>')

    chains = doors.get("top_chains", [])
    if chains:
        html.append('<div class="scroll-table"><table><thead><tr><th>#</th><th>Score</th><th>Person</th><th>Organization</th><th>Role</th><th>Date</th><th>Suppliers</th><th>Top Risk</th></tr></thead><tbody>')
        for i, c in enumerate(chains[:30], 1):
            sc = c.get("max_risk_score", 0)
            color = "#ef4444" if sc >= 70 else "#f59e0b" if sc >= 40 else "#22c55e"
            top_sup = c.get("suppliers", [{}])[0] if c.get("suppliers") else {}
            factors = "; ".join(top_sup.get("risk_factors", [])[:2])
            html.append(f'<tr><td>{i}</td><td><span class="score-badge" style="background:{color}">{sc:.0f}</span></td>')
            html.append(f'<td class="entity-name">{esc(c.get("person_name", "")[:35])}</td>')
            html.append(f'<td>{esc(c.get("organization", "")[:35])}</td>')
            html.append(f'<td class="detail-text">{esc(c.get("role", "")[:30])}</td>')
            html.append(f'<td>{esc(c.get("date", ""))}</td>')
            html.append(f'<td>{c.get("total_supplier_chains", 0)}</td>')
            html.append(f'<td class="detail-text">{esc(factors[:60])}</td></tr>')
        html.append('</tbody></table></div>')

    return "\n".join(html)


def build_alerts(tools_data):
    html = []
    alerts = tools_data.get("contract_alerts", {}).get("data", {})
    if not alerts or alerts.get("error"):
        return '<div class="empty-state">Run contract_alerts.py history to populate this tab.</div>'

    html.append(f'<div class="info-bar">🔔 Contract alert history and threshold breaches</div>')

    keys = alerts.get("_raw_preview_keys", [])
    if keys:
        html.append('<div class="metric-row">')
        for k in keys[:6]:
            v = alerts.get(k)
            if isinstance(v, (int, float)):
                html.append(f'<div class="metric"><div class="metric-value">{fmt_num(v)}</div><div class="metric-label">{esc(k.replace("_", " ").title())}</div></div>')
        html.append('</div>')

    return "\n".join(html) if html else '<div class="empty-state">No alert data available.</div>'


CATEGORY_BUILDERS = {
    "risk_anomalies": build_risk_anomalies,
    "financial": build_financial,
    "temporal": build_temporal,
    "procurement_patterns": build_procurement_patterns,
    "entities_networks": build_entities_networks,
    "cross_references": build_cross_references,
    "personnel": build_personnel,
    "alerts": build_alerts,
}


# ═════════════════════════════════════════════════════════════════════════════
#  HTML GENERATION
# ═════════════════════════════════════════════════════════════════════════════


def generate_dashboard(consolidated: dict) -> str:
    meta = consolidated.get("meta", {})
    categories = consolidated.get("categories", {})
    summaries = consolidated.get("category_summaries", {})
    tool_registry = consolidated.get("tool_registry", {})

    # Category definitions
    cat_defs = [
        {"id": "risk_anomalies", "label": "Risk & Anomalies", "icon": "🚨"},
        {"id": "financial", "label": "Financial", "icon": "💰"},
        {"id": "temporal", "label": "Temporal", "icon": "📅"},
        {"id": "procurement_patterns", "label": "Patterns", "icon": "🔄"},
        {"id": "entities_networks", "label": "Entities", "icon": "🏛️"},
        {"id": "cross_references", "label": "Cross-Ref", "icon": "🔗"},
        {"id": "personnel", "label": "Personnel", "icon": "👤"},
        {"id": "alerts", "label": "Alerts", "icon": "🔔"},
    ]

    # Build tab bar
    tab_buttons = []
    tab_panels = []
    for cat_def in cat_defs:
        cid = cat_def["id"]
        cat_data = categories.get(cid, {})
        tools_data = cat_data.get("tools", {})
        s = summaries.get(cid, {})
        loaded = s.get("loaded", 0)
        errors = s.get("errors", 0)

        badge = ""
        if loaded > 0:
            badge = f' <span class="tab-badge loaded">{loaded}</span>'
        if errors > 0:
            badge += f' <span class="tab-badge error">{errors}</span>'

        tab_buttons.append(f'<button class="tab-btn{" active" if cid == "risk_anomalies" else ""}" data-tab="{cid}">{cat_def["icon"]} {cat_def["label"]}{badge}</button>')

        content = CATEGORY_BUILDERS.get(cid, lambda t: '<div class="empty-state">No content.</div>')(tools_data)
        active = ' active' if cid == "risk_anomalies" else ''
        tab_panels.append(f'<div class="tab-panel{active}" id="panel-{cid}">{content}</div>')

    # Build summary cards
    total_tools = meta.get("tools_loaded", 0)
    total_failed = meta.get("tools_failed", 0)
    generated = meta.get("generated_at", "")[:19]

    # Count entities across categories
    total_entities = 0
    total_anomalies = 0
    for cat_id, cat_data in categories.items():
        for tool_key, tool_info in cat_data.get("tools", {}).items():
            d = tool_info.get("data", {})
            for count_key in ["total_flagged", "total_municipalities", "total_chains",
                              "total", "total_matches", "total_relationships",
                              "total_contracts"]:
                val = d.get(count_key)
                if isinstance(val, (int, float)):
                    total_entities += val
                    break

    summary_cards = f'''<div class="summary-row">
      <div class="summary-card"><div class="sc-icon">📊</div><div class="sc-value">{total_tools}</div><div class="sc-label">Tools Loaded</div></div>
      <div class="summary-card{" danger" if total_failed > 0 else ""}"><div class="sc-icon">⚠️</div><div class="sc-value">{total_failed}</div><div class="sc-label">Failed</div></div>
      <div class="summary-card"><div class="sc-icon">📁</div><div class="sc-value">{len(categories)}</div><div class="sc-label">Categories</div></div>
      <div class="summary-card"><div class="sc-icon">📋</div><div class="sc-value">{generated[:10]}</div><div class="sc-label">Generated</div></div>
    </div>'''

    # Assemble full HTML
    parts = []
    parts.append('<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append('<title>Analisa.pt — Unified Dashboard</title>')
    parts.append(f'''<style>
  :root {{
    --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --muted: #94a3b8;
    --border: #334155; --accent: #f59e0b; --danger: #ef4444; --success: #22c55e;
    --info: #3b82f6; --warning: #f59e0b;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }}
  .container {{ max-width: 1400px; margin: 0 auto; padding: 16px; }}

  .header {{ background: linear-gradient(135deg, #1e293b, #0f172a); padding: 24px; border-bottom: 2px solid var(--accent); border-radius: 12px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 24px; color: var(--accent); }}
  .header .sub {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}

  .summary-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
  @media (max-width: 800px) {{ .summary-row {{ grid-template-columns: repeat(2, 1fr); }} }}
  .summary-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px; text-align: center; }}
  .summary-card.danger {{ border-color: var(--danger); }}
  .sc-icon {{ font-size: 20px; }}
  .sc-value {{ font-size: 20px; font-weight: 700; color: var(--accent); margin: 4px 0; }}
  .sc-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}

  .tab-bar {{ display: flex; gap: 6px; margin-bottom: 16px; flex-wrap: wrap; background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 8px; }}
  .tab-btn {{ padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer; font-size: 13px; font-weight: 500; background: transparent; color: var(--muted); transition: all 0.2s; white-space: nowrap; }}
  .tab-btn:hover {{ color: var(--text); background: rgba(255,255,255,0.05); }}
  .tab-btn.active {{ background: var(--accent); color: #0f172a; font-weight: 600; }}
  .tab-badge {{ display: inline-block; padding: 0 5px; border-radius: 99px; font-size: 10px; font-weight: 600; margin-left: 4px; }}
  .tab-badge.loaded {{ background: rgba(245,158,11,0.2); color: var(--accent); }}
  .tab-badge.error {{ background: rgba(239,68,68,0.2); color: var(--danger); }}

  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}

  .info-bar {{ background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.2); border-radius: 8px; padding: 10px 16px; margin-bottom: 16px; font-size: 13px; color: var(--accent); }}
  .empty-state {{ text-align: center; padding: 48px; color: var(--muted); font-size: 14px; }}

  .metric-row {{ display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }}
  .metric {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 12px 20px; flex: 1; min-width: 140px; text-align: center; }}
  .metric-value {{ font-size: 18px; font-weight: 700; color: var(--accent); }}
  .metric-label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; margin-top: 2px; }}

  .scroll-table {{ max-height: 500px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border); margin-bottom: 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  th {{ text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--border); color: var(--muted); font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; background: var(--card); z-index: 1; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid rgba(51,65,85,0.5); }}
  tr:hover {{ background: rgba(255,255,255,0.03); }}
  .entity-name {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }}
  .nif {{ font-family: monospace; font-size: 11px; color: var(--muted); }}
  .value {{ text-align: right; font-weight: 600; font-family: monospace; }}
  .detail-text {{ color: var(--muted); font-size: 11px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .score-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; color: white; min-width: 32px; text-align: center; }}

  h4 {{ color: var(--text); font-size: 14px; margin: 16px 0 8px; }}

  .footer {{ text-align: center; color: var(--muted); font-size: 11px; margin-top: 24px; padding: 12px; border-top: 1px solid var(--border); }}
  </style>''')

    parts.append('</head><body><div class="container">')

    # Header
    parts.append(f'<div class="header"><h1>🛡️ Analisa.pt — Unified Dashboard</h1>')
    parts.append(f'<div class="sub">Generated {generated} — {total_tools} tools loaded across {len(categories)} categories</div></div>')

    # Summary cards
    parts.append(summary_cards)

    # Tab bar
    parts.append(f'<div class="tab-bar">{"".join(tab_buttons)}</div>')

    # Tab panels
    parts.extend(tab_panels)

    # Footer
    parts.append(f'<div class="footer">Analisa.pt Unified Dashboard — {total_tools} tools, {len(categories)} categories — Generated {generated}</div>')

    parts.append('</div>')

    # JavaScript for tab switching
    parts.append('''<script>
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});
</script></body></html>''')

    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Generate Unified Dashboard from consolidated.json")
    parser.add_argument("--in", dest="input_path", default=str(DEFAULT_INPUT), help="Input consolidated JSON")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="Output HTML path")
    parser.add_argument("--open", action="store_true", help="Open in browser after generation")
    args = parser.parse_args()

    input_path = Path(args.input_path)
    if not input_path.exists():
        print(f"ERROR: {input_path} not found. Run consolidate.py first.")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        consolidated = json.load(f)

    meta = consolidated.get("meta", {})
    print(f"  Loaded consolidated data: {meta.get('tools_loaded', 0)} tools, {len(consolidated.get('categories', {}))} categories")

    html = generate_dashboard(consolidated)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✅ Dashboard written to {out_path} ({len(html):,} bytes)")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    import sys
    main()
