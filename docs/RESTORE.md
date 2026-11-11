# Резервное копирование и проверка восстановления

## Что реализовано, а что нет

`infra/backup.sh` создаёт зашифрованный логический PostgreSQL archive через `pg_dump | age`; plaintext на диск не записывается. `infra/restore-test.sh` принимает этот archive только для явной пустой изолированной тестовой БД на loopback/не-5432, от ограниченной роли. Оба скрипта используют `set -euo pipefail`, не читают `.env`/`DATABASE_URL`, не выводят credentials и не выполняют очистку существующей БД.

Скрипты не создают расписание backup, offsite storage, аккаунты, ключи, test containers, failover или PITR. Успех `pg_dump` не доказывает восстановимость и полноту backup приложения. DB-архив не включает media, JWT/Fernet/fingerprint keys, настройки DNS или external provider state.

## Подготовка оператора

- Установить PostgreSQL client совместимой версии и `age` на защищённом host. Major-version `pg_dump` не должна быть старше сервера; совместимость restore проверить до инцидента.
- Отдельный `PGSERVICEFILE` и `PGPASSFILE` вне репозитория с минимальными правами. Секретные пароли — в password file/secret manager, не в командной строке. Скрипты получают имя service, а не credential-bearing URL.
- Backup role: только необходимые CONNECT/USAGE/SELECT для consistent dump всех таблиц/sequence; отдельно проверить RLS и полноту данных. Скрипт включает `default_transaction_read_only=on` и lock/connect timeout. Не давать backup job SUPERUSER без обоснования.
- `age` recipient — публичный ключ backup; identity/private key хранить отдельно от backup host и production credentials. Утрата ключа делает backup бесполезным. Key recovery регулярно проверять.
- Отключить shell tracing (`set -x`), логирование окружения и команды с выводом secret file. Stderr `pg_dump`/`pg_restore` не отправляется в общие логи; при неуспехе диагностировать отдельно в защищённой среде без публикации значений.

Пример с заранее настроенным service `windrop_backup`:

```bash
export PGSERVICEFILE=/secure/postgres-services.conf
export PGPASSFILE=/secure/postgres-passwords
export BACKUP_PGSERVICE=windrop_backup
export BACKUP_AGE_RECIPIENT=age1_REPLACE_WITH_PUBLIC_RECIPIENT
bash infra/backup.sh /secure/backups/windrop-YYYYMMDDTHHMMSSZ.dump.age
```

Файл назначения должен быть **новым**; перезапись запрещена. При сбое pipeline может остаться partial encrypted file; не публиковать его как успешную копию и не переиспользовать имя автоматически. Для offsite передавать только завершённые encrypted archives с checksum, timestamp, server/schema version и статусом проверки. Настроить отдельные credentials, versioning/immutability, retention, уведомления о пропуске. Сам offsite upload требует разрешения и в скриптах не выполняется.

### Media и секреты

В режиме `local` важен Docker volume `/app/media`. Сделать согласованную копию media вместе с DB snapshot: на время coordinated backup остановить запись media либо использовать проверенные snapshots с описанным порядком. DB dump плюс произвольная копия позже не гарантируют отсутствие отсутствующих файлов. Проверить, что все `media_assets.storage_key` существуют, и ограничить доступ к backup.

JWT/Fernet keys и giftcard fingerprint keys резервируются отдельно в secret manager с версиями и доступом минимум двух уполномоченных операторов. Восстановление только БД без ключей не позволяет расшифровать bot credentials/giftcards. Не помещать ключи внутрь архива с данными и не коммитить их. Секреты скомпрометированного snapshot нельзя автоматически переиспользовать для включения live-режима.

## Restore drill: только отдельный test target

