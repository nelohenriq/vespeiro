"""Personnel network graph builder — extracts people and appointments from DRE articles
and builds a network graph of state ↔ media connections.

Strategy:
1. Query DRE articles from the database.
2. Extract person names and organizations from article content using regex patterns
   common in Portuguese administrative documents (e.g. "Nomeia [Name] para [Role]").
3. Build a network graph: nodes (people, organizations, appointing bodies) and edges
   (appointment connections).
4. Return a structured graph suitable for D3.js force-directed visualization.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Models ────────────────────────────────────────────────────────────────────


class PersonnelNode(BaseModel):
    """A node in the personnel network graph."""

    id: str
    label: str
    type: str  # "person", "organization", "government"
    group: str  # "media", "state", "regulator", "other"


class PersonnelEdge(BaseModel):
    """An edge / connection in the personnel network graph."""

    source: str
    target: str
    label: str
    value: int = 1  # weight / strength of connection


class PersonnelNetwork(BaseModel):
    """Full personnel network graph."""

    nodes: list[PersonnelNode]
    edges: list[PersonnelEdge]
    total_people: int = 0
    total_appointments: int = 0
    generated_at: datetime


# ── Portuguese administrative text patterns ────────────────────────────────────

# Pattern 1: "Nomeia [Name] para o cargo de [Role]"
# Ex: "Nomeia Maria Silva para o cargo de vogal do conselho de administração da RTP"
# Uses \w for word chars since Python [a-zà-ú] range is unreliable across versions
_RE_NOMEIA_PARA = re.compile(
    r'(?:Nomeia|nomeia|Nomeiam|nomeiam)\s+'
    r'([A-ZÀ-Ü][\w\s]{3,60}?)\s+'
    r'(?:para\s+o\s+cargo\s+de\s+)'
    r'(.+?)(?:\.\s|\.$|$)',
    re.MULTILINE,
)

# Pattern 2: "designa [Name] como [Role]"
_RE_DESIGNA_COMO = re.compile(
    r'(?:Designa|designa|Designam|designam)\s+'
    r'([A-ZÀ-Ü][\w\s]{3,60}?)\s+como\s+'
    r'(.+?)(?:\.\s|\.$|$)',
    re.MULTILINE,
)

# Pattern 3: "nomeação de [Name]" (simpler fallback)
_RE_NOMEACAO_DE = re.compile(
    r'(?:nomeação|Nomeação)\s+(?:de|do|da)\s+'
    r'([A-ZÀ-Ü][\w\s]{3,60})',
    re.MULTILINE,
)

# Organization recognition — common media-related orgs in Portugal
_MEDIA_ORGS: dict[str, str] = {
    "rtp": "RTP",
    "rádio e televisão de portugal": "RTP",
    "lusa": "Lusa",
    "agência de notícias de portugal": "Lusa",
    "agência lusa": "Lusa",
    "erc": "ERC",
    "entidade reguladora da comunicação social": "ERC",
    "anacom": "ANACOM",
    "sic": "SIC",
    "tvi": "TVI",
    "impresa": "Impresa",
    "media capital": "Media Capital",
    "global media": "Global Media Group",
    "cofina": "Cofina",
    "observador": "Observador",
    "público": "Público",
    "publico": "Público",
    "sonae": "Sonae",
    "conselho de administração da rtp": "RTP",
    "conselho regulador da erc": "ERC",
    "conselho de opinião da rtp": "RTP",
    "conselho geral independente da lusa": "Lusa",
}

_GOV_ORGS: dict[str, str] = {
    "presidência do conselho de ministros": "PCM",
    "gabinete do primeiro-ministro": "PCM",
    "ministério da cultura": "Ministério da Cultura",
    "secretaria de estado da comunicação social": "SECS",
    "gabinete do secretário de estado": "Governo",
    "assembleia da república": "AR",
    "conselho de ministros": "Conselho de Ministros",
}


def _find_media_org(text: str) -> str | None:
    """Identify a media organization from text."""
    text_lower = text.lower()
    for key, value in _MEDIA_ORGS.items():
        if key in text_lower:
            return value
    return None


def _find_gov_org(text: str) -> str | None:
    """Identify a government body from text."""
    text_lower = text.lower()
    for key, value in _GOV_ORGS.items():
        if key in text_lower:
            return value
    return None


# ── Network builder ───────────────────────────────────────────────────────────


class PersonnelNetworkBuilder:
    """Builds a personnel network graph from DRE articles."""

    def __init__(self, db_session: object | None = None):
        self.db = db_session

    async def build(self) -> PersonnelNetwork:
        """Build the full personnel network from database articles."""
        nodes: dict[str, PersonnelNode] = {}
        edges: list[PersonnelEdge] = []
        appointments_found = 0
        people_found: set[str] = set()

        articles = await self._get_dre_articles()
        if not articles:
            logger.info("Personnel: no DRE articles found")
            return PersonnelNetwork(
                nodes=[], edges=[],
                generated_at=datetime.now(timezone.utc),
            )

        for article in articles:
            text = article.get("content_text") or ""
            if not text:
                continue

            # Extract person + role pairs
            pairs = self._extract_person_role_pairs(text)
            for person_name, role_desc in pairs:
                people_found.add(person_name)

                # Identify organizations in the role description
                media_org = _find_media_org(role_desc)
                gov_org = _find_gov_org(role_desc)

                # Add person node
                person_id = _slugify(person_name)
                if person_id not in nodes:
                    nodes[person_id] = PersonnelNode(
                        id=person_id,
                        label=person_name,
                        type="person",
                        group="media" if media_org else "other",
                    )

                # Add organization node + edge
                if media_org:
                    org_id = _slugify(media_org)
                    if org_id not in nodes:
                        nodes[org_id] = PersonnelNode(
                            id=org_id,
                            label=media_org,
                            type="organization",
                            group="media",
                        )
                    edges.append(PersonnelEdge(
                        source=person_id,
                        target=org_id,
                        label=role_desc[:80],
                        value=1,
                    ))
                    appointments_found += 1

                # Add government node + edge
                if gov_org:
                    gov_id = _slugify(gov_org)
                    if gov_id not in nodes:
                        nodes[gov_id] = PersonnelNode(
                            id=gov_id,
                            label=gov_org,
                            type="government",
                            group="state",
                        )
                    edges.append(PersonnelEdge(
                        source=person_id,
                        target=gov_id,
                        label="nomeado por",
                        value=1,
                    ))
                    appointments_found += 1

        # Also add ownership connections from config
        self._add_ownership_edges(nodes, edges)

        # Deduplicate edges (merge same source→target into single edge with incremented value)
        merged_edges: dict[tuple[str, str], PersonnelEdge] = {}
        for edge in edges:
            key = (edge.source, edge.target)
            if key in merged_edges:
                merged_edges[key].value += 1
            else:
                merged_edges[key] = edge

        return PersonnelNetwork(
            nodes=list(nodes.values()),
            edges=list(merged_edges.values()),
            total_people=len(people_found),
            total_appointments=appointments_found,
            generated_at=datetime.now(timezone.utc),
        )

    def _extract_person_role_pairs(self, text: str) -> list[tuple[str, str]]:
        """Extract (person_name, role_description) pairs from DRE text."""
        pairs: list[tuple[str, str]] = []

        for match in _RE_NOMEIA_PARA.finditer(text):
            name = match.group(1).strip()
            role = match.group(2).strip()
            if len(name.split()) >= 2 and len(role) > 3:
                pairs.append((_clean_name(name), role))

        for match in _RE_DESIGNA_COMO.finditer(text):
            name = match.group(1).strip()
            role = match.group(2).strip()
            if len(name.split()) >= 2 and len(role) > 3:
                pairs.append((_clean_name(name), role))

        # Fallback: if no structured patterns matched, try simpler ones
        if not pairs:
            for match in _RE_NOMEACAO_DE.finditer(text):
                name = match.group(1).strip()
                if len(name.split()) >= 2:
                    pairs.append((_clean_name(name), "cargo não especificado"))

        return pairs

    def _add_ownership_edges(
        self,
        nodes: dict[str, PersonnelNode],
        edges: list[PersonnelEdge],
    ) -> None:
        """Add ownership connections from ownership.yaml."""
        try:
            from src.config.ownership import load_ownership

            config = load_ownership()
            for outlet in config.outlets:
                # Add owner as a node if it's a person/family
                if outlet.ultimate_owner and outlet.ultimate_owner not in ("null", "", None):
                    owner_id = _slugify(outlet.ultimate_owner)
                    if owner_id not in nodes:
                        nodes[owner_id] = PersonnelNode(
                            id=owner_id,
                            label=outlet.ultimate_owner,
                            type="person",
                            group="media",
                        )

                    outlet_id = _slugify(outlet.id)
                    if outlet_id not in nodes:
                        nodes[outlet_id] = PersonnelNode(
                            id=outlet_id,
                            label=outlet.name,
                            type="organization",
                            group="media",
                        )

                    edges.append(PersonnelEdge(
                        source=owner_id,
                        target=outlet_id,
                        label="proprietário",
                        value=1,
                    ))

                # Add owner group as node
                if outlet.owner_group:
                    group_id = _slugify(outlet.owner_group)
                    if group_id not in nodes:
                        nodes[group_id] = PersonnelNode(
                            id=group_id,
                            label=outlet.owner_group,
                            type="organization",
                            group="media",
                        )
                    edges.append(PersonnelEdge(
                        source=group_id,
                        target=_slugify(outlet.id),
                        label="detém",
                        value=1,
                    ))
        except Exception as exc:
            logger.debug("Could not load ownership data: %s", exc)

    async def _get_dre_articles(self) -> list[dict]:
        """Query DRE articles from the database."""
        if self.db is None:
            return []

        try:
            from sqlalchemy import select
            from src.db.models import Article

            result = await self.db.execute(
                select(Article.content_text, Article.title, Article.id)
                .where(Article.source_id.in_(["dre_appointments", "dre_general_appointments"]))
                .where(Article.content_text.isnot(None))
                .limit(200)
            )
            # Return as list of dicts for simpler handling
            return [
                {"content_text": row[0], "title": row[1], "id": row[2]}
                for row in result.all()
            ]
        except Exception as exc:
            logger.warning("Failed to query DRE articles: %s", exc)
            return []


def _clean_name(name: str) -> str:
    """Clean up extracted person name.

    Preserves Portuguese name particles in lowercase (de, da, do, dos, das, e).
    """
    name = re.sub(r"[,.;:]$", "", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip()
    # Title case but preserve particles
    parts = name.split()
    particles = {"de", "da", "do", "dos", "das", "e"}
    cleaned = []
    for i, part in enumerate(parts):
        if i > 0 and part.lower() in particles:
            cleaned.append(part.lower())
        else:
            cleaned.append(part.capitalize())
    return " ".join(cleaned)


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug for node IDs.

    Normalizes accented characters and removes non-alphanumeric chars.
    """
    import unicodedata

    # Normalize unicode: decompose accented chars, then strip diacritics
    text = unicodedata.normalize("NFKD", text.lower().strip())
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Replace non-alphanumeric with hyphens
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")
