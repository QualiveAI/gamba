from app.economy.rng import ProvablyFairRNG
from core.engine.ledger.ledger import post_entry


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
