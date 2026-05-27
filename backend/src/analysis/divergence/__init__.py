"""Narrative Divergence Analyzer — detects omission, framing shift, and selective quoting."""

from src.analysis.divergence.models import (
    Fact, FactCategory, Quotation, ExtractedArticle,
    DivergenceReport, OutletDivergenceSummary,
)
from src.analysis.divergence.extractor import extract_article
from src.analysis.divergence.comparator import (
    compare_articles, compute_omission_score, analyze_sentiment,
)
from src.analysis.divergence.reporter import (
    report_to_json, report_to_markdown, aggregate_summary,
)

__all__ = [
    "Fact", "FactCategory", "Quotation", "ExtractedArticle",
    "DivergenceReport", "OutletDivergenceSummary",
    "extract_article", "compare_articles", "compute_omission_score",
    "analyze_sentiment",
    "report_to_json", "report_to_markdown", "aggregate_summary",
]
