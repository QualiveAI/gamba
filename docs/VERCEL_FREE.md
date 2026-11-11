# Vercel Hobby/free: безопасная схема WINDROP

## Короткий вывод

Vercel подходит для **статической раздачи** `landing/` и `frontend/` Mini App. Текущий FastAPI нельзя просто перенести в Vercel Functions: проект использует PostgreSQL durable inbox/outbox, долгоживущие bot/payment workers, scheduler с session advisory lock и локальное persistent media.

`vercel.json` в корне задаёт только статические маршруты:

- `/` → `landing/index.html`;
- `/app/*` → `frontend/*`;
- API, PostgreSQL, Redis, Telegram webhook и платежные callback URL на Vercel не создаются.

Перед коммерческим запуском нужно отдельно проверить актуальные Vercel Hobby/AUP и условия выбранных провайдеров. Бесплатный тариф нельзя считать автоматически разрешённым для real-money коммерческого продукта. Смена аккаунтов для обхода блокировок не допускается.

## Профиль preview/free

Назначение — визуальный QA и демонстрация без реальных денег:

```text
Vercel static landing + Mini App
        │
        ├── внешний preview API (может засыпать; не Telegram production webhook)
        ├── отдельная *_test PostgreSQL
        └── отдельный Redis dev instance
```

Правила:

- `ENV=test`/`dev`, `BOT_MODE=disabled`, `PAYMENTS_MODE=disabled` либо изолированный sandbox;
- никаких настоящих bot tokens, PSP credentials, treasury keys и gift-card codes;
- synthetic catalog и карты только с `TEST-ONLY-` префиксом;
- media — только статические репозиторные assets, без admin uploads на ephemeral filesystem;
- sleeping API не использовать для Telegram delivery, платежного webhook или очереди карт;
- preview DB/Redis не должны иметь доступ к рабочей БД, рабочему Redis или production webhook.

Для preview можно развернуть только `landing/` и `frontend/` через Vercel Git integration. Реальный API остаётся локальным или на отдельном dev-сервисе.

## Production candidate

```text
Vercel static CDN (landing + /app)
        │ HTTPS, стабильный домен/API rewrite или отдельный API origin
        ▼
Always-on Docker runtime / VPS
  Caddy → FastAPI API
         Telegram webhook worker
         payment worker
         gift-card delivery worker
         scheduler
        │
        ├── один writable managed PostgreSQL writer (TLS, PITR)
        ├── managed Redis по rediss:// (cache/flags/ephemeral coordination)
        └── S3-compatible/R2/B2 media storage (после отдельной реализации object mode)
```

**Oracle Cloud Always Free VM — основной free compute candidate** для закрытого технического стенда, если в регионе есть capacity и пройдена обычная верификация аккаунта. Для Ampere A1 Flex публично заявлялись суммарно до 4 OCPU, 24 GB RAM и до 200 GB block storage на tenancy; network quota, capacity, reclaim/idle policy, AUP/ToS и допустимость коммерческого real-money использования нужно сверять перед регистрацией. ARM64-совместимость Docker image и native-зависимостей обязательна.

Oracle VM не является managed PostgreSQL, managed media или HA. Один host с local Redis/media остаётся single point of failure. Если PostgreSQL тоже запустить на VM, это zero-budget lab/closed preview, а не production writer. Для production candidate нужен заранее согласованный always-on VPS/VM или другой runtime с подходящими гарантиями; free tier не даёт SLA сам по себе.

Sleeping Render/Koyeb-подобный сервис подходит только для небоевого preview: cold start, sleep и отсутствие постоянного worker lease несовместимы с Telegram delivery, payment settlement, gift-card delivery и scheduler. GitHub Actions hosted runners — только эфемерный CI; job, cron и artifact не заменяют API/worker, scheduler, Redis или backup daemon.

