from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.db import get_conn

router = APIRouter(tags=["wallet"])


@router.get("/wallet")
async def wallet(user=Depends(get_current_user)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT balance_units, balance_freebets FROM users WHERE id = %s", (user["id"],)
            )
        ).fetchone()
    return {"units_minor": row["balance_units"], "freebets_units": row["balance_freebets"]}


@router.get("/meta/limits")
async def limits():
    return {
        "min_deposit_minor": 10000,
        "withdraw_min_minor": 100000,
        "withdraw_fee_pct": 20,
        "hold_days": 1,
    }


class ReferralInfo(BaseModel):
    link: str
    invited: int
    confirmed: int


@router.get("/referrals/my", response_model=ReferralInfo)
async def my_referrals(user=Depends(get_current_user)):  # noqa: B008
    from app.referrals.service import create_referral_link

    async with get_conn() as conn:
        invited = await (
            await conn.execute(
                "SELECT COUNT(*) AS c FROM referrals WHERE referrer_id = %s",
                (user["id"],),
            )
        ).fetchone()
        confirmed = await (
            await conn.execute(
                "SELECT COUNT(*) AS c FROM referrals "
                "WHERE referrer_id = %s AND status = 'confirmed'",
                (user["id"],),
            )
        ).fetchone()
    return ReferralInfo(
        link=await create_referral_link(user["id"]),
        invited=int(invited["c"]),
        confirmed=int(confirmed["c"]),
    )


@router.get("/inventory")
async def my_inventory(user=Depends(get_current_user)):  # noqa: B008
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, label, game_key, currency, value_coins, rarity, status, created_at "
                "FROM user_items WHERE user_id = %s AND status = 'active' "
                "ORDER BY id DESC",
                (user["id"],),
            )
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/inventory/{item_id}/sell")
async def sell_item(item_id: int, user=Depends(get_current_user)):  # noqa: B008
    # Продажа предметов отключена: монеты можно получить только в мини-играх,
    # поставив предмет (ставка предметом -> выигрыш монетами)
    raise HTTPException(
        status_code=400,
        detail="Venda desativada: jogue minijogos com o item para ganhar moedas",
    )


class UpgradeTarget(BaseModel):
    target_value: int


@router.post("/inventory/{item_id}/upgrade")
async def upgrade_item(  # noqa: B008
    item_id: int, body: UpgradeTarget, user=Depends(get_current_user)  # noqa: B008
):
    """Апгрейд предмета: успех -> предмет дороже, провал -> предмет потерян."""
    import secrets as _secrets

    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT id, label, game_key, currency, value_coins FROM user_items "
                "WHERE id = %s AND user_id = %s AND status = 'active' FOR UPDATE",
                (item_id, user["id"]),
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")  # noqa: B904
        target = int(body.target_value)
        if target <= int(row["value_coins"]):
            raise HTTPException(  # noqa: B904
            status_code=400, detail="target must be higher"
        )
        chance = min(0.8, row["value_coins"] / target * 0.8)
        roll = _secrets.randbelow(10_000) / 10_000
        success = roll < chance
        if success:
            await conn.execute(
                "UPDATE user_items SET label = %s, value_coins = %s, "
                "rarity = 'Upgraded' WHERE id = %s",
                (f"Upgraded {row['game_key'] or 'item'}", target, row["id"]),
            )
        else:
            await conn.execute(
                "UPDATE user_items SET status = 'lost' WHERE id = %s", (row["id"],)
            )
        await conn.commit()
    return {"success": success, "chance": round(chance, 4), "roll": round(roll, 4),
            "value": target if success else 0}
