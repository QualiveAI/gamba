import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Response
from starlette.requests import Request

from app import main
from app.ops import health


class Cursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row


class Database:
    def __init__(self, **overrides):
        self.flags = {
            "recovery": False,
            "read_only": "off",
            "migrations": True,
            "registry": True,
            "inbox": True,
            "outbox": True,
            "marker": True,
            "guest": True,
            "permission": True,
            "delay": 0,
            **overrides,
        }
        self.queries = []

    @asynccontextmanager
    async def connection(self, *, timeout):
        await asyncio.sleep(self.flags["delay"])
        yield self

    async def execute(self, query, params=None):
        self.queries.append((query, params))
        if "pg_is_in_recovery" in query:
            return Cursor({key: self.flags[key] for key in ("recovery", "read_only")})
        if "to_regclass" in query:
            return Cursor(
                {key: self.flags[key] for key in ("migrations", "registry", "inbox", "outbox")}
            )
        if "FROM public.schema_migrations" in query:
            return Cursor({"exists": True} if self.flags["marker"] else None)
        if "information_schema.columns" in query:
            return Cursor({"exists": True} if self.flags["guest"] else None)
        if "SELECT status" in query and not self.flags["permission"]:
            raise PermissionError("Пароль не должен попасть в health response")
        return Cursor()


@pytest.fixture
def probe_settings(monkeypatch):
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            readiness_timeout_seconds=0.02,
            expected_schema_version="0018_giftcard_redemption.sql",
            redis_url="redis://test.invalid/15",
        ),
    )


async def test_database_ready_and_checks_expected_marker(monkeypatch, probe_settings):
    database = Database()
    monkeypatch.setattr(health, "get_pool", lambda: database)
    assert await health.check_database() == {"db": "ok", "schema": "ok", "outbox": "ok"}
    assert any(params == ("0018_giftcard_redemption.sql",) for _, params in database.queries)


@pytest.mark.parametrize(
    "override,failed",
    [
        ({"recovery": True}, "db"),
        ({"read_only": "on"}, "db"),
        ({"migrations": False}, "schema"),
        ({"marker": False}, "schema"),
        ({"guest": False}, "schema"),
        ({"outbox": False}, "outbox"),
        ({"inbox": False}, "outbox"),
        ({"registry": False}, "outbox"),
        ({"permission": False}, "outbox"),
        ({"delay": 0.1}, "db"),
    ],
)
async def test_database_fails_closed(monkeypatch, probe_settings, override, failed):
    monkeypatch.setattr(health, "get_pool", lambda: Database(**override))
    result = await health.check_database()
    assert result[failed] == "fail"
    assert set(result.values()) <= {"ok", "fail"}


@pytest.mark.parametrize("broken", [False, True])
async def test_redis_closes_client_even_on_failure(monkeypatch, probe_settings, broken):
    client = SimpleNamespace(ping=AsyncMock(return_value=True), aclose=AsyncMock())
    if broken:
        client.ping.side_effect = OSError("Секретный URL не должен попасть в ответ")
    monkeypatch.setattr(health.redis, "from_url", Mock(return_value=client))
    assert await health.check_redis() == ("fail" if broken else "ok")
    client.aclose.assert_awaited_once()


async def test_readiness_requires_outbox_and_returns_503(monkeypatch):
    monkeypatch.setattr(
        health,
        "check_database",
        AsyncMock(return_value={"db": "ok", "schema": "ok", "outbox": "fail"}),
    )
    monkeypatch.setattr(health, "check_redis", AsyncMock(return_value="ok"))
    response = Response()
    result = await main.health(response)
    assert response.status_code == 503
    assert result["status"] == "fail"
    assert response.headers["Cache-Control"] == "no-store"


async def test_liveness_never_probes_dependencies(monkeypatch):
    probe = AsyncMock(side_effect=AssertionError("Liveness не должна обращаться к зависимостям"))
    monkeypatch.setattr(main, "readiness", probe)
    assert await main.liveness() == {"status": "ok"}
    probe.assert_not_called()


@pytest.mark.parametrize(
    "configured,provided,status",
    [
        ("", "", 404),
        ("  ", "", 404),
        ("secret", "", 404),
        ("secret", "wrong", 404),
        ("secret", "secret", 200),
    ],
)
async def test_metrics_requires_nonempty_matching_key(monkeypatch, configured, provided, status):
    monkeypatch.setenv("METRICS_TOKEN", configured)
    monkeypatch.setenv("METRICS_ALLOW_IPS", "127.0.0.1")
    monkeypatch.setattr(main, "render_prometheus", lambda: "up 1\n")
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-admin-token", provided.encode())],
            "client": ("127.0.0.1", 1234),
        }
    )
    assert (await main.metrics(request)).status_code == status


async def test_disabled_lifespan_never_constructs_bot_client(monkeypatch):
    from app.bot import client

    constructor = Mock(side_effect=AssertionError("Disabled не должен создавать Telegram client"))
    monkeypatch.setattr(client, "MainStarsTransport", constructor)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(bot_mode="disabled", payments_mode="disabled", stars_enabled=True),
    )
    opened, closed = AsyncMock(), AsyncMock()
    monkeypatch.setattr(main, "init_pool", opened)
    monkeypatch.setattr(main, "close_pool", closed)
    monkeypatch.setattr(main, "configure_main_bot_transport", Mock())
    async with main.lifespan(main.app):
        constructor.assert_not_called()
    opened.assert_awaited_once()
    closed.assert_awaited_once()


async def test_active_lifespan_configures_and_closes_lazy_transport(monkeypatch):
    from app.bot import client

    transport = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(client, "MainStarsTransport", Mock(return_value=transport))
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(bot_mode="webhook", payments_mode="live", stars_enabled=True),
    )
    monkeypatch.setattr(main, "init_pool", AsyncMock())
    monkeypatch.setattr(main, "close_pool", AsyncMock())
    configure = Mock()
    monkeypatch.setattr(main, "configure_main_bot_transport", configure)
    async with main.lifespan(main.app):
        configure.assert_called_once_with(transport)
    configure.assert_called_with(None)
    transport.aclose.assert_awaited_once()
