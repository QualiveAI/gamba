import pytest

from app.db import get_conn
from core.admin.case_builder.router import (
    create_case,
    patch_case,
    create_version,
    put_prizes,
    preview,
    publish,
    archive,
    versions,
)
from fastapi import HTTPException


async def _ensure_user():
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (telegram_id, balance_units, region, created_at) "
            "VALUES (%s, 0, 'US', now()) ON CONFLICT (telegram_id) DO NOTHING",
            (999999,),
        )
        await conn.commit()
        row = await (await conn.execute(
            "SELECT id FROM users WHERE telegram_id = %s", (999999,)
        )).fetchone()
    return row["id"]


async def _cleanup_case(slug):
    async with get_conn() as conn:
        await conn.execute(
            "DELETE FROM case_prizes WHERE version_id IN ("
            "  SELECT id FROM case_versions WHERE case_id IN ("
            "    SELECT id FROM case_definitions WHERE slug = %s))",
            (slug,),
        )
        await conn.execute(
            "DELETE FROM case_versions WHERE case_id IN ("
            "  SELECT id FROM case_definitions WHERE slug = %s)",
            (slug,),
        )
        await conn.execute(
            "DELETE FROM case_definitions WHERE slug = %s", (slug,),
        )
        await conn.commit()
@pytest.mark.asyncio
async def test_create_draft():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("test-draft")
    result = await create_case(
        {"game_key": "cases", "slug": "test-draft", "title": "Test Draft"},
        admin=admin,
    )
    assert result["status"] == "draft"
    assert result["id"] is not None
    assert result["status"] != "published"
    await _cleanup_case("test-draft")
@pytest.mark.asyncio
async def test_create_draft_duplicate_slug_rejected():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("dup-slug")
    await create_case(
        {"game_key": "cases", "slug": "dup-slug", "title": "First"},
        admin=admin,
    )
    with pytest.raises(HTTPException) as exc:
        await create_case(
            {"game_key": "cases", "slug": "dup-slug", "title": "Second"},
            admin=admin,
        )
    assert exc.value.status_code == 409
    assert exc.value.status_code != 200
    await _cleanup_case("dup-slug")
@pytest.mark.asyncio
async def test_patch_draft():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("patch-test")
    case = await create_case(
        {"game_key": "cases", "slug": "patch-test", "title": "Original"},
        admin=admin,
    )
    cid = case["id"]
    result = await patch_case(cid, {"title": "Patched"}, admin=admin)
    assert result["ok"] is True
    assert result["ok"] != False
    await _cleanup_case("patch-test")
