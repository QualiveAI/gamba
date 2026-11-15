# WINDROP — бесплатный стек без ПК

Стек собран так, чтобы всё работало без домашнего компьютера и без платных планов:
**Neon** (Postgres) + **Upstash** (Redis) + **Vercel** (статика Mini App) +
**Render** (API + bot worker + scheduler в одном контейнере) + **Cloudflare R2** (зашифрованные бэкапы).
Landing остаётся на **Cloudflare Pages** из отдельного репозитория `gamba-landing`.

```
landing (Cloudflare Pages, repo gamba-landing)
  └─ CTA → https://t.me/robwindropbot
        └─ Mini App:  https://<vercel>/app/   ──HTTPS + CORS──▶  Render windrop-api
                                                                   ├─ uvicorn (API)
                                                                   ├─ bot worker (inbox/outbox)
                                                                   └─ scheduler (advisory lock)
Render windrop-api ──▶ Neon Postgres (Ohio, scale-to-zero)
                   └──▶ Upstash Redis (rediss://)
Render windrop-api, старт контейнера ──▶ python -m app.bot.main (provisioning webhook)
GitHub Actions 03:17 UTC ──▶ pg_dump | age → R2 (хранение 14 дней)
GitHub Actions вс 04:17 UTC ──▶ restore-drill: latest dump → одноразовая БД
```

Почему именно так:

- **Один контейнер на Render.** Free-план даёт ~750 instance-часов в месяц на аккаунт;
  отдельные web + worker + scheduler съели бы бюджет и сервисы вставали бы до конца месяца.
  `infra/entrypoint.prod.sh` держит три процесса в одном контейнере, а падение API роняет контейнер
  (Render перезапускает) — worker без API смысла не имеет.
- **Neon DIRECT endpoint, не `-pooler`.** Scheduler держит session advisory lock; транзакционный
  пулер Neon (PgBouncer) такие блокировки не сохраняет.
- **Region Ohio у Render = регион Neon из визарда.** Иначе каждый запрос к БД получает лишний RTT.
- **Событийный worker.** Neon free считает compute-часы по времени активности, поэтому worker
  не опрашивает БД каждую секунду, а ждёт сигнал в Redis (`app/bot/wakeup.py`), с периодическим
  rescan раз в 5 минут на случай падения Redis.
- **Пул соединений 3 + 3 + 1.** `DB_POOL_MAX_SIZE=3` у API и worker, 1 у scheduler.

## Порядок действий

Порядок важен: адрес Vercel нужен Render-у для `WEBAPP_URL`/`CORS_ALLOW_ORIGINS`, а адрес Render
нужен фронтенду для `WINDROP_API_ORIGIN`. Не открывай `/app` до шага 7 — иначе браузер закэширует
пустой API-origin.

| # | Сервис | Что сделать | Что получить |
|---|---|---|---|
| 1 | Neon | Create project (Postgres only, Ohio, 1 GB) | DIRECT DSN |
| 2 | Upstash | Create database (us-east-1, TLS) | `rediss://` URL |
| 3 | Vercel | Импорт `QualiveAI/gamba`, ветка `main` | домен `https://<project>.vercel.app` |
| 4 | BotFather | `/revoke` токена + Managed Bots | новый `BOT_TOKEN` |
| 5 | GitHub | secrets + variables, `migrate.yml` | схема БД в Neon |
| 6 | Render | **Blueprint** из `render.yaml` + env | `https://windrop-api.onrender.com` |
| 7 | Репозиторий | `frontend/js/api-config.js` = Render origin | фронт ходит в Render |
| 8 | Render | Restart сервиса `windrop-api` | webhook установлен |
| 9 | GitHub | первый ручной запуск backup | дамп в R2 |

## 1. Neon

1. neon.tech → New Project.
2. Имя `windrop`, **Postgres only** (без Neon Auth/Data API), регион **Ohio (us-east-2)**, 1 GB.
3. Dashboard → Connection string → выбери **host без `-pooler`**:
   `postgresql://<user>:<pass>@ep-xxxx.us-east-2.aws.neon.tech/neondb?sslmode=require`
