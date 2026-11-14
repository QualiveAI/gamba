# Развёртывание

## Границы конфигурации

- `infra/docker-compose.yml` — существующая локальная среда. Порты сохранены: Caddy `8090`, API `8001`, PostgreSQL `5432`, Redis `6379`; имя volume `pgdata` не меняется. Не используйте её для тестов и не выполняйте `down -v`.
- `infra/docker-compose.prod.yml` — **самостоятельная** production-конфигурация, а не override локальной. PostgreSQL внутри неё отсутствует: нужен отдельный постоянный сервис с **одним writable primary**. Vercel может раздавать frontend, но не PostgreSQL, scheduler или постоянно работающие workers.
- API, Telegram worker, payment inbox worker и scheduler — отдельные процессы. API принимает main/managed webhook по одному стабильному HTTPS-домену; polling в production запрещён.
- По умолчанию `BOT_MODE=disabled`, `PAYMENTS_MODE=disabled`, `MANAGED_BOTS_ENABLED=false`, `GIFTCARD_MODE=disabled`, `ALLOW_GUEST_AUTH=false`. Это закрытый preview, не анонимный работающий магазин. Для реального запуска режимы включаются отдельно после проверок.
- Один host с `media:/app/media` — поддерживаемый режим `MEDIA_STORAGE_MODE=local`. API primary/standby разделяют этот volume. Object storage ещё не реализован: `object` отклоняется, межхостовое переключение с локальным media обещать нельзя.

## Локальные команды

Команды ниже — действия оператора, не автоматический запуск. Выполнять из корня репозитория; работающий стек сначала согласовать с владельцем. Не читать, не печатать и не копировать существующие секреты ради проверки конфигурации.

```bash
# Проверить только конфигурацию без private env (Linux/Git Bash с /dev/null).
WINDROP_ENV_FILE=/dev/null docker compose --env-file /dev/null -f infra/docker-compose.yml config --quiet

# Только после согласования: обычный up НЕ запускает ботов/scheduler/миграции.
docker compose -f infra/docker-compose.yml up -d --build

# Миграции — отдельное явное действие. Сначала read-only статус.
docker compose -f infra/docker-compose.yml --profile ops run --rm migrate python tools/migrate.py --status
docker compose -f infra/docker-compose.yml --profile ops run --rm migrate

curl --fail http://127.0.0.1:8001/health/live
curl --fail http://127.0.0.1:8001/health/ready

# Scheduler — явный opt-in, отдельный процесс.
docker compose -f infra/docker-compose.yml --profile scheduler up -d scheduler

# Dev polling требует отдельных dev credentials и согласия на запросы Telegram.
# Нельзя запускать второй poller того же bot token или одновременно webhook.
docker compose -f infra/docker-compose.yml --profile dev-polling up -d bot worker
```

Локальный compose задаёт disabled режимы явно, даже если в старом `.env` лежат live ключи. Профиль `dev-polling` переопределяет только bot mode; платежи остаются выключенными. Для sandbox-платежей нужен отдельно проверенный override одновременно API и `payments-worker`, не изменение базовых безопасных defaults. Устаревший healthcheck-bot автоматически не запускается.

Новый local PG volume больше не применяет SQL через `docker-entrypoint-initdb.d`: только явный migration runner. Существующий volume **не удаляется и не пересоздаётся**. Если старая БД создана SQL-init без `schema_migrations`, не применять baseline вслепую: сначала сравнить фактическую схему с миграциями, резервировать и согласовать явное принятие baseline. Раннер автоматически не признаёт чужую схему мигрированной.

## Production / закрытый preview

Для текущей compose-схемы нужны Docker Compose v2 с поддержкой optional `env_file`, стабильный DNS, открытые 80/443 и один writable PostgreSQL writer. Сеть, DNS, сертификаты, registry и провайдеры здесь не создаются. Первый запуск Caddy выполняет внешние ACME-запросы — только после разрешения оператора.

### Free backend profile (только закрытый preview/технический стенд)

Основной free compute candidate — **Oracle Cloud Always Free VM** (предпочтительно Ampere A1 Flex) при наличии regional capacity и после проверки актуальных AUP/ToS. Официальный срез 2026-11-12 для tenancy после trial указывает до **2 OCPU и 12 GB RAM суммарно** по A1; storage/network quota, reclaim/idle policy, SLA и коммерческая допустимость должны быть подтверждены отдельно. Старые цифры 4 OCPU/24 GB в прежних черновиках считать устаревшими. ARM64 image/native dependencies нужно проверить до любого запуска. Один Oracle host с local Redis/media — single point of failure; PostgreSQL на нём означает zero-budget lab, а не production writer.

Neon Free и Supabase Free — кандидаты managed PostgreSQL только для `*_test`/closed preview; Render PostgreSQL Free — только если актуальный план и его срок жизни подтверждены. Scale-to-zero/pause/expiry, connection caps, quota, no-SLA и отсутствие доказанного PITR не позволяют назначать free DB production writer без отдельного approval и restore drill. Upstash Free — первый managed Redis candidate для TLS cache/flags/ephemeral coordination; Redis Cloud Free — небольшой dev-кандидат. Redis не является источником истины для ledger, durable inbox/outbox или gift inventory. Исторические limits не считать актуальными без проверки страницы тарифа.

