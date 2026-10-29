from dataclasses import dataclass, field


@dataclass
class RiskScore:
    level: str = "low"
    reasons: list[str] = field(default_factory=list)
