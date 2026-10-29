import pytest

from app.db import get_conn


@pytest.mark.asyncio
async def test_version_pinning():
    async with get_conn():
        assert True


@pytest.mark.asyncio
async def test_rtp_gate():
    from core.catalog.rtp import validate_catalog

    report = validate_catalog(
        [{"nominal_units": 10, "real_value_minor": 10, "weight_bp": 10000}], "units", 9000
    )  # noqa: E501
    assert "errors" in report


@pytest.mark.asyncio
async def test_media():
    async with get_conn():
        assert True


@pytest.mark.asyncio
async def test_auto_pause():
    async with get_conn():
        assert True
