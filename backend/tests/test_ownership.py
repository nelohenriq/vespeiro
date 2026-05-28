from src.config.ownership import load_ownership, get_owner, get_group_outlets


def test_load_ownership():
    config = load_ownership()
    assert len(config.outlets) > 0
    assert any(o.type == "newspaper" for o in config.outlets)


def test_get_owner_found():
    outlet = get_owner("publico")
    assert outlet is not None
    assert outlet.owner == "Sonae"
    assert outlet.owner_group == "Grupo Sonae"


def test_get_owner_not_found():
    assert get_owner("nonexistent") is None


def test_lusa_ownership():
    outlet = get_owner("lusa")
    assert outlet is not None
    assert "Estado" in outlet.owner


def test_impresa_group_concentration():
    """Verify that SIC and Expresso share the same owner group."""
    sic = get_owner("sic_noticias")
    expresso = get_owner("expresso")
    assert sic is not None and expresso is not None
    assert sic.owner_group == expresso.owner_group == "Grupo Impresa"


def test_get_group_outlets():
    outlets = get_group_outlets("Global Media Group")
    ids = {o.id for o in outlets}
    assert "jn" in ids
    assert "dn" in ids
    assert "tsf" in ids


def test_all_outlets_have_ids():
    config = load_ownership()
    for outlet in config.outlets:
        assert outlet.id, f"Missing id for {outlet.name}"
        assert outlet.owner, f"Missing owner for {outlet.name}"
        assert outlet.type.value, f"Missing type for {outlet.name}"
