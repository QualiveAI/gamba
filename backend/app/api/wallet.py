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
                "SELECT id, label, game_key, currency, value_coins, rarity, image, status, created_at "
                "FROM user_items WHERE user_id = %s AND status = 'active' "
                "ORDER BY id DESC",
                (user["id"],),
            )
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/inventory/{item_id}/sell")
async def sell_item(item_id: int, user=Depends(get_current_user)):  # noqa: B008
    """Продажа предмета за монеты по его стоимости (как в демо)."""
    from core.engine.ledger.ledger import post_entry

    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT id, value_coins, currency FROM user_items "
                "WHERE id = %s AND user_id = %s AND status = 'active' FOR UPDATE",
                (item_id, user["id"]),
            )
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="item not found")  # noqa: B904
        value = int(row["value_coins"])
        currency = row["currency"] or "units"
        await conn.execute(
            "UPDATE user_items SET status = 'sold' WHERE id = %s", (row["id"],)
        )
        await post_entry(conn, user["id"], currency, value, "item_sold", f"item:{row['id']}")
        await conn.commit()
    return {"sold": True, "value": value, "currency": currency}


class UpgradeTarget(BaseModel):
    target_value: int
    target_label: str | None = None
    target_image: str | None = None
    target_rarity: str | None = None


@router.post("/inventory/{item_id}/upgrade")
async def upgrade_item(  # noqa: B008
    item_id: int, body: UpgradeTarget, user=Depends(get_current_user)  # noqa: B008
):
    """Апгрейд предмета: успех -> целевой предмет из каталога, провал -> предмет потерян."""
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
                "UPDATE user_items SET label = %s, value_coins = %s, rarity = %s, image = %s "
                "WHERE id = %s",
                (
                    body.target_label or f"Upgraded {row['game_key'] or 'item'}",
                    target,
                    body.target_rarity or "Upgraded",
                    body.target_image,
                    row["id"],
                ),
            )
        else:
            await conn.execute(
                "UPDATE user_items SET status = 'lost' WHERE id = %s", (row["id"],)
            )
        await conn.commit()
    return {"success": success, "chance": round(chance, 4), "roll": round(roll, 4),
            "value": target if success else 0}


@router.get("/wallet/history")
async def wallet_history(user=Depends(get_current_user)):  # noqa: B008
    """История операций: леджер + выпавшие предметы (как в демо-профиле)."""
    async with get_conn() as conn:
        ledger = await (
            await conn.execute(
                "SELECT delta, currency, reason, created_at FROM ledger_entries "
                "WHERE user_id = %s ORDER BY id DESC LIMIT 25",
                (user["id"],),
            )
        ).fetchall()
        opens = await (
            await conn.execute(
                "SELECT o.created_at, r.label, r.image, r.rarity, c.currency "
                "FROM case_openings o "
                "JOIN case_rewards r ON r.id = o.reward_id "
                "JOIN cases c ON c.id = o.case_id "
                "WHERE o.user_id = %s ORDER BY o.id DESC LIMIT 10",
                (user["id"],),
            )
        ).fetchall()
    items = [
        {
            "t": r["created_at"].isoformat(),
            "kind": "ledger",
            "delta": int(r["delta"]),
            "currency": r["currency"] or "units",
            "text": r["reason"],
        }
        for r in ledger
    ]
    items += [
        {
            "t": r["created_at"].isoformat(),
            "kind": "item",
            "text": r["label"],
            "image": r["image"],
            "rarity": r["rarity"],
            "currency": r["currency"] or "units",
        }
        for r in opens
    ]
    items.sort(key=lambda x: x["t"], reverse=True)
    return items[:25]
