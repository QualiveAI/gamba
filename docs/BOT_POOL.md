# Основной бот и официальные Managed Bots

Этот модуль заменяет прежний plaintext CSV «пул». Это не ротация аккаунтов, не обход блокировок и не автономная регистрация Telegram-аккаунтов. Реальная готовность требует отдельной проверки Telegram/BotFather, HTTPS, merchant-настроек и изолированных интеграционных тестов.

## Режимы и настройки

По умолчанию `BOT_MODE=disabled`, `MANAGED_BOTS_ENABLED=false`, `ALLOW_GUEST_AUTH=false`. Импорты бота, worker и Stars transport не делают запросов. В отключённом режиме CLI main/worker завершаются без открытия сетевого клиента.

Включённому основному боту нужны `BOT_TOKEN`, `BOT_USERNAME`, `WEBAPP_URL`, `PUBLIC_BASE_URL`, `SUPPORT_USERNAME`, `FERNET_KEY`, `TELEGRAM_WEBHOOK_SECRET`, `JWT_SECRET` и настроенная БД. `WEBAPP_URL` — HTTPS адрес Mini App, `PUBLIC_BASE_URL` — HTTPS адрес API без query/fragment. Webhook secret — 32–256 символов `[A-Za-z0-9_-]`. Fernet-ключ не генерируется автоматически и должен сохраняться вне репозитория. Он нужен и основному боту: inbox зашифрован.

`BOT_MODE=webhook` — production/multi-bot. `BOT_MODE=polling` допускается только при `ENV=dev|test`, только для main. Poller отказывается работать при установленном webhook и использует PostgreSQL session advisory lock против второго poller того же token в той же БД. Автоматического `deleteWebhook`, удаления накопленных updates или второго managed poller нет. Копии с другим datastore этим lock не защищены: один token должен иметь одного оператора и один источник updates.

`HEALTHCHECK_BOT_TOKEN` и `HEALTHCHECK_TARGET_CHAT_ID` необязательны: без них сохраняется структурированное состояние, но внешнее оповещение не отправляется. Ключи giftcard storage и payment настройки принадлежат соответствующим модулям, не bot registry.

Реальные `.env`, токены, запросы к Telegram, запуск ботов, коммиты и деплой при этой реализации не использовались.

## Подключение к API и worker

- `app.api.bot_webhooks.router`: `POST /bot/webhook/{bot_id}`.
- `app.api.bot_webhooks.management_router`: `GET /bots/me`.
- `app.bot.worker.run_worker(*, stop: asyncio.Event | None = None, client=None)` — отдельная coroutine, использует уже инициализированный DB pool.
- `app.bot.worker.readiness_probe(conn)` — проверка существования таблиц, без сети и чтения payload.
- `app.bot.main.configure_main_bot(client)` — явный provisioning: `getMe`, проверка ID, команды, описания, меню, webhook.
- CLI `python -m app.bot.main` — только вручную: при webhook выполняет provisioning и завершается, при polling начинает dev poller.
- CLI `python -m app.bot.worker` — отдельный потребитель inbox/outbox и watchdog. Сам инициализирует/закрывает pool. Webhook процесс не должен автоматически запускать второй poller.

Для API lifespan при явно включённом bot/payment режиме можно создать `app.bot.client.MainStarsTransport()`, передать его в `app.payments.stars.configure_main_bot_transport(transport)` и при остановке отключить transport и вызвать `await transport.aclose()`. Конструктор запросов не делает. `merchant_bot_id` — ID только основного бота; методы `create_invoice(...)` и `refund(...)` используют `createInvoiceLink` и `refundStarPayment`. Проверку готовности настоящего merchant/API это не заменяет.

Все bot HTTP вызовы идут через переиспользуемый `TelegramClient`; aiogram не импортируется. Новые сырые `Update.managed_bot` не зависят от наличия типов Bot API 9.6+ в установленном aiogram. Изменение зависимостей ради этих типов не требуется.

## Команды и opt-in

