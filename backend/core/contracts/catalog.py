from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class Prize:
    prize_id: str
    label: str
    nominal_units: int
    real_value_minor: int
    weight_bp: int
    media_id: int | None = None


@dataclass
class Catalog:
    case_id: int
    version_id: int
    currency: str
    prizes: list[Prize]
    rtp_target_bp: int
    checksum: str


@runtime_checkable
class PrizeCatalogProvider(Protocol):
    def get_catalog(
        self, game_key: str, currency: str, version_id: int | None = None
    ) -> Catalog: ...
