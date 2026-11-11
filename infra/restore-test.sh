#!/usr/bin/env bash
# Восстановление только в пустую изолированную loopback *_test БД, без --clean.
set -euo pipefail
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }

[[ $# -eq 1 ]] || fail 'Укажите encrypted backup: bash infra/restore-test.sh /secure/backup.dump.age'
[[ -f "$1" ]] || fail 'Файл резервной копии не найден.'
[[ "${TARGET_TEST_DB:-}" =~ ^[a-z][a-z0-9_]*_test$ ]] || fail 'Требуется точное TARGET_TEST_DB с суффиксом _test.'
[[ "${TARGET_TEST_ROLE:-}" =~ ^[a-z][a-z0-9_]*_test$ ]] || fail 'Требуется точное TARGET_TEST_ROLE с суффиксом _test.'
[[ "${TARGET_TEST_PORT:-}" =~ ^[0-9]+$ && "$TARGET_TEST_PORT" -gt 1024 && "$TARGET_TEST_PORT" -le 65535 && "$TARGET_TEST_PORT" -ne 5432 ]] \
    || fail 'Требуется отдельный TARGET_TEST_PORT, не 5432.'
[[ "${RESTORE_PGSERVICE:-}" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail 'Требуется отдельный RESTORE_PGSERVICE.'
[[ "${CONFIRM_RESTORE:-}" == "$TARGET_TEST_DB" ]] || fail 'CONFIRM_RESTORE должен точно совпадать с TARGET_TEST_DB.'
[[ -n "${PGSERVICEFILE:-}" && -f "$PGSERVICEFILE" ]] || fail 'Требуется отдельный PGSERVICEFILE.'
[[ -n "${RESTORE_AGE_IDENTITY:-}" && -f "$RESTORE_AGE_IDENTITY" ]] || fail 'Требуется RESTORE_AGE_IDENTITY вне репозитория.'
for command in psql pg_restore age; do
    command -v "$command" >/dev/null || fail "Не найдена команда $command."
done

export PGCONNECT_TIMEOUT=5
export PGAPPNAME=windrop-test-restore
export PGOPTIONS='-c statement_timeout=10000 -c lock_timeout=5000'
# Параметры target переопределяют host/dbname/user из service: ошибочный alias
# не может отправить archive на удалённый host или рабочий порт.
connection="service=$RESTORE_PGSERVICE host=127.0.0.1 hostaddr=127.0.0.1 port=$TARGET_TEST_PORT dbname=$TARGET_TEST_DB user=$TARGET_TEST_ROLE"

# Даже неправильно названный service не должен направить pg_restore в рабочую БД.
# Имя role/database, ограничения роли, loopback+нештатный порт и пустота проверяются
# самим PostgreSQL. Пароли находятся в .pgpass/PGPASSFILE, не в argv и не в логах.
metadata=$(psql --dbname="$connection" --no-password --no-psqlrc \
    --tuples-only --no-align --field-separator='|' --set=ON_ERROR_STOP=1 \
    --command="
SELECT current_database(), current_user,
       COALESCE(inet_server_addr()::text, ''), inet_server_port(),
       (NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
        AND NOT rolreplication AND NOT rolbypassrls)::int,
       (NOT EXISTS (
           SELECT 1 FROM pg_database
           WHERE datallowconn AND NOT datistemplate AND datname <> current_database()
             AND has_database_privilege(current_user, oid, 'CONNECT')
       ))::int,
       (NOT EXISTS (
           SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
             AND n.nspname NOT LIKE 'pg_toast%'
             AND n.nspname NOT LIKE 'pg_temp_%'
       ) AND NOT EXISTS (
           SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
       ) AND NOT EXISTS (
           SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
             AND n.nspname NOT LIKE 'pg_toast%'
       ))::int
FROM pg_roles WHERE rolname = current_user;" 2>/dev/null) \
    || fail 'Не удалось безопасно проверить тестовую БД. Восстановление отменено.'
IFS='|' read -r database role address port restricted isolated empty <<<"$metadata"
[[ "$database" == "$TARGET_TEST_DB" && "$role" == "$TARGET_TEST_ROLE" ]] || fail 'Имя целевой БД или роли не соответствует тестовой.'
# В Docker inet_server_addr()/port — внутренний адрес/5432. Внешний loopback target
# уже жёстко задан conninfo, поэтому нельзя требовать loopback от сервера за NAT.
[[ -n "$address" && "$port" =~ ^[0-9]+$ ]] || fail 'Не удалось подтвердить TCP-подключение.'
[[ "$restricted" == '1' && "$isolated" == '1' && "$empty" == '1' ]] \
    || fail 'Нужны ограниченная изолированная роль и пустая тестовая БД.'

# pg_restore выполняет SQL из архива: используйте лишь доверенные собственные копии.
# Тестовая роль не получает SUPERUSER; сеть контейнера дополнительно изолируется оператором.
export PGOPTIONS='-c lock_timeout=5000'
if ! age --decrypt --identity "$RESTORE_AGE_IDENTITY" "$1" 2>/dev/null \
    | pg_restore --dbname="$connection" --no-password --no-owner --no-privileges \
        --exit-on-error --single-transaction 2>/dev/null; then
    fail 'Восстановление не завершено. БД не использовать до проверки; автоматической очистки нет.'
fi
printf '%s\n' 'Архив восстановлен в test DB. Проверьте схему, инварианты и media перед завершением drill.'