@pytest.mark.asyncio
async def test_patch_published_returns_409():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("pub-patch")
    case = await create_case(
        {"game_key": "cases", "slug": "pub-patch", "title": "To Publish"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    await put_prizes(cid, vid, {"prizes": [{"label": "p1", "nominal_units": 100, "real_value_minor": 100, "weight_bp": 10000}]}, admin=admin)
    await publish(cid, vid, {"changelog": "pub", "confirm": "PUBLISH v1"}, admin=admin)
    with pytest.raises(HTTPException) as exc:
        await patch_case(cid, {"title": "Too Late"}, admin=admin)
    assert exc.value.status_code == 409
    assert exc.value.detail == "ImmutableVersion"
    await _cleanup_case("pub-patch")
@pytest.mark.asyncio
async def test_add_prizes_weights_must_sum_10000():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("weights-test")
    case = await create_case(
        {"game_key": "cases", "slug": "weights-test", "title": "Weights Test"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    with pytest.raises(HTTPException) as exc:
        await put_prizes(cid, vid, {"prizes": [{"label": "p1", "nominal_units": 100, "real_value_minor": 100, "weight_bp": 9999}]}, admin=admin)
    assert exc.value.status_code == 400
    assert exc.value.status_code != 200
    await _cleanup_case("weights-test")
@pytest.mark.asyncio
async def test_freebet_cap_enforced():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("freebet-test")
    case = await create_case(
        {"game_key": "cases", "slug": "freebet-test", "title": "Freebet Test", "currency": "freebets"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    with pytest.raises(HTTPException) as exc:
        await put_prizes(cid, vid, {"prizes": [{"label": "fb", "nominal_units": 100, "real_value_minor": 2100, "weight_bp": 10000}]}, admin=admin)
    assert exc.value.status_code == 400
    assert exc.value.status_code != 200
    await _cleanup_case("freebet-test")
@pytest.mark.asyncio
async def test_preview_returns_rtp():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("preview-test")
    case = await create_case(
        {"game_key": "cases", "slug": "preview-test", "title": "Preview Test"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    await put_prizes(cid, vid, {"prizes": [{"label": "p1", "nominal_units": 100, "real_value_minor": 100, "weight_bp": 10000}]}, admin=admin)
    result = await preview(cid, vid, admin=admin)
    assert "rtp_bp" in result
    assert "ev_minor" in result
    assert "warnings" in result
    assert result["rtp_bp"] is not None
    await _cleanup_case("preview-test")
@pytest.mark.asyncio
async def test_preview_nonexistent_version_returns_404():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    with pytest.raises(HTTPException) as exc:
        await preview(1, 999, admin=admin)
    assert exc.value.status_code == 404
    assert exc.value.status_code != 200
@pytest.mark.asyncio
async def test_publish_requires_typed_confirmation():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("confirm-test")
    case = await create_case(
        {"game_key": "cases", "slug": "confirm-test", "title": "Confirm Test"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    await put_prizes(cid, vid, {"prizes": [{"label": "p1", "nominal_units": 100, "real_value_minor": 100, "weight_bp": 10000}]}, admin=admin)
    with pytest.raises(HTTPException) as exc:
        await publish(cid, vid, {"changelog": "no confirm"}, admin=admin)
    assert exc.value.status_code == 400
    assert exc.value.status_code != 200
    await _cleanup_case("confirm-test")
@pytest.mark.asyncio
async def test_publish_happy_path():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("happy-test")
    case = await create_case(
        {"game_key": "cases", "slug": "happy-test", "title": "Happy Path"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    await put_prizes(cid, vid, {"prizes": [{"label": "p1", "nominal_units": 100, "real_value_minor": 100, "weight_bp": 10000}]}, admin=admin)
    result = await publish(cid, vid, {"changelog": "Happy publish", "confirm": "PUBLISH v1"}, admin=admin)
    assert result["ok"] is True
    assert result["version_id"] == vid
    versions_list = await versions(cid, admin=admin)
    assert len(versions_list) >= 1
    assert len(versions_list) != 0
    await _cleanup_case("happy-test")
@pytest.mark.asyncio
async def test_edit_published_returns_409():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("immutable-test")
    case = await create_case(
        {"game_key": "cases", "slug": "immutable-test", "title": "Immutable"},
        admin=admin,
    )
    cid = case["id"]
    ver = await create_version(cid, {"rtp_target_bp": 9000, "changelog": "v1"}, admin=admin)
    vid = ver["version_id"]
    await put_prizes(cid, vid, {"prizes": [{"label": "p1", "nominal_units": 100, "real_value_minor": 100, "weight_bp": 10000}]}, admin=admin)
    await publish(cid, vid, {"changelog": "Publish", "confirm": "PUBLISH v1"}, admin=admin)
    with pytest.raises(HTTPException) as exc:
        await patch_case(cid, {"title": "Too Late"}, admin=admin)
    assert exc.value.status_code == 409
    assert exc.value.detail == "ImmutableVersion"
    await _cleanup_case("immutable-test")
@pytest.mark.asyncio
async def test_archive_blocks_new_sessions():
    admin_id = await _ensure_user()
    admin = {"id": admin_id}
    await _cleanup_case("archive-test")
    case = await create_case(
        {"game_key": "cases", "slug": "archive-test", "title": "Archive Test"},
        admin=admin,
    )
    cid = case["id"]
    result = await archive(cid, admin=admin)
    assert result["ok"] is True
    assert result["ok"] != False
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT status FROM case_definitions WHERE id = %s", (cid,)
        )).fetchone()
    assert row["status"] == "archived"
    assert row["status"] != "draft"
    await _cleanup_case("archive-test")