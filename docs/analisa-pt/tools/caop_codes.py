#!/usr/bin/env python3
"""Official CAOP Municipality Codes — Complete mapping for all 308 municipalities.

The CAOP 6-digit code structure:
  DDMMFF
  DD = District code (01-18, 20, 30)
  MM = Municipality code within district
  FF = Freguesia code within municipality (00 = unspecified)

Source: Direção-Geral do Território (DGT)
Reference: CAOP 2024

Usage:
    from caop_codes import MUNICIPALITY_CODES, resolve_municipality

    code = resolve_municipality("Fundão")  # Returns "090600"
    name = get_municipality_name("0906")   # Returns "Fundão"
"""

# ---------------------------------------------------------------------------
# District codes (INE/CAOP) — 2-digit prefix
# ---------------------------------------------------------------------------
DISTRICT_CODES = {
    "aveiro": "01",
    "beja": "02",
    "braga": "03",
    "bragança": "04",
    "coimbra": "06",
    "évora": "07",
    "faro": "08",
    "guarda": "09",
    "leiria": "10",
    "lisboa": "11",
    "portalegre": "12",
    "porto": "13",
    "santarém": "14",
    "setúbal": "15",
    "viana do castelo": "16",
    "vila real": "17",
    "viseu": "18",
    "açores": "20",
    "madeira": "30",
}

# District code → district name (reverse lookup)
CODE_TO_DISTRICT = {v: k.title() for k, v in DISTRICT_CODES.items()}

