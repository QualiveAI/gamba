# Интеграция платежей: безопасный локальный этап

## Статус и границы

По умолчанию `PAYMENTS_MODE=disabled`. Реальные запросы к платёжным API в этом этапе не выполнялись. Режим `sandbox` использует детерминированные локальные данные, не ссылки на фиктивный live checkout.

**Sandbox никогда не пополняет `users.balance_units` и не создаёт расходуемые игровые средства.** Он записывает отдельное событие `sandbox_wallet_deposit` и статус `sandbox_succeeded`. Это относится и к гостям, и к авторизованным пользователям. Отдельного расходуемого sandbox wallet пока нет. При попытке живого гостевого платежа — отказ.

Рабочая БД, реальные `.env`, реальные платежи, refund API и публикация не использовались. Миграция `0017_payment_safety.sql` не пересчитывает старые балансы. Неоднозначные legacy intents требуют отдельного аудита.

## Денежный контракт

- `coins` — целое число монет кошелька, без дробной части и без умножения на 100.
- Существующее имя `balance_units` сохраняется; новые поступления записываются в него как целые coins. Старые значения не исправляются автоматически.
- `amount_brl_minor` / `net_brl_minor` — базовая стоимость в BRL cents.
- `fee_brl_minor` — комиссия покупателя, округлённая вверх до cent.
- `gross_brl_minor = net_brl_minor + fee_brl_minor`.
- `provider_amount_atomic`, `provider_currency`, `provider_exponent` — отдельная сумма провайдера: BRL cents, XTR либо атомы конкретного crypto asset.
- В публичном JSON **`provider_amount_atomic` всегда строка** для безопасной передачи в JavaScript. В БД/расчётах — целое число. Fiat minor ограничены безопасным для JavaScript диапазоном; coins ограничены серверной настройкой.
- Расчёты только `Decimal`/целые. Комиссия применяется после округления базовой BRL суммы вверх.

Пример при `coin_usd_price=0.015`, `usd_brl_rate=5.4`, `payment_fee_percent=20`:

```text
100 coins -> 810 BRL cents net + 162 cents fee = 972 cents gross
Stars при stars_usd_price=0.02: ceil(9.72 / 5.4 / 0.02) = 90 XTR
Sandbox crypto: 1800000 атомов TEST-USDT, exponent=6
```

Котировка хранит цены/курс, rate/config version (SHA-256 канонической версии конфигурации), snapshot, срок, method/rail/mode/channel, владельца и auth context. UPDATE/DELETE quote запрещены триггером. В intent закреплены те же условия; изменяемы только операционные поля.

## HTTP API

Все пользовательские endpoints требуют текущего пользователя. Авторитетный владелец берётся из auth, не из тела запроса. `auth_scope` — `primary`, `managed`, `guest`, `roblox`. Managed может создавать заказ только на своего аутентифицированного пользователя; подтверждать платёж не может. `guest` и `roblox` не могут передать `channel=telegram` для обхода web policy.

### Доступность

`GET /meta/payment-methods`

```json
{
  "mode": "disabled",
  "methods": [
    {"method":"stars","label":"Telegram Stars","rail":"stars","enabled":false,"reason":"Pagamentos desativados.","mode":"disabled"},
    {"method":"gift","label":"Presentes do Telegram","rail":"gift","enabled":false,"reason":"Pagamentos desativados.","mode":"disabled"},
    {"method":"card","label":"Cartão","rail":"paygate","enabled":false,"reason":"Pagamentos desativados.","mode":"disabled"},
    {"method":"crypto","label":"Criptomoedas","rail":"paymento","enabled":false,"reason":"Pagamentos desativados.","mode":"disabled"}
  ]
}
```

`reason=null` только при `enabled=true`. Недоступность БД, неверная конфигурация или отсутствие выключателя закрывают метод.

### Котировка и intent

`POST /deposits/quote`

```json
{"coins":100,"method":"card","channel":"web"}
```

`channel` необязателен. Основные поля ответа:

```json
{
  "quote_id":"<32 hex>","coins":100,"wallet_unit":"coin","currency":"BRL",
  "amount_brl_minor":810,"net_brl_minor":810,"fee_brl_minor":162,"gross_brl_minor":972,
  "coin_usd_price":"0.015","usd_brl_rate":"5.4","fee_percent":"20",
  "rate_version":"<sha256>","config_version":"<sha256>",
  "tenant":"default","method":"card","rail":"paygate","mode":"sandbox","channel":"web",
  "provider_amount_atomic":"972","provider_currency":"BRL","provider_exponent":2,
  "chain":null,"token":null,"address":null,
  "created_at":"<ISO-8601>","expires_at":"<ISO-8601>"
}
```

`POST /deposits`

```json
{"quote_id":"<32 hex>","idempotency_key":"client-generated-key"}
```

```json
{
  "intent_id":"<32 hex>","quote_id":"<32 hex>","coins":100,"wallet_unit":"coin",
  "method":"card","rail":"paygate","mode":"sandbox","status":"pending",
  "expires_at":"<ISO-8601>","provider_amount_atomic":"972","provider_currency":"BRL",
  "provider_exponent":2,"refund_status":"none",
  "client_payload":{"intent_id":"<тот же intent_id>","mode":"sandbox","action":"sandbox"}
}
```

Идемпотентность: `(user_id, idempotency_key)` и SHA-256 payload. Повтор того же запроса возвращает тот же intent; другой quote/tenant с тем же ключом — `409 idempotency_conflict`. Одна котировка создаёт только один intent. Одновременно пришедшие запросы сериализованы advisory lock и уникальными индексами. Единственный канонический ID используется в БД, client payload, Stars invoice payload, Paymento `orderId` и PayGate callback reference.

`GET /deposits/{intent_id}` возвращает тот же ответ плюс `quote`. Это **чистое чтение**, без Verify API и без смены статуса.

`POST /deposits/{intent_id}/sandbox-settle` — явная локальная симуляция владельца sandbox intent. Результат `sandbox_processed`, `credited=false`, `sandbox=true`. После этого GET показывает `sandbox_succeeded`; деньги в live wallet не появляются.

Тела с legacy `{rail, amount_minor, currency}` и произвольными клиентскими курсами/ценами отвергаются `422`. HTTP бизнес-ошибка имеет `detail: {code,message}`; сообщения интерфейса PT-BR.

## Settlement и inbox

1. Webhook читает исходные байты `Request.stream()` (до JSON parsing), максимум 64 KiB.
2. Verifier проверяет подпись/источник. Сырой JSON с `verified=true`, `status=succeeded`, user ID или reference не получает доверие.
3. Аутентифицированное событие сохраняется в `payment_events` и транзакция inbox завершается **до** любого Verify, который может остановить provider retries.
4. Worker получает доказательство `VerifiedPayment`: reference, rail, mode, точная сумма, currency; для crypto дополнительно asset/chain/token/address и подтверждения.
5. `core.payments.apply.settlement_service` блокирует intent, сверяет immutable quote и inbox, выполняет `post_entry`, обновляет статус, записывает canonical event и notification outbox в одной транзакции.
6. Уникальный ref `deposit:<intent_id>` не зависит от provider event ID. Два callback, poll/webhook race или повтор Stars charge не дают вторую выплату.
7. Ошибка ledger invariant или outbox откатывает savepoint целиком. Возвращаются `ledger_rejected` / `settlement_failed`, intent не становится succeeded, inbox остаётся на повтор. Старый баланс не «чинится».

`pending`, `failed`, `expired` не зачисляют средства. Старый адаптер, вернувший лишь `PaymentStatus(status='succeeded')`, недостаточен. `apply_event(dict)` нормализованно отвергается. Возврат браузера и `GET /webhooks/{rail}` не доказывают платёж, GET callback отключён.

Подтверждение, пришедшее после срока и не содержащее доказуемого своевременного `paid_at`, идёт в `late_payment_review_required`, не пополняет баланс. Доставка paid event после failed/expired требует отдельного review. Это намеренно консервативное ограничение, а не заявленная поддержка всех late settlement случаев.

Notification contract, без секретов и без внутреннего commit:

```python
await app.bot.outbox.enqueue(
    conn, kind="deposit_confirmed", user_id=user_id,
    payload={"coins": coins, "rail": rail, "intent_id": intent_id},
    dedupe_key=f"deposit_confirmed:{intent_id}", bot_id=None,
)
```