1. Создать **новый отдельный** PostgreSQL test container/кластер, не `infra_pgdata`, с новым ephemeral volume и host-port, например `55433` (55432 может быть занят основным тестовым окружением). Ограничить его сеть; не запускать приложение/worker с live credentials. Удаление/создание контейнеров здесь не автоматизировано.
2. Создать БД и login-role, оба с суффиксом `_test`, роль `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`. Отозвать `PUBLIC CONNECT` у всех других нетemplate БД в **этом тестовом кластере**, разрешить CONNECT только к target. На рабочем кластере эту процедуру не выполнять. В target ещё не применять миграции: restore требует пустой БД.
3. Настроить отдельный service/password entry для тестовой роли. Выбрать проверенный собственный encrypted backup; архивы содержат исполняемый SQL, нельзя восстанавливать произвольные внешние dumps. `pg_restore` выполняется с ограниченными правами, не superuser.
4. Указать target и подтвердить его точное имя. Скрипт принудительно задаёт loopback, явный port, database и role поверх service; alias на production не переключит target. Проверяется фактическая роль, БД, отсутствие CONNECT к другим БД и пользовательских объектов.

```bash
export PGSERVICEFILE=/secure/postgres-services.conf
export PGPASSFILE=/secure/postgres-passwords
export RESTORE_PGSERVICE=windrop_restore_test
export TARGET_TEST_DB=windrop_restore_test
export TARGET_TEST_ROLE=windrop_restore_test
export TARGET_TEST_PORT=55433
export CONFIRM_RESTORE=windrop_restore_test
export RESTORE_AGE_IDENTITY=/secure/offline-backup-identity
bash infra/restore-test.sh /secure/backups/windrop-YYYYMMDDTHHMMSSZ.dump.age
```

Скрипт использует `--exit-on-error --single-transaction --no-owner --no-privileges`; **не** `--clean`, не `--create`. Встроенные guard снижают ошибки выбора, но не заменяют отдельный кластер: восстановление через tunnel к production запрещено, даже если loopback-порт и имена выглядят тестовыми. Объекты расширений/роли/grants могут потребовать отдельно проверенной подготовки. При ошибке не делать автоматический reset/очистку: остановить drill, сохранить безопасный диагноз, выбрать новый пустой target после согласования.

5. Read-only проверки: версия `schema_migrations`, числа записей ключевых таблиц, баланс/ledger и idempotency-инварианты, FK/уникальность, доступность и расшифровка выборки giftcards/bot registry в изолированной среде без отправок. Не печатать коды и токены.
6. Поднять приложение на изолированных test DB/Redis с `BOT_MODE=disabled`, `PAYMENTS_MODE=disabled`, `MANAGED_BOTS_ENABLED=false`, `GIFTCARD_MODE=disabled`, `ALLOW_GUEST_AUTH=false`. Не подключать к публичному webhook и не запускать restored outbox на production Telegram: pending записи могут повторно отправить сообщения/вызовы.
7. Проверить `/health/live` и `/health/ready`, media и тестовые сценарии. `/health/ready` marker проверяет ожидаемый релиз; старый backup сначала требует согласованного upgrade, не подмены marker. Записать время восстановления (измеренный RTO), возраст backup/RPO, результаты и проблемы. Отчёт не должен содержать dump/секреты.

## Free backend и пределы восстановления

Основной free compute candidate — Oracle Cloud Always Free VM (обычно Ampere A1 Flex) при наличии capacity и после проверки актуальных AUP/ToS. Один VM с локальными Docker volumes — одна failure domain: block volume, local Redis и `media:/app/media` не являются offsite backup, shared media или HA. Потеря/вытеснение VM требует поднять новый host, восстановить PostgreSQL, отдельно вернуть media и ключи и вручную проверить writer fencing. Если PostgreSQL тоже размещён на VM, профиль допустим только для закрытого preview/test; production RPO/RTO этим не доказывается.

Neon Free, Supabase Free и (если доступен) Render PostgreSQL Free — кандидаты для `*_test`/closed preview, не автоматически production restore targets. Scale-to-zero, pause/expiry, маленькие storage/connection quotas, no-SLA и возможное отсутствие PITR означают, что нельзя объявлять восстановление успешным по одному факту доступности endpoint. До использования зафиксировать exact plan, region, retention/PITR, direct/session endpoint и restore drill. Migration runner и scheduler требуют direct/session-compatible endpoint; transaction pooling несовместим с session advisory lock.