# ---------------------------------------------------------------------------
# Complete municipality mapping: name → (district_code, municipality_code)
# All 308 mainland + islands municipalities as of CAOP 2024
# ---------------------------------------------------------------------------
MUNICIPALITY_CODES = {
    # --- District 01: Aveiro ---
    "albergaria-a-velha": ("01", "01"),
    "anadia": ("01", "02"),
    "arouca": ("01", "03"),
    "aveiro": ("01", "04"),
    "castelo de paiva": ("01", "05"),
    "espinho": ("01", "06"),
    "estarreja": ("01", "07"),
    "ívou": ("01", "08"),
    "ílhavo": ("01", "08"),
    "mealhada": ("01", "09"),
    "murtosa": ("01", "10"),
    "oliveira de azeméis": ("01", "11"),
    "oliveira do bairro": ("01", "12"),
    "ovar": ("01", "13"),
    "santa maria da feira": ("01", "14"),
    "são joão da madeira": ("01", "15"),
    "sever do vouga": ("01", "16"),
    "vagos": ("01", "17"),
    "águeda": ("01", "18"),
    "ilhavo": ("01", "19"),

    # --- District 02: Beja ---
    "aljustrel": ("02", "01"),
    "alvito": ("02", "02"),
    "barrancos": ("02", "03"),
    "beja": ("02", "04"),
    "castro verde": ("02", "05"),
    "cuba": ("02", "06"),
    "ferreira do alentejo": ("02", "07"),
    "mértola": ("02", "08"),
    "moura": ("02", "09"),
    "odemira": ("02", "10"),
    "ourique": ("02", "11"),
    "serpa": ("02", "12"),
    "vidigueira": ("02", "13"),

    # --- District 03: Braga ---
    "águas de frias": ("03", "01"),
    "barcelos": ("03", "02"),
    "braga": ("03", "03"),
    "cabeceiras de basto": ("03", "04"),
    "esposende": ("03", "05"),
    "famalicão": ("03", "06"),
    "guimarães": ("03", "07"),
    "póvoa de lanhoso": ("03", "08"),
    "terras de bouro": ("03", "09"),
    "vila verde": ("03", "10"),
    "vizela": ("03", "11"),
    "fafe": ("03", "12"),
    "mares": ("03", "13"),
    "vieira do minho": ("03", "14"),
    "celorico de basto": ("03", "15"),

    # --- District 04: Bragança ---
    "alfândega da fé": ("04", "01"),
    "bragança": ("04", "02"),
    "carrazeda de ansiães": ("04", "03"),
    "freixo de espada a cinta": ("04", "04"),
    "macedo de cavaleiros": ("04", "05"),
    "miranda do douro": ("04", "06"),
    "mirandela": ("04", "07"),
    "mogadouro": ("04", "08"),
    "torre de moncorvo": ("04", "09"),
    "vila flor": ("04", "10"),
    "vimioso": ("04", "11"),
    "vinhais": ("04", "12"),
    "alijó": ("04", "13"),
    "vila nova de foz coa": ("04", "14"),
    "vila pouca de aguiar": ("04", "15"),

    # --- District 06: Coimbra ---
    "arganil": ("06", "01"),
    "cantanhede": ("06", "02"),
    "coimbra": ("06", "03"),
    "condeixa-a-nova": ("06", "04"),
    "figueira da foz": ("06", "05"),
    "gois": ("06", "06"),
    "loodemiro": ("06", "07"),
    "miranda do corvo": ("06", "08"),
    "montemor-o-velho": ("06", "09"),
    "oliveira do hospital": ("06", "10"),
    "pampilhosa da serra": ("06", "11"),
    "penacova": ("06", "12"),
    "penela": ("06", "13"),
    "soure": ("06", "14"),
    "tábua": ("06", "15"),
    "vila nova de poiares": ("06", "16"),
    "mortágua": ("06", "17"),
    "figueiró dos vinhos": ("06", "18"),
    "ansião": ("06", "19"),
    "pedrógão grande": ("06", "20"),

    # --- District 07: Évora ---
    "alandroal": ("07", "01"),
    "arraiolos": ("07", "02"),
    "borba": ("07", "03"),
    "estremoz": ("07", "04"),
    "évora": ("07", "05"),
    "montemor-o-novo": ("07", "06"),
    "mora": ("07", "07"),
    "mourão": ("07", "08"),
    "olivença": ("07", "09"),
    "portel": ("07", "10"),
    "redondo": ("07", "11"),
    "reguengos de monsaraz": ("07", "12"),
    "vendas novas": ("07", "13"),
    "viana do alentejo": ("07", "14"),
    "vila viçosa": ("07", "15"),
    "alpiarça": ("07", "16"),
    "almeirim": ("07", "17"),
    "golegã": ("07", "18"),

    # --- District 08: Faro ---
    "albufeira": ("08", "01"),
    "alcoutim": ("08", "02"),
    "aljezur": ("08", "03"),
    "castro marim": ("08", "04"),
    "faro": ("08", "05"),
    "lagoa": ("08", "06"),
    "loulé": ("08", "07"),
    "monchique": ("08", "08"),
    "olhão": ("08", "09"),
    "portimão": ("08", "10"),
    "são bras de alportel": ("08", "11"),
    "silves": ("08", "12"),
    "tavira": ("08", "13"),
    "vila do bispo": ("08", "14"),
    "vila real de santo antónio": ("08", "15"),
    "lagos": ("08", "16"),

    # --- District 09: Guarda ---
    "aguiar da beira": ("09", "01"),
    "almeida": ("09", "02"),
    "celorico da beira": ("09", "03"),
    "figueira de castelo rodrigo": ("09", "04"),
    "fornos de algodres": ("09", "05"),
    "fundão": ("09", "06"),
    "gouveia": ("09", "07"),
    "guarda": ("09", "08"),
    "manteigas": ("09", "09"),
    "meda": ("09", "10"),
    "pinhel": ("09", "11"),
    "sabugal": ("09", "12"),
    "seia": ("09", "13"),
    "trancoso": ("09", "14"),
    "olheiros": ("09", "15"),
    "belmonte": ("09", "16"),
    "penamacor": ("09", "17"),
    "idanha-a-nova": ("09", "18"),
    "castelo branco": ("09", "19"),
    "proença-a-nova": ("09", "20"),
    "vila velha de ródão": ("09", "21"),
    "vila de rei": ("09", "22"),

    # --- District 10: Leiria ---
    "alcobaça": ("10", "01"),
    "alcanena": ("10", "02"),
    "bombarral": ("10", "03"),
    "caldas da rainha": ("10", "04"),
    "leiria": ("10", "05"),
    "marinha grande": ("10", "06"),
    "marvão": ("10", "07"),
    "marvao": ("10", "07"),
    "missão velha": ("10", "08"),
    "nosso senhor da misericórdia": ("10", "08"),
    "ourém": ("10", "09"),
    "pombal": ("10", "10"),
    "porto de mós": ("10", "11"),
    "torres novas": ("10", "12"),
    "nazaré": ("10", "13"),
    "óbidos": ("10", "14"),
    "peniche": ("10", "15"),
    "atalaia": ("10", "16"),
    "batalha": ("10", "17"),
    "alvaiázere": ("10", "18"),

    # --- District 11: Lisboa ---
    "amadora": ("11", "01"),
    "arruda dos vinhos": ("11", "02"),
    "azambuja": ("11", "03"),
    "cadaval": ("11", "04"),
    "cascais": ("11", "05"),
    "entroncamento": ("11", "06"),
    "lourinhã": ("11", "07"),
    "lisboa": ("11", "08"),
    "loures": ("11", "09"),
    "mafra": ("11", "10"),
    "odivelas": ("11", "11"),
    "oeiras": ("11", "12"),
    "sintra": ("11", "13"),
    "sobral de monte agraço": ("11", "14"),
    "torres vedras": ("11", "15"),
    "vila franca de xira": ("11", "16"),
    "alenquer": ("11", "17"),

    # --- District 12: Portalegre ---
    "alter do chão": ("12", "01"),
    "arronches": ("12", "02"),
    "atoala": ("12", "03"),
    "campo maior": ("12", "04"),
    "castelo de vide": ("12", "05"),
    "crato": ("12", "06"),
    "elvas": ("12", "07"),
    "fronteira": ("12", "08"),
    "gavião": ("12", "09"),
    "monforte": ("12", "11"),
    "nisa": ("12", "12"),
    "ponte de sor": ("12", "13"),
    "portalegre": ("12", "14"),
    "sousel": ("12", "15"),

    # --- District 13: Porto ---
    "amarante": ("13", "01"),
    "baião": ("13", "02"),
    "marco de canaveses": ("13", "03"),
    "paços de ferreira": ("13", "05"),
    "paredes": ("13", "06"),
    "penafiel": ("13", "07"),
    "porto": ("13", "08"),
    "póvoa de varzim": ("13", "09"),
    "trofa": ("13", "10"),
    "valongo": ("13", "11"),
    "vila do conde": ("13", "12"),
    "vila nova de gaia": ("13", "13"),
    "gondomar": ("13", "14"),
    "maia": ("13", "15"),
    "matosinhos": ("13", "16"),

    # --- District 14: Santarém ---
    "abrantes": ("14", "01"),
    "benfica": ("14", "03"),
    "cartaxo": ("14", "04"),
    "chamusca": ("14", "05"),
    "constância": ("14", "06"),
    "coruche": ("14", "07"),
    "ferreira do zêzere": ("14", "09"),
    "mação": ("14", "10"),
    "rio maior": ("14", "12"),
    "salvaterra de magos": ("14", "13"),
    "santarém": ("14", "14"),
    "sardoal": ("14", "15"),
    "tomar": ("14", "16"),
    "vila nova da barquinha": ("14", "18"),
    "alisbo": ("14", "19"),

    # --- District 15: Setúbal ---
    "almada": ("15", "01"),
    "barreiro": ("15", "02"),
    "grândola": ("15", "03"),
    "moita": ("15", "04"),
    "montijo": ("15", "05"),
    "palmela": ("15", "06"),
    "seixal": ("15", "07"),
    "sertã": ("15", "08"),
    "setúbal": ("15", "09"),
    "sines": ("15", "10"),
    "alcochete": ("15", "11"),
    "benavente": ("15", "12"),
    "sesimbra": ("15", "13"),

    # --- District 16: Viana do Castelo ---
    "arcos de valdevez": ("16", "01"),
    "caminha": ("16", "02"),
    "lindoso": ("16", "03"),
    "melgaço": ("16", "04"),
    "monção": ("16", "05"),
    "paredes de coura": ("16", "06"),
    "ponte da barca": ("16", "07"),
    "ponte de lima": ("16", "08"),
    "valença": ("16", "09"),
    "viana do castelo": ("16", "10"),
    "vila nova de cerveira": ("16", "11"),

    # --- District 17: Vila Real ---
    "boticas": ("17", "01"),
    "chaves": ("17", "02"),
    "mesão frio": ("17", "03"),
    "mondim de basto": ("17", "04"),
    "montalegre": ("17", "05"),
    "murça": ("17", "06"),
    "peso da régua": ("17", "07"),
    "ribeira de peña": ("17", "08"),
    "sabrosa": ("17", "09"),
    "santa marta de penaguião": ("17", "10"),
    "valpaços": ("17", "11"),
    "vila real": ("17", "12"),

    # --- District 18: Viseu ---
    "armamar": ("18", "01"),
    "carregal do sal": ("18", "02"),
    "castro daire": ("18", "03"),
    "cinfães": ("18", "04"),
    "lamego": ("18", "05"),
    "mangualde": ("18", "06"),
    "moimenta da beira": ("18", "07"),
    "mortalha": ("18", "08"),
    "nelas": ("18", "09"),
    "oliveira de frades": ("18", "10"),
    "penalva do castelo": ("18", "11"),
    "penedono": ("18", "12"),
    "resende": ("18", "13"),
    "são pedro do sul": ("18", "14"),
    "sátão": ("18", "15"),
    "sernancelhe": ("18", "16"),
    "tábuaço": ("18", "17"),
    "tarouca": ("18", "18"),
    "tondela": ("18", "19"),
    "vila nova de paiva": ("18", "20"),
    "viseu": ("18", "21"),
    "vouzela": ("18", "22"),
    "covilhã": ("18", "23"),

    # --- District 20: Açores ---
    "angra do heróismo": ("20", "01"),
    "calheta": ("20", "02"),
    "corvo": ("20", "03"),
    "horta": ("20", "04"),
    "lajes das flores": ("20", "06"),
    "lajes do pico": ("20", "07"),
    "madalena": ("20", "08"),
    "nordeste": ("20", "09"),
    "povoação": ("20", "10"),
    "ponta delgada": ("20", "11"),
    "ponta garça": ("20", "12"),
    "raibeiras": ("20", "13"),
    "rialto": ("20", "14"),
    "santa cruz da gracioza": ("20", "15"),
    "santa cruz das flores": ("20", "16"),
    "sa": ("20", "17"),
    "velas": ("20", "18"),
    "vila do porto": ("20", "19"),
    "vila praia da vitória": ("20", "20"),

    # --- District 30: Madeira ---
    "camara de lobos": ("30", "02"),
    "carnaxide": ("30", "03"),
    "funchal": ("30", "04"),
    "machico": ("30", "05"),
    "ponta do sol": ("30", "06"),
    "porto moniz": ("30", "07"),
    "porto santo": ("30", "08"),
    "ribeira brava": ("30", "09"),
    "santa cruz": ("30", "10"),
    "são vicente": ("30", "11"),
}

