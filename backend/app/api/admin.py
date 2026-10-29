from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.db import get_conn
from app.economy.ledger import reconcile

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ledger/reconcile")
async def ledger_reconcile(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        broken = await reconcile(conn)
    return {"broken_users": broken}


@router.get("/plugins")
async def list_plugins(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008  # noqa: B008
    from core.registry.registry import registry

    return {"health": registry.health()}


@router.post("/plugins/{ptype}/{key}/toggle")
async def toggle_plugin(ptype: str, key: str, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    return {"ok": True, "type": ptype, "key": key}


@router.post("/plugins/reload")
async def reload_plugins(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008  # noqa: B008
    import os

    if os.getenv("ENV") != "dev":
        raise HTTPException(status_code=403, detail="dev only")  # noqa: B904
    return {"ok": True}


@router.get("/referrals")
async def list_referrals(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, referrer_id, referee_id, status, created_at FROM referrals ORDER BY id DESC"  # noqa: E501
            )
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/referrals/{ref_id}/reject")
async def reject_referral(ref_id: int, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        await conn.execute("UPDATE referrals SET status = 'rejected' WHERE id = %s", (ref_id,))
        await conn.commit()
    return {"ok": True}


@router.get("/freebets/config")
async def get_freebets_config(admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    import os

    import yaml

    path = "configs/games/cases.freebet.prizes.yaml"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return {"catalog": data}
    return {"catalog": []}


@router.post("/freebets/config")
async def set_freebets_config(payload: dict, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    return {"ok": True, "version": 1}

@router.post("/cases/{case_id}/unpause")
async def unpause_case(case_id: int, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        await conn.execute("UPDATE case_definitions SET status = 'published' WHERE id = %s", (case_id,))
        await conn.execute(
            "INSERT INTO events (user_id, event_type, payload) VALUES (%s, %s, %s)",
            (None, "case_unpaused", {"case_id": case_id}),
        )
        await conn.commit()
    return {"ok": True}
