from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.db import get_conn
from core.catalog.rtp import validate_catalog

router = APIRouter(prefix="/admin/cases", tags=["admin_cases"])


@router.post("")
async def create_case(payload: dict, admin=Depends(require_admin)):  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        try:
            cur = await conn.execute(
                "INSERT INTO case_definitions (tenant, game_key, slug, title, description, artwork_media_id, currency, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",  # noqa: E501
                (
                    payload.get("tenant", "default"),
                    payload.get("game_key"),
                    payload.get("slug"),
                    payload.get("title"),
                    payload.get("description"),
                    payload.get("artwork_media_id"),
                    payload.get("currency", "units"),
                    admin["id"],
                ),
            )
            cid = (await cur.fetchone())["id"]
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(status_code=409, detail="DuplicateSlug")  # noqa: B904
            raise
    return {"id": cid, "status": "draft"}


@router.get("")
async def list_cases(admin=Depends(require_admin)):  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, title, status, game_key, currency FROM case_definitions ORDER BY id DESC"  # noqa: E501
            )
        ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/{case_id}")
async def patch_case(case_id: int, payload: dict, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008
    async with get_conn() as conn:
        row = await (
            await conn.execute("SELECT status FROM case_definitions WHERE id = %s", (case_id,))
        ).fetchone()
        if row is None or row["status"] != "draft":
            raise HTTPException(status_code=409, detail="ImmutableVersion")  # noqa: B904
        # also check if any version is published
        pub = await (
            await conn.execute("SELECT COUNT(*) AS c FROM case_versions WHERE case_id = %s AND published_at IS NOT NULL", (case_id,))
        ).fetchone()
        if pub and pub["c"] > 0:
            raise HTTPException(status_code=409, detail="ImmutableVersion")  # noqa: B904
        await conn.execute(
            "UPDATE case_definitions SET title = COALESCE(%s, title), description = COALESCE(%s, description) WHERE id = %s AND status = 'draft'",  # noqa: E501
            (payload.get("title"), payload.get("description"), case_id),
        )
        await conn.commit()
    return {"ok": True}


@router.post("/{case_id}/versions")
async def create_version(case_id: int, payload: dict, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT COALESCE(MAX(version_no),0)+1 AS n FROM case_versions WHERE case_id = %s",
                (case_id,),
            )
        ).fetchone()
        vno = row["n"]
        cur = await conn.execute(
            "INSERT INTO case_versions (case_id, version_no, rtp_target_bp, published_by, changelog) VALUES (%s, %s, %s, %s, %s) RETURNING id",  # noqa: E501
            (
                case_id,
                vno,
                payload.get("rtp_target_bp", 9000),
                admin["id"],
                payload.get("changelog"),
            ),
        )
        vid = (await cur.fetchone())["id"]
        await conn.commit()
    return {"version_id": vid, "version_no": vno}


@router.put("/{case_id}/versions/{vid}/prizes")
async def put_prizes(case_id: int, vid: int, payload: dict, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008
    prizes = payload.get("prizes", [])
    async with get_conn() as conn:
        # ensure draft
        vrow = await (
            await conn.execute("SELECT published_at FROM case_versions WHERE id = %s", (vid,))
        ).fetchone()
        if vrow and vrow["published_at"] is not None:
            raise HTTPException(status_code=409, detail="ImmutableVersion")  # noqa: B904
        # get currency
        cdef = await (
            await conn.execute("SELECT currency FROM case_definitions WHERE id = %s", (case_id,))
        ).fetchone()
        currency = cdef["currency"] if cdef else "units"
        # validate
        from core.catalog.rtp import validate_catalog
        report = validate_catalog(prizes, currency, 9000)
        if not report["valid"]:
            raise HTTPException(status_code=400, detail=report)  # noqa: B904
        await conn.execute("DELETE FROM case_prizes WHERE version_id = %s", (vid,))
        for i, p in enumerate(prizes):
            await conn.execute(
                "INSERT INTO case_prizes (version_id, sort_order, label, media_id, nominal_units, real_value_minor, weight_bp) VALUES (%s, %s, %s, %s, %s, %s, %s)",  # noqa: E501
                (
                    vid,
                    i,
                    p.get("label"),
                    p.get("media_id"),
                    p.get("nominal_units"),
                    p.get("real_value_minor", 0),
                    p.get("weight_bp"),
                ),
            )
        await conn.commit()
    return {"ok": True}


@router.post("/{case_id}/versions/{vid}/preview")
async def preview(case_id: int, vid: int, admin=Depends(require_admin)):  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        vrow = await (
            await conn.execute("SELECT rtp_target_bp FROM case_versions WHERE id = %s", (vid,))
        ).fetchone()
        if vrow is None:
            raise HTTPException(status_code=404, detail="VersionNotFound")  # noqa: B904
        prizes = await (
            await conn.execute(
                "SELECT label, media_id, nominal_units, real_value_minor, weight_bp FROM case_prizes WHERE version_id = %s",  # noqa: E501
                (vid,),
            )
        ).fetchall()
        report = validate_catalog([dict(p) for p in prizes], "units", vrow["rtp_target_bp"])
    return {"rtp_bp": report["rtp_bp"], "ev_minor": report["ev_minor"], "warnings": report["warnings"]}


@router.post("/{case_id}/versions/{vid}/publish")
async def publish(case_id: int, vid: int, payload: dict, admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008
    async with get_conn() as conn:
        vrow = await (
            await conn.execute(
                "SELECT published_at, rtp_target_bp FROM case_versions WHERE id = %s", (vid,)
            )
        ).fetchone()
        if vrow is None:
            raise HTTPException(status_code=404, detail="VersionNotFound")  # noqa: B904
        if vrow["published_at"] is not None:
            raise HTTPException(status_code=409, detail="ImmutableVersion")  # noqa: B904
        # typed confirmation required
        if payload.get("confirm") != "PUBLISH v1":
            raise HTTPException(status_code=400, detail="TypedConfirmationRequired")  # noqa: B904
        prizes = await (
            await conn.execute(
                "SELECT label, media_id, nominal_units, real_value_minor, weight_bp FROM case_prizes WHERE version_id = %s",  # noqa: E501
                (vid,),
            )
        ).fetchall()
        cdef = await (
            await conn.execute("SELECT currency FROM case_definitions WHERE id = %s", (case_id,))
        ).fetchone()
        currency = cdef["currency"] if cdef else "units"
        report = validate_catalog([dict(p) for p in prizes], currency, vrow["rtp_target_bp"])
        if not report["valid"]:
            raise HTTPException(status_code=400, detail=report)  # noqa: B904
        await conn.execute(
            "UPDATE case_versions SET published_at = now(), published_by = %s, changelog = %s WHERE id = %s",  # noqa: E501
            (admin["id"], payload.get("changelog"), vid),
        )
        await conn.commit()
    return {"ok": True, "version_id": vid}


@router.post("/{case_id}/archive")
async def archive(case_id: int, admin=Depends(require_admin)):  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE case_definitions SET status = 'archived' WHERE id = %s", (case_id,)
        )
        await conn.commit()
    return {"ok": True}


@router.get("/{case_id}/versions")
async def versions(case_id: int, admin=Depends(require_admin)):  # noqa: B008  # noqa: B008
    async with get_conn() as conn:
        rows = await (
            await conn.execute(
                "SELECT id, version_no, rtp_target_bp, published_at, changelog FROM case_versions WHERE case_id = %s ORDER BY version_no",  # noqa: E501
                (case_id,),
            )
        ).fetchall()
    return [dict(r) for r in rows]
