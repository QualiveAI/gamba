from app.economy.rng import ProvablyFairRNG
from core.engine.ledger.ledger import post_entry


def crash_multiplier(roll: float) -> float:
    if roll >= 1.0:
        roll = 0.999999
    return max(1.0, (1.0 / (1.0 - roll)) * 0.95)


async def play_crash(conn, user, bet, cashout_at, client_seed):
    rng = ProvablyFairRNG("server", client_seed, 1)
    roll = rng.roll()
    crash = crash_multiplier(roll)
    win = cashout_at <= crash
    if win:
        await post_entry(
            conn, user["id"], "units", int(bet * cashout_at) - bet, "crash_win", "crash"
        )
    else:
        await post_entry(conn, user["id"], "units", -bet, "crash_loss", "crash")
    await conn.commit()
    return {"crash": crash, "cashout_at": cashout_at, "win": win}
