import os
import sys
from pathlib import Path
from fastapi import Request, Response


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        if (parent / "backend" / "app").is_dir():
            return parent
    raise RuntimeError("backend package not found")


ROOT = find_repo_root()
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import ConnectionFence, close_pool, fenced_connection, get_pool, init_pool  # noqa: E402
from core.catalog.analytics import auto_pause_all_cases  # noqa: E402

LOCK_KEY = 0x57494E4453434844


async def handler(request: Request) -> Response:
    expected = os.getenv("CRON_SECRET", "").strip()
    if not expected or request.headers.get("authorization", "") != f"Bearer {expected}":
        return Response(status_code=404)
    await init_pool()
    pool = get_pool()
    try:
        async with pool.connection() as conn:
            row = await (await conn.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired", (LOCK_KEY,)
            )).fetchone()
            if not row or not row["acquired"]:
                return Response(content='{"status":"already_running"}', media_type="application/json", status_code=202)
            fence = ConnectionFence(conn)
            try:
                async with fenced_connection(fence):
                    paused = await auto_pause_all_cases()
                    await conn.commit()
                return Response(
                    content='{"status":"ok","paused":%d}' % len(paused),
                    media_type="application/json",
                )
            finally:
                fence.revoke()
                await conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
                await conn.commit()
    finally:
        await close_pool()