## Выключатели и worker

Настройки: `payments_mode='disabled'`, `payment_web_enabled=False`, `coin_usd_price='0.015'`, `usd_brl_rate='5.4'`, `payment_fee_percent='20'`, `quote_ttl_seconds=900`, `payments_max_coins=1000000`, `stars_usd_price='0.02'`, `stars_enabled=False`, `gifts_enabled=False`, `stars_refunds_enabled=False`; treasury asset/network/address, `paymento_secret_key`, `paymento_api_key` по умолчанию пустые. Наличие ключа само по себе не включает live adapter.

DB flags: `deposits_enabled` и `payments_{stars,gift,card,crypto}_enabled`; отдельно `payments_stars_refunds_enabled`. Значения совместимы с admin API: `{"value":true}` или `{"enabled":true}`. Отсутствующее/не boolean значение — false. Чтение транзакционное, без Redis; изменение флага админом не обходится кэшем.

Из каталога backend, только в согласованном окружении:

```text
python -m core.payments.worker --once --batch-size 100 --max-attempts 12
python -m core.payments.worker --interval 5 --batch-size 100 --max-attempts 12
```

При `disabled` worker выходит до открытия соединений. При работе — batch до 1000, по умолчанию 12 попыток, exponential backoff до 1 часа. Исчерпанные записи не удаляются: нужен операторский разбор и контролируемый повтор. Heartbeat выводит только тип ошибки, не provider payload/секрет. Cleanup закрывает pool при остановке. Verify сериализуется advisory lock reference, без wallet/ledger row lock на время transport; финансовые locks берутся после него.

## Telegram Stars: контракт основного бота

`POST /payments/stars/invoice {"intent_id":"..."}`. Клиент не выбирает invoice title, сумму XTR и payload. Payload: `deposit:<intent_id>`, цена из quote. Sandbox не создаёт Telegram invoice.

```python
await validate_stars_precheckout(
    conn, user_id=user_id, invoice_payload=payload, currency=currency, total_amount=amount,
)  # bool; ожидаемый бизнес-отказ False

await settle_stars_payment(
    conn, user_id=user_id, invoice_payload=payload, currency=currency,
    total_amount=amount, charge_id=telegram_payment_charge_id,
)  # ApplyResult(status, credited, intent_id, sandbox), без commit
```

Эти функции **не являются HTTP proof endpoints**. Их вызывают только main-bot handlers после проверки bot/merchant source и authenticated Telegram update. Managed bot update запрещён. Telegram user ID и charge ID, пришедшие от клиента, не принимаются как доказательство.

`configure_main_bot_transport(transport)` инъецирует transport с `merchant_bot_id`, совпадающим с основным ботом. Методы `create_invoice(...)` и `refund(...)` асинхронные. Платёжный модуль не создаёт клиент Bot API сам и не читает токены из payload. При отсутствии transport — отказ.

### Возвраты

`request_stars_refund(conn, *, intent_id, owner)` — только primary admin основного бота. После подтверждённого платежа удерживает ровно credited coins через ledger и ставит `requested`. Повтор идемпотентен. Недостаточный баланс/нарушенный ledger — отказ с полным откатом.

`execute_stars_refund(*, intent_id, owner)` — server-only main owner flow. Переходы: `requested -> processing -> refunded | failed | unknown`. Состояние processing фиксируется до transport. Нет transport — requested с диагностикой. Ошибка/неизвестный ответ не выпускает hold и не повторяет refund автоматически. Отдельный процесс восстановления `processing/unknown` и UI ручного решения в этом этапе не реализованы. Нельзя слепо повторять неизвестный refund.

## Подарки

- `record_business_gift` вызывается только после подтверждённого business update основного бота.
- `record_manual_gift_receipt` — primary admin подтверждает реальное получение с custody/inventory reference. URL и скриншоты не являются proof.
- `review_gift` требует сохранённый подтверждённый receipt, правильного владельца и операторскую BRL valuation, совпадающую с quote. Несовпадение требует новой котировки; исходная не редактируется.
- В зачислении используется тот же settlement/ledger/outbox. Gift ID уникален в receipt/charge, повтор не платит снова.
- HTTP operator endpoints: `POST /payments/gifts/{intent_id}/receipt {gift_id,custody_reference}` и `/review {receipt_event_id,valued_brl_minor}`.
- Legacy `handle_gift(user_id,gift_id)` только создаёт pending_review, не конвертирует прежний RUB price в coins.

