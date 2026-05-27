"""Generate structured reports from divergence analysis results."""

import json
from datetime import datetime
from typing import Sequence
from src.analysis.divergence.models import (
    DivergenceReport, OutletDivergenceSummary,
)


def report_to_json(report: DivergenceReport) -> str:
    """Serialize a DivergenceReport to a pretty-printed JSON string."""

    def _serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, "value"):
            return obj.value
        return str(obj)

    return json.dumps(report.model_dump(), indent=2, default=_serializer)


def report_to_markdown(report: DivergenceReport) -> str:
    """Format a divergence report as human-readable Markdown."""
    lines: list[str] = []

    header_icon = _divergence_icon(report.overall_divergence_score)
    lines.append(
        f"{header_icon} DIVERGÊNCIA: {report.original_source_id} → "
        f"{report.portuguese_outlet_id}"
    )
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    if report.overall_divergence_score is not None:
        lines.append(
            f"📐 **Geral:** {report.overall_divergence_score:.0%}"
        )
        lines.append("")

    # Omission
    if report.fact_omission_score is not None:
        total_facts = len(report.omitted_facts) + len(report.preserved_facts)
        icon = "📝" if report.fact_omission_score > 0.3 else "📄"
        lines.append(
            f"{icon} **Omissão:** {report.fact_omission_score:.0%} "
            f"— {len(report.omitted_facts)}/{total_facts} factos omitidos"
        )
        if report.omitted_facts:
            omitted_texts = [f.text for f in report.omitted_facts[:5]]
            lines.append(f"   Perdido: {', '.join(omitted_texts)}")
        lines.append("")

    # Sentiment / Framing
    if report.sentiment_shift is not None:
        direction = "mais positivo" if report.sentiment_shift > 0 else "mais negativo"
        orig_s = (
            report.original_sentiment.get("sentiment", "?")
            if report.original_sentiment else "?"
        )
        pt_s = (
            report.portuguese_sentiment.get("sentiment", "?")
            if report.portuguese_sentiment else "?"
        )
        lines.append(
            f"🎭 **Framing:** Original {orig_s} → {pt_s} "
            f"({direction}, Δ={abs(report.sentiment_shift):.2f})"
        )
        lines.append("")

    # Quotes
    if report.quote_fidelity is not None:
        if report.quote_fidelity < 1.0:
            lines.append(
                f"💬 **Citações:** {report.quote_fidelity:.0%} preservadas"
            )
            for aq in report.altered_quotes[:3]:
                icon = "🔄" if aq.get("status") == "altered" else "❌"
                speaker = aq.get("speaker", "?")
                orig = aq["original"]
                lines.append(
                    f"   {icon} {speaker}: \"{orig[:60]}\u2026\""
                )
            lines.append("")

    # Headline
    if report.headline_divergence is not None and report.headline_divergence > 0.2:
        lines.append(
            f"📰 **Manchete:** {report.headline_divergence:.0%} divergente"
        )
        lines.append(f"   Original: _{report.headline_original}_")
        lines.append(f"   PT:       _{report.headline_portuguese}_")
        lines.append("")

    return "\n".join(lines)


def _divergence_icon(score: float | None) -> str:
    if score is None:
        return "⚪"
    if score < 0.2:
        return "🟢"
    elif score < 0.4:
        return "🟡"
    elif score < 0.6:
        return "🟠"
    elif score < 0.8:
        return "🔴"
    return "🟣"


def aggregate_summary(
    reports: Sequence[DivergenceReport],
    outlet_id: str,
    period_start: datetime,
    period_end: datetime,
) -> OutletDivergenceSummary:
    """Aggregate multiple reports into a per-outlet summary over a time window."""
    n = len(reports)

    if n == 0:
        return OutletDivergenceSummary(
            outlet_id=outlet_id,
            period_start=period_start,
            period_end=period_end,
            stories_analyzed=0,
            avg_omission=0.0,
            avg_sentiment_shift=0.0,
            avg_quote_fidelity=0.0,
            avg_headline_divergence=0.0,
            top_omitted_facts=[],
        )

    omissions = [
        r.fact_omission_score for r in reports
        if r.fact_omission_score is not None
    ]
    sentiment_shifts = [
        r.sentiment_shift for r in reports
        if r.sentiment_shift is not None
    ]
    quote_fidelities = [
        r.quote_fidelity for r in reports
        if r.quote_fidelity is not None
    ]
    headline_divs = [
        r.headline_divergence for r in reports
        if r.headline_divergence is not None
    ]

    # Collect top omitted facts across all reports
    fact_counter: dict[str, int] = {}
    for r in reports:
        for f in r.omitted_facts:
            fact_counter[f.text] = fact_counter.get(f.text, 0) + 1
    top_facts = sorted(fact_counter, key=fact_counter.get, reverse=True)[:10]

    return OutletDivergenceSummary(
        outlet_id=outlet_id,
        period_start=period_start,
        period_end=period_end,
        stories_analyzed=n,
        avg_omission=sum(omissions) / len(omissions) if omissions else 0.0,
        avg_sentiment_shift=(
            sum(sentiment_shifts) / len(sentiment_shifts)
            if sentiment_shifts else 0.0
        ),
        avg_quote_fidelity=(
            sum(quote_fidelities) / len(quote_fidelities)
            if quote_fidelities else 0.0
        ),
        avg_headline_divergence=(
            sum(headline_divs) / len(headline_divs)
            if headline_divs else 0.0
        ),
        top_omitted_facts=top_facts,
    )
