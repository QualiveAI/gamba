from app.economy.rng import ProvablyFairRNG
from core.engine.ledger.ledger import post_entry


def upgrade_chance(item_price: int, target_price: int) -> float:
    if target_price <= 0:
        return 0.0
    return (item_price / target_price) * 0.8


async def do_upgrade(conn, user, item_price, target_price, client_seed):
    chance = upgrade_chance(item_price, target_price)
    rng = ProvablyFairRNG("server", client_seed, 1)
    roll = rng.roll()
    success = roll < chance
    if success:
        await post_entry(
            conn, user["id"], "units", target_price - item_price, "upgrade_win", "upgrade"
        )
    else:
        await post_entry(conn, user["id"], "units", -item_price, "upgrade_loss", "upgrade")
    await conn.commit()
    return {"success": success, "chance": chance, "roll": roll}
