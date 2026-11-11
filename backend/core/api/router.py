import hashlib
import inspect
from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.api.deps import get_current_user
from app.db import get_conn
from core.config.tenants import load_tenant
from core.contracts.payment import AuthenticatedCallback, PaymentError, VerifiedPayment
from core.payments.events import (
    MAX_BODY_BYTES,
    authenticate_event,
    ingest,
    process_event,
    record_verified_event,
)
from core.payments.intents import create_intent, get_intent
from core.payments.policy import METHODS, available_methods, runtime_settings
from core.payments.quotes import compute_client_fee, create_quote, get_quote  # noqa: F401
from core.registry.registry import registry

from .schemas import (
    DepositQuoteRequest,
    DepositRequest,
    DepositResponse,
    GameMeta,
    GeoMeta,
    WebhookResponse,
)

router = APIRouter(prefix="/meta", tags=["meta"])


def payment_http_error(exc: PaymentError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


@router.get("/tenant")
async def meta_tenant(x_tenant: str = Header(default="default")):
    """Бренд и активные гео тенанта."""
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
    for game in tenant.games:
        if not game.enabled:
            continue
        plugin = registry.get("game", game.game_key)
        if plugin is not None:
            out.append(
                GameMeta(
                    game_key=game.game_key,
                    display_name=getattr(plugin, "display_name", game.game_key),
                    currencies=getattr(plugin, "supported_currencies", []),
                )
            )
    return out


@router.get("/geos", response_model=list[GeoMeta])
async def meta_geos(x_geo: str = Header(default=None), x_tenant: str = Header(default="default")):
    tenant = load_tenant(x_tenant)
    out = []
    for geo in tenant.geos:
        if not geo.enabled:
            continue
        methods = []
        for rail in registry.list("payment", geo=geo.geo) + registry.list("payment", geo="*"):
            key = getattr(rail, "rail_key", None) or getattr(rail, "MANIFEST", {}).get("key")
            if key in geo.rails:
                methods.extend(getattr(m, "key", str(m)) for m in getattr(rail, "methods", []))
        out.append(GeoMeta(geo=geo.geo, methods=methods))
    return out


@router.get("/payment-methods")
async def meta_payment_methods(user=Depends(get_current_user)):  # noqa: B008
    channel = "web" if user.get("auth_scope") in ("guest", "roblox") else "telegram"
    try:
        async with get_conn() as conn:
            methods = await available_methods(conn, user, channel=channel)
        return {"mode": methods[0].mode, "methods": [asdict(item) for item in methods]}
    except Exception:
        # Даже недоступная БД/конфигурация не оставляет UI с включённой кнопкой оплаты.
        mode = getattr(runtime_settings(), "payments_mode", "disabled")
        if mode not in ("disabled", "sandbox", "live"):
            mode = "disabled"
        return {
            "mode": mode,
            "methods": [
                {
                    "method": method,
                    "label": label,
                    "rail": rail,
                    "enabled": False,
                    "reason": "Serviço de pagamentos indisponível.",
                    "mode": mode,
                }
                for method, (label, rail) in METHODS.items()
            ],
        }


@router.get("/cases")
async def meta_cases(
    game_key: str = None, currency: str = None, x_tenant: str = Header(default="default")
):
    async with get_conn() as conn:
        query = (
            "SELECT id, title, game_key, currency, status "
            "FROM case_definitions WHERE status = 'published'"
        )
        params = []
        if game_key:
            query += " AND game_key = %s"
            params.append(game_key)
        if currency:
            query += " AND currency = %s"
            params.append(currency)
        rows = await (await conn.execute(query, tuple(params))).fetchall()
    return [dict(row) for row in rows]


def resolve_rail(tenant, rail_key: str):
    """Совместимость discovery старых потребителей, но не обход payment policy."""
    for geo in tenant.geos:
        if geo.enabled and rail_key in geo.rails:
            for rail in registry.list("payment", geo=geo.geo) + registry.list("payment", geo="*"):
                key = getattr(rail, "rail_key", None) or getattr(rail, "MANIFEST", {}).get("key")
                if key == rail_key:
                    return rail
    return None


deposits_router = APIRouter(prefix="/deposits", tags=["deposits"])


@deposits_router.post("/quote")
async def deposit_quote(
    body: DepositQuoteRequest,
    user=Depends(get_current_user),  # noqa: B008
    x_tenant: str = Header(default="default"),
):
    try:
        async with get_conn() as conn, conn.transaction():
            quote = await create_quote(
                conn,
                user=user,
                coins=body.coins,
                method=body.method,
                tenant=x_tenant,
                channel=body.channel,
            )
        return quote.public()
    except PaymentError as exc:
        raise payment_http_error(exc) from exc


@deposits_router.post("", response_model=DepositResponse)
async def create_deposit(
    body: DepositRequest,
    user=Depends(get_current_user),  # noqa: B008
    x_tenant: str = Header(default="default"),
    x_geo: str = Header(default=None),
):
    try:
        async with get_conn() as conn, conn.transaction():
            intent = await create_intent(
                conn=conn,
                user=user,
                tenant=x_tenant,
                quote_id=body.quote_id,
                idempotency_key=body.idempotency_key,
            )
        return intent.public()
    except PaymentError as exc:
        raise payment_http_error(exc) from exc


@deposits_router.get("/{intent_id}")
async def deposit_status(intent_id: str, user=Depends(get_current_user)):  # noqa: B008
    # GET читает durable state. Никакого side-effect Verify, смены status или credit.
    async with get_conn() as conn:
        intent = await get_intent(intent_id, conn=conn)
        if intent is None or intent.user_id != user["id"]:
            raise HTTPException(status_code=404, detail="Depósito não encontrado.")
        if intent.quote_id is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "legacy_intent_unsafe",
                    "message": "Depósito antigo exige revisão.",
                },
            )
        quote = await get_quote(conn, intent.quote_id)
    return dict(intent.public(), quote=quote.public() if quote else None)


