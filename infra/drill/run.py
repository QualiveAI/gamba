"""Явная локальная репетиция: только существующие images, отдельный *_test target.

Подготовка DB/role/internal network выполняется оператором отдельно. Скрипт не
читает .env, не создаёт аккаунты, не вызывает provider API и не удаляет БД/данные.
"""

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import jwt
import psycopg
from cryptography.fernet import Fernet
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
TARGET = "windrop_failover_retry_test"
NETWORK = "windrop-failover-drill-test"
DATABASE = f"postgresql://{TARGET}:synthetic-drill-only@127.0.0.1:55432/{TARGET}"
CONTAINER_DATABASE = (
    f"postgresql://{TARGET}:synthetic-drill-only@drill-db:5432/{TARGET}"
)
IMAGE = "sha256:53ce99818696dcb63a973380092bfecb0962a1fae2ba71c7f0c4d2dafed793c2"
BOT_ID = 990000001
TELEGRAM_ID = 990000002
PREFIX = "windrop-failover-retry-"
PORTS = (18181, 18182, 18183, 18184)


def docker(*args: str, timeout: int = 45) -> str:
    process = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if process.returncode:
        # Runtime env содержит исключительно synthetic keys, но не печатаем argv.
        raise RuntimeError(f"Docker {args[0]} failed: {process.stderr[-3000:]}")
    return process.stdout.strip()


def fetch(conn, query, params=()):
    return conn.execute(query, params).fetchone()


def wait_for(predicate, *, seconds=40, label):
    started = time.monotonic()
    last = None
    while time.monotonic() - started < seconds:
        try:
            value = predicate()
            if value:
                return value
        except (httpx.HTTPError, OSError) as exc:
            last = type(exc).__name__
        time.sleep(0.3)
    raise RuntimeError(f"Timeout: {label}; last={last}")


