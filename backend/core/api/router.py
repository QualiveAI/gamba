import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.deps import get_current_user
from app.db import get_conn
from core.config.tenants import load_tenant
from core.payments.apply import apply_event
from core.payments.intents import attach_provider_ref, create_intent, get_intent
from core.registry.registry import registry

from .schemas import (
    DepositRequest,
    DepositResponse,
    GameMeta,
    GeoMeta,
    WebhookResponse,
)

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/tenant")
async def meta_tenant(x_tenant: str = Header(default="default")):
    """Бренд и активные гео тенанта — фронт применяет это как white-label тему."""
    tenant = load_tenant(x_tenant)
    return {
        "tenant": tenant.tenant,
        "brand": {
            "name": tenant.brand.name,
            "logo_url": tenant.brand.logo_url,
            "primary_color": tenant.brand.primary_color,
        },
        "domains": {"frontend": tenant.domains.frontend, "api": tenant.domains.api},
        "geos": [g.geo for g in tenant.geos if g.enabled],
        "games": [g.game_key for g in tenant.games if g.enabled],
    }


@router.get("/games", response_model=list[GameMeta])
async def meta_games(x_tenant: str = Header(default="default")):
    tenant = load_tenant(x_tenant)
    out = []
    for g in tenant.games:
        if not g.enabled:
            continue
        plugin = registry.get("game", g.game_key)
        if plugin is None:
            continue
        out.append(
            GameMeta(
                game_key=g.game_key,
                display_name=getattr(plugin, "display_name", g.game_key),
                currencies=getattr(plugin, "supported_currencies", []),
            )
        )
    return out


@router.get("/geos", response_model=list[GeoMeta])
async def meta_geos(x_geo: str = Header(default=None), x_tenant: str = Header(default="default")):
    tenant = load_tenant(x_tenant)
    # return all enabled geos
    out = []
    for geo in tenant.geos:
        if not geo.enabled:
            continue
        methods = []
        rails = registry.list("payment", geo=geo.geo) + registry.list("payment", geo="*")
        for r in rails:
            rk = getattr(r, "rail_key", None) or getattr(r, "MANIFEST", {}).get("key")
            if rk in geo.rails:
                for m in getattr(r, "methods", []):
                    methods.append(getattr(m, "key", str(m)))
        out.append(GeoMeta(geo=geo.geo, methods=methods))
    return out


# deposits router separate
@router.get("/cases")
async def meta_cases(
    game_key: str = None, currency: str = None, x_tenant: str = Header(default="default")
):
    async with get_conn() as conn:
        q = "SELECT id, title, game_key, currency, status FROM case_definitions WHERE status = 'published'"  # noqa: E501
        params = []
        if game_key:
            q += " AND game_key = %s"
            params.append(game_key)
        if currency:
            q += " AND currency = %s"
            params.append(currency)
        rows = await (await conn.execute(q, tuple(params))).fetchall()
    return [dict(r) for r in rows]


deposits_router = APIRouter(prefix="/deposits", tags=["deposits"])


def resolve_rail(tenant, rail_key: str):
    """Найти платёжный плагин по rail_key среди рельсов, разрешённых тенантом."""
    for geo in tenant.geos:
        if geo.enabled and rail_key in geo.rails:
            for r in registry.list("payment", geo=geo.geo) + registry.list("payment", geo="*"):
                rk = getattr(r, "rail_key", None) or getattr(r, "MANIFEST", {}).get("key")
                if rk == rail_key:
                    return r
    return None


def compute_client_fee(amount_minor: int, fee_percent: float) -> int:
    """Комиссию платит клиент: возвращаем надбавку поверх суммы (в minor)."""
    if fee_percent <= 0:
        return 0
    return int(math.ceil(amount_minor * fee_percent / 100.0))


@deposits_router.post("", response_model=DepositResponse)
async def create_deposit(
    body: DepositRequest,
    user=Depends(get_current_user),  # noqa: B008
    x_tenant: str = Header(default="default"),
    x_geo: str = Header(default=None),
):
    tenant = load_tenant(x_tenant)
    rail_plugin = resolve_rail(tenant, body.rail)
    if rail_plugin is None:
        raise HTTPException(status_code=400, detail="unknown rail")  # noqa: B904
    # Комиссия рельса оплачивается клиентом: в инвойс уходит gross-сумма
    fee_pct = float(getattr(rail_plugin, "client_fee_percent", lambda: 0.0)())
    fee_minor = compute_client_fee(body.amount_minor, fee_pct)
    gross_minor = body.amount_minor + fee_minor

    intent_id = str(uuid.uuid4())
    # В интенте храним net (сколько упадёт на баланс), в инвойс провайдеру — gross:
    # разницу забирает провайдер как свою комиссию, т.е. клиент платит её сверху
    await create_intent(
        user["id"], x_tenant, body.rail, body.amount_minor, body.currency, intent_id
    )
    result = rail_plugin.create_payment(user["id"], gross_minor, body.currency, intent_id)
    if hasattr(result, "intent_id"):
        client_payload = dict(getattr(result, "client_payload", {}))
    else:
        client_payload = dict(result.get("client_payload", result))
    provider_ref = client_payload.get("invoice_id") or client_payload.get(
        "polygon_address_in"
    )
    if provider_ref:
        await attach_provider_ref(intent_id, str(provider_ref))
    client_payload["fee_minor"] = fee_minor
    client_payload["amount_net_minor"] = body.amount_minor
    client_payload["amount_gross_minor"] = gross_minor
    return DepositResponse(
        intent_id=intent_id,
        client_payload=client_payload,
        fee_minor=fee_minor,
        amount_gross_minor=gross_minor,
    )