Sleeping Render/Koyeb-подобные runtimes подходят только для demo/visual preview: cold start и sleep несовместимы с Telegram/payment callbacks, bot/payment workers, gift-card delivery и scheduler. GitHub Actions hosted runners — эфемерный CI с quota/concurrency, не API, worker, webhook listener, scheduler, Redis или backup daemon. Vercel — статический UI-слой. Ранжированная матрица limits/ToS/media/backup находится в `docs/FREE_BACKEND_OPTIONS.md`.

1. Подготовить отдельный PostgreSQL writer: диски, TLS, backup/PITR, runtime role, migration role. Настроить TLS с проверкой сертификата (`sslmode=verify-full`, доступный CA). Не использовать read replica как writer и не давать приложению список независимых primary. Free managed PostgreSQL (Neon/Supabase/Render) допустим здесь только после проверки exact plan, connection cap, direct/session endpoint, pause/expiry, ToS, retention/PITR и restore drill; иначе использовать его только для `*_test`.
2. Создать **новый** приватный файл окружения вне git на базе `infra/.env.example`. Не перезаписывать существующий local `.env`. Задать `ENV=prod`, `PUBLIC_DOMAIN`, `DATABASE_URL`, при необходимости `MIGRATION_DATABASE_URL`, уникальный `JWT_SECRET`; выключенные интеграции не требуют настоящих provider credentials. Значение `JWT_SECRET` из шаблона непригодно для production. Не печатать `docker compose config` без `--quiet`.
3. Для активного бота нужны `BOT_MODE=webhook`, `BOT_TOKEN`, `BOT_USERNAME`, `FERNET_KEY`, `TELEGRAM_WEBHOOK_SECRET`. `PUBLIC_BASE_URL` и `WEBAPP_URL` compose строит из стабильного домена. Main bot provisioning/webhook registration — **явная** команда bot CLI, не побочный эффект старта API. Не класть token в webhook URL, query string, access logs или Caddy upstream.
4. Для provider/Stars/giftcard live-режимов отдельно включить соответствующие flags и реальные проверенные credentials. Не считать запись в `.env` прохождением KYC/AUP, проверкой PSP или допуском к публикации. Managed bots не включать как способ обхода блокировок/лимитов аккаунта.

Пример команд с **путём** к приватному env; значений секретов в argv нет. `PRODUCTION_ENV_FILE` и `--env-file` должны ссылаться на один и тот же файл. В Windows/Git Bash используйте абсолютный путь, понятный Docker Desktop.

```bash
export PRODUCTION_ENV_FILE=/secure/windrop-production.env

docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml config --quiet
docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml build

# Explicit one-shot, до API rollout. Команда никогда не запускается из API startup.
docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml --profile ops run --rm migrate python tools/migrate.py --status
docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml --profile ops run --rm migrate

docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml up -d api worker payments-worker scheduler redis caddy

docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml exec -T api python -m app.ops.probe ready
```

В preview с disabled режимами Telegram/payment workers штатно завершаются с кодом 0; `restart: on-failure` не создаёт цикл перезапусков. Scheduler работает отдельно и не использует provider credentials.

`backend/tools/migrate.py` и `migrations/` включены в backend image. Миграции применяются по журналу `schema_migrations`, с DB advisory lock для concurrent runs. В deployment pipeline должен быть один migration job; не параллелить DDL с несовместимым rollout. Проверять статус/ожидаемую схему до включения traffic. `EXPECTED_SCHEMA_VERSION=0018_giftcard_redemption.sql` следует обновлять согласованно с релизом.

В production Redis приватный, с AOF `everysec`, без host port. Это не HA Redis и не гарантия zero-loss: durable inbox/outbox хранятся в PostgreSQL. Для managed Redis можно передать `REDIS_URL=rediss://...` с TLS и отдельно адаптировать deployment dependencies. Compose сам не настраивает внешние ACL/backup. DB pool по умолчанию до 10 соединений на API worker; учесть все процессы и ограничения внешнего сервиса.

## Health и наблюдаемость

