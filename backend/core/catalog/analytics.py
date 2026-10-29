from app.db import get_conn


async def case_stats(case_id: int, days: int = 30):
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT COUNT(*) AS opens FROM case_openings WHERE case_id = %s", (case_id,)
            )
        ).fetchall()
    return {"opens": rows[0]["opens"] if rows else 0}


async def auto_pause_if_drift(case_id: int):
    async with get_conn() as conn:
        vrow = await (
            await conn.execute(
                "SELECT case_id, rtp_target_bp FROM case_versions WHERE id = %s", (case_id,)
            )
        ).fetchone()
        if vrow is None:
            return False
        case_id_real = vrow["case_id"]
        target = vrow["rtp_target_bp"] / 10000.0
        rows = await (
            await conn.execute(
                "SELECT co.id, cp.real_value_minor, c.price_units FROM case_openings co JOIN case_prizes cp ON cp.id = co.reward_id JOIN cases c ON c.id = co.case_id WHERE co.catalog_version_id = %s",  # noqa: E501
                (case_id,),
            )
        ).fetchall()
        if len(rows) < 1000:
            return False
        total_price = sum(r["price_units"] for r in rows)
        total_reward = sum(r["real_value_minor"] for r in rows)
        empirical = (total_reward / total_price) if total_price else 0
        if abs(empirical - target) > 0.05:
            await conn.execute(
                "UPDATE case_definitions SET status = 'paused' WHERE id = %s", (case_id_real,)
            )
            await conn.execute(
                "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
                (None, "case_paused", {"case_id": case_id_real}),
            )
            await conn.commit()
            return True
        return False
