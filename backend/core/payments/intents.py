import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from core.contracts.payment import PaymentError
from core.payments.policy import ensure_enabled, validate_actor
from core.payments.quotes import PaymentQuote, get_quote


@dataclass(frozen=True)
class PaymentIntent:
    id: str
    user_id: int
    tenant: str
    rail: str
    amount_minor: int
    currency: str
    status: str
    provider_ref: str | None
    quote_id: str | None = None
    coins: int | None = None
    method: str | None = None
    mode: str = "disabled"
    provider_amount_atomic: int | None = None
    provider_currency: str | None = None
    provider_exponent: int | None = None
    chain: str | None = None
    token: str | None = None
    address: str | None = None
    merchant_bot_id: int | None = None
    expires_at: datetime | None = None
    client_payload: dict = field(default_factory=dict)
    payload_hash: str | None = None
    charge_id: str | None = None
    refund_status: str = "none"

    def public(self) -> dict:
        return {
            "intent_id": self.id,
            "quote_id": self.quote_id,
            "coins": self.coins,
            "wallet_unit": "coin",
            "method": self.method,
            "rail": self.rail,
            "mode": self.mode,
            "status": self.status,
            "expires_at": self.expires_at,
            "provider_amount_atomic": str(self.provider_amount_atomic)
            if self.provider_amount_atomic is not None
            else None,
            "provider_currency": self.provider_currency,
            "provider_exponent": self.provider_exponent,
            "client_payload": self.client_payload,
            "refund_status": self.refund_status,
        }


def intent_from_row(row) -> PaymentIntent:
    values = {key: row[key] for key in PaymentIntent.__dataclass_fields__ if key in row}
    if isinstance(values.get("client_payload"), str):
        values["client_payload"] = json.loads(values["client_payload"])
    return PaymentIntent(**values)


def request_hash(user_id: int, quote_id: str, tenant: str) -> str:
    payload = {"version": 1, "user_id": user_id, "quote_id": quote_id, "tenant": tenant}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def get_intent(intent_id: str, *, conn=None, lock: bool = False) -> PaymentIntent | None:
    if conn is None:
        from app.db import get_conn

        async with get_conn() as owned_conn:
            return await get_intent(intent_id, conn=owned_conn, lock=lock)
    row = await (
        await conn.execute(
            "SELECT * FROM payment_intents WHERE id=%s" + (" FOR UPDATE" if lock else ""),
            (intent_id,),
        )
    ).fetchone()
    return intent_from_row(row) if row else None