4. Скопируй строку целиком. Это будущий `DATABASE_URL` и GitHub-secret `DATABASE_URL_PROD`.

Не создавай отдельную ветку под прод: free-план считает compute-часы на проект.

## 2. Upstash

1. console.upstash.com → Create Database.
2. Имя `windrop`, регион **us-east-1** (ближе всего к Ohio), TLS включён.
3. Вкладка Connect → скопируй `rediss://default:<pass>@<host>.upstash.io:6379`.

Это `REDIS_URL`. Free-план — 500k команд в месяц; при событийном worker это ~90k/мес (BLPOP раз
в 30 секунд, пока контейнер жив) плюс кэш каталога и флагов.

Две ловушки:

- CLI Upstash показывает команду вида `redis-cli --tls -u redis://…`. Схема `redis://` там только
  потому, что TLS включает флаг `--tls`; приложению нужен именно **`rediss://`**, иначе клиент
  пойдёт открытым текстом и получит таймаут.
- Регион базы должен совпадать с Render — **us-east-2 (Ohio)**; «Global» с primary в us-east-2
  тоже подходит. Иначе каждый Redis-запрос идёт через полмира (флаги и кэш каталога читаются
  на каждом запросе API). Если база создана в другом регионе — удали и создай заново, данных там нет.

## 3. Vercel

1. vercel.com → Add New → Project → Import Git Repository → `QualiveAI/gamba`.
2. Настройки: **Framework Preset: Other**, Root Directory: `./`, Build Command и Output Directory
   — **пустые**, Environment Variables — **никаких**.
3. Deploy. Репозиторий уже содержит `vercel.json` (legacy `routes`: `/app` → `frontend/`,
   всё остальное → `landing/`). Никаких crons/functions — на Hobby они ломают сборку.
4. Запиши production-домен: `https://<project>.vercel.app`.

Если деплой упал — смотри Build Logs: почти всегда это лишний Framework Preset (Next.js) или
непустой Output Directory.

## 4. BotFather

1. `/mybots` → `@robwindropbot` → **API Token** → **Revoke current token**.
   Оба токена, которые присылались в чат, считаются скомпрометированными.
2. Новый токен вставь **только** в Render env `BOT_TOKEN` (не в git, не в Vercel, не в Cloudflare).
   Он понадобится на шаге 6.
3. Включи Managed Bots для главного бота (`/managebots` либо Bot Settings → Managed Bots).

## 5. GitHub: секреты, миграции, бэкапы

Миграции идут **до** первого деплоя Render: `/health` проверяет наличие `schema_migrations`
и таблиц ботов, поэтому без схемы сервис не пройдёт health check.

Repo → Settings → Secrets and variables → Actions.

**Secrets:**

| Secret | Откуда |
|---|---|
| `DATABASE_URL_PROD` | DSN Neon (тот же, что попадёт в Render) |
| `R2_ACCOUNT_ID` | Cloudflare dashboard → R2 → Account ID |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | R2 → Manage API Tokens → Create (Object Read & Write) |
| `R2_BUCKET` | имя бакета, например `windrop-backups` |
| `AGE_PRIVATE_KEY` | содержимое приватного ключа age (см. ниже) |

**Variables:** `AGE_RECIPIENT_PUBLIC` — публичная часть age.

Минимум для первого запуска — **только `DATABASE_URL_PROD`**: без него не пройдёт шаг с миграциями.
R2 и age нужны лишь для бэкапов, их можно добавить после того, как приложение поднимется.

```bash
age-keygen -o windrop-backup.key            # приватный ключ в файл (chmod 600)
grep '^# public key:' windrop-backup.key    # → AGE_RECIPIENT_PUBLIC
# AGE_PRIVATE_KEY = всё содержимое windrop-backup.key (включая строку с public key)
```

Файл `windrop-backup.key` храни в менеджере паролей и удали после загрузки секрета.
Потеря приватного ключа = невозможность восстановить дампы.

**Миграции.** Render free не даёт Shell, поэтому DDL применяется отдельным workflow:

1. Actions → **Migrate production database** → Run workflow.
2. `confirm` = `MIGRATE` (обязательно, иначе job падает на первой проверке).
3. Job покажет список pending до применения, применит и покажет статус после.

Ожидаемый результат: 18 миграций (`0001` … `0018_giftcard_redemption.sql`).

## 6. Render

В скриншоте «Create a new Worker» — это **не тот** путь: worker-сервис запускает только worker и
съедает второй instance-час-бюджет. Нужен **Blueprint**.

1. dashboard.render.com → **New +** → **Blueprint**.
2. Connect GitHub → выбери `QualiveAI/gamba`, ветка `main`. Render прочитает `render.yaml`
   и покажет один сервис `windrop-api` (web). Cron-сервиса в Blueprint нет: Render не разрешает
   `plan: free` для типа `cron`, поэтому provisioning встроен в старт контейнера.
3. Apply. В форме Blueprint сразу заполни `sync: false` переменные:

| Переменная | Значение |
|---|---|
| `DATABASE_URL` | DSN из Neon (**direct**, `?sslmode=require`) |
| `REDIS_URL` | `rediss://…` из Upstash |
| `BOT_TOKEN` | новый токен @robwindropbot из шага 4 |
| `ADMIN_TELEGRAM_IDS` | твой Telegram ID (@userinfobot), через запятую если несколько |
| `PUBLIC_BASE_URL` | `https://windrop-api.onrender.com` — нужен и web, и cron: у cron нет своего URL, он ставит webhook на этот адрес |
| `WEBAPP_URL` | `https://<project>.vercel.app/app/` — обязательно со слэшем на конце |
| `CORS_ALLOW_ORIGINS` | `https://<project>.vercel.app` — без пути и без слэша |
| `FERNET_KEY` | сгенерировать один раз: `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |

`JWT_SECRET` и `TELEGRAM_WEBHOOK_SECRET` Render сгенерирует сам (`generateValue`).

`FERNET_KEY` — самый важный ключ: им зашифрованы токены managed-ботов, payload-ы inbox/outbox и
коды gift-card. Потеря ключа делает бэкапы бесполезными, поэтому сохрани его в менеджере паролей.

Дождись деплоя. Адрес API: `https://windrop-api.onrender.com` (если имя занято — Render добавит
суффикс, тогда используй фактический адрес из dashboard).

## 7. Подключить фронтенд к API

`frontend/js/api-config.js`:

```js
window.WINDROP_API_ORIGIN = "https://windrop-api.onrender.com";
```

И в `frontend/index.html` подними версию файла: `api-config.js?v=1` → `?v=2` (ассеты под `/app`
кэшируются на год, версия в query — единственный способ доставить новое значение).
Commit + push в `main` → Vercel пересоберётся сам.

Проверка: `https://<project>.vercel.app/app/` открывается без ошибок CORS в консоли.
Если CORS ругается — сверь `CORS_ALLOW_ORIGINS` в Render с фактическим origin (схема+хост,
без слэша); после правки Render перезапустит сервис.

## 8. Webhook

`infra/entrypoint.prod.sh` запускает `python -m app.bot.main` при каждом старте контейнера:
upsert registry + `setWebhook` (без удаления updates). Render free засыпает и просыпается —
это же свойство заодно переустанавливает webhook после любого рестарта и деплоя.

1. Render → `windrop-api` → **Manual Deploy** → **Restart service** (если сервис уже поднят,
   провижининг уже прошёл при первом старте).
2. В логах найди `[entrypoint] webhook provisioning: ok`. Если там `failed` — смотри ошибку выше:
   чаще всего пустой `BOT_TOKEN` или неверный `PUBLIC_BASE_URL`.
3. Проверка без токена в shell history:

```bash
read -r -s TG_TOKEN        # вставь токен, Enter; в истории его не будет
curl -s "https://api.telegram.org/bot$TG_TOKEN/getWebhookInfo" | python -m json.tool
unset TG_TOKEN
```

