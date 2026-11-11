# Варианты бесплатного backend

## Статус и границы

Это ранжированная архитектурная схема для закрытого preview и недорогого технического стенда, а не подтверждение доступности конкретного тарифа. Срез подготовлен **11 ноября 2026 года без network/login/deploy**. Free-квоты, региональная доступность, AUP/ToS и правила коммерческого использования меняются; перед созданием аккаунта оператор должен сверить официальные страницы провайдера и зафиксировать дату проверки.

Free tier не означает SLA, production-grade backup, право на real-money продукт или гарантию сохранности ресурса. Не выполнять смену аккаунтов, регистрацию нескольких free-тенантов, обход региональных/ресурсных ограничений или публикацию реальных платежей ради этой схемы.

## Ранжированное решение

### 1. Основной free compute: Oracle Cloud Always Free VM

**Oracle Cloud Always Free VM — первый кандидат для always-on compute**, если в выбранном регионе есть capacity и аккаунт проходит обычную верификацию. Предпочтительный профиль — Ampere A1 Flex (ARM64): суммарно до 4 OCPU и 24 GB RAM на tenancy, до 200 GB block storage; сетевые квоты, включая egress, и актуальные правила reclaim нужно проверить перед использованием. Это лимиты tenancy, а не гарантия одного непрерывного инстанса.

На VM можно разместить Caddy, FastAPI API, bot/payment workers, scheduler и, для закрытого preview, Redis. `infra/docker-compose.prod.yml` всё ещё предполагает один host и внешний PostgreSQL writer; документ не меняет compose и не превращает Oracle VM в managed database. ARM64 требует отдельной проверки всех Docker image и native-зависимостей.

Ограничения, которые являются частью решения:

- capacity в регионе не гарантирована; free-инстанс может быть недоступен при создании или попасть под reclaim/idle policy;
- нет SLA, автоматического failover, managed PostgreSQL и managed media;
- block volume — хранилище одной failure domain, не offsite backup и не shared volume между host;
- если PostgreSQL и Redis тоже запустить на этой VM, это zero-budget lab/closed preview с единой точкой отказа, а не production writer;
- для live webhook, settlement и финансового ledger нужны проверенные backup/restore, мониторинг и ручной план отказа; одного бесплатного VM недостаточно;
- Oracle AUP/ToS и допустимость коммерческого real-money использования проверяются отдельно; несколько аккаунтов для обхода ограничений запрещены.

**Резерв:** заранее согласованный небольшой платный VPS/VM с тем же Docker-профилем. Постоянной бесплатной замены с сопоставимыми гарантиями в этой схеме не утверждается.

### 2. Managed PostgreSQL: только preview/test до отдельного approval

Кандидаты для изолированной `*_test` БД и закрытого preview:

1. **Neon Free** — удобен для ephemeral/branch-based тестов, но scale-to-zero, compute/storage quota и отсутствие production SLA несовместимы с предположением о постоянном writer/scheduler.
2. **Supabase Free** — полноценный PostgreSQL и отдельный Storage, но маленькие квоты, возможная пауза проекта, no-SLA и отсутствие гарантированного production PITR делают его preview/dev-кандидатом.
3. **Render PostgreSQL Free, если такой план доступен в текущем регионе/продукте** — рассматривать только для короткой проверки: в старых публичных описаниях free-вариант имел ограниченный срок жизни/объём и не подходил для writer.

Ни один free managed PostgreSQL из списка не назначается production writer без проверки exact plan, connection endpoint, retention/PITR, региона, ToS и restore drill. Для migration runner и scheduler нужен direct или session-compatible endpoint. Transaction pooling нельзя использовать для session advisory lock.

### 3. Managed Redis: только cache/coordination

1. **Upstash Free** — первый TLS managed кандидат для cache, flags и ephemeral coordination при соблюдении command/storage quota.
2. **Redis Cloud Free** — небольшой managed кандидат для dev/preview; размер и connection cap слишком малы для текущего общего production design.
3. **Redis на Oracle VM** — вариант без отдельного счёта, но не managed и с отказом всего host. Его можно пересоздать из PostgreSQL/конфигурации, но нельзя использовать как источник истины для ledger, inbox/outbox или gift inventory.

В любом варианте durable bot/payment inbox, outbox, idempotency и финансовый ledger остаются в PostgreSQL. Redis eviction, restart или потеря free-экземпляра не должны приводить к потере бизнес-события.

### 4. Sleeping runtimes: только preview

Render Free Web Service, Koyeb-подобные free/sleeping web runtimes и другие сервисы с cold start допустимы для статического demo/API без внешних событий. Они **не являются** заменой always-on VM для Telegram webhook, payment callback, bot worker, payment worker, gift-card delivery, scheduler или durable queue.

Vercel Hobby в этом проекте — статический `landing/` и Mini App слой. Serverless/edge invocation не превращается в постоянный процесс и не получает durable local filesystem.

