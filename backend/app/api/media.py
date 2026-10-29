import hashlib
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.api.deps import require_admin
from app.db import get_conn
from core.media.local_storage import validate_image

router = APIRouter(tags=["media"])


@router.post("/admin/media")
async def upload_media(file: UploadFile = File(...), admin=Depends(require_admin)):  # noqa: E501, B008  # noqa: B008
    data = await file.read()
    if len(data) > 512 * 1024:
        raise HTTPException(status_code=400, detail="too large")  # noqa: B904
    try:
        w, h, ct = validate_image(data)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid image")  # noqa: B904
    sha = hashlib.sha256(data).hexdigest()
    async with get_conn() as conn:
        row = await (
            await conn.execute("SELECT id FROM media_assets WHERE sha256 = %s", (sha,))
        ).fetchone()
        if row:
            return {"media_id": row["id"]}
        # store file
        import os

        os.makedirs("./media", exist_ok=True)
        path = os.path.join("./media", sha + ".webp")
        if not os.path.exists(path):
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            img = img.convert("RGB")
            img.thumbnail((512, 512))
            img.save(path, format="WEBP")
        cur = await conn.execute(
            "INSERT INTO media_assets (owner_tenant, kind, storage_key, content_type, width, height, bytes, sha256, created_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",  # noqa: E501
            ("default", "image", sha + ".webp", ct, w, h, len(data), sha, admin["id"]),
        )
        mid = (await cur.fetchone())["id"]
        await conn.commit()
    return {"media_id": mid}


@router.get("/media/{media_id}")
async def serve_media(media_id: int):
    async with get_conn() as conn:
        row = await (
            await conn.execute(
                "SELECT storage_key, content_type FROM media_assets WHERE id = %s", (media_id,)
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")  # noqa: B904
    import os

    path = os.path.join("./media", row["storage_key"])
    with open(path, "rb") as f:
        data = f.read()
    return Response(
        content=data,
        media_type=row["content_type"],
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
