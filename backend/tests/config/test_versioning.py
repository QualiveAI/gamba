import pytest

from app.db import get_conn
from core.config.versioning import create_version, activate_config, rollback, get_active_config


@pytest.mark.asyncio
async def test_create_and_activate():
    tenant = f"t-{pytest.current_test_id()}" if hasattr(pytest, "current_test_id") else "tenant-x"
    tenant = "tenant-test"
    async with get_conn() as conn:
        await conn.execute("DELETE FROM tenant_config_versions WHERE tenant = %s", (tenant,))
        await conn.commit()
    v1 = await create_version(tenant, {"a": 1})
    v2 = await create_version(tenant, {"a": 2})
    assert v2 == v1 + 1
    assert v2 != v1
    await activate_config(tenant, v1)
    active = await get_active_config(tenant)
    assert active["version"] == v1
    assert active["config"]["a"] == 1
    await activate_config(tenant, v2)
    active2 = await get_active_config(tenant)
    assert active2["version"] == v2
    assert active2["version"] != v1


@pytest.mark.asyncio
async def test_rollback_previous():
    tenant = "tenant-rb"
    async with get_conn() as conn:
        await conn.execute("DELETE FROM tenant_config_versions WHERE tenant = %s", (tenant,))
        await conn.commit()
    v1 = await create_version(tenant, {"x": 1})
    v2 = await create_version(tenant, {"x": 2})
    await activate_config(tenant, v2)
    await rollback(tenant)
    active = await get_active_config(tenant)
    assert active["version"] == v1
    assert active["version"] != v2


@pytest.mark.asyncio
async def test_activate_missing_version_raises():
    tenant = "tenant-missing"
    async with get_conn() as conn:
        await conn.execute("DELETE FROM tenant_config_versions WHERE tenant = %s", (tenant,))
        await conn.commit()
    with pytest.raises(ValueError):
        await activate_config(tenant, 999)


@pytest.mark.asyncio
async def test_pinned_flag_persisted():
    tenant = "tenant-pinned"
    async with get_conn() as conn:
        await conn.execute("DELETE FROM tenant_config_versions WHERE tenant = %s", (tenant,))
        await conn.commit()
    v = await create_version(tenant, {"p": True}, pinned=True)
    versions = await list_versions(tenant) if False else None
    async with get_conn() as conn:
        row = await (await conn.execute(
            "SELECT pinned FROM tenant_config_versions WHERE tenant = %s AND version = %s", (tenant, v)
        )).fetchone()
    assert row["pinned"] is True
    assert row["pinned"] != False