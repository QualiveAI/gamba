#!/bin/bash
# Единая точка входа для always-on runtime с ограниченным free-бюджетом часов.
# Render free даёт ~750 ч/мес на аккаунт: отдельный worker и отдельный scheduler
# съели бы бюджет вдвое, поэтому API, bot worker и scheduler идут одним сервисом.
#
# Семантика выхода:
# - API — primary: его падение гасит контейнер с ненулевым кодом (перезапуск);
# - worker при BOT_MODE=disabled штатно выходит с 0 и не считается отказом;
# - scheduler держит advisory lock и сам ретраит без leader, не унося API;
# - SIGTERM убивает детей и выходит 0 (штатная остановка оркестратором).

set -uo pipefail

PORT="${PORT:-8000}"
CHILD_PIDS=()
STOPPING=0

log() { printf '[entrypoint] %s\n' "$*"; }

shutdown() {
    STOPPING=1
    for pid in "${CHILD_PIDS[@]:-}"; do
        [[ -n "${pid}" ]] && kill -TERM "${pid}" 2>/dev/null || true
    done
}
trap shutdown TERM INT

uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers 1 \
    --no-access-log \
    --timeout-graceful-shutdown 30 &
API_PID=$!
CHILD_PIDS+=("$API_PID")
log "api запущен (pid ${API_PID})"

if [[ "${BOT_WORKER_ENABLED:-true}" == "true" ]]; then
    python -m app.bot.worker &
    CHILD_PIDS+=("$!")
    log "bot worker запущен (pid ${CHILD_PIDS[-1]})"
fi

if [[ "${SCHEDULER_ENABLED:-true}" == "true" ]]; then
    python -m app.ops.scheduler &
    CHILD_PIDS+=("$!")
    log "scheduler запущен (pid ${CHILD_PIDS[-1]})"
fi

wait "${API_PID}"
API_CODE=$?

if [[ "${STOPPING}" -eq 1 ]]; then
    shutdown
    wait 2>/dev/null || true
    log "остановлено по сигналу"
    exit 0
fi

log "api завершился сам (code ${API_CODE}); гасим контейнер для перезапуска"
shutdown
wait 2>/dev/null || true
# uvicorn не выходит с 0 без внешнего сигнала; нулевой код считаем отказом.
[[ "${API_CODE}" -eq 0 ]] && API_CODE=1
exit "${API_CODE}"
