# Coinso: полная инструкция по интеграции (WINDROP)

> Источник: официальная спецификация https://coinso.io/docs (OpenAPI, движок CryptoProc).
> Проверено: 2026-11-06.

## 0. Что такое Coinso и что он закрывает

- Способы: **SBP, карты (RU), крипта (USDT 6 сетей, USDC, TON, BTC, ETH, TRX, LTC), P2P** (`p2p_sbp`, `p2p_card` — включаются менеджером).
- **Все суммы в API — рубли** (`amount` в RUB). Coinso — рельс для СНГ-гео.
- **PIX нет.** Для Бразилии (ROBLOXWINDROP) нужен отдельный PIX-эквайер (кандидат: PayOp) — Coinso подключаем как крипта+СНГ рельс.
- Ключевой вопрос, который остаётся уточнить у саппорта: **конвертация рублёвых приходов (SBP/карты) в USDT при выводе** и список стран приёма карт. В API-доках этого нет — только дашборд/менеджер.

## 1. Аккаунт и проект (без кода)

1. Зарегистрироваться на coinso.io, подтвердить аккаунт.
2. Создать **проект** (Project). Требования модерации: сайт по HTTPS с доменом (не IP, без `#`/`?`/креденшелов в адресе), заполненный сайт без заглушек, страницы ToS и Privacy, контакты поддержки. Иначе ошибка `merchant_site_rejected` при создании счетов.
3. В настройках проекта взять два ключа:
   - **API Key** — публичный идентификатор проекта (показывается клиентам/в логах, ничего не авторизует).
   - **Secret Key** (= Webhook Secret) — приватный. **Им авторизуются все запросы на создание счетов**: заголовок `Authorization: Bearer <Secret_Key>`. Не светить, хранить только в `.env`.
4. Указать в проекте **success_url / fail_url** (можно переопределять per-invoice).
5. Попросить менеджера включить: нужные методы (crypto, sbp, card, p2p_*), при необходимости **H2H** (реквизиты прямо в API, без страницы Coinso) и нужные сети USDT (`GET /payment/methods` покажет, что реально включено).
6. Включить **Test mode** (toggle в дашборде, через API не управляется) — до конца интеграции.

## 2. Как проходит платёж

### Standard (простой путь — оффбординг на страницу Coinso)
1. `POST https://coinso.io/api/payment/create` (Bearer Secret Key, JSON):
   - `project_id`, `amount` (RUB, > 0),
   - `custom` — наш идентификатор заказа (вернётся в вебхуке),
   - `method: "crypto"` (или без method — плательщик выбирает на странице),
   - `currency: "usdt_trc20"` (только для method=crypto),
   - `client_telegram_id` (у нас всегда есть), `client_user_id` — для антифрода,
   - `success_url`, `fail_url`.
2. Ответ: `invoice_id` (8 символов), `payment_url` — редиректим игрока.
3. После оплаты игрок возвращается на `success_url?order=…&txn=…&invoice_id=…&custom=…` — **это НЕ подтверждение оплаты**, только для «спасибо»-страницы.
4. Приходят вебхуки `payment.success` / `payment.failed` на `webhook_url` проекта. Оплата зачисляется **только** по вебхуку или `GET /payment/status?invoice_id=…`.

### H2H (для мини-аппа: свой UI без ухода на Coinso)
- `integration_type: "h2h"` + обязательные `client_ip` (IP игрока!) и контакт (`client_telegram_id`) или `client_user_id`.
- Ответ содержит реквизиты прямо: крипто-адрес, `nspk_link` (SBP) или P2P-реквизиты (`requisite`, `expires_in` ~10 мин, `payer_warning`).
- `method=crypto` доступен в h2h сразу; SBP/P2P h2h — только после включения менеджером. Карты через h2h не работают.
- Таймаут HTTP-клиента: SBP QR может выдаваться до 30 сек → таймаут ≥ 40 сек.
- Игрок обязан перевести ровно `amount`.

### Ошибки
Всегда JSON `success:false` + `error_code`, `error_source` (`bank`/`merchant`/`payer`/`coinso`), `error_description_en`, `retryable`, `invoice_id`. Повторы — не чаще, чем раз в 10–15 сек (каждый retry для `bank_*` создаёт новый инвойс). Не ретраить `retryable:false`.

## 3. Тестовый прогон

1. Test mode ON → создать инвойс обычным запросом → открыть `payment_url` → кнопки **Simulate success / Simulate failure**.
2. Проверить: вебхук пришёл реальный, `GET /payment/status` отдаёт `test_mode: true`, деньги НЕ попадают на выводимый баланс.
3. **Не выдавать баланс игрокам за платежи с `test_mode: true`** (флаг есть и в вебхуке, и в status).
4. Всё зелёное → Test mode OFF.

## 4. Интеграция в бэкенд WINDROP

Паттерн — как существующий `plugins/payments/gowd_latam`. Состав работ:

1. **Env** (`infra/.env` + `backend/.env`, в git не попадают):
   ```
   COINSO_API_BASE=https://coinso.io/api
   COINSO_PROJECT_ID=123
   COINSO_SECRET_KEY=<Secret Key>
   COINSO_WEBHOOK_SECRET=<тот же Secret Key>
   ```
2. **Плагин** `backend/plugins/payments/coinso/adapter.py`:
   - `MANIFEST = {"key": "coinso", "type": "payment", "contract_version": 1}`
   - `create_payment(user, amount_rub, intent_id)` → POST /payment/create, `custom=intent_id`, `client_telegram_id`, таймаут 40 c;
   - `verify(invoice_id)` → GET /payment/status (сверка при споре);
   - `register(reg)` → `registry.register(...)`.
3. **Вебхук-эндпоинт** (в `core/api/router.py` рядом с другими платёжными):
   - `POST /api/payments/coinso/webhook`;
   - верификация Secret Key (схему подписи вебхука уточнить у саппорта — до этого проверять source IP + сверять invoice_id через GET /payment/status перед зачислением);
   - **идемпотентность по `invoice_id`** (таблица `payment_events`, `apply_event` — никаких прямых записей в ledger);
   - игнор `test_mode: true` (или зачисление только на staging-окружении);
   - ответ 200 быстро, обработка в фоне.
4. **Конфиг рельса**: `backend/configs/payments/coinso.yaml` + добавить `coinso` в `rails` нужных гео в `configs/tenants/<tenant>.yaml` (для СНГ-тенантов; в BR-тенант не добавляем).
5. **Тесты**: happy path (success-вебхук → баланс вырос, ledger-инвариант цел), дубль вебхука (баланс не растёт дважды), failed-вебхук, чужая подпись/незнакомый invoice_id, test_mode.
6. **Ввод в строй**: Test mode → staging прогон → Test mode OFF → мини-апп: кнопка «Пополнить» → create → редирект на `payment_url` → закрытие по вебхуку.

## 5. Чек-лист вопросов саппорту Coinso (до продакшена)

- [ ] В какие страны принимаете карты? (гео-список)
- [ ] Конвертируете ли рублёвые приходы (SBP/карты) в USDT при выводе? Автоматически?
- [ ] Куда выводится баланс: на некастодиальный USDT-кошелёк? Какая сеть/комиссия вывода?
- [ ] Схема подписи вебхука (header/алгоритм)?
- [ ] Rolling reserve / холды? Лимиты на инвойс по методам?
- [ ] P2P и карты — нужен ли отдельный договор с менеджером?