@deposits_router.get("/{intent_id}")
async def deposit_status(intent_id: str, user=Depends(get_current_user)):  # noqa: B008
    intent = await get_intent(intent_id)
    if intent is None or intent.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="not found")  # noqa: B904
    plugin = resolve_rail(load_tenant(intent.tenant), intent.rail)
    status = intent.status
    if plugin is not None and intent.status not in ("succeeded", "failed"):
        try:
            polled = plugin.poll_payment(intent.id, intent.provider_ref)
            status = polled.status
            if status in ("succeeded", "failed"):
                async with get_conn() as conn:
                    await conn.execute(
                        "UPDATE payment_intents SET status=%s WHERE id=%s",
                        (status, intent.id),
                    )
                    await conn.commit()
        except Exception:  # noqa: BLE001 — poll у части рельсов не реализован
            pass
    return {
        "intent_id": intent.id,
        "status": status,
        "amount_minor": intent.amount_minor,
        "currency": intent.currency,
    }


webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _handle_webhook(rail: str, headers: dict, body: Any) -> WebhookResponse:
    """Общий путь для POST и GET вебхуков: верификация -> apply_event."""

    plugin = registry.get("payment", rail)
    if plugin is None:
        raise HTTPException(status_code=404, detail="rail not found")  # noqa: B904
    outcome = plugin.handle_webhook(headers, body)
    if outcome.status != "succeeded" or not outcome.intent_id:
        return WebhookResponse(ok=True, credited=False)

    intent = await get_intent(outcome.intent_id)
    if intent is None or intent.status == "succeeded":
        return WebhookResponse(ok=True, credited=False)

    # Верификация payload против сохранённого интента
    if rail == "paygate" and isinstance(body, dict):
        addr = str(body.get("address_in", "") or "")
        if intent.provider_ref and addr and addr.lower() != intent.provider_ref.lower():
            return WebhookResponse(ok=True, credited=False)
        try:
            value = float(
                body.get("value_forwarded_coin", "") or body.get("value_coin", "") or 0
            )
        except ValueError:
            value = 0.0
        expected = float(intent.amount_minor) / 100.0
        # официальный SDK принимает от 60% USD-суммы; берём консервативные 90%
        if value < expected * 0.9:
            return WebhookResponse(ok=True, credited=False)
    elif rail == "coinso" and intent.provider_ref:
        polled = plugin.poll_payment(intent.id, intent.provider_ref)
        if polled.status != "succeeded":
            return WebhookResponse(ok=True, credited=False)

    async with get_conn() as conn:
        result = await apply_event(
            conn,
            {
                "rail": rail,
                "provider_event_id": outcome.event_id,
                "user_id": intent.user_id,
                "amount_minor": intent.amount_minor,
                "currency": intent.currency,
            },
        )
        await conn.commit()
    credited = result.credited and result.status != "duplicate"
    if result.status != "duplicate":
        async with get_conn() as conn:
            tg_row = await (
                await conn.execute(
                    "SELECT telegram_id FROM users WHERE id=%s", (intent.user_id,)
                )
            ).fetchone()
            await conn.execute(
                "UPDATE payment_intents SET status='succeeded' WHERE id=%s",
                (intent.id,),
            )
            await conn.commit()
        # Уведомление игроку в Telegram (fire-and-forget, вне транзакции)
        if tg_row is not None:
            import asyncio as _asyncio

            from app.payments.notify import notify_deposit

            _asyncio.get_running_loop().create_task(
                notify_deposit(tg_row["telegram_id"], intent.amount_minor, rail)
            )
    return WebhookResponse(ok=True, credited=credited)


@webhooks_router.post("/{rail}", response_model=WebhookResponse)
async def webhook(rail: str, request: Any):
    req: Request = request
    body_bytes = await req.body()
    headers = dict(req.headers)
    body: Any
    try:
        import json as _json

        body = _json.loads(body_bytes)
    except Exception:  # noqa: BLE001 — не-JSON тело передаём как есть
        body = body_bytes
    return await _handle_webhook(rail, headers, body)


@webhooks_router.get("/{rail}", response_model=WebhookResponse)
async def webhook_get(rail: str, request: Any):
    """GET-колбэки (PayGate присылает уведомление GET-запросом с параметрами)."""
    req: Request = request
    headers = dict(req.headers)
    params = {k: v for k, v in req.query_params.items()}
    resp = await _handle_webhook(rail, headers, params)
    # PayGate повторяет колбэк, пока не получит ок
    return resp