### 5. GitHub Actions: CI, не worker

GitHub-hosted runners эфемерны, ограничены временем job, concurrency, minutes/quota и завершаются после job. Actions разрешены для lint, тестов, compose/config checks и иных явно согласованных CI-задач. Нельзя держать там bot/payment worker, scheduler, webhook listener, Redis, backup daemon или бесконечный process; scheduled workflow не заменяет lease/heartbeat и не даёт RPO/RTO.

## Рекомендуемые профили

### `free-preview`

```text
Vercel static landing + Mini App
        -> sleeping/mock API (только visual QA)
        -> отдельная *_test PostgreSQL/Redis
```

- `BOT_MODE=disabled`;
- `PAYMENTS_MODE=disabled`;
- `GIFTCARD_MODE=disabled` либо изолированный sandbox;
- без реальных Telegram/PSP credentials, treasury keys и card codes;
- media только из репозитория, без uploads;
- sleep/cold start допустим, потому что это не webhook и не денежный поток.

### `free-pilot-candidate`

```text
Oracle Always Free VM
  Caddy + API + bot worker + payment worker + scheduler + Redis
       -> один внешний managed PostgreSQL writer
       -> object storage позже, пока local media = single-host
Vercel -> static landing/Mini App по желанию
```

Это кандидат для private staging/технического пилота после отдельной проверки, а не разрешение live-режима. PostgreSQL на Oracle VM допустим только для закрытого preview/test: тогда DB, Redis, API, media и workers находятся в одной failure domain.

## Сводная таблица limits / ToS / media / backup

Значения с пометкой «исторически/публично указывалось» — ориентир для отбора, а не live-проверка. Точные лимиты нужно перепроверить на странице тарифа перед регистрацией.

| Ранг / роль | Кандидат и ориентировочные limits | ToS, коммерция и эксплуатация | Media | Backup / restore | Решение |
| --- | --- | --- | --- | --- | --- |
| 1 — compute | **Oracle Always Free A1 Flex VM**: до 4 OCPU и 24 GB RAM суммарно, до 200 GB block storage; network/egress quota и capacity зависят от актуальной квоты/региона | Free account/AUP, верификация, региональная capacity, отсутствие SLA; возможен reclaim idle-ресурсов; один tenancy и одна failure domain | Block volume не является shared/object media. Текущий `MEDIA_STORAGE_MODE=local` остаётся single-host; `object` в приложении ещё не реализован | Нет автоматического application backup. `infra/backup.sh` делает только зашифрованный logical DB dump; media, keys и provider state резервируются отдельно | **Основной free compute candidate**, но не гарантия production |
| 1a — zero-budget lab | PostgreSQL + Redis на той же Oracle VM: лимит задаётся общей RAM/CPU/disk budget | Нет managed HA, SLA или автоматического promotion; отказ VM останавливает весь стек | Local Docker volume, одна host failure domain | VM/block snapshot не заменяет offsite dump и restore drill; Redis можно восстановить, DB/media/keys — отдельной процедурой | Только закрытый preview/test |
| 2 — managed PostgreSQL | **Neon Free**: исторически публично указывались 0.5 GB storage и 100 CU-hours/project/month; scale-to-zero и project/connection quotas меняются | Free plan без production SLA; scale-to-zero ломает предположение о постоянной session advisory lock; допустимость коммерческого live-продукта проверяется по актуальному ToS | Не использовать как media store; object adapter приложения отсутствует | Branch/restore features не равны гарантированному PITR. Делать собственный encrypted `pg_dump` и drill; retention/free backup проверить | Preview/test candidate |
| 3 — managed PostgreSQL | **Supabase Free**: исторически 500 MB DB/project, 5 GB bandwidth, 1 GB file storage и ограниченное число free projects; проект может pause при неактивности | Free/no-SLA, quotas и pause policy; direct/session endpoint нужен для migration/scheduler; pooler transaction mode несовместим с advisory lock | Supabase Storage не подключён к текущему media adapter; local `/app/media` не становится shared | Не считать free backup/PITR гарантией. Export, ключи и media резервировать отдельно; restore drill обязателен | Preview/dev candidate |
| 4 — managed PostgreSQL | **Render PostgreSQL Free, если доступен**: исторически маленький объём и ограниченный срок жизни (в публичных описаниях встречалось 1 GB/30 дней); подтвердить актуальный plan | Возможное автоматическое истечение, no-SLA и plan availability; не использовать как writer | Не использовать для media | Нет принятого production RPO/RTO; только отдельный test dump/drill | Не выбирать для production; максимум короткий test |
| 1 — managed Redis | **Upstash Redis Free**: исторически 256 MB и около 500k commands/month, TLS; quotas/limits меняются | Free quota, rate/latency limits, no production HA/SLA по умолчанию; `rediss://` и connection budget проверить | Media не хранить | Не считать durable backup источником истины; потеря/eviction Redis должна быть безопасной | Cache/flags/ephemeral coordination |
| 2 — managed Redis | **Redis Cloud Free**: исторически около 30 MB, одна DB и около 30 connections; точные limits проверить | Малый free plan, no-SLA и ограничения inactivity/connection/region могут измениться | Media не хранить | Не обещать backup/PITR; Redis rebuild-ится из PostgreSQL/конфигурации | Малый dev/preview |
| 3 — self-hosted Redis | Redis 7 на Oracle VM, в compose — AOF `everysec` и private port | Не managed, без HA; общий отказ VM и resource contention | Только local volume; не shared | AOF не заменяет PostgreSQL backup. Состояние можно пересоздать; durable events должны быть в DB | Closed preview only |
| preview runtime | **Render Free Web Service**: исторически 512 MB RAM/0.1 CPU, 750 h/month и sleep после idle; quotas/правила меняются | Cold start, no-SLA, ephemeral runtime; нельзя принимать Telegram/PSP callbacks или держать worker lease | Filesystem ephemeral; только packaged static assets | Нет durable backup/RPO; не target для restore | Только demo/preview |
| preview runtime | **Koyeb Free или аналогичный sleeping runtime**: quota, sleep и регион зависят от текущего plan; проверить перед использованием | Cold start/scale-to-zero, no-SLA и AUP; не подтверждать постоянный процесс | Ephemeral filesystem; media uploads запрещены | Не считать deployment artifact backup; отдельные DB/media dumps | Только demo/preview |
| static / edge | **Vercel Hobby**: static hosting и plan-dependent function/edge quotas; нет постоянного process/filesystem | Hobby/AUP и коммерческое использование проверяются отдельно; смена аккаунтов для обхода лимитов запрещена | Только repository assets; local write не durable | Git/deploy history не является DB/media backup; Vercel Cron не backup SLA | Static UI only |
| CI | **GitHub Actions hosted runners**: plan/repository-dependent minutes, concurrency и artifact retention; runner эфемерен | CI automation — да; daemon, worker, webhook listener и обход quota — нет | Runner disk эфемерен; artifacts не являются media storage | Artifacts не заменяют encrypted DB backup, offsite copy и restore drill | CI/checks only |

