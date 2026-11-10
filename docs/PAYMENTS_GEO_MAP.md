# WINDROP: карта платёжных рельсов по гео

> Модель: одна площадка (тенант) на гео → локальный способ оплаты → конвертация в USDT →
> единый крипто-кошелёк. Комиссии платёжек оплачиваются на стороне клиента (gross в инвойс,
> net на баланс). Без KYC — приоритет.

## Волна 1 — Бразилия (ROBLOXWINDROP, запускается сейчас)

| Rail | Ключ | Провайдер | Метод | Комиссия (на клиенте) | Статус |
|---|---|---|---|---|---|
| Карта/страница | `paygate` | PayGate.to (без KYC, без ключей, выплата USDC сразу на наш Polygon-кошелёк) | Visa/MC/Apple/Google Pay, hosted-страница с автовыбором провайдера | 4% (env `PAYGATE_FEE_PERCENT`) | ✅ адаптер готов |
| Крипта | `coinso` | Coinso.io (без KYC, Bearer Secret Key) | USDT TRC20/TON/BEP20 и др. | 1% (env `COINSO_FEE_PERCENT`) | ✅ адаптер готов |

Env: `PAYGATE_WALLET` (USDC Polygon), `PAYGATE_CALLBACK_BASE`, `COINSO_SECRET_KEY`,
`COINSO_PROJECT_ID`, `COINSO_SUCCESS_URL`, `COINSO_USD_RUB_RATE` (инвойсы Coinso в RUB).

Открытый вопрос: нативный PIX (QR/ключ, оплата из банковского приложения) — PayGate даёт
карточную страницу без PIX. Если конверсия карт будет низкой — подключить P2P-PIX-агрегатора
(искать в Telegram-каналах iGaming-арбитража, в открытой сети не индексируются).

## Волна 2 — Мексика, Филиппины, Индонезия

| Гео | Метод | Кандидаты (no-KYC) | План |
|---|---|---|---|
| **MX** (SPEI) | SPEI-перевод | Серые агрегаторы через TG-каналы; Coinso — уточнить SPEI у саппорта | Прототип rail `spei` по паттерну paygate; тест малой суммой |
| **PH** (QRPh/GCash) | QR-код | P2P-агрегаторы GCash/Maya из iGaming-сообществ | rail `qrph` (каркас в tenant уже заложен, выключен) |
| **ID** (QRIS) | QRIS | P2P-агрегаторы (GoPay/OVO/DANA через посредников) | rail `qris` (каркас заложен, выключен) |

Для всех трёх крипто-рельс `coinso` уже работает — игроки с USDT закрываются сразу.

## Волна 3 — Африка и Европа

- **Африка**: M-Pesa (Кения/Танзания), мобильные деньги Нигерии (оплаты через P2P-агрегаторов), USDT как основной метод (крипто-адаптация высокая). Кандидат-крипта: Paymento/PayRam (некастодиально).
- **Европа**: SEPA-переводы (PayGate поддерживает SEPA через hosted-страницу — вероятно, закроется текущим рельсом `paygate`), карты — тот же `paygate`. Регуляторика строже: не запускать без проверки статуса площадки.

## Волна 4 — весь мир

- Карты глобально: PayGate (уже подключён, geo `*`).
- Крипта глобально: Coinso + некастодиальный шлюз (Paymento/PayRam) как резерв — supplier fallback в коде уже поддерживает primary → fallback → deferred.
- Локальные рельсы добавляются по спросу: новый адаптер по паттерну `plugins/payments/paygate` + rail в tenant YAML.

## Как добавить новое гео / рельс (чек-лист)

1. Адаптер `plugins/payments/<rail>/` по паттерну paygate/coinso:
   `MANIFEST`, `rail_key`, `methods`, `client_fee_percent()`, `create_payment()`,
   `poll_payment()`, `handle_webhook()`; реэкспорт в `plugin.py`.
2. `configs/geos/<GEO>.yaml` + geo в `configs/tenants/<tenant>.yaml` (`rails: [...]`).
3. Env-переменные в `infra/.env` и `backend/.env` (в git не коммитятся).
4. Вебхук: POST `/{base}/webhooks/<rail>` (или GET — обработчик общий) + верификация
   в `core/api/router.py::_handle_webhook` против сохранённого интента.
5. Тесты в `tests/payments/`: create (mock httpx), webhook parse, fee.
6. Тенант-валидация сама проверит, что rail зарегистрирован (`load_tenant`).

## Правила эксплуатации (анти-заморозка)

- Не держать баланс у процессора: свип в USDT/на кошелёк минимум раз в сутки.
- Два провайдера на гео (primary/fallback) — переключение через tenant YAML без деплоя.
- Нового провайдера всегда обкатывать малой суммой с немедленным выводом.
- `test_mode` Coinso — для проверки цепочки до боевых платежей; платежи с
  `test_mode: true` на баланс игроков не зачислять.