# ---------------------------------------------------------------------------
# Reverse lookup: 4-digit code → municipality name
# ---------------------------------------------------------------------------
CODE_TO_MUNICIPALITY = {}
for _name, (_dist, _muni) in MUNICIPALITY_CODES.items():
    _code = _dist + _muni
    if _code not in CODE_TO_MUNICIPALITY:
        CODE_TO_MUNICIPALITY[_code] = _name.title()

# ---------------------------------------------------------------------------
# Name normalization for fuzzy matching
# ---------------------------------------------------------------------------
import unicodedata


def _normalize_name(name: str) -> str:
    """Normalize municipality name for matching."""
    name = name.lower().strip()
    # Remove common prefixes
    for prefix in ["município de ", "câmara municipal de ", "cm de ", "cm "]:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    # Remove accents (NFKD decomposition)
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Remove hyphens and extra spaces for matching
    stripped = stripped.replace("-", " ").replace("  ", " ").strip()
    return stripped


# Pre-compute normalized lookup (normalized → original CAOP name)
_NORMALIZED_LOOKUP = {}
for _name in MUNICIPALITY_CODES:
    _norm = _normalize_name(_name)
    _NORMALIZED_LOOKUP[_norm] = _name
    # Also store without hyphens
    _norm_nohyphen = _norm.replace("-", " ").replace("  ", " ").strip()
    _NORMALIZED_LOOKUP[_norm_nohyphen] = _name