Ожидаемо: `url = https://windrop-api.onrender.com/bot/webhook/<bot_id>`, `pending_update_count: 0`,
`last_error_message` отсутствует.

## 9. Бэкапы

Actions → **Backup PostgreSQL to R2** → Run workflow (ручной прогон). В Summary будут
`dump_bytes`, `dump_sha256` и число дампов в бакете. Дальше job идёт по расписанию 03:17 UTC.

Раз в неделю `Restore drill` скачивает `windrop-latest.dump.age`, расшифровывает и восстанавливает
в одноразовую БД внутри runner, проверяя инвариант ledger (`balance_units/freebets == SUM(delta)`)
и наличие миграции `0018`. Он никогда не читает `DATABASE_URL_PROD`.

## Проверка после деплоя

1. `curl -s https://windrop-api.onrender.com/health` → 200 (первый запрос после сна ~30–60 с).
2. `getWebhookInfo` — см. шаг 8.
3. Cloudflare landing → кнопка открывает `https://t.me/robwindropbot?start=lp_organic`.
4. В боте `/start` → кнопка «Abrir WINDROP» открывает Mini App.
5. `/createbot` → официальный Managed Bot flow; personal-бот получает `auth_bot_id`.
6. Логи `windrop-api`: три процесса стартовали (`uvicorn`, `app.bot.worker`, `app.ops.scheduler`).

## Известные ограничения бесплатного стека

- **Render free засыпает** после ~15 минут без трафика; первый запрос — холодный старт 30–60 с.
  Telegram повторяет доставку webhook, поэтому сообщения не теряются, но ответ бота после простоя
  придёт с задержкой. Это цена нулевого счёта; постоянный сервис требует платного плана (или VPS).
- **Диск Render эфемерный.** `MEDIA_STORAGE_MODE=local`: загруженные через админку картинки
  исчезнут при рестарте. Для теста терпимо; перед продом нужен R2 + `MEDIA_STORAGE_MODE=object`.
- **0.1 CPU / 512 MB** на сервис. Трёх процессов хватает для теста, но пиковая нагрузка упрётся
  в CPU раньше, чем в память.
- **Neon scale-to-zero.** Холодный старт БД 1–2 с; событийный worker специально не будит её вхолостую.
- **Cron на free-плане недоступен.** Render отвечает `plan: free not a valid plan for service
  type cron`, поэтому webhook ставится на старте контейнера (`BOT_PROVISION_ON_START=true`).
  Платить за cron не нужно.
- **Платежи и выдача карт выключены** (`PAYMENTS_MODE=disabled`, `GIFTCARD_MODE=disabled`).
  Игры, баланс, инвентарь и Managed Bots работают; для выдачи карт нужны реальные коды и отдельные
  ключи (`GIFTCARD_FERNET_KEY`, `GIFTCARD_FINGERPRINT_KEY`), для приёма Stars — включение
  `PAYMENTS_MODE` и merchant-настройки главного бота.
- **Vercel Hobby — некоммерческая лицензия.** Для теста нормально; перед реальным запуском
  проверить AUP или перенести статику на Cloudflare Pages.
- **Vercel preview-домены не в allowlist CORS.** Тестировать нужно на production-домене.

## Перенос с бесплатного стека на постоянный

Всё состояние — в Neon (Postgres) и R2 (дампы); статика и API stateless.

1. Новый Postgres (VPS/managed) → `pg_restore` из последнего `windrop-latest.dump.age`.
2. `DATABASE_URL`/`REDIS_URL` → новые значения в env.
3. Поднять API+worker+scheduler тем же `infra/entrypoint.prod.sh` (Docker) или systemd-юнитами
   из `deploy/hosting/systemd/`.
4. Обновить `PUBLIC_BASE_URL`; запустить `python -m app.bot.main` — webhook переедет на новый адрес.
5. `WEBAPP_URL`/`CORS_ALLOW_ORIGINS` — если меняется домен статики.

Старые `deploy/hosting/vercel/api/` (serverless-обёртка) и `deploy/hosting/cloudflare/build-dist.sh`
в этой схеме не используются: API живёт на Render, статика Mini App — на Vercel.
