def f_win(streak: int) -> float:
    if streak <= 1:
        return 1.00
    if streak == 2:
        return 0.95
    return 0.88


def f_bet(bet: float, p50: float, p90: float) -> float:
    if bet <= p50:
        return 1.00
    if bet <= p90:
        return 0.95
    return 0.90


def f_chase(losses_5m: int, stakes_since_loss: int, avg_stake: float) -> float:
    if losses_5m < 3:
        return 1.00
    # stakes_since_loss represents the new stake amount
    if stakes_since_loss <= 2 * avg_stake:
        return 0.85
    return 0.78


def f_admin(is_admin: bool, promo_override: bool) -> float:
    return 1.00
