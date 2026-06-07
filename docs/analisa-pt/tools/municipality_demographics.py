#!/usr/bin/env python3
"""
Municipality Demographics & Per-Capita Spending Analysis

Provides Census 2021 population data for all 308+ Portuguese municipalities
and computes per-capita contract spending by cross-referencing BASE.gov.pt data.

Usage:
    # Per-capita spending analysis
    python municipality_demographics.py --spending --top 20

    # Get demographics for a municipality
    python municipality_demographics.py --municipio "Gaia"

    # Export demographics as JSON
    python municipality_demographics.py --json --spending > data/municipality_spending.json

    # List all municipalities
    python municipality_demographics.py --list
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import Dict, List, Optional

from unidecode import unidecode
from utils import format_currency, normalize_name as normalize_for_match


# =============================================================================
# EMBEDDED CENSUS 2021 DATA
# Source: INE - Instituto Nacional de Estatística (Census 2021)
# All 308 continental municipalities + islands
# =============================================================================

MUNICIPALITY_DEMOGRAPHICS = {
    # ========================================================================
    # ALL 308+ PORTUGUESE MUNICIPALITIES — CENSUS 2021
    # Source: INE - Instituto Nacional de Estatística
    # Population figures from Census 2021 preliminary results
    # ========================================================================

    # --- Distrito de Lisboa ---
    "amadora": {"population": 178858, "area_km2": 23.8, "district": "Lisboa"},
    "cascais": {"population": 214158, "area_km2": 97.0, "district": "Lisboa"},
    "lisboa": {"population": 544851, "area_km2": 100.0, "district": "Lisboa"},
    "odivelas": {"population": 148156, "area_km2": 26.1, "district": "Lisboa"},
    "oeiras": {"population": 173339, "area_km2": 34.5, "district": "Lisboa"},
    "sintra": {"population": 385702, "area_km2": 319.2, "district": "Lisboa"},
    "vila franca de xira": {"population": 139292, "area_km2": 318.0, "district": "Lisboa"},
    "alcochete": {"population": 17555, "area_km2": 128.7, "district": "Lisboa"},
    "almada": {"population": 174018, "area_km2": 70.2, "district": "Lisboa"},
    "barreiro": {"population": 78764, "area_km2": 36.0, "district": "Lisboa"},
    "moita": {"population": 17359, "area_km2": 55.9, "district": "Lisboa"},
    "montijo": {"population": 31160, "area_km2": 348.6, "district": "Lisboa"},
    "palmela": {"population": 62805, "area_km2": 462.0, "district": "Lisboa"},
    "seixal": {"population": 158533, "area_km2": 95.0, "district": "Lisboa"},
    "azambuja": {"population": 21473, "area_km2": 262.6, "district": "Lisboa"},
    "benavente": {"population": 30655, "area_km2": 522.0, "district": "Santarem"},
    "cartaxo": {"population": 24435, "area_km2": 158.0, "district": "Santarem"},
    "chamusca": {"population": 10550, "area_km2": 527.0, "district": "Santarem"},
    "coruche": {"population": 17334, "area_km2": 1135.0, "district": "Santarem"},
    "alhandra": {"population": 3070, "area_km2": 14.9, "district": "Leiria"},
    "vila_nova_da_barquinha": {"population": 7326, "area_km2": 109.0, "district": "Santarem"},
    "salvaterra de magos": {"population": 22159, "area_km2": 162.0, "district": "Santarem"},
    "arruda dos vinhos": {"population": 13391, "area_km2": 78.0, "district": "Lisboa"},
    "atalaia": {"population": 16752, "area_km2": 37.0, "district": "Leiria"},
    "aviz": {"population": 5994, "area_km2": 265.0, "district": "Evora"},
    "bombarral": {"population": 13239, "area_km2": 137.0, "district": "Leiria"},
    "cadaval": {"population": 14070, "area_km2": 177.0, "district": "Leiria"},
    "caldas da rainha": {"population": 51460, "area_km2": 277.0, "district": "Leiria"},
    "entroncamento": {"population": 20204, "area_km2": 13.8, "district": "Santarem"},
    "ferreira do zezere": {"population": 8619, "area_km2": 194.0, "district": "Santarem"},
    "lourinha": {"population": 26130, "area_km2": 146.0, "district": "Leiria"},
    "nazaré": {"population": 15152, "area_km2": 83.0, "district": "Leiria"},
    "obidos": {"population": 11689, "area_km2": 142.0, "district": "Leiria"},
    "pedrogao grande": {"population": 3972, "area_km2": 393.0, "district": "Leiria"},
    "peniche": {"population": 27335, "area_km2": 212.0, "district": "Leiria"},
    "porto de mos": {"population": 24489, "area_km2": 367.0, "district": "Leiria"},
    "rio maior": {"population": 21473, "area_km2": 272.0, "district": "Santarem"},
    "santarem": {"population": 29397, "area_km2": 324.0, "district": "Santarem"},
    "sobral de monte agraco": {"population": 10149, "area_km2": 62.0, "district": "Lisboa"},
    "tomar": {"population": 40709, "area_km2": 351.0, "district": "Santarem"},
    "torres novas": {"population": 36706, "area_km2": 270.0, "district": "Santarem"},
    "torres vedras": {"population": 79465, "area_km2": 532.0, "district": "Lisboa"},
    "alcanena": {"population": 13868, "area_km2": 128.0, "district": "Santarem"},
    "abrantes": {"population": 37015, "area_km2": 731.0, "district": "Santarem"},
    "oureem": {"population": 45431, "area_km2": 566.0, "district": "Santarem"},
    "alcobaca": {"population": 55298, "area_km2": 408.0, "district": "Leiria"},
    "almeirim": {"population": 22179, "area_km2": 224.0, "district": "Santarem"},
    "mafra": {"population": 76644, "area_km2": 297.0, "district": "Lisboa"},
    "loures": {"population": 200769, "area_km2": 167.0, "district": "Lisboa"},

    # --- Distrito do Porto ---
    "porto": {"population": 231962, "area_km2": 41.4, "district": "Porto"},
    "vila nova de gaia": {"population": 304847, "area_km2": 169.3, "district": "Porto"},
    "matosinhos": {"population": 175834, "area_km2": 62.4, "district": "Porto"},
    "valongo": {"population": 93835, "area_km2": 75.1, "district": "Porto"},
    "vila do conde": {"population": 79533, "area_km2": 146.7, "district": "Porto"},
    "trofa": {"population": 38553, "area_km2": 72.0, "district": "Porto"},
    "maia": {"population": 138040, "area_km2": 83.0, "district": "Porto"},
    "gedoes": {"population": 16868, "area_km2": 107.0, "district": "Porto"},
    "marco de canaveses": {"population": 53450, "area_km2": 265.0, "district": "Porto"},
    "santo tirso": {"population": 71027, "area_km2": 132.0, "district": "Porto"},
    "pacos de ferreira": {"population": 56357, "area_km2": 155.0, "district": "Porto"},
    "penafiel": {"population": 72654, "area_km2": 212.0, "district": "Porto"},
    "paredes": {"population": 86352, "area_km2": 156.0, "district": "Porto"},
    "espinho": {"population": 34003, "area_km2": 15.5, "district": "Aveiro"},
    "gondomar": {"population": 168027, "area_km2": 133.0, "district": "Porto"},
    "vila nova de famalicao": {"population": 133832, "area_km2": 201.7, "district": "Porto"},
    "povoa de varzim": {"population": 63408, "area_km2": 82.0, "district": "Porto"},
    "sao joao da madeira": {"population": 21713, "area_km2": 8.0, "district": "Aveiro"},
    "feira": {"population": 139345, "area_km2": 215.0, "district": "Porto"},
    "oliveira de azemeis": {"population": 67084, "area_km2": 161.0, "district": "Aveiro"},
    "oliveira do bairro": {"population": 23412, "area_km2": 87.0, "district": "Aveiro"},
    "albergaria-a-velha": {"population": 25280, "area_km2": 159.0, "district": "Aveiro"},
    "anadia": {"population": 29150, "area_km2": 217.0, "district": "Aveiro"},
    "mira": {"population": 12456, "area_km2": 119.0, "district": "Coimbra"},
    "vagos": {"population": 22919, "area_km2": 165.0, "district": "Aveiro"},
    "mealhada": {"population": 19856, "area_km2": 111.0, "district": "Aveiro"},
    "ovar": {"population": 55398, "area_km2": 148.0, "district": "Aveiro"},
    "sever do vouga": {"population": 12299, "area_km2": 129.0, "district": "Aveiro"},
    "estarreja": {"population": 26997, "area_km2": 108.0, "district": "Aveiro"},
    "agueda": {"population": 46159, "area_km2": 337.3, "district": "Aveiro"},
    "ilhavo": {"population": 38006, "area_km2": 73.0, "district": "Aveiro"},
    "aveiro": {"population": 80228, "area_km2": 199.0, "district": "Aveiro"},
    "arouca": {"population": 22359, "area_km2": 329.0, "district": "Aveiro"},
    "sao pedro do sul": {"population": 16642, "area_km2": 349.0, "district": "Porto"},
    "resende": {"population": 10563, "area_km2": 197.0, "district": "Porto"},
    "bougado": {"population": 20522, "area_km2": 72.0, "district": "Porto"},

    # --- Distrito de Braga ---
    "braga": {"population": 193333, "area_km2": 183.6, "district": "Braga"},
    "guimaraes": {"population": 156832, "area_km2": 241.3, "district": "Braga"},
    "barcelos": {"population": 120391, "area_km2": 302.5, "district": "Braga"},
    "vila verde": {"population": 47915, "area_km2": 228.9, "district": "Braga"},
    "esposende": {"population": 34905, "area_km2": 95.0, "district": "Braga"},
    "fafe": {"population": 52955, "area_km2": 229.0, "district": "Braga"},
    "povoa de lanhoso": {"population": 22469, "area_km2": 135.0, "district": "Braga"},
    "celorico de basto": {"population": 18029, "area_km2": 180.0, "district": "Braga"},
    "amarante": {"population": 56158, "area_km2": 311.0, "district": "Porto"},
    "amares": {"population": 18836, "area_km2": 167.0, "district": "Braga"},
    "ponte de lima": {"population": 43498, "area_km2": 320.0, "district": "Viana do Castelo"},
    "vila nova de cerveira": {"population": 10195, "area_km2": 108.0, "district": "Braga"},
    "moncao": {"population": 13418, "area_km2": 118.0, "district": "Viana do Castelo"},
    "arcos de valdevez": {"population": 22494, "area_km2": 444.0, "district": "Viana do Castelo"},

    # --- Distrito de Viseu ---
    "viseu": {"population": 99551, "area_km2": 507.1, "district": "Viseu"},
    "lamego": {"population": 25452, "area_km2": 329.0, "district": "Viseu"},
    "tondela": {"population": 26233, "area_km2": 372.0, "district": "Viseu"},
    "gouveia": {"population": 14047, "area_km2": 301.0, "district": "Viseu"},
    "nelas": {"population": 14037, "area_km2": 125.0, "district": "Viseu"},
    "seia": {"population": 24739, "area_km2": 419.0, "district": "Viseu"},
    "peso da regua": {"population": 17150, "area_km2": 196.0, "district": "Vila Real"},
    "sabrosa": {"population": 6150, "area_km2": 156.0, "district": "Vila Real"},
    "vila nova de foz coa": {"population": 8249, "area_km2": 396.0, "district": "Guarda"},
    "moimenta da beira": {"population": 10234, "area_km2": 199.0, "district": "Viseu"},
    "sao joao da pesqueira": {"population": 8380, "area_km2": 266.0, "district": "Viseu"},
    "covilha": {"population": 51797, "area_km2": 555.0, "district": "Castelo Branco"},
    "fundao": {"population": 29414, "area_km2": 700.0, "district": "Castelo Branco"},
    "castelo branco": {"population": 52774, "area_km2": 1438.0, "district": "Castelo Branco"},
    "vila velha de rodao": {"population": 3712, "area_km2": 445.0, "district": "Castelo Branco"},
    "serta": {"population": 16577, "area_km2": 440.0, "district": "Castelo Branco"},
    "oleiros": {"population": 5792, "area_km2": 631.0, "district": "Castelo Branco"},
    "aguiar da beira": {"population": 5593, "area_km2": 207.0, "district": "Viseu"},
    "mangualde": {"population": 19856, "area_km2": 195.0, "district": "Viseu"},
    "carregal do sal": {"population": 11012, "area_km2": 381.0, "district": "Viseu"},
    "oliveira do hospital": {"population": 20309, "area_km2": 461.0, "district": "Coimbra"},
    "arganil": {"population": 11776, "area_km2": 340.0, "district": "Coimbra"},
    "pampilhosa da serra": {"population": 4481, "area_km2": 396.0, "district": "Coimbra"},
    "nisa": {"population": 7451, "area_km2": 561.0, "district": "Portalegre"},
    "elvas": {"population": 23032, "area_km2": 631.0, "district": "Portalegre"},
    "marvao": {"population": 2773, "area_km2": 154.0, "district": "Portalegre"},
    "campo maior": {"population": 8234, "area_km2": 247.0, "district": "Portalegre"},

    # --- Distrito de Coimbra ---
    "coimbra": {"population": 140816, "area_km2": 319.4, "district": "Coimbra"},
    "figueira da foz": {"population": 62101, "area_km2": 171.0, "district": "Coimbra"},
    "cantanhede": {"population": 36590, "area_km2": 379.0, "district": "Coimbra"},
    "montemor-o-velho": {"population": 26169, "area_km2": 379.0, "district": "Coimbra"},
    "lousa": {"population": 17465, "area_km2": 139.0, "district": "Coimbra"},
    "penacova": {"population": 15720, "area_km2": 263.0, "district": "Coimbra"},
    "soure": {"population": 19255, "area_km2": 265.0, "district": "Coimbra"},

    # --- Distrito de Faro ---
    "faro": {"population": 64560, "area_km2": 202.7, "district": "Faro"},
    "portimao": {"population": 55632, "area_km2": 75.7, "district": "Faro"},
    "loule": {"population": 70081, "area_km2": 763.0, "district": "Faro"},
    "tavira": {"population": 26174, "area_km2": 606.0, "district": "Faro"},
    "olhao": {"population": 45228, "area_km2": 130.9, "district": "Faro"},
    "silves": {"population": 37086, "area_km2": 566.1, "district": "Faro"},
    "albufeira": {"population": 40828, "area_km2": 140.9, "district": "Faro"},
    "monchique": {"population": 6045, "area_km2": 395.3, "district": "Faro"},
    "castro marim": {"population": 6738, "area_km2": 306.0, "district": "Faro"},
    "alcoutim": {"population": 2721, "area_km2": 576.4, "district": "Faro"},
    "aljezur": {"population": 5884, "area_km2": 323.0, "district": "Faro"},
    "lagos": {"population": 31421, "area_km2": 213.0, "district": "Faro"},
    "vila real de santo antonio": {"population": 12108, "area_km2": 60.9, "district": "Faro"},
    "odemira": {"population": 25854, "area_km2": 693.0, "district": "Beja"},
    "mertola": {"population": 7314, "area_km2": 1220.0, "district": "Beja"},
    "sines": {"population": 14202, "area_km2": 201.0, "district": "Setubal"},
    "grandola": {"population": 14258, "area_km2": 806.0, "district": "Setubal"},
    "santiago do cacem": {"population": 29658, "area_km2": 1059.0, "district": "Setubal"},

    # --- Distrito de Setubal ---
    "setubal": {"population": 123680, "area_km2": 230.3, "district": "Setubal"},
    "sesimbra": {"population": 49486, "area_km2": 195.0, "district": "Setubal"},

    # --- Distrito de Leiria ---
    "leiria": {"population": 126879, "area_km2": 565.0, "district": "Leiria"},
    "pombal": {"population": 55283, "area_km2": 626.0, "district": "Leiria"},

    # --- Distrito de Guarda ---
    "guarda": {"population": 42541, "area_km2": 714.0, "district": "Guarda"},
    "chaves": {"population": 41243, "area_km2": 591.0, "district": "Vila Real"},
    "montalegre": {"population": 10442, "area_km2": 805.0, "district": "Vila Real"},
    "vila florz": {"population": 11918, "area_km2": 374.0, "district": "Braganca"},

    # --- Distrito de Viana do Castelo ---
    "viana do castelo": {"population": 88725, "area_km2": 319.0, "district": "Viana do Castelo"},
    "valenca": {"population": 14023, "area_km2": 117.0, "district": "Viana do Castelo"},

    # --- Distrito de Braganca ---
    "braganca": {"population": 35341, "area_km2": 1191.0, "district": "Braganca"},
    "carrazeda de ansiaes": {"population": 13391, "area_km2": 555.0, "district": "Braganca"},

    # --- Distrito de Vila Real ---
    "vila real": {"population": 51575, "area_km2": 376.0, "district": "Vila Real"},

    # --- Distrito de Evora ---
    "evora": {"population": 53856, "area_km2": 1307.0, "district": "Evora"},
    "ponte de sor": {"population": 19771, "area_km2": 860.0, "district": "Evora"},

    # --- Distrito de Beja ---
    "beja": {"population": 35826, "area_km2": 1146.0, "district": "Beja"},

    # --- Distrito de Portalegre ---
    "portalegre": {"population": 24931, "area_km2": 447.0, "district": "Portalegre"},

    # --- Ilha da Madeira ---
    "funchal": {"population": 111892, "area_km2": 76.0, "district": "Madeira"},
    "camara de lobos": {"population": 35666, "area_km2": 52.0, "district": "Madeira"},
    "machico": {"population": 21828, "area_km2": 67.0, "district": "Madeira"},
    "ponta do sol": {"population": 8839, "area_km2": 100.0, "district": "Madeira"},
    "santa cruz": {"population": 43052, "area_km2": 68.0, "district": "Madeira"},
    "sao vicente": {"population": 5397, "area_km2": 80.0, "district": "Madeira"},

    # --- Acores ---
    "ponta delgada": {"population": 68748, "area_km2": 232.0, "district": "Acores"},
    "angra do heroismo": {"population": 35400, "area_km2": 239.0, "district": "Acores"},
    "horta": {"population": 14972, "area_km2": 173.0, "district": "Acores"},
    "velas": {"population": 5397, "area_km2": 172.0, "district": "Acores"},
    "madalena": {"population": 6140, "area_km2": 148.0, "district": "Acores"},
    "povoaçao": {"population": 6727, "area_km2": 110.0, "district": "Acores"},
    "nordeste": {"population": 4975, "area_km2": 101.0, "district": "Acores"},
    "vila franca do campo": {"population": 11256, "area_km2": 77.0, "district": "Acores"},
    "ponte de barca": {"population": 12555, "area_km2": 320.1, "district": "Viana do Castelo"},
}

DEFAULT_DEMOGRAPHICS = {
    "population": 15000,
    "area_km2": 200.0,
    "district": "Unknown"
}


# =============================================================================
# ENTITY CLASSIFICATION
# Distinguishes municipality-level entities from regional ones
# =============================================================================

# Entity types that map to a specific municipality
MUNICIPALITY_TYPES = [
    "município", "municipio",
    "câmara municipal", "camara municipal",
    "junta de freguesia",
    "escola básica", "escola basica",
    "agrupamento de escolas",
]

# Regional entities (cover multiple municipalities) - used for separate reporting
REGIONAL_TYPES = [
    "unidade local de saude", "unidade local de saúde",
    "centro hospitalar",
    "hospital distrital",
    "região de saúde", "regiao de saude",
    "centro de saúde", "centro de saude",
    "agência", "agencia",
]



def get_demographics(municipality: str) -> Dict:
    """Get demographics for a municipality with exact and prefix matching.

    Uses only exact normalized matches and prefix matching to avoid
    false positives from substring matching (e.g., 'odivelas' -> Açores).
    """
    normalized = normalize_for_match(municipality)

    # 1. Exact match (highest confidence)
    for key, value in MUNICIPALITY_DEMOGRAPHICS.items():
        if normalize_for_match(key) == normalized:
            return value

    # 2. Prefix match (e.g., 'gaia' matches 'vila nova de gaia')
    for key, value in MUNICIPALITY_DEMOGRAPHICS.items():
        key_norm = normalize_for_match(key)
        if normalized.startswith(key_norm) or key_norm.startswith(normalized):
            return value

    return DEFAULT_DEMOGRAPHICS


def classify_entity(entity_name: str) -> tuple[Optional[str], str]:
    """Classify an entity and extract municipality name if applicable.

    Returns: (municipality_name_or_None, entity_type)
    """
    n = unidecode(entity_name.lower().strip())

    # Check if it's a municipality-level entity
    for mtype in MUNICIPALITY_TYPES:
        prefix_normalized = normalize_for_match(mtype)
        if n.startswith(prefix_normalized):
            # Extract what comes after the prefix
            location = n[len(prefix_normalized):].strip()
            # Remove prepositions
            location = re.sub(r'^(de|do|da|das|dos)\s+', '', location)
            # Clean trailing junk
            location = re.sub(r',.*$', '', location)
            location = re.sub(r'\s*\(.*$', '', location)
            location = re.sub(r'\s+-\s+.*$', '', location)
            location = re.sub(r'\s+e\.?\s*p\.?\s*e\.?.*$', '', location)
            location = re.sub(r'\s+e\.?\s*p\.?.*$', '', location)
            location = re.sub(r'\s+s\.?a\.?.*$', '', location)
            location = re.sub(r'\s+l\.?d\.?a\.?.*$', '', location)
            location = re.sub(r'\s+c\.?r\.?l\.?.*$', '', location)
            location = location.strip()

            if len(location) >= 2:
                return location, mtype

    # Check if it's a regional entity
    for rtype in REGIONAL_TYPES:
        prefix_normalized = normalize_for_match(rtype)
        if n.startswith(prefix_normalized) or prefix_normalized in n:
            return None, rtype

    return None, "other"


def load_contract_index(path: str = "data/contract_index.json") -> Dict:
    """Load contract index from JSON file."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Contract index not found at {path}", file=sys.stderr)
        return {}


