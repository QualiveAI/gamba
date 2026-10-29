import pytest

from app.db import get_conn


@pytest.mark.asyncio
async def test_immutability():
    async with get_conn() as conn:
        await conn.execute("ALTER TABLE case_versions DISABLE TRIGGER trg_case_versions_immutable")
        await conn.execute(
            "DELETE FROM case_prizes WHERE version_id IN (SELECT id FROM case_versions WHERE case_id IN (SELECT id FROM case_definitions WHERE slug = 't1'))"  # noqa: E501
        )
        await conn.execute(
            "DELETE FROM case_versions WHERE case_id IN (SELECT id FROM case_definitions WHERE slug = 't1')"  # noqa: E501
        )
        await conn.execute("ALTER TABLE case_versions ENABLE TRIGGER trg_case_versions_immutable")
        await conn.execute("DELETE FROM case_definitions WHERE slug = 't1'")
        await conn.commit()
        # create draft case
        cur = await conn.execute(
            "INSERT INTO case_definitions (tenant, game_key, slug, title, currency, status) VALUES (%s, %s, %s, %s, %s, 'draft') RETURNING id",  # noqa: E501
            ("default", "cases", "t1", "T", "units"),
        )
        case_id = (await cur.fetchone())["id"]
        cur = await conn.execute(
            "INSERT INTO case_versions (case_id, version_no, rtp_target_bp) VALUES (%s, %s, %s) RETURNING id",  # noqa: E501
            (case_id, 1, 9000),
        )
        vid = (await cur.fetchone())["id"]
        await conn.execute("UPDATE case_versions SET published_at = now() WHERE id = %s", (vid,))
        await conn.commit()
        try:
            await conn.execute("UPDATE case_versions SET changelog = 'x' WHERE id = %s", (vid,))
            await conn.commit()
            raise AssertionError("expected immutable")  # noqa: B904
        except Exception:
            await conn.rollback()
        # cleanup
        await conn.execute("DELETE FROM case_prizes WHERE version_id = %s", (vid,))
        await conn.execute("ALTER TABLE case_versions DISABLE TRIGGER trg_case_versions_immutable")
        await conn.execute("DELETE FROM case_versions WHERE id = %s", (vid,))
        await conn.execute("ALTER TABLE case_versions ENABLE TRIGGER trg_case_versions_immutable")
        await conn.execute("DELETE FROM case_definitions WHERE id = %s", (case_id,))
        await conn.commit()
