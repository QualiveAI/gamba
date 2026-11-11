#!/usr/bin/env bash
# Только явный PostgreSQL service; .env и DATABASE_URL не читаются.
set -euo pipefail
set -o noclobber
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }

[[ $# -eq 1 ]] || fail 'Укажите новый файл назначения: bash infra/backup.sh /secure/new.dump.age'
[[ -n "${BACKUP_PGSERVICE:-}" ]] || fail 'Требуется BACKUP_PGSERVICE.'
[[ "$BACKUP_PGSERVICE" =~ ^[a-zA-Z0-9_.-]+$ ]] || fail 'Недопустимое имя PostgreSQL service.'
[[ -n "${BACKUP_AGE_RECIPIENT:-}" ]] || fail 'Требуется публичный BACKUP_AGE_RECIPIENT.'
[[ -n "${PGSERVICEFILE:-}" && -f "$PGSERVICEFILE" ]] || fail 'Требуется отдельный PGSERVICEFILE.'
[[ ! -e "$1" && ! -L "$1" ]] || fail 'Файл уже существует; перезапись запрещена.'
for command in pg_dump age; do
    command -v "$command" >/dev/null || fail "Не найдена команда $command."
done

export PGCONNECT_TIMEOUT=5
export PGAPPNAME=windrop-backup
export PGOPTIONS='-c default_transaction_read_only=on -c lock_timeout=10000'

# Plaintext дамп не записывается на диск. Ошибка любой стадии возвращает exit 1.
# При ошибке оставшийся partial-файл не использовать; он не перезаписывается повторно.
if ! pg_dump --dbname="service=$BACKUP_PGSERVICE" --no-password \
    --format=custom --no-owner --no-privileges 2>/dev/null \
    | age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" >"$1" 2>/dev/null; then
    fail 'Backup не завершён. Возможный partial-файл не является резервной копией.'
fi
printf '%s\n' 'Зашифрованная логическая копия создана; offsite и проверка восстановления отдельно.'