## Connection budget и single-host ограничения

В текущем production compose API запускается с двумя Uvicorn workers, а отдельно запускаются bot worker, payment worker и scheduler. Реальный PostgreSQL connection budget зависит от pool settings и числа процессов; перед выбором free DB его нужно посчитать по фактической конфигурации, включая migration job, а не сверять только с размером VM. Free DB с маленьким connection cap нельзя «лечить» параллельными независимыми writer или transaction pooling для scheduler.

Oracle VM, local Redis и local media остаются single points of failure. Один VM не даёт DB failover, shared media, автоматический promotion или zero-loss recovery. `infra/docker-compose.prod.yml` не меняется этим документом.

## Сигналы, при которых free-профиль нельзя включать

- нет отдельного encrypted offsite DB backup и проверенного restore drill;
- media лежит только на локальном VM volume, но обещан multi-host failover;
- выбран free DB с scale-to-zero/expiry, а на него направляются webhook, scheduler или live settlement;
- Redis используется как ledger, durable inbox/outbox или единственный источник idempotency;
- worker/scheduler планируется держать в Vercel Functions, sleeping runtime или GitHub Actions;
- provider ToS/AUP, real-money use, регион, quota и account verification не подтверждены владельцем;
- для запуска требуется реальный bot/payment credential, но не определены один writer, rollback и manual fencing.

## Что нужно подтвердить до live-режима

1. Текущие страницы limits, AUP/ToS и commercial-use policy Oracle, выбранных DB/Redis/runtime провайдеров.
2. Региональную capacity Oracle и ARM64-совместимость image/dependencies.
3. Один writable PostgreSQL writer, direct/session endpoint, connection cap, TLS, backup/PITR и измеренный restore RTO.
4. Offsite encrypted DB dump, согласованную копию media, versioned keys и процедуру ручного writer fencing.
5. Stable HTTPS webhook origin, health/alerting, pending/dead-letter monitoring и отсутствие worker на CI/sleeping runtime.
6. Отдельное разрешение на включение Telegram/PSP/gift-card live paths. Этот документ не выполняет регистрацию, login, deploy или provider approval.

## Официальные страницы для повторной проверки

- Oracle Cloud Free Tier: <https://www.oracle.com/cloud/free/> и <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm>
- Neon pricing: <https://neon.tech/pricing>
- Supabase pricing: <https://supabase.com/pricing>
- Upstash pricing: <https://upstash.com/pricing>
- Redis Cloud pricing: <https://redis.io/pricing/>
- Render pricing: <https://render.com/pricing>
- Koyeb pricing: <https://www.koyeb.com/pricing>
- Vercel limits/fair use: <https://vercel.com/docs/limits/fair-use-guidelines>
- GitHub Actions billing: <https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions>
