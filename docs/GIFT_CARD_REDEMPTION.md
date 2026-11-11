# Безопасный обмен монет на gift cards Roblox / BR

## Границы продукта

Игрок тратит **целые монеты** (`users.balance_units`, ledger currency `units`) на **одну заранее закупленную карту одного явно настроенного SKU**. Это не вывод денег, PIX, криптовалюты или перевод Robux. `freebets` не принимаются. Никакого автоматического заказа у поставщика, конвертации денежного баланса, изменения текущих цен или скрытой комиссии нет.

У SKU отдельно хранятся:

- `coin_cost`: точная цена в целых существующих ledger units, без умножения/деления баланса на 100;
- `face_value_minor`: настоящий номинал карты в centavos;
- `card_currency='BRL'`, `brand='Roblox'`, `region='BR'`;
- `operator_sku`: артикул, заданный оператором;
- `sandbox`: обязательный признак тестовой карты.

Равенство цены в монетах и номинала карты не подразумевается. Один заказ всегда содержит ровно одну карту. `quantity`, пользовательские `amount`, `region`, `fee`, цена или номинал в запросе покупки не принимаются. Новый SKU создаётся выключенным; изменить его денежный смысл через API нельзя — для нового mapping создаётся новый SKU, старый выключается.

## По умолчанию всё выключено

Настройки добавляются основной интеграцией в `app.config.Settings`:

| Настройка | Безопасное значение по умолчанию |
| --- | --- |
| `giftcard_redemption_enabled` | `False` |
| `giftcard_mode` | `'disabled'`; допустимые рабочие режимы `'sandbox'`, `'live'` |
| `giftcard_fernet_key` | пусто |
| `giftcard_fingerprint_key` | пусто |

Два ключа разные: Fernet и отдельный base64url-encoded 32-byte HMAC ключ. Ключи никогда не генерируются автоматически при запуске, не хранятся в репозитории и не возвращаются API. При отсутствии или некорректности настроек публичный каталог пуст и выключен; новое списание невозможно. Ключи gift card не подменяются общим `fernet_key` для ботов. Вызовы тестового кода генерируют только временные тестовые ключи.

Миграция — только `backend/migrations/0018_giftcard_redemption.sql`, после `0016_managed_bots.sql` и `0017_payment_safety.sql`. Она создаёт пустые `giftcard_skus`, `giftcard_batches`, `giftcard_inventory`, `giftcard_redemptions`; **ничего не закупает, не импортирует, не пересчитывает и не ремапит**. Нельзя запускать её на рабочей БД без отдельного операционного согласования, резервной копии и проверки на изолированной тестовой БД. В локальной интеграции 2026-11-11 она успешно применена только к изолированным тестовым БД; рабочая схема не менялась. Результаты — [LOCAL_ACCEPTANCE.md](LOCAL_ACCEPTANCE.md).

## Кто может обменивать

Нужен подтверждённый Telegram пользователь с `is_guest=False`, `auth_scope='primary'` либо `'managed'`. Guest запрещён и для live, и для sandbox. Roblox-only login не даёт права на выдачу в Telegram.

`managed` разрешён только своему владельцу: `auth_bot_id`, `auth_owner_telegram_id == telegram_id`, проверка владельца/credential version в auth deps. Клиент не передаёт `user_id` или `bot_id` в теле создания заказа. Из БД повторно проверяются `is_guest` и Telegram identity, которая сохраняется в заказе. Включение sandbox не создаёт пользователей, монеты или SKU: тестовый пользователь и тестовый mapping должны быть заданы отдельно.

## Склад и импорт

Партия должна быть **уже оплачена и получена оператором**. Admin API не поддерживает покупку, supplier API и фоновую проверку активации.