Тексты игроку и описания команд — PT-BR. `/start`, `/menu`, `/balance`, `/withdraw`, `/support`, `/paysupport`, `/mycards`, `/mybot` доступны в основном и персональном боте. `/withdraw` — обмен Coins на gift cards, не обещание денежного вывода. `/mycards ID` повторно показывает **тот же** уже выданный код исключительно владельцу в проверенном private chat.

Управление происходит через основной бот:

1. `/mybot` или `/start managed` показывает состояние и объяснение. Ничего не создаётся автоматически.
2. `/createbot` — явный opt-in, создаёт pending intent на 15 минут и official reply keyboard.
3. Кнопка содержит `request_managed_bot: {request_id, suggested_name, suggested_username}`. Имя/username — предложения; выбранное игроком имя не меняется. `setMyName` не вызывается.
4. При регистрации main получает официальный `Update.managed_bot` с `ManagedBotUpdated{user: owner, bot: bot}`. Request ID не выдумывается внутри этого update: связь проверяется по свежему server-side intent того же owner. Один pending intent на owner; при переподключении он также связан с конкретным bot ID.
5. Main вызывает `getManagedBotToken {user_id: bot.id}`, сверяет token prefix и `getMe.id/is_bot`, затем `setManagedBotAccessSettings {user_id, is_access_restricted: true, added_user_ids: []}`. После настройки webhook/меню и проверки неизменности credential version intent потребляется и registry становится active.
6. `/reconnectbot ID` выдаёт новый intent. Для получения свежего official manager update может понадобиться повторное действие в Telegram/BotFather; обычная команда сама не доказывает смену token и не реанимирует доверие.
7. `/revokebot ID` локально отзывает trust, уничтожает используемые encrypted credentials, меняет webhook secret и credential version. Telegram-account/бот не удаляется; ownership в BotFather не меняется.

Manager capability включается вручную в BotFather. Никаких Telegram password, session string, OTP или пользовательского API token бот не запрашивает. Официальный flow зависит от Bot API 9.6+, поддержки клиента и настройки manager capability; live flow здесь не проверялся.

`GET /bots/me` возвращает `{enabled, main_bot_username, managed_bots:[{bot_id,username,status}], create_url}`. Секретов нет. Список фильтруется по внутреннему user ID и реальному Telegram owner, для guest/Roblox пуст. `create_url` ведёт в main `/start managed`; UI должен открывать его только после действия игрока.

## Граница доверия авторизации

**Владелец персонального бота знает его token.** Поэтому он технически способен подписать `initData` от имени любого Telegram ID. Managed HMAC подпись сама по себе не является primary аутентификацией.

`POST /auth/telegram` принимает только `{init_data: string, auth_bot_id?: number}`. Owner ID от клиента не принимается. Нет `auth_bot_id` — проверка main token. Managed Mini App URL содержит `auth_bot_id=<bot.id>`; frontend обязан передать этот ID при обмене `initData` и не повторять managed login через main fallback.

Для managed login обязательно совпадение `initData.user.id == bot_registry.owner_telegram_id`, active status, owner user FK и текущий зашифрованный token. Новый аккаунт по managed login не создаётся; username/account/balance не переносятся. JWT содержит:

- `sub`, `iat`, `exp`;
- `scope = primary | managed | guest | roblox`;
- `auth_bot_id` для primary/managed;
- `owner_telegram_id`, `credential_version` для managed.

Каждый `get_current_user` повторно сверяет managed claims с registry и users. Возвращает `auth_scope`, `auth_bot_id`, а для managed ещё `auth_owner_telegram_id`, `auth_credential_version` из проверенной registry. `require_admin` допускает **только primary**, не managed/guest даже при Telegram ID из admin allowlist. `require_primary` доступен сервисам, требующим main trust.

Owner change/official token event отзывает старое доверие в транзакции приёма main manager update **до HTTP ACK**, а не после обработки очереди. Owner change всегда оставляет revoked запись без owner account FK/token; старые intents аннулируются. Новый owner должен отдельно зайти в main и opt-in. Старый аккаунт, баланс и назначенные gift cards остаются прежнему владельцу.

