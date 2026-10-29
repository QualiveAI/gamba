import json
from typing import Any

from app.db import get_conn


def _normalize(args, kwargs, names):
    conn = kwargs.get("conn")
    values = {}
    idx = 0
    if args and hasattr(args[0], "execute"):
        conn = args[0]
        idx = 1
    for name in names:
        if name in kwargs:
            values[name] = kwargs[name]
        elif idx < len(args):
            values[name] = args[idx]
            idx += 1
        else:
            values[name] = None
    return conn, values


async def create_version(*args, **kwargs):
    conn, v = _normalize(args, kwargs, ["tenant", "config", "version", "pinned"])
    tenant = v["tenant"]
    config = v["config"] if v["config"] is not None else {}
    version = v["version"]
    pinned = bool(v["pinned"]) if v["pinned"] is not None else False
    if tenant is None:
        raise ValueError("tenant is required")
    if not isinstance(config, str):
        config = json.dumps(config)
    async def body(conn):
        if version is None:
            row = await (await conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS m FROM tenant_config_versions WHERE tenant = %s",
                (tenant,),
            )).fetchone()
            version_local = int(row["m"]) + 1
        else:
            version_local = int(version)
        await conn.execute(
            "INSERT INTO tenant_config_versions (tenant, version, config, pinned) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (tenant, version) DO UPDATE "
            "SET config = EXCLUDED.config, pinned = EXCLUDED.pinned",
            (tenant, version_local, config, pinned),
        )
        await conn.commit()
        return version_local
    if conn is not None and hasattr(conn, "execute"):
        return await body(conn)
    async with get_conn() as c:
        return await body(c)


async def activate_config(*args, **kwargs):
    conn, v = _normalize(args, kwargs, ["tenant", "version"])
    tenant = v["tenant"]
    version = v["version"]
    if tenant is None or version is None:
        raise ValueError("tenant and version are required")
    async def body(conn):
        row = await (await conn.execute(
            "SELECT id FROM tenant_config_versions WHERE tenant = %s AND version = %s",
            (tenant, int(version)),
        )).fetchone()
        if row is None:
            raise ValueError("version not found")
        await conn.execute(
            "UPDATE tenant_config_versions SET is_active = FALSE WHERE tenant = %s",
            (tenant,),
        )
        await conn.execute(
            "UPDATE tenant_config_versions SET is_active = TRUE, activated_at = now() "
            "WHERE tenant = %s AND version = %s",
            (tenant, int(version)),
        )
        await conn.commit()
        return {"tenant": tenant, "version": int(version), "status": "activated"}
    if conn is not None and hasattr(conn, "execute"):
        return await body(conn)
    async with get_conn() as c:
        return await body(c)


async def rollback(*args, **kwargs):
    conn, v = _normalize(args, kwargs, ["tenant", "version"])
    tenant = v["tenant"]
    version = v["version"]
    async def body(conn):
        if version is None:
            row = await (await conn.execute(
                "SELECT version FROM tenant_config_versions WHERE tenant = %s AND is_active = TRUE",
                (tenant,),
            )).fetchone()
            current = int(row["version"]) if row else None
            prev = await (await conn.execute(
                "SELECT version FROM tenant_config_versions WHERE tenant = %s AND version < %s ORDER BY version DESC LIMIT 1",
                (tenant, current if current is not None else 10**9),
            )).fetchone()
            if prev is None:
                raise ValueError("no previous version")
            version_local = int(prev["version"])
        else:
            version_local = int(version)
        await conn.execute(
            "UPDATE tenant_config_versions SET is_active = FALSE WHERE tenant = %s",
            (tenant,),
        )
        await conn.execute(
            "UPDATE tenant_config_versions SET is_active = TRUE, activated_at = now() "
            "WHERE tenant = %s AND version = %s",
            (tenant, version_local),
        )
        await conn.commit()
        return {"tenant": tenant, "version": version_local, "status": "rolled_back"}
    if conn is not None and hasattr(conn, "execute"):
        return await body(conn)
    async with get_conn() as c:
        return await body(c)

async def get_active_config(*args, **kwargs):
    conn, v = _normalize(args, kwargs, ["tenant"])
    tenant = v["tenant"]
    async def body(conn):
        row = await (await conn.execute(
            "SELECT version, config, pinned FROM tenant_config_versions WHERE tenant = %s AND is_active = TRUE",
            (tenant,),
        )).fetchone()
        if row is None:
            return None
        cfg = row["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        return {"tenant": tenant, "version": int(row["version"]), "config": cfg, "pinned": bool(row["pinned"])}
    if conn is not None and hasattr(conn, "execute"):
        return await body(conn)
    async with get_conn() as c:
        return await body(c)


async def list_versions(*args, **kwargs):
    conn, v = _normalize(args, kwargs, ["tenant"])
    tenant = v["tenant"]
    async def body(conn):
        rows = await (await conn.execute(
            "SELECT version, is_active, pinned, created_at FROM tenant_config_versions WHERE tenant = %s ORDER BY version",
            (tenant,),
        )).fetchall()
        return [dict(r) for r in rows]
    if conn is not None and hasattr(conn, "execute"):
        return await body(conn)
    async with get_conn() as c:
        return await body(c)