Автоматическая инвентаризация и независимая проверка ручного оператора не реализованы: ручной процесс доверяет контролируемому owner аккаунту. Потерянный/чужой подарок без подтверждения не зачисляется.

## Paymento: реализованный точный контракт и блокеры live

Публичная документация проверена 2026-11-11:

- https://docs.paymento.io/api-documentation/payment-request
- https://docs.paymento.io/api-documentation/payment-callback
- https://docs.paymento.io/api-documentation/payment-verify

API IPN использует **`X-HMAC-SHA256-Signature` = uppercase hex HMAC-SHA256 от исходного тела**, ключ UTF-8 Secret Key. Поля callback PascalCase: `Token`, `PaymentId`, `OrderId`, `OrderStatus`. Это не другой продукт Payment Links с `X-Paymento-Signature` от event headers. Локальные signed fixtures проверяют изменение байтов, другой ключ/тип подписи и duplicate JSON keys.

IPN не содержит суммы, поэтому подписи недостаточно для credit. API `POST https://api.paymento.io/v1/payment/verify` с `Api-Key` и `{token}` вызывается только после durable inbox через инъецируемый transport. `success=true` и `orderStatus=8` проверяются вместе; затем exact amount, asset/network/token contract/toAddress, completed transactions и confirmations. Ответы разбираются с `Decimal`, не float. Partial paid и ожидающие подтверждения не оплачивают заказ. Verify после Paid меняет статус на Approve и прекращает IPN retries — поэтому порядок durable inbox обязателен.

Реализованы request builder, IPN verifier, Verify parser, `PaymentoTransport` protocol и mock fixtures. **Не реализованы/не включены** production HTTP transport, серверное создание live order, привязка авторитетного crypto destination к immutable quote, аудит treasury mapping/merchant settings. Live crypto остаётся `enabled=false`. `settlement.toAddress` — депозитный адрес конкретного платежа, не автоматически treasury payout address; подменять одно другим запрещено.

## PayGate: реализованный контракт и блокер live

Документация: https://paygate.to/docs/payment-gateway-api/index.html

Реализованы pure builders `GET /control/wallet.php` и checkout `https://checkout.paygate.to/process-payment.php` с точной десятичной суммой, а также explicit sandbox. Никакого сетевого вызова в builder нет.

Официальный GET callback не имеет документированной криптографической подписи. `ipn_token` указан как token для support tracking, не proof. Сравнение txid/address/value из такого callback без доверенного verifier не принимается. Прежние 90% допуски суммы и `.example` live successes удалены. **Live card отключён** до независимой authenticated merchant/on-chain сверки с закреплёнными суммой/currency/chain/token/address. Самодельная «официальная» HMAC-подпись не придумана.

## Проверки и оставшиеся ограничения

Добавлены регрессии quote/idempotency, owner/channel/guest policy, immutable БД, worker unverified/pending/failed, sandbox isolation, двух событий одного intent, amount/chain/address mismatch, ledger/outbox rollback, Stars main precheckout, gift custody/review, raw HMAC и HTTP маршрутов через ASGI.

Общий изолированный прогон 2026-11-11: **269 backend-тестов прошли**, включая payment/chaos, HTTP ASGI, bot/auth, gift cards и ops. Миграции `0001`–`0018` применены только к отдельным тестовым БД. Браузерный sandbox-платёж завершился `sandbox_succeeded`, не изменив баланс; это локальная симуляция, не PSP sandbox и не реальная оплата. Сводка окружения, повторных прогонов и ограничений — [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md). Мок-тесты не заменяют staging/audit реального провайдера.

Отключённые legacy HTTP `/payments/yoomoney/*`, polling status и manual-claim возвращают 410; ядро нового flow не импортирует `yoomoney_sbp`. Старые модули вне области этого этапа не считаются проверенными live интеграциями.

Не заявлены готовность live запуска, конвертация treasury, реальные refunds, антифрод/AML/KYC и легальность конкретного провайдера для продукта/региона. Они требуют отдельного согласованного этапа. До этого выключатели остаются закрытыми.