События managed `message.from` принимаются только от owner в совпадающем private chat. Managed merchant/Stars/gift/manager events отклоняются. Известный владельцу token не даёт доступ к чужим balances/codes; сам owner при этом сохраняет доступ к собственным данным в пределах managed scope. Бот не может гарантировать тайну кода от его собственного владельца либо оператора, с которым владелец добровольно поделился token.

Гостевой вход разрешён только при **точном** `ENV in {dev,test}` и отдельном `ALLOW_GUEST_AUTH=true`. Guest имеет `users.is_guest=true`, `telegram_id=NULL`, JWT scope guest; включение флага в production/неизвестной среде не открывает fallback. Guest не получает Telegram notifications или административных прав. Roblox login имеет отдельный scope roblox, не primary.

## Durable inbox, secrets и ограниченные retries

Миграция `0016_managed_bots.sql` добавляет `users.is_guest`, `bot_registry`, `bot_managed_intents`, `bot_private_chats`, `bot_inbox`, `bot_outbox`, `bot_user_attribution`. Старые `bot_pool`/`bot_health` не мигрируются автоматически и не используются. Уже существующие plaintext записи требуют отдельной контролируемой операторской очистки/ротации; этот код не читает и не переносит их.

Webhook сначала проверяет режим, registry и `X-Telegram-Bot-Api-Secret-Token`, **до** чтения body. Затем streaming limit 256 KiB, проверка update ID и повторная secret/version проверка под блокировкой. Update сохраняется зашифрованным; ACK только после commit. Дедуп — `UNIQUE(bot_id,update_id)`. Недоверенные managed события сохраняют только update ID и статус dropped, без чужого payload. Polling продвигает offset только после сохранения всей пачки.

Token/secret зашифрованы Fernet at rest. В public URLs, outbox, exception strings, health-state и логах credentials отсутствуют. Bot API официально требует token в HTTPS path: это неизбежный ephemeral transport URL, не сохраняемый приложением. HTTPX/httpcore transport logs подавлены, redirect/proxy inheritance отключены. Внешние APM/proxy/request-body logs также должны быть выключены/отредактированы оператором — библиотечный фильтр не управляет чужими агентами наблюдения.

Inbox/outbox: `pending → processing → done|dead|dropped`, lease 180 секунд, claim UUID и максимум 8 попыток. Истёкший lease возвращается в обработку; старый worker не может завершить claim другого worker. Inbox сохраняет последовательность одного bot ID. HTTP 429 уважает `retry_after`, transport/5xx временные, 401/403 и нарушения trust не маскируются. На исчерпании попыток сохраняется dead состояние для ручного разбора; автоматического удаления/requeue бесконечно нет.

Доставка Telegram имеет at-least-once, **не exactly-once** семантику. Telegram не предоставляет idempotency key для `sendMessage`: timeout после принятого сообщения может привести к повтору того же сообщения. Giftcard заказ никогда не освобождается и не заменяется из-за такой неоднозначности. Длительный provision/обработка сверх lease могут быть повторены; изменения trust защищены version checks, внешняя сеть не транзакционна с БД. Production требует подобрать concurrency/лимиты и наблюдать backlog/precheckout latency.

## Общий outbox контракт

```python
await app.bot.outbox.enqueue(
    conn, kind=kind, user_id=user_id, payload=payload,
    dedupe_key=dedupe_key, bot_id=None,
)  # -> int, NO commit
```

Глобально уникальный `dedupe_key` возвращает исходный ID; reuse с иным user/kind/payload/bot запрещён. Поддерживаемые публичные kinds:

- `deposit_confirmed`: `{coins, rail, intent_id}`; маршрут только через main merchant, `bot_id` нормализуется в `None`.
- `giftcard_delivery`: `{redemption_id}`; никаких plaintext codes/token.

Внутренний `bot_message` хранит только имя фиксированного шаблона и credential version (для `/mycards ID` ещё redemption ID), не произвольный text/code.

Default notification handler выбирает подтверждённый `bot_private_chats` с текущей credential version и `chat_id == users.telegram_id`. Для giftcard предпочтителен active owned personal bot, иначе проверенный main private chat. При отсутствии private chat — bounded retry, не отправка случайному chat ID. Deposit всегда main. Поля фактического получателя записываются отдельно от origin/auth bot.

