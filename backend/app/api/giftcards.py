import os
import tempfile

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import require_admin
from app.db import get_conn
from app.giftcards import service

router = APIRouter(tags=["giftcards"])


@router.post("/admin/giftcards/import")
async def import_giftcards(file: UploadFile = File(...), admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008  # noqa: B008
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:  # noqa: B008
        tmp.write(content)
        path = tmp.name
    try:
        async with get_conn() as conn:
            count = await service.import_csv(conn, path)
    finally:
        os.remove(path)
    return {"imported": count}


@router.get("/admin/giftcards/stats")
async def giftcard_stats(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        rows = await (
            await conn.execute("SELECT status, COUNT(*) AS c FROM gift_codes GROUP BY status")
        ).fetchall()
    return {r["status"]: r["c"] for r in rows}
