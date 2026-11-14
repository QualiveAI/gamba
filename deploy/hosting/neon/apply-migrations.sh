#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
  printf 'Usage: %s DATABASE_URL\n' "$0" >&2
  exit 2
fi
url="$1"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
shopt -s nullglob
migrations=("$repo_root"/backend/migrations/*.sql)
if ((${#migrations[@]} == 0)); then
  echo 'Миграции не найдены' >&2
  exit 1
fi
for migration in "${migrations[@]}"; do
  printf 'Применяю %s\n' "$(basename "$migration")"
  psql "$url" --set ON_ERROR_STOP=1 --file "$migration"
done
printf 'Миграции применены: %d\n' "${#migrations[@]}"
