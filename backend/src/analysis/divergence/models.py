"""Data models for narrative divergence analysis."""

from enum import Enum
from pydantic import BaseModel
from datetime import datetime


class FactCategory(str, Enum):
    MONEY = "money"
    PERCENTAGE = "pct"
    DATE = "date"
    PERSON = "person"
    LOCATION = "location"
    ORGANIZATION = "org"
    NUMBER = "number"


class Fact(BaseModel):
    text: str
    category: FactCategory
    span_start: int
    span_end: int


class Quotation(BaseModel):
    speaker: str | None
    text: str
    span_start: int
    span_end: int


class ExtractedArticle(BaseModel):
    source_id: str
    title: str
    content_text: str
    language: str
    facts: list[Fact]
    quotations: list[Quotation]
    sentences: list[str]
    word_count: int


class DivergenceReport(BaseModel):
    """Full divergence report for one source → outlet pair."""

    story_cluster_id: str
    original_source_id: str
    portuguese_outlet_id: str
    analyzed_at: datetime

    overall_divergence_score: float | None
    fact_omission_score: float | None
    sentiment_shift: float | None
    quote_fidelity: float | None
    headline_divergence: float | None

    omitted_facts: list[Fact]
    preserved_facts: list[Fact]
    altered_quotes: list[dict]
    headline_original: str
    headline_portuguese: str
    original_sentiment: dict | None
    portuguese_sentiment: dict | None


class OutletDivergenceSummary(BaseModel):
    """Aggregated metrics per outlet over a time window."""

    outlet_id: str
    period_start: datetime
    period_end: datetime
    stories_analyzed: int
    avg_omission: float
    avg_sentiment_shift: float
    avg_quote_fidelity: float
    avg_headline_divergence: float
    top_omitted_facts: list[str]
