import pytest

from core.config.versioning import create_version, activate_config, get_active_config


@pytest.mark.asyncio
async def test_config_rollback_pinned():
    tenant = "chaos-tenant"
    v1 = await create_version(tenant, {"a": 1})
    v2 = await create_version(tenant, {"a": 2})
    await activate_config(tenant, v1)

    # open session with config_version_id=1
    opening = {"config_version_id": v1}

    # activate v2
    await activate_config(tenant, v2)

    # settle
    active = await get_active_config(tenant)
    assert active["version"] == v2

    # pinned: opening still has v1
    assert opening["config_version_id"] == v1
    assert opening["config_version_id"] != v2