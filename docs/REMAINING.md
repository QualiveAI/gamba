# Что осталось доделать (актуализировано 2026-11-06)

## Выполнено (было в старом списке, подтверждено кодом и тестами)

- ✅ Payment events pipeline: `ingest()`, `process_pending()`, `create_intent()` (tests/payments)
- ✅ Verify gate: `POST /admin/withdrawals/{id}/finalize` подключён (tests/withdrawals)
- ✅ Supplier fallback: primary → fallback → deferred + circuit breaker (core/delivery/supplier_client.py)
- ✅ Config versioning: `tenant_config_versions`, activate/rollback, pinned (core/config/versioning.py)
- ✅ ServiceDisabled + kill switch (core/service_disabled.py)
- ✅ RTP wiring: cases_freebet вызывает `effective_rtp`; roblox-каталог из БД
- ✅ Auto-pause: тесты зелёные, scheduler в main.py
- ✅ Builder UI publish flow (frontend/js/admin_builder.js)
- ✅ Chaos-тесты против реальных API
- ✅ Раннер миграций `tools/migrate.py` + миграция 0009 (withdrawals.idempotency_key)
- ✅ Тестовая изоляция (conftest: очистка БД на прогон); 116+ тестов зелёные, ruff чист

## Выполнено в этой итерации (платежи WINDROP)

- ✅ Плагин `paygate` (карты, без KYC, USDC-выплата на свой кошелёк) + GET-вебхук
- ✅ Плагин `coinso` (крипта USDT) + вебхук + сверка через /payment/status
- ✅ Депозиты: JWT, intents в БД, комиссия на клиенте (gross в инвойс, net на баланс),
  зачисление через apply_event (идемпотентно)
- ✅ Мини-апп: выбор способа оплаты, показ комиссии, поллинг статуса
- ✅ Фронт игр (crash/mines/upgrade/shell) переписан на боевой API
  (раньше вызывал mock-эндпоинты, которых нет)
- ✅ Удалены mock-роутеры core (перехватывали боевой POST /withdrawals)
- ✅ GET /withdrawals/{id}/status для поллинга вывода
- ✅ White-label брендинг: GET /meta/tenant + применение бренда тенанта на фронте
  (tenant default = ROBLOXWINDROP)
- ✅ docs/PAYMENTS_COINSO.md, docs/PAYMENTS_GEO_MAP.md (волны: BR → MX/PH/ID → Африка/ЕС → мир)

## Осталось (приоритет)

### Высокий
- **Боевые ключи платежей**: PAYGATE_WALLET, COINSO_SECRET_KEY/PROJECT_ID в infra/.env;
  прогон цепочки через Test mode Coinso до продакшена.
- **Нативный PIX**: PayGate не даёт PIX-QR; если конверсия карт низкая — P2P-PIX-агрегатор
  (искать в TG-каналах iGaming-арбитража), rail по чек-листу из PAYMENTS_GEO_MAP.md.
- **i18n**: модуль core/i18n мёртв (никто не вызывает), локаль одна en.yaml. Подключить
  локали в мини-апп (pt-BR) и тексты бота — отдельная задача white-label.

### Средний
- Перевод stars/gifts/yoomoney с прямого post_entry на events pipeline
  (идемпотентность уже есть в post_entry — низкий риск, отложено сознательно).
- Coинько-адаптер Coinso: уточнить у саппорта схему подписи вебхука (сейчас доверяем +
  сверяем статус через API) и реальный курс RUB (env COINSO_USD_RUB_RATE=90).
- Playwright e2e на новые потоки депозитов и игр.

### Низкий
- Метрики/алерты по payment events (Prometheus render есть).
- Расширить chaos-тесты на новые платёжные рельсы.