1. Создать выключенный SKU с фактическим номиналом BRL и согласованной ценой в монетах.
2. Подготовить CSV UTF-8 с единственным заголовком `code`, одним кодом в строке. Лимит — 1 MiB и 2000 строк; произвольные дополнительные столбцы запрещены. Коды — ASCII буквы/цифры, разделители `-`, длина 8–256, регистр нормализуется. Неподдерживаемый формат запрещается, а не исправляется эвристикой.
3. Для sandbox каждый код обязательно начинается с `TEST-ONLY-`. Такие коды ничего не обещают и не являются настоящими redeemable Roblox cards. В live импорте тестовые префиксы отвергаются.
4. Заполнить `supplier_name`, `batch_reference`, `provenance_reference`; live также требует `distribution_agreement_reference`. Это ссылки/номера внутренних документов, **не коды, пароли или документы с персональными данными**. Поля metadata могут попадать в access logs URL, поэтому никакие секреты туда не помещаются.
5. Загрузить raw CSV через `POST /admin/giftcards/import?...` с `Content-Type: text/csv`. Это не multipart `UploadFile`: библиотечный spool мог бы записать plaintext на диск ещё до endpoint. Endpoint читает ограниченный поток в памяти. Не включать body logging, tracing locals или proxy request capture для импорта и Telegram отправки.
6. Только после проверки mapping и документов явно включить SKU. Глобальный режим и ключи всё равно должны быть настроены; activation SKU не включает систему.

CSV целиком проверяется до вставки; вся партия атомарна. Повтор внутри файла, в предыдущей партии или параллельном импорте отменяет **всю** загрузку. В БД отправляются только Fernet ciphertext и keyed HMAC-SHA256 fingerprint. Fingerprint общий для live/sandbox и всех SKU; он нормализует регистр и `-`, чтобы повтор кода под другим SKU не был принят. Ни code, ни ciphertext, ни fingerprint не выдаются администратору. Ошибки импорта содержат только безопасный код и сообщение, не ошибочную строку или psycopg detail.

Ротация ключей требует отдельной контролируемой операции: перешифровать ciphertext, сохранить корректный HMAC-index и уникальность. Просто заменить ключ в настройках нельзя — это блокирует дешифровку/ломает дедупликацию. Автоматической ротации или восстановления plaintext в этой задаче нет. Legacy `gift_codes.code` не переносится автоматически; старое plaintext-хранилище остаётся отдельным закрытым legacy-риском и требует согласованной инвентаризации/очистки с оператором.

## Атомарный обмен и повторы

`app.withdrawals.service.redeem(conn,user,*,sku_id,idempotency_key)` использует один `conn.transaction()`:

1. `FOR UPDATE` пользователя сериализует списания и повторы одного владельца.
2. Проверяется `(user_id,idempotency_key)`. Тот же SKU возвращает прежний заказ (даже если сейчас выключен обмен); другой SKU — `409 idempotency_conflict`. Ключ scoped к пользователю, не глобален.
3. Читается активный SKU нужного режима, затем один код через `FOR UPDATE SKIP LOCKED`.
4. Вставляется заказ со snapshot цены/номинала/владельца, единственный код связывается с ним.
5. `post_entry(conn,user_id,'units',-coin_cost,'giftcard_redemption',...)` списывает целые монеты.
6. `app.bot.outbox.enqueue` записывает `kind='giftcard_delivery'`, `payload={'redemption_id': id}`, уникальный dedupe key и origin `bot_id` из trusted auth context. Ни enqueue, ни reserve, ни ledger не выполняют промежуточный commit.

Любая ошибка откатывает заказ, списание, назначение и событие. Если последнего свободного кода нет или он заблокирован другим заказом — `409 no_inventory` без списания. Snapshot номинала не уменьшается на fee и не сравнивается с ценой в монетах. Никакой последующей supplier settlement-функции для этого потока нет.

## Контракт bot worker и неоднозначная отправка

Публичные функции находятся в `app.giftcards.service`:

```python
prepare_delivery(conn, *, redemption_id, user_id) -> DeliveryData | None
record_delivery(conn, *, redemption_id, user_id, telegram_message_id, bot_id=None) -> dict
list_owned_cards(conn, *, user_id, limit=100) -> list[dict]
get_my_card(conn, *, redemption_id, user_id) -> dict
```

