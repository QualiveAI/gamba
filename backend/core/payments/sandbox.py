"""Детерминированный sandbox без provider URL, подписи live и денег в wallet."""

from core.contracts.payment import PaymentError, PaymentIntent, PaymentStatus, VerifiedPayment


class SandboxAdapter:
    rail_key = "sandbox"

    def create_payment(
        self,
        user_id: int,
        amount_minor: int,
        currency: str,
        idempotency_key: str,
        *,
        mode: str = "disabled",
        metadata: dict | None = None,
    ) -> PaymentIntent:
        if mode != "sandbox":
            raise PaymentError("provider_live_not_configured", status_code=503)
        if type(amount_minor) is not int or amount_minor <= 0:
            raise PaymentError("invalid_provider_amount")
        return PaymentIntent(
            idempotency_key,
            self.rail_key,
            amount_minor,
            currency,
            {"intent_id": idempotency_key, "action": "sandbox", "mode": "sandbox"},
            mode="sandbox",
            provider_ref=f"sandbox:{idempotency_key}",
        )

    def poll_payment(
        self, intent_id: str, provider_ref: str | None = None, *, payment: dict | None = None
    ) -> PaymentStatus:
        if payment is None or payment.get("mode") != "sandbox":
            return PaymentStatus(intent_id, "pending", 0)
        return PaymentStatus(intent_id, "pending", payment["provider_amount_atomic"])

    def sandbox_evidence(self, intent, *, status: str = "succeeded", suffix: str = "1"):
        if intent.mode != "sandbox" or intent.rail != self.rail_key:
            raise PaymentError("sandbox_source_mismatch")
        return VerifiedPayment(
            reference=intent.id,
            rail=intent.rail,
            mode="sandbox",
            provider_event_id=f"sandbox:{intent.id}:{status}:{suffix}",
            status=status,
            amount_atomic=intent.provider_amount_atomic,
            currency=intent.provider_currency,
            source="sandbox_fixture",
            chain=intent.chain,
            token=intent.token,
            address=intent.address,
            user_id=intent.user_id,
        )


async def settle_sandbox(conn, *, intent_id: str, user: dict, status: str = "succeeded"):
    """Не public webhook. Нужны владелец, sandbox mode и все выключатели."""
    from core.payments.apply import settlement_service
    from core.payments.events import record_verified_event
    from core.payments.intents import get_intent
    from core.payments.policy import ensure_enabled, validate_actor

    intent = await get_intent(intent_id, conn=conn, lock=True)
    if intent is None or intent.user_id != user["id"]:
        raise PaymentError("intent_not_found", status_code=404)
    validate_actor(user, "sandbox")
    if intent.mode != "sandbox":
        raise PaymentError("sandbox_source_mismatch")
    await ensure_enabled(conn, intent.method, "sandbox")
    adapter = SandboxAdapter()
    adapter.rail_key = intent.rail
    evidence = adapter.sandbox_evidence(intent, status=status)
    event_id = await record_verified_event(conn, evidence)
    return await settlement_service(conn, evidence, event_id=event_id)
