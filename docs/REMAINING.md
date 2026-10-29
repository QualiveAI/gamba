# Что осталось доделать

## Высокий приоритет (блокирует запуск)

- **Payment events pipeline**
  - `core/payments/events.py`: `ingest()`, `process_pending()`, `create_intent()` (интенты уже есть).
  - таблицы `payment_events` и `payment_intents` уже добавлены, но обработчик pending-событий отсутствует.
  - мигрировать оставшиеся прямые `post_entry` в `stars.py`, `gifts.py`, `yoomoney` на `apply_event`.

- **Wire verify gate в API**
  - добавить `POST /admin/withdrawals/{id}/finalize`.
  - подключить `finalize()` к фоновой задаче/очереди, чтобы gate реально срабатывал.

- **Supplier fallback**
  - `core/delivery/supplier_client.py`: primary → fallback → deferred.
  - circuit breaker, корректные статусы `pending_supplier` / `manual_review`.

- **Config versioning**
  - таблица `tenant_config_versions`.
  - `activate_config()` с rollback и pinned-версиями.

- **ServiceDisabled exception + kill switch**
  - реализовать исключение и middleware для отключения сервисов на лету.

## Средний приоритет

- **RTP wiring**
  - `cases_freebet` должен вызывать `effective_rtp`.
  - Roblox plugin должен читать каталог из БД, а не YAML.

- **Auto-pause**
  - убрать зависимость от null `catalog_version_id` в `case_openings`.
  - проверить scheduler каждые 10 минут на реальных данных.

- **Builder UI**
  - завершить publish flow: create case → version → prizes → preview → publish (сейчас stub alert).

- **Chaos tests**
  - переписать против реальных API после появления модулей.
  - покрыть webhook race, supplier down, kill switch, config rollback.

- **Real-money smoke**
  - прогон на staging с mock suppliers.

## Низкий приоритет / улучшения

- убрать оставшиеся прямые вызовы ledger вне `apply.py`;
- расширить i18n и локализацию ошибок;
- добавить метрики/алерты для новых payment events;
- документация API и RUNBOOK для новых эндпоинтов.

## Текущий статус тестов

- 44+ тестов проходят, ruff clean, AST guard проходит.
- chaos tests пока skip (зависимости отсутствуют).
- payment intents покрыты 4 тестами (все проходят).
