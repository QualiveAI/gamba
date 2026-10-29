from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from core.registry.registry import registry


class GameConfig(BaseModel):
    game_key: str
    enabled: bool = True
    rtp_profile: dict = Field(default_factory=dict)


class GeoConfig(BaseModel):
    geo: str
    enabled: bool = True
    rails: list[str] = Field(default_factory=list)
    currency_display: str = "USD"
    kyc: str = "none"
    min_deposit_minor: int = 0
    max_deposit_minor: int = 1000000


class BrandConfig(BaseModel):
    name: str = "CasePlatform"
    logo_url: str = ""
    primary_color: str = "#101014"


class DomainsConfig(BaseModel):
    frontend: str = ""
    api: str = ""


class TenantConfig(BaseModel):
    tenant: str
    brand: BrandConfig = Field(default_factory=BrandConfig)
    domains: DomainsConfig = Field(default_factory=DomainsConfig)
    games: list[GameConfig] = Field(default_factory=list)
    geos: list[GeoConfig] = Field(default_factory=list)

    def validate_against_registry(self):
        errors = []
        # games exist
        for g in self.games:
            if g.enabled:
                obj = registry.get("game", g.game_key)
                if obj is None:
                    errors.append(f"unknown game {g.game_key}")
        # geos rails
        for geo in self.geos:
            if not geo.enabled:
                continue
            if not geo.rails:
                errors.append(f"geo {geo.geo} has no rails")
            for rail in geo.rails:
                # find rail plugin supporting geo
                rails = registry.list("payment", geo=geo.geo)
                keys = [
                    getattr(r, "rail_key", None) or getattr(r, "MANIFEST", {}).get("key")
                    for r in rails
                ]
                if rail not in keys:
                    # allow global rails
                    global_rails = registry.list("payment", geo="*")
                    gkeys = [
                        getattr(r, "rail_key", None) or getattr(r, "MANIFEST", {}).get("key")
                        for r in global_rails
                    ]
                    if rail not in gkeys:
                        errors.append(f"unknown rail {rail} for geo {geo.geo}")
        if errors:
            raise ValueError("; ".join(errors))  # noqa: B904


def load_tenant(name: str = "default") -> TenantConfig:
    path = Path("configs/tenants") / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    tc = TenantConfig(**data)
    tc.validate_against_registry()
    return tc