Managed PostgreSQL candidates для `*_test`/closed preview — Neon Free и Supabase Free; Render PostgreSQL Free можно рассматривать только если актуальный план доступен и его срок жизни/лимиты подтверждены. Scale-to-zero, pause/expiry, connection caps и отсутствие production SLA означают, что ни один такой free plan нельзя назначить writer без отдельной проверки direct/session endpoint, ToS, PITR/retention и restore drill. Upstash Free — первый managed Redis candidate для TLS cache/flags/ephemeral coordination; Redis Cloud Free — небольшой dev-кандидат. Redis не хранит ledger, durable inbox/outbox или gift inventory.

Подробная ранжированная матрица limits/ToS/media/backup находится в `docs/FREE_BACKEND_OPTIONS.md`.

Минимальный production candidate требует:

1. внешний API origin с публичным HTTPS и стабильным DNS;
2. один writer PostgreSQL и отдельный migration job;
3. отдельные always-on bot/payment workers и scheduler на VM/VPS, не на sleeping runtime или GitHub Actions;
4. Redis TLS, connection limits и readiness ping;
5. offsite encrypted backups, PITR и restore drill;
6. стабильный Telegram webhook URL;
7. verified BotFather manager capability и merchant/provider settings;
8. подтверждённые права на закупку и распространение BR gift cards.

## Почему API и workers не Vercel Functions

- FastAPI pool создаётся на процесс; serverless fan-out может превысить connection cap бесплатной PostgreSQL.
- `app.bot.worker` и `core.payments.worker` — постоянные loop с lease/retry и интервалом около 5 секунд.
- scheduler держит session advisory lock и heartbeat; Vercel Cron не заменяет эту сессию.
- Telegram/PSP callback должен быстро сохранить raw body и durable inbox до ACK, после чего отдельный worker делает обработку.
- локальный `MEDIA_STORAGE_MODE=local` пишет в `./media`; filesystem serverless не durable и не shared.
- `MEDIA_STORAGE_MODE=object` сейчас намеренно отвергается: S3-compatible backend ещё не подключён.

Теоретический serverless API потребовал бы отдельного ASGI adapter, external DB/Redis, explicit CORS/API origin, bounded pool lifecycle и полностью отдельного worker runtime. Это не входит в текущий skeleton и не должно включаться заменой `vercel.json`.

## PostgreSQL, Redis и media

- **PostgreSQL:** Neon/Supabase можно рассматривать как dev/free candidates после проверки текущих лимитов, сна, connection cap, ToS и региона. Для migration/scheduler нужен direct или session-compatible endpoint; transaction pooling несовместим с session advisory lock.
- **Redis:** Upstash или другой TLS managed Redis — только cache/flags/ephemeral coordination. Ledger, payment events, bot inbox/outbox и gift inventory всегда в PostgreSQL.
- **Media:** для multi-host нужен R2/B2/S3-compatible bucket + CDN. Сейчас объектное хранилище не реализовано, поэтому не обещать failover media.
- **Backups:** `infra/backup.sh` создаёт зашифрованный logical dump, но не создаёт расписание/offsite upload и не резервирует media/keys/provider state. Не использовать Vercel Cron как backup SLA.

## API origin и rewrites

Сейчас frontend использует same-origin `/auth`, `/cases`, `/deposits` и другие API paths. Поэтому безопасные варианты:

1. держать frontend и API за одним стабильным reverse proxy/origin;
2. настроить Vercel rewrite `/api/*` на внешний API и изменить frontend API client на явный `/api` base;
3. использовать отдельный API origin только после добавления CORS с точным allowlist и HTTPS.

Не встраивать `DATABASE_URL`, JWT/Fernet keys, bot tokens, PSP keys или treasury address в Vercel assets. `vercel.json` в этом репозитории намеренно не содержит внешний API host: его нельзя угадывать и нельзя публиковать без отдельного согласования.

## Что не сделано этим файлом

- `vercel deploy`, login и публикация не выполнялись;
- аккаунты Vercel/Oracle/Neon/Supabase/Upstash не создавались;
- production API/worker/DB не переключались;
- live Telegram/PSP не подключались;
- object storage и CORS/API-base refactor не реализованы.