Для новой выдачи:

1. `get_conn` + `conn.transaction`: `app.giftcards.service.prepare_delivery(conn, redemption_id, user_id)` проверяет owner, назначенный заказ и сохраняет delivery-start marker. `None` — terminal, отправки нет.
2. Полностью выйти из transaction **и connection**.
3. Повторно проверить registry/private chat version, загрузить token и отправить тот же code.
4. Новые `get_conn` + transaction: `record_delivery(..., telegram_message_id, bot_id=<фактический bot>)` и затем receipt outbox.

`/mycards ID` использует `get_my_card` только в trusted bot worker transaction. Issued карта возвращает прежний code; pending/ambiguous — metadata и повтор той же доставки. Секреты не добавляются в API responses или очередь. Если service не подключён, показывается недоступность, никаких выдуманных карт/балансов.

## Платежи, Stars и gifts

Только main trusted pre-checkout вызывает `app.payments.stars.validate_stars_precheckout(conn, user_id, invoice_payload, currency, total_amount)`. Ответ fail-closed при ошибке. Только main `message.successful_payment` вызывает `settle_stars_payment(..., charge_id)`. Payload ожидается `deposit:<canonical intent id>`; amount/user ID не берутся как достаточное доказательство credit. Отрицательный settlement status оставляет inbox на retry/dead с alert, а не done. Операции самих платёжных сервисов фиксируются внешней transaction.

Managed source никогда не создаёт merchant evidence и не подтверждает Stars/gifts/payments. `/paysupport` направляет в main support, не раскрывает коды.

Автоматический импорт business gifts **не подключён**: один `business_message.gift` без доказанной custody и однозначной связи с intent недостаточен. Сервис payments поддерживает отдельную ручную аттестацию реально полученного подарка primary-администратором и review; бот не вызывает credit по пользовательским gift IDs, скриншотам или «квитанциям». Это не заявление о live-готовности gift rail.

## Пользователи, Welcome, referral и landing

Main commands и main Telegram login выполняют единый upsert по `telegram_id` и idempotent Welcome под users row lock. Используется существующий ledger primitive без скрытого commit. Referral payload `ref_<internal users.id>` проверяет обе users FK, self-referral/guest исключены, `ON CONFLICT(referee_id)` не меняет первого referrer. Ссылка берёт username из `BOT_USERNAME`, не из hardcoded имени.

`/start lp_<campaign>` сохраняет первый touch только от main. Allowlist: `organic`, `telegram`, `social`, `creator`, `launch-br`; payload ASCII до 32 символов, slug 1–29. Таблица attribution отдельно от referral/owner/account. Повторный start не переписывает кампанию и не меняет ownership.

## Health и проверки

Registry хранит `health_status`, `consecutive_failures`, `last_error_code`, таймер проверки, `alert_pending/attempts/next_alert_at/last_alert_error_code`. Watchdog сверяет `getMe.id`, классифицирует ошибки, ограниченно повторяет alerts, не хранит raw response/URL. 401 managed отзывает credential version; переподключение только через официальный opt-in. Бан не вызывает смену аккаунта/перенос игроков.

Focused tests находятся в `backend/tests/bot/` и `backend/tests/test_auth{,_guest}.py`: чужая/admin initData под managed token, owner change/revocation, intent/getMe binding, guest prod fail-closed, inbox duplicates/header-before-body, transactional outbox reuse, no-secret payload, одинаковый code после ambiguous send, main-only merchant, Welcome/ref FK и first-touch. Тестовые tokens синтетические, HTTP только MockTransport/fake, production `.env` не нужен.

Общий изолированный прогон 2026-11-11: **269 backend-тестов прошли**, включая bot/auth и четыре регрессии порядка блокировок Stars. Реальные Telegram flow, BotFather provisioning и нагрузка не проверялись. Итоговые проверки и условия стенда — [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md). Перед включением необходимы HTTPS ingress limits, отдельный worker, менеджер BotFather, реальные безопасно настроенные secrets, проверки основной merchant identity и эксплуатационный разбор dead/revoked состояния. Наличие реализации само по себе не означает live ready.