class InternalHTTP:
    def __init__(self, container):
        self.process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                container,
                "python",
                "-I",
                "/sandbox/drill/runtime.py",
                "controller",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )

    def request(self, method, url, **kwargs):
        mapping = {
            "http://127.0.0.1:18181": "http://api:18181",
            "http://127.0.0.1:18182": "http://api-standby:18182",
            "http://127.0.0.1:18183": "http://drill-proxy:18183",
            "http://127.0.0.1:18184": "http://drill-sink:18184",
        }
        for source, destination in mapping.items():
            if url.startswith(source + "/"):
                url = destination + url[len(source) :]
                break
        else:
            raise RuntimeError(
                "Controller допускает только четыре внутренних drill endpoint"
            )
        self.process.stdin.write(
            json.dumps({"method": method, "url": url, **kwargs}) + "\n"
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Internal HTTP controller завершился")
        data = json.loads(line)
        if "error" in data:
            # Недоступный proxy/API — ожидаемый результат финальной проверки.
            # Возвращаем HTTP 503, чтобы controller не превращал его в необработанный exception.
            return httpx.Response(503, headers={}, json={"detail": "drill_unavailable"})
        return httpx.Response(
            data["status"], headers=data["headers"], json=data["body"]
        )

    def get(self, url):
        return self.request("GET", url)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-test-db", required=True, choices=(TARGET,))
    options = parser.parse_args()
    assert options.target_test_db == TARGET
    for port in PORTS:
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))
    network = json.loads(docker("network", "inspect", NETWORK))[0]
    if not network["Internal"]:
        raise RuntimeError("Нужна internal сеть")
    docker("image", "inspect", IMAGE, "--format", "{{.Id}}")
    docker("image", "inspect", "caddy:2-alpine", "--format", "{{.Id}}")
    conn = psycopg.connect(
        DATABASE, autocommit=True, row_factory=dict_row, connect_timeout=3
    )
    role = fetch(
        conn,
        "SELECT current_database() AS db, current_user AS role, rolsuper, rolcreatedb, "
        "rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user",
    )
    if (
        role["db"] != TARGET
        or role["role"] != TARGET
        or any(
            role[key]
            for key in (
                "rolsuper",
                "rolcreatedb",
                "rolcreaterole",
                "rolreplication",
                "rolbypassrls",
            )
        )
    ):
        raise RuntimeError("Небезопасная DB роль")
    others = fetch(
        conn,
        "SELECT count(*) AS n FROM pg_database WHERE datallowconn AND NOT datistemplate "
        "AND datname<>current_database() AND has_database_privilege(current_user,oid,'CONNECT')",
    )
    if (
        others["n"]
        or fetch(conn, "SELECT count(*) AS n FROM pg_tables WHERE schemaname='public'")[
            "n"
        ]
    ):
        raise RuntimeError("Нужна пустая DB и роль без CONNECT к другим БД")

    # Миграции идут только в явно проверенный новый target, без импорта app settings.
    migration_env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "DATABASE_URL": DATABASE,
    }
    migrated = subprocess.run(
        [sys.executable, "-I", str(ROOT / "backend/tools/migrate.py")],
        env=migration_env,
        cwd=tempfile.gettempdir(),
        capture_output=True,
        text=True,
        timeout=40,
        check=False,
    )
    if migrated.returncode:
        raise RuntimeError(f"Migration failed, exit={migrated.returncode}")
    if fetch(conn, "SELECT count(*) AS n FROM schema_migrations")["n"] != 18:
        raise RuntimeError("Ожидаются ровно 18 согласованных миграций")

    jwt_key = "synthetic-drill-jwt-" + base64.urlsafe_b64encode(os.urandom(32)).decode()
    settings = {
        "WINDROP_TESTING": "1",
        "WINDROP_DRILL_TARGET": TARGET,
        "ENV": "test",
        "DATABASE_URL": CONTAINER_DATABASE,
        "REDIS_URL": "redis://drill-redis:6379/15",
        "BOT_MODE": "webhook",
        "BOT_TOKEN": f"{BOT_ID}:SYNTHETIC_NOT_A_REAL_BOT_TOKEN",
        "BOT_USERNAME": "synthetic_drill_bot",
        "JWT_SECRET": jwt_key,
        "FERNET_KEY": Fernet.generate_key().decode(),
        "TELEGRAM_WEBHOOK_SECRET": "SYNTHETIC_DRILL_WEBHOOK_SECRET_ONLY",
        "WEBAPP_URL": "https://drill.example.invalid/app/",
        "PUBLIC_BASE_URL": "https://drill.example.invalid",
        "PAYMENTS_MODE": "disabled",
        "MANAGED_BOTS_ENABLED": "false",
        "ALLOW_GUEST_AUTH": "false",
        "STARS_ENABLED": "false",
        "GIFTS_ENABLED": "false",
        "PAYMENT_WEB_ENABLED": "false",
        "GIFTCARD_MODE": "sandbox",
        "GIFTCARD_REDEMPTION_ENABLED": "true",
        "GIFTCARD_FERNET_KEY": Fernet.generate_key().decode(),
        "GIFTCARD_FINGERPRINT_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "HEALTHCHECK_BOT_TOKEN": "",
        "HEALTHCHECK_TARGET_CHAT_ID": "",
        "METRICS_TOKEN": "",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    mounts = []
    for directory in ("app", "core", "plugins", "configs", "locales"):
        mounts.extend(
            [
                "--mount",
                f"type=bind,source={ROOT / 'backend' / directory},target=/sandbox/{directory},readonly",
            ]
        )
    mounts.extend(
        [
            "--mount",
            f"type=bind,source={ROOT / 'infra/drill'},target=/sandbox/drill,readonly",
        ]
    )
    containers = []
    results = {
        "target": TARGET,
        "migrations": 18,
        "telegram": "synthetic injected sink; no live requests",
    }
    scratch = Path(tempfile.mkdtemp(prefix="windrop-failover-drill-"))
    print(f"DRILL_STARTED target={TARGET} artifacts={scratch}", flush=True)

    def run(name, *command, aliases=(), ports=(), detached=True):
        full_name = PREFIX + name + "-test"
        args = [
            "run",
            "--pull",
            "never",
            "--name",
            full_name,
            "--network",
            NETWORK,
            "--label",
            "windrop.drill=failover-test",
            "--read-only",
            "--init",
            "--tmpfs",
            "/tmp:rw,nosuid,size=32m",
            "--workdir",
            "/sandbox",
        ]
        if detached:
            args.append("-d")
        for alias in aliases:
            args.extend(["--network-alias", alias])
        # На internal bridge Docker29 host port mapping не действует. HTTP controller
        # находится в этой же сети, ни один порт приложения на host не публикуется.
        for key, value in settings.items():
            args.extend(["-e", f"{key}={value}"])
        args.extend(mounts)
        args.extend(
            [
                "--entrypoint",
                "python",
                IMAGE,
                "-I",
                "/sandbox/drill/runtime.py",
                *command,
            ]
        )
        containers.append(full_name)
        return docker(*args)

    def stop(name, *, abrupt=False):
        full_name = PREFIX + name + "-test"
        docker(
            "kill" if abrupt else "stop",
            *([] if abrupt else ["--time", "10"]),
            full_name,
        )

    client = None
    try:
        seeded = json.loads(run("seed", "seed", detached=False))
        results["seed"] = seeded
        user_id, sku_id = seeded["user_id"], seeded["sku_id"]
        token = jwt.encode(
            {
                "sub": str(user_id),
                "iat": int(time.time()),
                "exp": int(time.time()) + 3600,
                "scope": "primary",
                "auth_bot_id": BOT_ID,
            },
            jwt_key,
            algorithm="HS256",
        )
        authorization = {"Authorization": f"Bearer {token}"}
        run("sink", "sink", aliases=("drill-sink",), ports=(18184,))
        client = InternalHTTP(PREFIX + "sink-test")
        run(
            "primary",
            "api",
            "--instance",
            "primary",
            "--port",
            "18181",
            aliases=("api",),
            ports=(18181,),
        )
        run(
            "standby",
            "api",
            "--instance",
            "standby",
            "--port",
            "18182",
            aliases=("api-standby",),
            ports=(18182,),
        )
        for port in (18181, 18182):
            wait_for(
                lambda p=port: (
                    client.get(f"http://127.0.0.1:{p}/health/ready").status_code == 200
                ),
                label=f"API ready {port}",
            )
        wait_for(
            lambda: client.get("http://127.0.0.1:18184/stats").status_code == 200,
            label="sink ready",
        )
        caddy = (ROOT / "infra/Caddyfile.failover").read_text(encoding="utf-8")
        caddy = caddy.replace("api:8000", "api:18181").replace(
            "api-standby:8000", "api-standby:18182"
        )
        config = scratch / "Caddyfile"
        config.write_text(caddy, encoding="utf-8")
        caddy_name = PREFIX + "proxy-test"
        containers.append(caddy_name)
        docker(
            "run",
            "--pull",
            "never",
            "-d",
            "--name",
            caddy_name,
            "--network",
            NETWORK,
            "--label",
            "windrop.drill=failover-test",
            "--network-alias",
            "drill-proxy",
            "-e",
            "PUBLIC_DOMAIN=:18183",
            "--mount",
            f"type=bind,source={config},target=/etc/caddy/Caddyfile,readonly",
            "caddy:2-alpine",
            "caddy",
            "run",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        base = "http://127.0.0.1:18183"
        initial = wait_for(
            lambda: (
                r
                if (r := client.get(base + "/giftcards/catalog")).status_code == 200
                else None
            ),
            label="proxy ready",
        )
        assert initial.headers["x-drill-instance"] == "primary"
        results["primary_initial"] = True
        assert client.get(base + "/metrics").status_code == 404
        assert client.get(base + "/health/ready").status_code == 404
        request = {"sku_id": sku_id, "idempotency_key": "TEST-ONLY-FAILOVER-REDEMPTION"}
        first = client.post(base + "/redemptions", json=request, headers=authorization)
        assert first.status_code == 200, f"Redemption HTTP={first.status_code}"
        order = first.json()
        assert first.headers["x-drill-instance"] == "primary"
        started = time.monotonic()
        stop("primary")
        switched = wait_for(
            lambda: (
                r
                if (r := client.get(base + "/giftcards/catalog")).status_code == 200
                and r.headers.get("x-drill-instance") == "standby"
                else None
            ),
            label="failover to standby",
        )
        results["standby_switch_seconds"] = round(time.monotonic() - started, 2)
        assert switched.status_code == 200
        replay = client.post(base + "/redemptions", json=request, headers=authorization)
        assert replay.status_code == 200 and replay.json()["id"] == order["id"]
        assert replay.headers["x-drill-instance"] == "standby"
        results["cross_instance_idempotency"] = True
        assert (
            fetch(conn, "SELECT balance_units FROM users WHERE id=%s", (user_id,))[
                "balance_units"
            ]
            == 863
        )
        assert fetch(conn, "SELECT count(*) AS n FROM giftcard_redemptions")["n"] == 1
        assert (
            fetch(
                conn,
                "SELECT count(*) AS n FROM ledger_entries WHERE reason='giftcard_redemption'",
            )["n"]
            == 1
        )
        assert (
            fetch(
                conn,
                "SELECT count(*) AS n FROM bot_outbox WHERE kind='giftcard_delivery'",
            )["n"]
            == 1
        )

        run("worker-crash", "worker", "--pause-after-send")
        wait_for(
            lambda: (
                client.get("http://127.0.0.1:18184/stats").json()["giftcard_send_count"]
                == 1
            ),
            label="synthetic send accepted before receipt",
        )
        claimed = fetch(
            conn,
            "SELECT status, attempts, lease_until, now() AS observed FROM bot_outbox WHERE kind='giftcard_delivery'",
        )
        assert claimed["status"] == "processing" and claimed["attempts"] == 1
        before = fetch(
            conn,
            "SELECT inventory_id,status FROM giftcard_redemptions WHERE id=%s",
            (order["id"],),
        )
        assert before["status"] == "delivering"
        stop("worker-crash", abrupt=True)
        run("worker-resumed", "worker")
        time.sleep(3)
        assert (
            client.get("http://127.0.0.1:18184/stats").json()["giftcard_send_count"]
            == 1
        )
        results["lease_seconds"] = 180
        remaining = max(
            0, (claimed["lease_until"] - claimed["observed"]).total_seconds()
        )
        print(f"WAITING_FOR_REAL_LEASE seconds={remaining:.1f}", flush=True)
        resume_started = time.monotonic()
        wait_for(
            lambda: (
                fetch(
                    conn, "SELECT status FROM bot_outbox WHERE kind='giftcard_delivery'"
                )["status"]
                == "done"
            ),
            seconds=200,
            label="natural lease reclaim and completion",
        )
        results["resume_to_done_seconds"] = round(time.monotonic() - resume_started, 2)
        after = fetch(
            conn,
            "SELECT inventory_id,status,delivery_attempts FROM giftcard_redemptions WHERE id=%s",
            (order["id"],),
        )
        sends = client.get("http://127.0.0.1:18184/stats").json()
        assert (
            sends["giftcard_send_count"] == 2 and sends["unique_giftcard_messages"] == 1
        )
        assert sends["all_giftcard_protected"] is True
        assert (
            after["status"] == "issued"
            and before["inventory_id"] == after["inventory_id"]
        )
        assert after["delivery_attempts"] == 2
        assert (
            fetch(
                conn,
                "SELECT count(*) AS n FROM giftcard_inventory WHERE status='issued'",
            )["n"]
            == 1
        )
        assert (
            fetch(
                conn,
                "SELECT count(*) AS n FROM giftcard_inventory WHERE status='available'",
            )["n"]
            == 1
        )
        assert (
            fetch(conn, "SELECT balance_units FROM users WHERE id=%s", (user_id,))[
                "balance_units"
            ]
            == 863
        )
        assert (
            fetch(
                conn,
                "SELECT count(*) AS n FROM ledger_entries WHERE reason='giftcard_redemption'",
            )["n"]
            == 1
        )
        results["giftcard_recovery"] = {
            "synthetic_sends": 2,
            "distinct_card_messages": 1,
            "issued_cards": 1,
            "debits": 1,
            "coins_remaining": 863,
            "duplicate_external_send_expected": True,
        }

        update = {
            "update_id": 990000003,
            "message": {
                "message_id": 11,
                "from": {"id": TELEGRAM_ID, "is_bot": False},
                "chat": {"id": TELEGRAM_ID, "type": "private"},
                "text": "/balance",
            },
        }
        headers = {
            "X-Telegram-Bot-Api-Secret-Token": settings["TELEGRAM_WEBHOOK_SECRET"]
        }
        for _ in range(5):
            reply = client.post(
                base + f"/bot/webhook/{BOT_ID}", json=update, headers=headers
            )
            assert reply.status_code == 200
        wait_for(
            lambda: (
                fetch(conn, "SELECT count(*) AS n FROM bot_inbox WHERE status='done'")[
                    "n"
                ]
                == 1
            ),
            label="duplicate webhook processing",
        )
        wait_for(
            lambda: (
                fetch(
                    conn,
                    "SELECT count(*) AS n FROM bot_outbox WHERE kind='bot_message' AND status='done'",
                )["n"]
                == 1
            ),
            label="single command outbox completion",
        )
        assert fetch(conn, "SELECT count(*) AS n FROM bot_inbox")["n"] == 1
        assert (
            fetch(
                conn, "SELECT count(*) AS n FROM bot_outbox WHERE kind='bot_message'"
            )["n"]
            == 1
        )
        results["webhook_dedupe"] = {
            "http_deliveries": 5,
            "inbox_rows": 1,
            "command_outbox_rows": 1,
        }
        stop("worker-resumed")
        run("worker-final", "worker")
        time.sleep(3)
        assert client.get("http://127.0.0.1:18184/stats").json()["send_count"] == 3
        results["completed_rows_not_resent_after_second_restart"] = True

        docker("start", PREFIX + "primary-test")
        returned = wait_for(
            lambda: (
                r
                if (r := client.get(base + "/giftcards/catalog")).status_code == 200
                and r.headers.get("x-drill-instance") == "primary"
                else None
            ),
            seconds=45,
            label="primary recovery and failback",
        )
        assert returned.status_code == 200
        results["primary_failback"] = True
        stop("primary")
        stop("standby")
        unavailable = client.get(base + "/giftcards/catalog")
        assert unavailable.status_code in (502, 503)
        results["both_apis_down_status"] = unavailable.status_code
        results["status"] = "passed"
        print("DRILL_RESULT " + json.dumps(results, ensure_ascii=False), flush=True)
    except Exception:
        for container in containers:
            try:
                logs = docker("logs", "--tail", "12", container)
                (scratch / f"{container}.log").write_text(logs, encoding="utf-8")
            except (OSError, RuntimeError):
                # Сохраняем первичную ошибку drill; отсутствие логов не меняет verdict.
                print(f"DRILL_LOG_UNAVAILABLE {container}", flush=True)
        raise
    finally:
        if client is not None:
            try:
                client.close()
            except (OSError, RuntimeError, subprocess.SubprocessError):
                print("CONTROLLER_CLOSE_REQUIRES_CHECK", flush=True)
        conn.close()
        for container in containers:
            try:
                if (
                    docker("inspect", container, "--format", "{{.State.Running}}")
                    == "true"
                ):
                    docker("stop", "--time", "10", container)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                print(f"CLEANUP_REQUIRES_CHECK {container}", flush=True)
        # Только созданные процессы останавливаются; DB/role/data не удаляются.
        (scratch / "result.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"DRILL_ARTIFACTS {scratch}", flush=True)


if __name__ == "__main__":
    main()
