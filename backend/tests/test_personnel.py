"""Tests for the personnel network graph builder."""

import pytest
from src.analysis.personnel import (
    PersonnelNetworkBuilder,
    _clean_name,
    _slugify,
    _RE_NOMEIA_PARA,
    _RE_DESIGNA_COMO,
    _RE_NOMEACAO_DE,
)


class TestNameExtraction:
    """Test extraction of person names from DRE Portuguese administrative text."""

    def test_nomeia_para_pattern(self) -> None:
        text = (
            "Ao abrigo do disposto, nomeia Maria Silva para o cargo de "
            "vogal do conselho de administração da RTP, S.A."
        )
        matches = list(_RE_NOMEIA_PARA.finditer(text))
        assert len(matches) == 1
        assert "Maria Silva" in matches[0].group(1)

    def test_designa_como_pattern(self) -> None:
        text = (
            "Designa João Costa como diretor de informação da Lusa — "
            "Agência de Notícias de Portugal."
        )
        matches = list(_RE_DESIGNA_COMO.finditer(text))
        assert len(matches) == 1
        assert "João Costa" in matches[0].group(1)

    def test_nomeacao_de_fallback(self) -> None:
        text = "Foi publicada a nomeação de Ana Rodrigues para o cargo."
        matches = list(_RE_NOMEACAO_DE.finditer(text))
        assert len(matches) == 1
        assert "Ana Rodrigues" in matches[0].group(1)

    def test_multiple_appointments(self) -> None:
        text = (
            "Nomeia Carlos Santos para o cargo de presidente do conselho "
            "de administração da RTP. Nomeia Marta Oliveira para o cargo de vogal do "
            "conselho regulador da ERC."
        )
        matches = list(_RE_NOMEIA_PARA.finditer(text))
        assert len(matches) == 2

    def test_empty_text(self) -> None:
        assert len(list(_RE_NOMEIA_PARA.finditer(""))) == 0
        assert len(list(_RE_DESIGNA_COMO.finditer(""))) == 0
        assert len(list(_RE_NOMEACAO_DE.finditer(""))) == 0

    def test_no_match_text(self) -> None:
        text = "Relatório de atividades do primeiro semestre de 2026."
        assert len(list(_RE_NOMEIA_PARA.finditer(text))) == 0


class TestCleanName:
    def test_clean_basic(self) -> None:
        assert _clean_name("maria silva") == "Maria Silva"

    def test_clean_with_punctuation(self) -> None:
        assert _clean_name("João Costa.") == "João Costa"

    def test_clean_extra_spaces(self) -> None:
        assert _clean_name("  Ana   Rodrigues  ") == "Ana Rodrigues"


class TestSlugify:
    def test_simple(self) -> None:
        assert _slugify("Maria Silva") == "maria-silva"

    def test_with_accents(self) -> None:
        # The slugify function normalizes accents: ã → a
        assert _slugify("João Costa") == "joao-costa"

    def test_with_special_chars(self) -> None:
        assert _slugify("RTP, S.A.") == "rtp-s-a"


class TestPersonnelNetworkBuilder:
    """Test the network builder with synthetic data."""

    def test_extract_person_role_pairs_empty(self) -> None:
        builder = PersonnelNetworkBuilder()
        pairs = builder._extract_person_role_pairs("")
        assert pairs == []

    def test_extract_person_role_pairs_nomeia(self) -> None:
        builder = PersonnelNetworkBuilder()
        text = "Nomeia Pedro Alves para o cargo de vogal do conselho de administração da RTP."
        pairs = builder._extract_person_role_pairs(text)
        assert len(pairs) >= 1
        name, role = pairs[0]
        assert "Pedro Alves" in name
        assert "RTP" in role.upper()

    def test_extract_person_role_pairs_designa(self) -> None:
        builder = PersonnelNetworkBuilder()
        text = "Designa Rita Santos como diretora de comunicação da Lusa."
        pairs = builder._extract_person_role_pairs(text)
        assert len(pairs) >= 1
        name, role = pairs[0]
        assert "Rita Santos" in name

    def test_extract_single_name_excluded(self) -> None:
        """Single-word names should be excluded (likely false positives)."""
        builder = PersonnelNetworkBuilder()
        text = "Nomeia João para o cargo de vogal."
        pairs = builder._extract_person_role_pairs(text)
        # "João" has only 1 word — should be excluded
        for name, _role in pairs:
            assert len(name.split()) >= 2

    @pytest.mark.asyncio
    async def test_build_no_db(self) -> None:
        """Network builder returns empty graph without DB session."""
        builder = PersonnelNetworkBuilder(db_session=None)
        network = await builder.build()
        assert network.nodes == []
        assert network.edges == []
        assert network.total_people == 0
        assert network.total_appointments == 0
