# Architecture

## Layers

- Frontend: Telegram Mini App and admin panel (HTML/CSS/JS, Canvas).
- Backend: FastAPI Python 3.12, raw SQL, psycopg async.
- Bot: aiogram 3 dispatcher, healthcheck bot, bot pool.
- DB: PostgreSQL 16.
- Cache: Redis 7.
- Infra: Docker, docker-compose, Caddy.

## Data flow

User -> Telegram initData -> JWT. Case open -> RNG -> ledger. Withdrawal -> freeze/approve -> gift card. Payments -> deposit -> balance.

## DB schema (ASCII)

users, cases, case_rewards, case_openings, gift_codes, gift_conversions, withdrawals, withdrawal_freezes, ledger_entries, referrals, referral_flags, daily_rewards, deposit_streaks, missions, mission_progress, mines_sessions, mines_predictions, user_subscriptions, events, antifraud_flags, payment_polling, bot_pool, bot_health, analytics_daily, system_config, win_feed.

## Ledger invariant

SUM(ledger_entries.delta) == users.balance_units per user. post_entry enforces. reconcile returns broken users.

## Dynamic RTP

compute_segment: new <10 openings, active 10-49, veteran >=50. resolve_rtp reads case.rtp_profile[segment]. Subscription adds +2%.

## Silent predictor
## Payments

Telegram Stars, Gifts, YooMoney SBP QR. Webhook + polling fallback. Manual claim.

## Referrals

Hold 7 days. Anti-fraud by IP/device. Bonus release after deposit.

## Missions

Daily chain: open case, mines reveal, claim daily. Reward free case.

## Win feed

Wins above threshold stored, last 50, shareable.

## Security

Roblox OAuth PKCE, Telegram initData HMAC, JWT HS256, Fernet tokens.

## Deployment

Docker compose. Migrations auto. Healthcheck /health.

## Monitoring

bot_health, analytics_daily, logs.

Accuracy by bet: <=10 -> 0.80 (5 cells), >=100 -> 0.20 (1 cell), linear between. Silent mode returns fewer cells, confidence shown. Admin mode 100%.

## Next-move bias

Mines bias applies on NEXT move, not current click. Re-roll mines among unrevealed cells weighted by historical click distribution. Revealed cells never get mines.

## Analytics pipeline

events table with idempotency. daily_rollup computes per-game RTP, retention D1/D7, conversion, LTV. Stored in analytics_daily.

## Bot pool lifecycle

Pool CSV tokens. Warm-up 24h. Healthcheck bot monitors main bot. Ban triggers rotation.
## Additional details

The platform uses double-entry ledger accounting for all balance changes.
Each case opening generates a server seed hash for provable fairness.
Gift card codes are region and nominal specific.
Withdrawals require admin approval before code issuance.
Antifraud scoring combines multiple rules into a single risk level.
Game adapters provide quotes and delivery instructions without direct transfer where unsupported.
Analytics aggregates daily metrics for retention and conversion.
Bot pool supports warm-up and rotation.
Predictor uses silent mode to limit suggestions as bets grow.
Mines bias applies only to next move, never current click.
Referral bonuses are held for seven days.
Missions reset at UTC midnight.
Win feed stores last fifty wins.
Payments support Stars, Gifts, and YooMoney SBP.
Healthcheck bot monitors main bot every five minutes.
## Extra
## Extra2

Document all endpoints. Keep schema diagrams. Update on changes.

Add monitoring dashboards. Use alerts for failures. Keep runbook updated. Review quarterly.
Extra line 0
Extra line 1
Extra line 2
Extra line 3
Extra line 4
Extra line 5
Extra line 6
Extra line 7