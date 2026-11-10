import math
import secrets
from datetime import UTC, datetime

from app.economy.rng import ProvablyFairRNG
from core.engine.ledger.ledger import post_entry

# Ракетка: множитель растёт как в демо, m(t) = exp(0.12 * t), кэшаут в любой момент
GROWTH = 0.12
SESSION_RTP = 0.97
MAX_MULT = 1000.0


def multiplier_at(elapsed: float) -> float:
    return math.floor(math.exp(GROWTH * max(0.0, elapsed)) * 100) / 100


def crash_multiplier(roll: float) -> float:
    if roll >= 1.0:
        roll = 0.999999
    return max(1.0, (1.0 / (1.0 - roll)) * 0.95)


async def start_crash(conn, user, bet):
    """Старт раунда: ставка списывается, точка взрыва фиксируется на сервере."""
    if bet <= 0:
        raise ValueError("invalid bet")  # noqa: B904
    rng = ProvablyFairRNG("server", secrets.token_hex(16), 1)
    roll = rng.roll()
    crash_point = max(1.0, min(MAX_MULT, round(SESSION_RTP / (1.0 - roll), 2)))
    cur = await conn.execute(
        "INSERT INTO crash_sessions (user_id, bet_units, crash_point, status) "
        "VALUES (%s, %s, %s, 'active') RETURNING id, started_at",
        (user["id"], bet, crash_point),
    )
    row = await cur.fetchone()
    sid = row["id"]
    await post_entry(conn, user["id"], "units", -bet, "crash_stake", f"crash:{sid}")
    await conn.commit()
    return {
        "session_id": sid,
        "crash_point": float(crash_point),
        "t0_ms": int(row["started_at"].timestamp() * 1000),
        "growth": GROWTH,
    }


async def cash_crash(conn, user, session_id):
    """Кэшаут в любой момент: множитель считает сервер по времени раунда."""
    row = await (
        await conn.execute(
            "SELECT id, user_id, bet_units, crash_point, started_at, status FROM crash_sessions WHERE id = %s FOR UPDATE",  # noqa: E501
            (session_id,),
        )
    ).fetchone()
    if row is None or row["user_id"] != user["id"]:
        raise ValueError("session not found")  # noqa: B904
    if row["status"] != "active":
        raise ValueError("session not active")  # noqa: B904
    bet = int(row["bet_units"])
    cp = float(row["crash_point"])
    elapsed = (datetime.now(UTC) - row["started_at"]).total_seconds()
    m = multiplier_at(elapsed)
    if m >= cp:
        await conn.execute(
            "UPDATE crash_sessions SET status='busted', cashout_multiplier=%s, ended_at=now() WHERE id=%s",  # noqa: E501
            (cp, session_id),
        )
        await conn.commit()
        return {"win": False, "m": cp, "crash": cp, "payout": 0}
    payout = int(bet * m)
    await post_entry(conn, user["id"], "units", payout, "crash_cashout", f"crash:{session_id}:cash")
    await conn.execute(
        "UPDATE crash_sessions SET status='cashed', cashout_multiplier=%s, payout_units=%s, ended_at=now() WHERE id=%s",  # noqa: E501
        (m, payout, session_id),
    )
    await conn.commit()
    return {"win": True, "m": m, "crash": cp, "payout": payout}


# Легаси-мгновенный раунд с авто-cashout — оставлен для совместимости
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
