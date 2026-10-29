import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.db import get_conn
from core.config.tenants import load_tenant
from core.registry.registry import registry

from .schemas import (
    DepositRequest,
    DepositResponse,
    GameMeta,
    GameSessionResponse,
    GeoMeta,
    WebhookResponse,
    WithdrawalRequest,
    WithdrawalResponse,
    WithdrawalStatus,
)

router = APIRouter(prefix="/meta", tags=["meta"])

_intents: dict[str, Any] = {}
_sessions: dict[str, Any] = {}
_withdrawals: dict[str, Any] = {}


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


@deposits_router.post("", response_model=DepositResponse)
async def create_deposit(
    body: DepositRequest,
    x_tenant: str = Header(default="default"),
    x_geo: str = Header(default=None),
):
    tenant = load_tenant(x_tenant)
    # resolve rail
    rail_plugin = None
    for geo in tenant.geos:
        if geo.enabled and body.rail in geo.rails:
            for r in registry.list("payment", geo=geo.geo) + registry.list("payment", geo="*"):
                rk = getattr(r, "rail_key", None) or getattr(r, "MANIFEST", {}).get("key")
                if rk == body.rail:
                    rail_plugin = r
                    break
            if rail_plugin:
                break
    if rail_plugin is None:
        raise HTTPException(status_code=400, detail="unknown rail")  # noqa: B904
    intent_id = str(uuid.uuid4())
    idem = intent_id
    result = rail_plugin.create_payment(0, body.amount_minor, body.currency, idem)
    # result may be object or dict
    if hasattr(result, "intent_id"):
        intent = result
        client_payload = getattr(result, "client_payload", {})
    else:
        intent = result
        client_payload = result.get("client_payload", result)
    _intents[intent_id] = {"rail": body.rail, "plugin": rail_plugin, "intent": intent}
    return DepositResponse(
        intent_id=intent_id,
        client_payload=client_payload if isinstance(client_payload, dict) else {},
    )


webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhooks_router.post("/{rail}", response_model=WebhookResponse)
async def webhook(rail: str, request: Any):

    req: Request = request
    body = await req.body()
    headers = dict(req.headers)
    # find plugin
    plugin = None
    for r in registry.list("payment", geo=None) + []:
        rk = getattr(r, "rail_key", None) or getattr(r, "MANIFEST", {}).get("key")
        if rk == rail:
            plugin = r
            break
    # fallback: iterate registry items
    if plugin is None:
        from core.registry.registry import registry as reg

        for (t, k, _g), obj in reg._items.items():
            if t == "payment" and k == rail:
                plugin = obj
                break
    if plugin is None:
        raise HTTPException(status_code=404, detail="rail not found")  # noqa: B904
    outcome = plugin.handle_webhook(headers, body)
    credited = outcome.credited if hasattr(outcome, "credited") else outcome.get("credited", False)
    return WebhookResponse(ok=True, credited=credited)


games_router = APIRouter(prefix="/games", tags=["games"])


@games_router.post("/{game_key}/session", response_model=GameSessionResponse)
async def create_session(
    game_key: str, case_id: int = None, x_tenant: str = Header(default="default")
):
    tenant = load_tenant(x_tenant)
    enabled = [g.game_key for g in tenant.games if g.enabled]
    if game_key not in enabled:
        raise HTTPException(status_code=404, detail="game not enabled")  # noqa: B904
    plugin = registry.get("game", game_key)
    if plugin is None:
        raise HTTPException(status_code=404, detail="game not registered")  # noqa: B904
    sid = str(uuid.uuid4())
    _sessions[sid] = {"game_key": game_key, "plugin": plugin}
    return GameSessionResponse(session_id=sid, game_key=game_key)


withdrawals_router = APIRouter(prefix="/withdrawals", tags=["withdrawals"])


@withdrawals_router.post("", response_model=WithdrawalResponse)
async def create_withdrawal(body: WithdrawalRequest, x_tenant: str = Header(default="default")):
    wid = str(uuid.uuid4())
    _withdrawals[wid] = {"status": "pending", "body": body}
    return WithdrawalResponse(withdrawal_id=wid, status="pending")


@withdrawals_router.get("/{wid}", response_model=WithdrawalStatus)
async def get_withdrawal(wid: str):
    w = _withdrawals.get(wid)
    if w is None:
        raise HTTPException(status_code=404, detail="not found")  # noqa: B904
    return WithdrawalStatus(withdrawal_id=wid, status=w["status"])
