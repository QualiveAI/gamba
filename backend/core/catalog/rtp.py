def compute_rtp(prizes):
    total_w = sum(p.get("weight_bp", p.get("weight", 0)) for p in prizes)
    if total_w <= 0:
        return {"ev_minor": 0, "rtp_bp": 0}
    ev = (
        sum(p.get("real_value_minor", 0) * p.get("weight_bp", p.get("weight", 0)) for p in prizes)
        / total_w
    )
    return {
        "ev_minor": ev,
        "rtp_bp": int(ev * 100),
    }


def validate_catalog(prizes, currency, rtp_target_bp, tolerance_bp=50):
    errors = []
    warnings = []
    total_w = sum(p.get("weight_bp", 0) for p in prizes)
    if total_w != 10000:
        errors.append("weights sum != 10000")
    for p in prizes:
        if p.get("nominal_units", 0) <= 0:
            errors.append("nominal_units <= 0")
        if p.get("real_value_minor", 0) < 0:
            errors.append("real_value_minor < 0")
        if currency == "freebets" and p.get("real_value_minor", 0) > 2000:
            errors.append("freebet real value cap exceeded")
        if p.get("real_value_minor", 0) == 0:
            warnings.append("zero real value prize")
    # rtp
    rtp_bp = 0
    ev_minor = 0
    if total_w > 0:
        ev = sum(p.get("real_value_minor", 0) * p.get("weight_bp", 0) for p in prizes) / total_w
        ev_minor = ev
        rtp_bp = int(ev * 100)
        if abs(rtp_bp - rtp_target_bp) > tolerance_bp:
            errors.append("rtp drift too high")
    return {"errors": errors, "warnings": warnings, "valid": len(errors) == 0, "rtp_bp": rtp_bp, "ev_minor": ev_minor}