async def create_intent(
    user_id: int | None = None,
    tenant: str = "default",
    rail: str | None = None,
    amount_minor: int | None = None,
    currency: str | None = None,
    idempotency_key: str | None = None,
    *,
    conn=None,
    user: dict | None = None,
    quote_id: str | None = None,
) -> PaymentIntent:
    # Старый positional API остаётся явным отказом, а не конвертацией неоднозначных units.
    if amount_minor is not None or currency is not None or rail is not None or not quote_id:
        raise PaymentError(
            "legacy_amount_ambiguous",
            "Crie uma cotação com moedas antes do depósito.",
            422,
        )
    if user is None or user_id is not None and user_id != user.get("id"):
        raise PaymentError("actor_mismatch", status_code=403)
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 128:
        raise PaymentError("invalid_idempotency_key", status_code=422)
    if any(ord(c) < 33 or ord(c) > 126 for c in idempotency_key):
        raise PaymentError("invalid_idempotency_key", status_code=422)
    if conn is None:
        from app.db import get_conn

        async with get_conn() as owned_conn, owned_conn.transaction():
            return await create_intent(
                tenant=tenant,
                idempotency_key=idempotency_key,
                conn=owned_conn,
                user=user,
                quote_id=quote_id,
            )
    fingerprint = request_hash(user["id"], quote_id, tenant)
    # Транзакционный advisory lock сериализует один scoped ключ, в том числе
    # конкурирующие запросы с РАЗНЫМИ quote_id. Уникальный индекс остаётся барьером БД.
    scope = f"deposit:{user['id']}:{idempotency_key}"
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (scope,))
    existing = await (
        await conn.execute(
            "SELECT * FROM payment_intents WHERE user_id=%s AND idempotency_key=%s FOR UPDATE",
            (user["id"], idempotency_key),
        )
    ).fetchone()
    if existing:
        if existing["payload_hash"] != fingerprint:
            raise PaymentError("idempotency_conflict", "Esta chave já foi usada em outro depósito.")
        return intent_from_row(existing)
    quote: PaymentQuote | None = await get_quote(conn, quote_id, lock=True)
    if quote is None or quote.user_id != user["id"] or quote.tenant != tenant:
        raise PaymentError("quote_not_found", "Cotação não encontrada.", 404)
    validate_actor(user, quote.mode)
    if quote.auth_scope != user["auth_scope"] or quote.auth_bot_id != user.get("auth_bot_id"):
        raise PaymentError("quote_auth_context_mismatch", status_code=403)
    if quote.expires_at <= datetime.now(UTC):
        raise PaymentError("quote_expired", "A cotação expirou. Solicite uma nova.")
    await ensure_enabled(conn, quote.method, quote.mode, creation=True, channel=quote.channel)
    used = await (
        await conn.execute("SELECT id FROM payment_intents WHERE quote_id=%s", (quote.id,))
    ).fetchone()
    if used:
        raise PaymentError("quote_already_used", "Esta cotação já possui um depósito.")
    intent_id = uuid.uuid4().hex
    payload = {
        "intent_id": intent_id,
        "mode": quote.mode,
        "action": "sandbox" if quote.mode == "sandbox" else "pending_review",
    }
    if quote.method == "stars":
        payload.update({"invoice_payload": f"deposit:{intent_id}", "action": "invoice_required"})
        if quote.mode == "sandbox":
            payload["action"] = "sandbox"
    values = {
        "id": intent_id,
        "user_id": user["id"],
        "tenant": tenant,
        "rail": quote.rail,
        "amount_minor": quote.provider_amount_atomic,
        "currency": quote.provider_currency,
        "idempotency_key": idempotency_key,
        "quote_id": quote.id,
        "coins": quote.coins,
        "method": quote.method,
        "mode": quote.mode,
        "provider_amount_atomic": quote.provider_amount_atomic,
        "provider_currency": quote.provider_currency,
        "provider_exponent": quote.provider_exponent,
        "chain": quote.chain,
        "token": quote.token,
        "address": quote.address,
        "merchant_bot_id": quote.merchant_bot_id,
        "expires_at": quote.expires_at,
        "client_payload": json.dumps(payload),
        "payload_hash": fingerprint,
        "wallet_unit": "coin",
        "config_version": quote.config_version,
    }
    columns = list(values)
    row = await (
        await conn.execute(
            "INSERT INTO payment_intents ("
            + ",".join(columns)
            + ") VALUES ("
            + ",".join(["%s"] * len(columns))
            + ") RETURNING *",
            tuple(values[c] for c in columns),
        )
    ).fetchone()
    return intent_from_row(row)


async def attach_provider_ref(intent_id: str, provider_ref: str, *, conn=None) -> None:
    if not isinstance(provider_ref, str) or not provider_ref or len(provider_ref) > 512:
        raise PaymentError("invalid_provider_reference")
    if conn is None:
        from app.db import get_conn

        async with get_conn() as owned_conn, owned_conn.transaction():
            return await attach_provider_ref(intent_id, provider_ref, conn=owned_conn)
    intent = await get_intent(intent_id, conn=conn, lock=True)
    if intent is None:
        raise PaymentError("intent_not_found", status_code=404)
    if intent.quote_id is None:
        raise PaymentError("legacy_intent_unsafe")
    if intent.provider_ref is not None and intent.provider_ref != provider_ref:
        raise PaymentError("provider_reference_conflict")
    await conn.execute(
        "UPDATE payment_intents SET provider_ref=%s WHERE id=%s AND provider_ref IS NULL",
        (provider_ref, intent_id),
    )
