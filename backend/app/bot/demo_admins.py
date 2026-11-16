"""Демо-админы для записи роликов: доступ выдаётся через бота и хранится в БД.

Назначение узкое: владелец (/grant) даёт человеку право командой /topup
накручивать Coins на свой аккаунт, чтобы записывать демо-видео. Это не
платёжный и не игровой код: любые записи идут через обычный ledger
(reason=demo_topup), поэтому инвариант балансов не нарушается.

Список хранится в system_config["bot_demo_admins"] = {"ids": [...]}.
Корневые админы — settings.admin_ids (ADMIN_TELEGRAM_IDS), они же могут
выдавать и отбирать доступ.
"""

import json

DEMO_ADMINS_KEY = "bot_demo_admins"


async def demo_admin_ids(conn) -> set[int]:
    row = await (
        await conn.execute("SELECT value FROM system_config WHERE key = %s", (DEMO_ADMINS_KEY,))
    ).fetchone()
    if not row or not isinstance(row["value"], dict):
        return set()
    ids = row["value"].get("ids", [])
    if not isinstance(ids, list):
        return set()
    out = set()
    for item in ids:
        if isinstance(item, int) and item > 0:
            out.add(item)
        elif isinstance(item, str) and item.isdigit():
            out.add(int(item))
    return out


async def _store(conn, ids: set[int]) -> None:
    await conn.execute(
        "INSERT INTO system_config (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (DEMO_ADMINS_KEY, json.dumps({"ids": sorted(ids)})),
    )
    await conn.execute(
        "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
        (None, "flag_change", json.dumps({"key": DEMO_ADMINS_KEY, "ids": sorted(ids)})),
    )


async def grant_demo_admin(conn, telegram_id: int) -> None:
    ids = await demo_admin_ids(conn)
    ids.add(telegram_id)
    await _store(conn, ids)


async def revoke_demo_admin(conn, telegram_id: int) -> None:
    ids = await demo_admin_ids(conn)
    ids.discard(telegram_id)
    await _store(conn, ids)


async def is_demo_admin(conn, telegram_id: int) -> bool:
    return telegram_id in await demo_admin_ids(conn)
