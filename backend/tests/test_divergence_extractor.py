"""Tests for the divergence fact/entity extractor."""

from src.analysis.divergence.extractor import extract_article
from src.analysis.divergence.models import FactCategory


SAMPLE_PT_TEXT = (
    "O governo português anunciou ontem um pacote de 2.3 milhões de euros "
    "para a saúde. O primeiro-ministro António Costa afirmou que \"esta verba vai "
    "permitir contratar 500 enfermeiros\". A decisão foi tomada numa "
    "reunião em Lisboa com representantes da União Europeia."
)


def test_extract_entities_pt():
    result = extract_article(
        source_id="lusa",
        title="Governo anuncia 2.3M€ para a saúde",
        content_text=SAMPLE_PT_TEXT,
        language="pt",
    )
    assert result.source_id == "lusa"
    assert result.title == "Governo anuncia 2.3M€ para a saúde"
    assert result.word_count > 0
    assert len(result.facts) > 0

    # Check money entity
    money_facts = [f for f in result.facts if f.category == FactCategory.MONEY]
    assert len(money_facts) >= 1
    assert "euros" in money_facts[0].text or "milhões" in money_facts[0].text

    # Check person entity
    person_facts = [f for f in result.facts if f.category == FactCategory.PERSON]
    assert len(person_facts) >= 1

    # Check location
    loc_facts = [f for f in result.facts if f.category == FactCategory.LOCATION]
    assert len(loc_facts) >= 1

    # Check organization
    org_facts = [f for f in result.facts if f.category == FactCategory.ORGANIZATION]
    assert len(org_facts) >= 1

    # Check number
    num_facts = [f for f in result.facts if f.category == FactCategory.NUMBER]
    assert len(num_facts) >= 1


def test_extract_quotations_pt():
    result = extract_article(
        source_id="lusa",
        title="Test",
        content_text=SAMPLE_PT_TEXT,
        language="pt",
    )
    assert len(result.quotations) >= 1
    assert "enfermeiros" in result.quotations[0].text


def test_extract_empty_text():
    result = extract_article(
        source_id="test",
        title="Empty",
        content_text="",
        language="pt",
    )
    assert len(result.facts) == 0
    assert len(result.quotations) == 0
    # Title alone contributes 1 word
    assert result.word_count == 1


def test_extract_english_text():
    text = (
        'President Trump announced a $500 million aid package for Ukraine '
        'during a press conference in Washington. '
        'The UN Secretary General said "this is a historic moment for peace."'
    )
    result = extract_article(
        source_id="reuters",
        title="Trump announces $500M aid for Ukraine",
        content_text=text,
        language="en",
    )
    assert len(result.facts) > 0
    money = [f for f in result.facts if f.category == FactCategory.MONEY]
    assert len(money) >= 1
    assert len(result.quotations) >= 1


def test_extract_short_text():
    """Articles < 100 chars should still work."""
    result = extract_article(
        source_id="test",
        title="Short",
        content_text="Notícia curta sem detalhes.",
        language="pt",
    )
    assert result.word_count > 0
    assert isinstance(result.facts, list)
