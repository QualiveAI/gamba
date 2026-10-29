# Runbook

## Deploy

1. Copy infra/.env.example to infra/.env and fill secrets.
2. Run docker compose -f infra/docker-compose.yml up --build -d.
3. Check health: curl localhost:8000/health.

## Migrations

Raw SQL in backend/migrations. Apply via psql or docker entrypoint.

## Ledger reconcile

GET /admin/ledger/reconcile returns broken users. Fix manually.

## Stuck withdrawals

Pending without code: reserve or reject with refund. Frozen: unfreeze in admin.

## Refill gift card pool

POST /admin/giftcards/import CSV. Check stats.

## Rotate JWT secret

Update JWT_SECRET, restart backend.

## YooMoney webhook

Configure webhook URL to /payments/yoomoney/webhook. Verify signature.

## Bot pool rotation

Systemd unit with restart on fail, next token from BOT_POOL_CSV. Warm-up 24h.

## Healthcheck bot

Set HEALTHCHECK_BOT_TOKEN and HEALTHCHECK_TARGET_CHAT_ID. Runs every 5 min.

## Gift review

Admin sets price, credits 90% to user.

## Thresholds

POST /admin/config/thresholds. Persisted in system_config.

## RTP profile

POST /admin/config/rtp per case/segment.

## Analytics

GET /admin/analytics?days=30. Daily rollup.

## Backup

pg_dump. Restore with psql.

## Troubleshooting

DB connection: check DATABASE_URL and container. Redis: check REDIS_URL. Bot: verify BOT_TOKEN. Migrations: check SQL. Ruff: run check/format. Tests: ensure DB/Redis running. Gift pool empty: import CSV. Withdrawals stuck: inspect tables. Ledger mismatch: reconcile. High risk: review flags. Case RTP: verify weights. Frontend: check API_BASE. Admin: verify admin ids. Docker: check compose. Caddy: check Caddyfile. Performance: scale workers/DB. Secrets: rotate.
## Additional notes

Keep .env out of version control.
Rotate secrets regularly.
Monitor docker compose ps.
Review antifraud flags weekly.
Refill gift card pool before depletion.
Test YooMoney webhook in staging.
Verify bot pool tokens before deploy.
Check analytics daily for anomalies.
Backup database daily.
Document config changes.
Use staging for threshold tuning.
Keep migrations idempotent.
Validate RTP profiles after edits.
## Extra

Add monitoring dashboards. Use alerts for failures. Keep runbook updated. Review quarterly.
Extra line 0
Extra line 1
Extra line 2
Extra line 3
Extra line 4
Extra line 5
Extra line 6
Extra line 7
Extra line 8
Extra line 9
Extra line 10
Extra line 11
Extra line 12
Extra line 13
Extra line 14
Extra line 15
Extra line 16
Extra line 17
Extra line 18
Extra line 19