`prepare_delivery`, `record_delivery`, `get_my_card` — **NO commit primitives**, требующие явной активной транзакции вызывающего кода. Worker выбирает и проверяет доверенный private-chat маршрут перед раскрытием кода. Правильная граница:

```python
async with get_conn() as conn:
    async with conn.transaction():
        delivery = await prepare_delivery(conn, redemption_id=order_id, user_id=owner_id)
# Только после выхода из обоих контекстов marker точно committed.
# Telegram send выполняется worker-ом вне транзакции и без логирования delivery/code.
# После успешной отправки — новая connection/transaction и record_delivery(actual_bot_id).
```

`prepare_delivery` проверяет владельца/Telegram identity и неизменное назначение inventory, выставляет `status='delivering'`, `delivery_started_at`, счётчик попыток; расшифровывает лишь непосредственно для отправки. Возвращает `redemption_id`, `user_id`, `telegram_id`, `bot_id`/`origin_bot_id`, `code`, `brand`, `region`, `card_currency`, `face_value_minor`, `coin_cost`, `sandbox`. `DeliveryData` скрывает code в `repr/str`, но это не разрешение сериализовать или логировать содержимое. Для issued/rejected возвращается `None`.

Таймаут Telegram может означать, что сообщение доставлено. Retry берёт **тот же redemption и тот же inventory/code**, не резервирует новый. Exactly-once отправку Telegram гарантировать невозможно; возможен повтор сообщения с тем же кодом, но не выдача второй карты. Inventory после committed prepare не возвращается в доступный склад по TTL, таймауту или отсутствию активации.

`record_delivery` вызывается после send, сохраняет первый Telegram message id, фактический `delivered_bot_id` и `delivered_credential_version`, не изменяя origin `bot_id`. Повтор подтверждения идемпотентен. Фактический sender проверяется по активному `bot_registry`, `bot_private_chats` того же пользователя, `chat_id == order.telegram_id`, текущей credential version. Main должен проходить `trusted_main`; managed — принадлежать тому же owner user/Telegram identity, иметь валидный active registry и не находиться в owner-change. `bot_id=None` означает только проверенный main private chat. Fallback из managed в main разрешён **лишь при таком подтверждённом private chat**; иначе worker оставляет событие ожидающим, не отправляет в чужой бот и не подделывает receipt. Если проверка после send не проходит из-за ротации/отзыва, заказ остаётся assigned/delivering, не возвращается в склад.

`/mycards` — только доверенная команда бот-воркера в private chat своего пользователя, не HTTP-доступ по произвольному user id. `list_owned_cards` всегда без кодов. `get_my_card` для pending/delivering/manual_review/rejected возвращает только metadata. Для issued и совпадающего режима возвращает тот же code с `status='issued'`, без нового резерва. Список сам по себе не рассылает все коды повторно. `GiftCardError` имеет безопасные `.code`, `.status_code`, `str(...)`.

## Отмена, manual review, legacy

`POST /admin/redemptions/{id}/reject` разрешён только `pending` **до** committed `delivery_started_at`. Блокировки user/order/inventory согласованы с выдачей. Refund ledger имеет явную валюту `'units'` и уникальный ref; повтор возвращает состояние rejected без второго возврата. Код может вернуться в склад только после этого подтверждённого отказа до отправки. Старый outbox этого rejected заказа безопасно даёт `None`, даже если код уже зарезервирован новым заказом.

Если delivery уже начиналась, отказ возвращает `409 manual_review_required`; delivering переводится в manual_review без возврата и без освобождения кода. Issued остаётся issued; нужен ручной разбор. Установка флага manual_review не означает автоматическое решение конфликта, refund или замену карты. Поздний настоящий receipt разрешено записать через доверенную `record_delivery`; ручной HTTP finalize для новых заказов не существует.

`withdrawals` и `gift_codes` старого формата не содержат надёжного mapping цена/номинал/комиссия. Они не ремапятся, не выдаются и не возвращаются автоматически. `/withdrawals/mine` и `/withdrawals/{id}/status` сохраняют owner-only просмотр прежнего состояния с `legacy=true, read_only=true`. Старые approve/reject/unfreeze блокируются. Legacy finalize только возвращает manual_review/read_only, не вызывает supplier и не переписывает историю. Старые `release_expired`/verification jobs больше не возвращают issued/assigned коды в склад.

