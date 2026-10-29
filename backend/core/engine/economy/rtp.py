def clamp_rtp(value: float) -> float:
    return max(0.80, min(0.95, float(value)))


def apply_modifiers(base: float, modifiers: dict[str, float] | None = None) -> float:
    val = base
    if modifiers:
        for _k, v in modifiers.items():
            val = val * (1.0 + float(v))
    return clamp_rtp(val)