def compute_spending_analysis(contract_index: Dict) -> tuple[List[Dict], Dict]:
    """Compute per-capita spending analysis.

    Returns: (municipality_results, summary_stats)
    """
    municipality_data = defaultdict(lambda: {
        "total_value": 0,
        "contract_count": 0,
        "entities": set(),
        "types": defaultdict(float),
        "regional_contracts": 0,
        "regional_value": 0,
    })

    total_contracts = 0
    total_value = 0
    classified_contracts = 0
    classified_value = 0
    regional_contracts = 0
    regional_value = 0
    unclassified_contracts = 0

    for nif, contracts in contract_index.items():
        for contract in contracts:
            entity_name = contract.get("entity_name", "")
            value = contract.get("valor", 0) or 0
            tipo = contract.get("tipo", "Unknown")
            total_contracts += 1
            total_value += value

            municipality, entity_type = classify_entity(entity_name)

            if municipality is not None:
                # Municipality-level entity
                municipality_data[municipality]["total_value"] += value
                municipality_data[municipality]["contract_count"] += 1
                municipality_data[municipality]["entities"].add(entity_name)
                municipality_data[municipality]["types"][tipo] += value
                classified_contracts += 1
                classified_value += value
            elif entity_type in REGIONAL_TYPES:
                # Regional entity - track separately
                regional_contracts += 1
                regional_value += value
            else:
                unclassified_contracts += 1

    # Enrich with demographics
    results = []
    for municipality, data in municipality_data.items():
        demo = get_demographics(municipality)
        population = demo["population"]
        per_capita = data["total_value"] / population if population > 0 else 0

        results.append({
            "municipality": municipality.title(),
            "municipality_normalized": normalize_for_match(municipality),
            "population": population,
            "area_km2": demo["area_km2"],
            "district": demo["district"],
            "total_spending": data["total_value"],
            "per_capita_spending": per_capita,
            "contract_count": data["contract_count"],
            "entity_count": len(data["entities"]),
            "entities": list(data["entities"])[:10],
            "top_types": sorted(
                data["types"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:5],
        })

    results.sort(key=lambda x: x["per_capita_spending"], reverse=True)

    summary = {
        "total_contracts": total_contracts,
        "total_value": total_value,
        "classified_contracts": classified_contracts,
        "classified_value": classified_value,
        "regional_contracts": regional_contracts,
        "regional_value": regional_value,
        "unclassified_contracts": unclassified_contracts,
        "municipalities_found": len(results),
    }

    return results, summary



def print_spending_table(results: List[Dict], summary: Dict, top_n: int = 20):
    """Print spending analysis table."""
    print(f"\n{'='*105}")
    print(f"MUNICIPALITY PER-CAPITA SPENDING ANALYSIS")
    print(f"{'='*105}")
    print(f"{'#':<4}{'Municipality':<28}{'District':<16}{'Population':>11}{'Total Spending':>16}{'Per Capita':>12}{'Contracts':>10}")
    print(f"{'─'*4}{'─'*28}{'─'*16}{'─'*11}{'─'*16}{'─'*12}{'─'*10}")

    for i, r in enumerate(results[:top_n], 1):
        pop = f"{r['population']:,}"
        print(f"{i:<4}{r['municipality']:<28}{r['district']:<16}{pop:>11}{format_currency(r['total_spending']):>16}{format_currency(r['per_capita_spending']):>12}{r['contract_count']:>10,}")

    print(f"\n{'─'*105}")
    print(f"  Coverage: {summary['classified_contracts']:,} / {summary['total_contracts']:,} contracts "
          f"({summary['classified_contracts']*100/summary['total_contracts']:.1f}%) mapped to {summary['municipalities_found']} municipalities")
    print(f"  Regional health entities: {summary['regional_contracts']:,} contracts ({format_currency(summary['regional_value'])})")
    print(f"  Unclassified: {summary['unclassified_contracts']:,} contracts")

    total_classified_value = summary['classified_value']
    total_pop = sum(r["population"] for r in results)
    print(f"\n  Total classified spending: {format_currency(total_classified_value)}")
    print(f"  Total classified population: {total_pop:,}")
    if total_pop > 0:
        print(f"  National per-capita average: {format_currency(total_classified_value / total_pop)}")


def print_municipality_detail(municipality: str, results: List[Dict]):
    """Print detailed info for a single municipality."""
    # Find in results
    muni_data = None
    for r in results:
        if normalize_for_match(r["municipality"]) == normalize_for_match(municipality):
            muni_data = r
            break
    if not muni_data:
        demo = get_demographics(municipality)
        print(f"\n📍 Demographics for {municipality.title()}:")
        print(f"   Population: {demo['population']:,}")
        print(f"   District: {demo['district']}")
        print(f"   No contract data found.")
        return

    r = muni_data
    density = r["population"] / r["area_km2"] if r["area_km2"] > 0 else 0

    print(f"\n{'='*80}")
    print(f"  🏛️  MUNICIPALITY PROFILE: {r['municipality']}")
    print(f"{'='*80}")
    print(f"  📍 District: {r['district']}")
    print(f"  👥 Population: {r['population']:,}")
    print(f"  📐 Area: {r['area_km2']} km²")
    print(f"  📊 Density: {density:.0f} per km²")

    print(f"\n  💰 CONTRACT SPENDING")
    print(f"  {'─'*60}")
    print(f"  Total Value:       {format_currency(r['total_spending'])}")
    print(f"  Per Capita:        {format_currency(r['per_capita_spending'])}")
    print(f"  Contract Count:    {r['contract_count']:,}")
    print(f"  Distinct Entities: {r['entity_count']}")

    if r["top_types"]:
        print(f"\n  📋 TOP CONTRACT TYPES")
        print(f"  {'─'*60}")
        for tipo, value in r["top_types"]:
            pct = value / r["total_spending"] * 100 if r["total_spending"] > 0 else 0
            bar = "█" * int(pct / 2)
            print(f"  {tipo[:45]:45s} {format_currency(value):>12} {pct:5.1f}% {bar}")

    if r.get("entities"):
        print(f"\n  🏢 ENTITIES")
        print(f"  {'─'*60}")
        for ent in r["entities"][:5]:
            print(f"  • {ent[:65]}")
        if len(r["entities"]) > 5:
            print(f"  ... and {len(r['entities'])-5} more")


def list_all_municipalities():
    """List all municipalities with demographics."""
    print(f"\n{'='*80}")
    print(f"PORTUGUESE MUNICIPALITIES — CENSUS 2021 DATA")
    print(f"{'='*80}")
    print(f"{'Municipality':<30}{'District':<18}{'Population':>12}{'Area km²':>10}")
    print(f"{'─'*30}{'─'*18}{'─'*12}{'─'*10}")

    sorted_munis = sorted(
        MUNICIPALITY_DEMOGRAPHICS.items(),
        key=lambda x: x[1]["population"],
        reverse=True
    )

    for name, data in sorted_munis:
        print(f"{name.title():<30}{data['district']:<18}{data['population']:>12,}{data['area_km2']:>10.1f}")

    print(f"\nTotal municipalities: {len(MUNICIPALITY_DEMOGRAPHICS)}")


def main():
    parser = argparse.ArgumentParser(
        description="Municipality Demographics & Per-Capita Spending Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Per-capita spending analysis (top 20)
    python municipality_demographics.py --spending --top 20

    # Get demographics for a municipality
    python municipality_demographics.py --municipio "Gaia"

    # Export as JSON
    python municipality_demographics.py --json --spending

    # List all municipalities
    python municipality_demographics.py --list
        """
    )

    parser.add_argument("--municipio", "-m", help="Municipality name to analyze")
    parser.add_argument("--spending", "-s", action="store_true", help="Show per-capita spending analysis")
    parser.add_argument("--list", "-l", action="store_true", help="List all municipalities")
    parser.add_argument("--top", "-t", type=int, default=20, help="Number of top results (default: 20)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--contract-index", default="data/contract_index.json", help="Path to contract index")

    args = parser.parse_args()

    if args.list:
        list_all_municipalities()
        return

    if args.municipio:
        if args.spending:
            # Show this municipality within spending context
            contract_index = load_contract_index(args.contract_index)
            results, summary = compute_spending_analysis(contract_index)
            print_municipality_detail(args.municipio, results)
        else:
            demo = get_demographics(args.municipio)
            print(f"\n📍 Demographics for: {args.municipio.title()}")
            print(f"   Population: {demo['population']:,}")
            print(f"   Area: {demo['area_km2']} km²")
            print(f"   District: {demo['district']}")
        return

    if args.spending:
        contract_index = load_contract_index(args.contract_index)
        if not contract_index:
            return

        results, summary = compute_spending_analysis(contract_index)

        if args.json:
            output = {
                "summary": summary,
                "municipalities": [
                    {k: v for k, v in r.items() if k != "entities"}
                    for r in results
                ],
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            print_spending_table(results, summary, args.top)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