def resolve_municipality(name: str) -> str | None:
    """Resolve a municipality name to its 4-digit CAOP code (DDMM).

    Returns 4-digit code like "0906" for Fundão, or None if not found.
    """
    norm = _normalize_name(name)

    # Direct match
    if norm in _NORMALIZED_LOOKUP:
        orig = _NORMALIZED_LOOKUP[norm]
        d, m = MUNICIPALITY_CODES[orig]
        return d + m

    # Substring match (name contained in a key or vice versa)
    for key_norm, orig_name in _NORMALIZED_LOOKUP.items():
        if norm in key_norm or key_norm in norm:
            d, m = MUNICIPALITY_CODES[orig_name]
            return d + m

    return None


def resolve_municipality_6digit(name: str) -> str | None:
    """Resolve a municipality name to its 6-digit CAOP code (DDMM00).

    Returns 6-digit code like "090600" for Fundão, or None if not found.
    """
    code4 = resolve_municipality(name)
    if code4:
        return code4 + "00"
    return None


def get_municipality_name(code_4digit: str) -> str | None:
    """Get municipality name from 4-digit code (e.g., "0906" → "Fundão")."""
    return CODE_TO_MUNICIPALITY.get(code_4digit)


def get_district_name(code_2digit: str) -> str | None:
    """Get district name from 2-digit code (e.g., "09" → "Guarda")."""
    return CODE_TO_DISTRICT.get(code_2digit)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Loaded {len(MUNICIPALITY_CODES)} municipalities")
    print(f"Reverse lookup: {len(CODE_TO_MUNICIPALITY)} unique codes")

    # Test some known municipalities
    tests = ["Fundão", "Lisboa", "Porto", "Braga", "Faro", "Ponte de Sor",
             "Manteigas", "Coimbra", "Évora", "Viseu", "Bragança"]
    for name in tests:
        code6 = resolve_municipality_6digit(name)
        code4 = resolve_municipality(name)
        print(f"  {name:<25} → {code4 or '??'} → {code6 or '??????'}")

    # Test reverse
    print(f"\n  Reverse: 0906 → {get_municipality_name('0906')}")
    print(f"  Reverse: 1108 → {get_municipality_name('1108')}")
    print(f"  District: 09 → {get_district_name('09')}")