## HTTP API

Все маршруты регистрируются существующими `app.api.giftcards.router`, `app.api.withdrawals.router`, `app.api.admin_withdrawals.router` — дополнительных include_router не требуется.

| Метод и путь | Назначение |
| --- | --- |
| `GET /giftcards/catalog` | `{enabled,mode,items:[{id,operator_sku,brand,region,card_currency,face_value_minor,coin_cost,sandbox,available_count,available}]}` |
| `POST /redemptions` | Строго `{sku_id:int,idempotency_key:str}`; owner metadata заказа, без code |
| `GET /redemptions` | Последние 100 заказов своего пользователя без code |
| `GET /redemptions/{id}` | Owner-only status и snapshot без code |
| `POST /withdrawals` | Только adapter с новым explicit SKU body; ответ с `redemption_id` и `/redemptions/{id}` status_url; старый body отвергается |
| `GET /withdrawals/mine`, `GET /withdrawals/{id}/status` | Только legacy просмотр, id-пространства не смешиваются |
| `GET /admin/giftcards/skus`, `POST /admin/giftcards/skus` | Явная настройка SKU; новый always inactive |
| `PATCH /admin/giftcards/skus/{id}` | Строго `{active:bool}` |
| `POST /admin/giftcards/import` | Raw CSV, metadata через query, атомарная загрузка |
| `GET /admin/giftcards/stats` | Только счётчики по режиму/статусу |
| `GET /admin/redemptions` | Без code, ciphertext, fingerprint; необязательный status |
| `POST /admin/redemptions/{id}/reject` | `{reason:'operator_rejected'|'requested_by_owner'|'risk_review'}` |
| `GET /admin/withdrawals` | Legacy read-only без code |

Admin endpoints требуют primary admin, не managed admin. В `frontend/admin.js` показаны coin cost и настоящий BRL-номинал, явный sandbox, управление inactive/active SKU и защищённая загрузка. Там нет кнопки «показать код», произвольной стоимости карты, автоматической покупки или возврата после начала доставки.

## Поставщики и права

Первичный список для **ручной** проверки оператором: **Reloadly, Tillo, Runa**. Это не утверждение о доступности конкретного Roblox BR SKU, его цене, лицензии нашей платформы или заключённом договоре. До live нужны проверка каталога/номиналов/региона/условий активации и **distribution agreement**, разрешающий нужную модель распространения/перепродажи с соблюдением Roblox BR terms. Нельзя называть сервис «лицензированным» или перепродавать карты только потому, что публичный поставщик упоминает Roblox. Контактов/покупок/сетевой проверки этих условий здесь не выполнялось.

## Проверки и известные ограничения

Добавлены целевые тесты на concurrent last-code exchange и locked code SKIP LOCKED, user-scoped idempotency и payload conflict, rollback при ошибке outbox, отсутствие списания без склада/с freebets, atomic duplicate import, шифрование, sandbox/guest/disabled gates, retry неоднозначной отправки тем же кодом, refund ровно один раз до send, запрет refund/recycle после send, owner-only `/mycards`, первый delivery receipt, foreign/stale bot и primary fallback. Legacy tests теперь фиксируют read-only/manual-review, а не небезопасную выдачу по старой hidden-fee формуле.

Интеграционные тесты можно выполнять только после готовности общего защитного `TEST_DATABASE_URL` harness, в изолированной БД и без реальных кодов. Статическая проверка синтаксиса/линтер не доказывает корректность PostgreSQL гонок или Telegram маршрутизации; результаты конкретного тестового прогона фиксируются отдельно в отчёте основной интеграции. Сеть, покупки, выдача настоящих карт и миграция рабочей БД требуют отдельного операционного согласования. Не реализованы автоматическое разрешение manual-review, ротация ключей, сверка закупки с внешним поставщиком или автоматическая очистка legacy plaintext.
