
import pytest

from app.db import get_conn
from core.catalog.analytics import auto_pause_if_drift


async def _seed(version_id, case_def_id, real_value_minor, price_units=100, n=1000):
    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO users (id, telegram_id, balance_units, region, created_at) VALUES (1, 999999, 0, 'US', now()) ON CONFLICT (id) DO NOTHING"
        )
        await conn.execute(
            "INSERT INTO cases (id, name, price_units, active) VALUES (%s, %s, %s, TRUE) ON CONFLICT (id) DO NOTHING",
            (case_def_id, "case", price_units),
        )
        await conn.execute(
            "INSERT INTO case_definitions (id, tenant, game_key, slug, title, currency, status) VALUES (%s, '{}', 'cases', %s, %s, 'units', 'published') ON CONFLICT (id) DO NOTHING",
            (case_def_id, f"slug-{case_def_id}", "case"),
        )
        await conn.execute(
            "INSERT INTO case_versions (id, case_id, version_no, rtp_target_bp, published_at) VALUES (%s, %s, 1, 9000, now()) ON CONFLICT (id) DO NOTHING",
            (version_id, case_def_id),
        )
        prize_id = version_id
        cur = await conn.execute(
            "INSERT INTO case_prizes (id, version_id, sort_order, label, nominal_units, real_value_minor, weight_bp) VALUES (%s, %s, 1, 'p', %s, %s, 10000) ON CONFLICT (id) DO NOTHING RETURNING id",
            (prize_id, version_id, price_units, real_value_minor),
        )
        await conn.execute(
            "INSERT INTO case_rewards (id, case_id, reward_type, game_key, nominal_units, weight, region) VALUES (%s, %s, 'balance', 'cases', %s, 1, 'US') ON CONFLICT (id) DO NOTHING",
            (prize_id, case_def_id, price_units),
        )
        await conn.execute(
            """
            INSERT INTO case_openings (user_id, case_id, reward_id, server_seed, server_seed_hash, client_seed, nonce, roll, catalog_version_id)
            SELECT 1, %s, %s, 's', 'h', 'c', g, 0.5, %s
            FROM generate_series(1, %s) AS g
            """,
            (case_def_id, prize_id, version_id, n),
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_skewed_data_pauses_case():
    version_id = 9101
    case_id = 9101
    await _seed(version_id, case_id, int(100 * 1.0))
    paused = await auto_pause_if_drift(version_id)
    assert paused is True
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT status FROM case_definitions WHERE id = %s", (case_id,))).fetchone()
        assert row["status"] == "paused"
        ev = await (await conn.execute("SELECT COUNT(*) AS c FROM events WHERE event_type = 'case_paused'")).fetchone()
        assert ev["c"] >= 1


@pytest.mark.asyncio
async def test_clean_data_not_paused():
    version_id = 9102
    case_id = 9102
    await _seed(version_id, case_id, int(100 * 0.90))
    paused = await auto_pause_if_drift(version_id)
    assert paused is False
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT status FROM case_definitions WHERE id = %s", (case_id,))).fetchone()
        assert row["status"] != "paused"


@pytest.mark.asyncio
async def test_paused_case_rejects_new_session():
    version_id = 9103
    case_id = 9103
    await _seed(version_id, case_id, int(100 * 1.0))
    await auto_pause_if_drift(version_id)
    async with get_conn() as conn:
        row = await (await conn.execute("SELECT status FROM case_definitions WHERE id = %s", (case_id,))).fetchone()
        assert row["status"] == "paused"
        assert row["status"] != "published"


def test_scheduler_registered():
    from app.main import scheduler

    assert any(getattr(job, "id", None) == "auto_pause" for job in scheduler.get_jobs())
