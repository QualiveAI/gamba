# API

## Auth

POST /auth/telegram {init_data} -> {access_token}
GET /auth/roblox/url -> {url,state,code_verifier}
POST /auth/roblox/callback {code,code_verifier} -> {access_token}

## Cases

GET /cases
POST /cases/{id}/open {client_seed}

## Games

POST /games/upgrade {item_price,target_price,client_seed}
POST /games/crash {bet,cashout_at,client_seed}
POST /games/mines/start {bet,mine_count}
POST /games/mines/reveal {session_id,cell}
POST /games/mines/cashout?session_id=
POST /games/shell {bet,guess,client_seed}

## Payments

POST /payments/stars/invoice {title,description,payload,amount_stars}
POST /payments/yoomoney/create {amount_rub}
GET /payments/{id}/status
POST /payments/yoomoney/webhook
POST /payments/{id}/manual-claim {receipt_url}

## Gift cards

POST /admin/giftcards/import (multipart)
GET /admin/giftcards/stats

## Withdrawals

POST /withdrawals {amount,region}
GET /withdrawals/mine
GET /admin/withdrawals?status=
POST /admin/withdrawals/{id}/approve
POST /admin/withdrawals/{id}/reject?reason=
POST /admin/withdrawals/{id}/unfreeze

## Rewards

POST /rewards/daily/claim
GET /rewards/streak
GET /rewards/missions/today
POST /rewards/missions/progress?step=
GET /rewards/winfeed

## Predictor

POST /predictor/predict {session_id,bet}
POST /predictor/subscribe {days}
GET /predictor/status

## Admin
## Examples

POST /auth/telegram:
{"init_data":"..."} -> {"access_token":"jwt","token_type":"bearer"}

POST /cases/1/open:
{"client_seed":"seed"} -> {"id":1,"reward_id":2,"nominal_units":10,"rtp_used":0.8}

POST /payments/yoomoney/create:
{"amount_rub":100} -> {"payment_id":1,"external_id":"...","qr_url":"...","status":"pending"}

GET /admin/analytics?days=30 -> [{"date":"2026-10-29","data":{"game_rtp":{},"retention_d1":0.0}}]

GET /admin/ledger/reconcile
GET /admin/gift-reviews
POST /admin/gift-reviews/{id}/set-price {price_rub}
GET /admin/analytics?days=30
POST /admin/config/thresholds {low,high}
POST /admin/config/rtp {case_id,segment,rtp}
GET /admin/antifraud/flags

## Health

GET /health -> {db,redis}
## Additional endpoints

GET /health
GET /rewards/streak
POST /rewards/missions/progress
GET /rewards/winfeed
POST /predictor/subscribe
GET /predictor/status
GET /admin/gift-reviews
GET /admin/analytics
POST /admin/config/thresholds
POST /admin/config/rtp
GET /admin/antifraud/flags
POST /admin/withdrawals/{id}/unfreeze

## Notes

All endpoints require Bearer JWT except webhooks.
Admin endpoints require admin telegram id.
Errors return {detail}.