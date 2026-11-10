from app.economy.rng import ProvablyFairRNG
from core.engine.ledger.ledger import post_entry

# Уровни «Копосов» (напёрстки): с каждым победным уровнем больше стаканчиков
CUPS_BY_LEVEL = {1: 3, 2: 3, 3: 4, 4: 4, 5: 5, 6: 5}
RTP = 0.97


def shell_mult(cups: int) -> float:
    # x = 0.97 * n, как в демо: шанс 1/n
    return int(RTP * cups * 100 + 1e-6) / 100


async def start_shell(conn, user, bet, level, client_seed):
    """Раунд копосов: шарик фиксируется на старте (provably fair), ставка списывается."""
    cups = CUPS_BY_LEVEL.get(int(level))
    if cups is None:
        raise ValueError("invalid level")  # noqa: B904
    if bet <= 0:
        raise ValueError("invalid bet")  # noqa: B904
    rng = ProvablyFairRNG("server", client_seed, 1)
    ball = int(rng.roll() * cups)
    cur = await conn.execute(
        "INSERT INTO shell_sessions (user_id, bet_units, cups, ball, status) "
        "VALUES (%s, %s, %s, %s, 'active') RETURNING id",
        (user["id"], bet, cups, ball),
    )
    sid = (await cur.fetchone())["id"]
    await post_entry(conn, user["id"], "units", -bet, "shell_stake", f"shell:{sid}")
    await conn.commit()
    return {"session_id": sid, "cups": cups, "ball": ball, "mult": shell_mult(cups)}


async def pick_shell(conn, user, session_id, guess):
    row = await (
        await conn.execute(
            "SELECT id, user_id, bet_units, cups, ball, status FROM shell_sessions WHERE id = %s FOR UPDATE",  # noqa: E501
            (session_id,),
        )
    ).fetchone()
    if row is None or row["user_id"] != user["id"]:
        raise ValueError("session not found")  # noqa: B904
    if row["status"] != "active":
        raise ValueError("session not active")  # noqa: B904
    cups, ball, bet = int(row["cups"]), int(row["ball"]), int(row["bet_units"])
    if not (0 <= guess < cups):
        raise ValueError("invalid guess")  # noqa: B904
    win = guess == ball
    mult = shell_mult(cups)
    payout = int(bet * mult) if win else 0
    if win:
        await post_entry(conn, user["id"], "units", payout, "shell_win", f"shell:{session_id}:win")
    await conn.execute(
        "UPDATE shell_sessions SET status='done', guess=%s, win=%s, payout_units=%s WHERE id=%s",
        (guess, win, payout, session_id),
    )
    await conn.commit()
    return {"win": win, "ball": ball, "guess": guess, "mult": mult, "payout": payout}


# Легаси-раунд «1 из 3» — оставлен для совместимости (старый UI/тесты)
async def play_shell(conn, user, bet, guess, client_seed):
    rng = ProvablyFairRNG("server", client_seed, 1)
    roll = rng.roll()
    ball = int(roll * 3)
    win = guess == ball
    if win:
        await post_entry(conn, user["id"], "units", bet * 2 - bet, "shell_win", "shell")
    else:
        await post_entry(conn, user["id"], "units", -bet, "shell_loss", "shell")
    await conn.commit()
    return {"ball": ball, "guess": guess, "win": win}
