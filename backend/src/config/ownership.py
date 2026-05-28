from enum import Enum
from pydantic import BaseModel
import yaml
from pathlib import Path


class MediaType(str, Enum):
    NEWSPAPER = "newspaper"
    COMMERCIAL_TV = "commercial_tv"
    PUBLIC_BROADCASTER = "public_broadcaster"
    DIGITAL_NATIVE = "digital_native"
    NEWS_AGENCY = "news_agency"
    RADIO = "radio"
    MAGAZINE = "magazine"


class MediaOutlet(BaseModel):
    id: str
    name: str
    owner: str
    owner_group: str
    ultimate_owner: str | None = None
    type: MediaType
    country: str = "PT"
    notes: str | None = None


class OwnershipConfig(BaseModel):
    outlets: list[MediaOutlet]


def load_ownership() -> OwnershipConfig:
    """Load all media ownership data from ownership.yaml."""
    config_path = Path(__file__).parent / "ownership.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return OwnershipConfig.model_validate(data)


def get_owner(outlet_id: str) -> MediaOutlet | None:
    """Look up ownership info for a media outlet by ID."""
    config = load_ownership()
    for outlet in config.outlets:
        if outlet.id == outlet_id:
            return outlet
    return None


def get_group_outlets(owner_group: str) -> list[MediaOutlet]:
    """Get all outlets belonging to a given owner group."""
    config = load_ownership()
    return [o for o in config.outlets if o.owner_group == owner_group]