- `/health/live` — 200 без БД, Redis и provider I/O. Контейнерный healthcheck использует именно liveness, чтобы отказ БД не превращался в restart storm.
- `/health/ready` и совместимый `/health` — 200/503. Проверяются writable DB, Redis ping, marker ожидаемой миграции, `users.is_guest`, доступность таблиц `bot_registry`, `bot_inbox`, `bot_outbox`. Ответ содержит только `ok/fail`, без DSN/секретов/текстов драйвера. Timeouts: `DB_CONNECT_TIMEOUT_SECONDS`, `DB_POOL_TIMEOUT_SECONDS`, `READINESS_TIMEOUT_SECONDS`.
- Пустой `METRICS_TOKEN` всегда закрывает `/metrics` (404); нужен `X-Admin-Token`. IP localhost/reverse proxy не заменяет ключ. В production Caddy публично закрывает `/metrics`, `/health*`, `/docs`, `/redoc`, `/openapi.json`; scraper размещается в защищённой сети.
- Readiness подтверждает схему/доступ к очередям, **не** работоспособность Telegram/PSP и не завершённость доставки. Настроить отдельные алерты на возраст pending, dead-letter, worker heartbeat, retries, диски, Redis memory, backup freshness. Telegram и payment workers не проверяются HTTP-probe API.
- Caddy access logs и Uvicorn access log выключены. Не включать debug HTTP transport логирование без редактирования секретов. Журнал scheduler выводит только класс ошибки, не DSN.

## Scheduler и техническое переключение API

`python -m app.ops.scheduler` — один логический scheduler на writer. Для scheduler и migration runner нужен **прямой PostgreSQL endpoint или session pooling**; PgBouncer transaction/statement pooling несовместим с session advisory lock и запрещён для этих процессов. `auto_pause` выполняется каждые 10 минут, `max_instances=1`, с coalescing. Процесс получает session advisory lock, heartbeat каждые 5 секунд. Все job-вызовы `get_conn()` используют **ту же** физическую DB-сессию через fence: потерянная/отозванная сессия не подменяется pool connection. При ошибке задачи отменяются, соединение закрывается, затем выполняется новая попытка lock. SIGTERM прекращает задачи и освобождает сессию. Долгие jobs ограничены timeout; задача не должна порождать неотслеживаемый параллельный SQL или внешние эффекты.

Это fencing только внутри **одного** PostgreSQL writer. Advisory lock не предотвращает записи на двух независимых восстановленных/продвинутых БД. Promotion требует ручной изоляции старого writer и старых приложений — см. `RESTORE.md`. Автоматический failover БД не реализован.

Опциональный API standby на том же host включается отдельным override, не изменением локальных портов:

```bash
docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml -f infra/docker-compose.failover.yml --profile standby config --quiet
docker compose --env-file "$PRODUCTION_ENV_FILE" -f infra/docker-compose.prod.yml -f infra/docker-compose.failover.yml --profile standby up -d api api-standby caddy
```

`Caddyfile.failover` использует primary-first и active readiness; при недоступности обоих возвращает отказ. Проверка каждые 10 секунд и два последовательных результата не дают мгновенный RTO. Retry разрешён для GET/HEAD; mutating запросы не переигрываются автоматически. Telegram может повторить webhook — durable dedupe обязателен. Primary/standby API используют одинаковые ключи, одну БД, один Redis и общий media. Scheduler/платёжные workers не должны запускаться в API lifespan; polling standby нет. Один Docker host, один Caddy и local volume остаются single points of failure.

## Vercel и бесплатный статический слой

`vercel.json` в корне предназначен только для статического `landing/` и Mini App `frontend/`: `/` ведёт в landing, `/app/*` — в frontend. Vercel Hobby/free не заменяет FastAPI, Telegram/payment workers, scheduler, PostgreSQL writer, Redis или persistent media. Для preview допустим внешний sleeping API с отключёнными ботами и платежами; это не production webhook/settlement runtime.

Для production candidate используйте Vercel только как CDN/edge для UI, а API и workers — на always-on Docker/VPS runtime; PostgreSQL остаётся одним writable внешним writer с TLS/PITR, Redis — managed TLS, media — object storage после отдельной реализации. Same-origin API paths текущего frontend не превращаются автоматически в Vercel Functions; нужен стабильный API origin/rewrite или отдельный согласованный CORS/API-base этап. Не публикуйте credentials в статических assets и не используйте смену Vercel-аккаунтов для обхода ограничений. Детали и ограничения — `docs/VERCEL_FREE.md`.

## CI и ограничения проверки

CI использует отдельные ephemeral services `postgres_test`/`redis_test` на 55432/56379, ограниченную роль `caseplatform_test`, обязательные `TEST_DATABASE_URL`/`TEST_REDIS_URL`, `WINDROP_TESTING=1`. Суперпользователь используется только для bootstrap, тесты и миграции идут от изолированной роли. CI не публикует image/site и не включает платежи/Telegram. Exit codes lint/migrate/test/compose не скрываются pipe в tail.

Локальный test stack управляется отдельным инструментом основной задачи, не этими compose. Никогда не указывать тестам `infra_pgdata` или workspace `DATABASE_URL`. Полный тестовый прогон, реальный image build, Caddy validation, delivery/failover и restore drill требуют отдельных проверок; наличие конфигурации не означает их успешное выполнение. Локальный отчёт `docs/LOCAL_ACCEPTANCE.md` фиксирует последнюю изолированную репетицию: API failover, idempotency, worker lease recovery и webhook dedupe прошли; финальный запрос при остановленных обоих API ранее получил controller timeout, поэтому полный failover verdict требует повторения при доступном Docker Desktop.
