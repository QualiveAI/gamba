import yaml
from pydantic import BaseModel

FREEBET_MAX_REAL_VALUE_MINOR = 2000


class FreebetPrize(BaseModel):
    prize_id: str
    name: str
    nominal_units: int
    real_value_minor: int
    weight: float


class FreebetCatalog(BaseModel):
    prizes: list[FreebetPrize]

    def validate_cap(self):
        for p in self.prizes:
            if p.real_value_minor > FREEBET_MAX_REAL_VALUE_MINOR:
                raise ValueError(f"prize {p.prize_id} exceeds cap")  # noqa: B904


def load_freebet_catalog(path: str = "configs/games/cases.freebet.prizes.yaml") -> FreebetCatalog:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    cat = FreebetCatalog(prizes=data)
    cat.validate_cap()
    return cat