@deposits_router.post("/{intent_id}/sandbox-settle")
async def sandbox_deposit(intent_id: str, user=Depends(get_current_user)):  # noqa: B008
    from app.config import settings
    from core.payments.sandbox import settle_sandbox

    if settings.env.lower() not in {"dev", "test"}:
        raise HTTPException(status_code=404, detail={"code": "not_found"})
    try:
        async with get_conn() as conn, conn.transaction():
            result = await settle_sandbox(conn, intent_id=intent_id, user=user)
        return asdict(result)
    except PaymentError as exc:
        raise payment_http_error(exc) from exc


async def settle_polled_payment(intent_id: str):
    """Явный server-only poll через durable inbox и тот же settlement.

    Paymento намеренно использует reconcile_event после IPN, а не Verify из GET.
    Обычный PaymentStatus без доказательства не записывает status=succeeded.
    """
    intent = await get_intent(intent_id)
    if intent is None:
        raise PaymentError("intent_not_found", status_code=404)
    plugin = registry.get("payment", intent.rail)
    if plugin is None:
        raise PaymentError("provider_not_configured", status_code=503)
    polled = plugin.poll_payment(intent.id, intent.provider_ref, payment=asdict(intent))
    if inspect.isawaitable(polled):
        polled = await polled
    evidence = getattr(polled, "evidence", None)
    if not isinstance(evidence, VerifiedPayment) or evidence.source != "provider_poll":
        raise PaymentError("poll_unverified")
    if (evidence.reference, evidence.rail, evidence.mode) != (intent.id, intent.rail, intent.mode):
        raise PaymentError("payment_reference_mismatch")
    async with get_conn() as conn, conn.transaction():
        event_id = await record_verified_event(conn, evidence)
    async with get_conn() as conn, conn.transaction():
        return await process_event(conn, event_id)


webhooks_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _handle_webhook(rail: str, headers: dict, body: bytes) -> WebhookResponse:
    if type(body) is not bytes:
        raise HTTPException(status_code=400, detail={"code": "raw_body_required"})
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"code": "webhook_too_large"})
    # Другие legacy плагины не могут зачислять через этот общий путь.
    if rail not in ("paymento", "paygate"):
        raise HTTPException(status_code=404, detail={"code": "rail_not_available"})
    plugin = registry.get("payment", rail)
    if plugin is None:
        raise HTTPException(status_code=503, detail={"code": "provider_not_configured"})
    try:
        authenticate = getattr(plugin, "authenticate_webhook", None)
        if authenticate is None:
            plugin.handle_webhook(headers, body)
            raise PaymentError("unverified_webhook", status_code=503)
        callback = authenticate(headers, body)
        if inspect.isawaitable(callback):
            callback = await callback
        if not isinstance(callback, AuthenticatedCallback) or callback.rail != rail:
            raise PaymentError("unverified_webhook", status_code=401)
        # Raw тело сохраняется ДО Verify (который у Paymento останавливает retries).
        async with get_conn() as conn, conn.transaction():
            event_id = await ingest(
                rail,
                callback.event_id,
                {"body_sha256": hashlib.sha256(body).hexdigest()},
                callback.reference,
                mode=callback.mode,
                raw_body=body,
                conn=conn,
            )
            await authenticate_event(
                conn, event_id, source=callback.source, reference=callback.reference
            )
        # Надёжный worker повторит verified-but-unprocessed. HTTP ACK = inbox saved,
        # а не утверждение, что деньги уже зачислены.
        return WebhookResponse(ok=True, credited=False, status="stored")
    except PaymentError as exc:
        raise payment_http_error(exc) from exc


@webhooks_router.post("/{rail}", response_model=WebhookResponse)
@webhooks_router.put("/{rail}", response_model=WebhookResponse)
async def webhook(rail: str, request: Request):
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail={"code": "webhook_too_large"})
    return await _handle_webhook(rail, dict(request.headers), bytes(chunks))


@webhooks_router.get("/{rail}", response_model=WebhookResponse)
async def webhook_get(rail: str, request: Request):
    # Return URL и PayGate query callback не содержат надёжного proof.
    raise HTTPException(
        status_code=503,
        detail={
            "code": "unsigned_callback_disabled",
            "message": "Confirmação segura indisponível.",
        },
    )
