import hashlib
import json

from app.db import get_conn


async def get_catalog(
    game_key: str, currency: str, version_id: int | None = None, tenant: str = "default"
):
    async with get_conn() as conn:
        # find case definition
        row = await (
            await conn.execute(
                "SELECT id FROM case_definitions WHERE tenant = %s AND game_key = %s AND currency = %s AND status = 'published' ORDER BY id DESC LIMIT 1",  # noqa: E501
                (tenant, game_key, currency),
            )
        ).fetchone()
        if row is None:
            raise ValueError("case not found")  # noqa: B904
        case_id = row["id"]
        if version_id is None:
            vrow = await (
                await conn.execute(
                    "SELECT id, rtp_target_bp FROM case_versions WHERE case_id = %s ORDER BY version_no DESC LIMIT 1",  # noqa: E501
                    (case_id,),
                )
            ).fetchone()
        else:
            vrow = await (
                await conn.execute(
                    "SELECT id, rtp_target_bp FROM case_versions WHERE id = %s",
                    (version_id,),
                )
            ).fetchone()
        if vrow is None:
            raise ValueError("version not found")  # noqa: B904
        vid = vrow["id"]
        prizes = await (
            await conn.execute(
                "SELECT label, media_id, nominal_units, real_value_minor, weight_bp FROM case_prizes WHERE version_id = %s ORDER BY sort_order",  # noqa: E501
                (vid,),
            )
        ).fetchall()
        from core.contracts.catalog import Catalog, Prize

        plist = [
            Prize(
                p["label"],
                p["label"],
                p["nominal_units"],
                p["real_value_minor"],
                p["weight_bp"],
                p["media_id"],
            )
            for p in prizes
        ]
        # checksum
        checksum = hashlib.sha256(
            json.dumps([p.__dict__ for p in plist], sort_keys=True).encode()
        ).hexdigest()
        return Catalog(case_id, vid, currency, plist, vrow["rtp_target_bp"], checksum)