Upstash/Redis Cloud Free и Redis на Oracle VM — только cache/flags/ephemeral coordination. Redis не содержит источник истины для ledger, durable bot/payment inbox/outbox или gift inventory. Redis backup/AOF не заменяет PostgreSQL dump, media copy, secret/key backup или provider-state recovery. Потеря Redis должна отрабатываться пересозданием и readiness, без потери DB-событий.

Sleeping Render/Koyeb-подобный runtime и GitHub Actions hosted runner не являются restore targets для API, webhook, workers или scheduler: первый может спать/иметь ephemeral filesystem, второй завершается после job. Actions artifacts не являются offsite DB/media backup. Vercel может раздавать только статические `landing/` и Mini App assets. Он не хранит writable PostgreSQL, durable bot/payment inbox, scheduler lease или persistent media. При размещении UI на Vercel API/webhook должен оставаться на стабильном внешнем HTTPS origin; для preview все payments/bots должны быть отключены.

В free-схеме restore drill должен явно фиксировать: тип и дату DB backup, подтверждение encrypted offsite copy, целостность и наличие media, версии/доступность ключей, measured RPO/RTO, provider quota/capacity и точный новый writable target. Не принимать наличие snapshot, deploy artifact или доступного sleeping endpoint за доказанный restore. Ранжированная таблица limits/ToS/media/backup находится в `docs/FREE_BACKEND_OPTIONS.md`.

## PITR

Логический `pg_dump` **не обеспечивает point-in-time recovery**. Для PITR нужны физическая base backup плюс непрерывный архив всех WAL от её начала до целевой точки, совместимые PostgreSQL major-version, timeline history и проверенные retention/credentials. Для managed PostgreSQL включить и проверить штатный PITR провайдера; для self-hosted использовать проверенный `pgBackRest`/`WAL-G` или другую эксплуатационную процедуру. Наличие скрипта dump не заменяет WAL archive, мониторинг отсутствующих segments или restore drill на новой timeline.

Восстановление выполняется в новый изолированный кластер до `recovery_target_time`/LSN, затем проверяется до допуска записи. Не переключать приложение на replica recovery endpoint: readiness отклоняет recovery/read-only соединение. Actual RPO зависит от непрерывности WAL и подтверждённых provider гарантий, RTO — от измеренного drill; в этом репозитории эти SLA не доказаны.

## Аварийное переключение writer: только управляемая процедура

1. Перевести сервис в maintenance и прекратить новые записи/приём внешних событий. Согласовать окно и порядок с владельцем. Не пытаться лечить DB split-brain балансировщиком API.
2. **Сначала изолировать прежний writer и все прежние API/workers/scheduler/pollers**: network/credential fencing и контроль отсутствия записи. Одна advisory lock не распространяется на независимую restored/promoted БД.
3. Проверить recovery target, schema, ключи, media, RPO, ledger/provider reconciliation на новом кластере. Утраченные события и внешние подтверждения разбирать до повторного включения очередей. Redis не является источником истины для финансового ledger.
4. Назначить ровно один новый writable primary. Явно изменить единственный writer endpoint/credentials во всех процессах; никогда не оставлять две независимые активные базы, автоматический dual-write или два poller одного токена.
5. Сначала проверить readiness новой API, потом постепенно включить traffic и workers. Webhook hostname остаётся стабильным; dedupe должен выдерживать повтор Telegram, но side effects могут требовать reconciliation после ambiguous external timeout. Контролировать pending/dead backlog, ошибки и историю событий.

Технический API standby/Caddy помогает при отказе процесса, но не автоматизирует promotion БД, восстановление ключей/media, provider reconciliation или сетевой fencing. Изолированная локальная репетиция API failover/worker lease recovery описана в `docs/LOCAL_ACCEPTANCE.md`; финальный сценарий «оба API недоступны» не получил полного verdict из-за timeout internal controller, а повтор был заблокирован недоступным Docker Desktop. Эти действия не считаются production-проверкой и требуют отдельной утверждённой операции. Блокировки/санкции аккаунта не являются поводом для переключения на новые аккаунты или обходы ограничений платформы.
