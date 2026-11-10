[P] ROADMAP — Bot + Backend + Mini-App Project

## FAZE 1: BOT HANDLERS — COMPLETED ✅
- Created: c:\Артём\Бизнес\Ваня\Drop\RB\bot_handlers.py
- Commands: /start, /menu, /balance, /withdraw
- Integration with Mini-App via user_id and database
- Warmup period: 24 hours from registration

## FAZE 2: MINI-APP IMPROVEMENTS — IN PROGRESS
- Mini-app HTML created: c:\Артём\Бизнес\Ваня\Drop\RB\mini_app.html (111 lines)
- JavaScript functionality added (Telegram WebApp, session management, balance updates, game start/close)
- Need: Connect to real API_BASE URL, test all games

## FAZE 3: ANTI-BAN SYSTEME — PLANNED
- Bot rotation mechanism
- Warmup tracking (24 hours)
- IP rotation strategy
- Website/domain rotation

## FAZE 4: DEPOSIT & FREEBETS — PLANNED
- Minimum deposit: 500 фрибетов
- Bonus accrual after payment
- Transaction logging
- Withdrawal system

## FAZE 5: HOSTING & DEPLOY — PLANNED
- Vercel for backend API
- GitHub Pages / Vercel for Mini-App
- Bot token @BotFather
- Database: Neon.tech (PostgreSQL)
- Cache: Upstash (Redis)

## FAZE 5: TESTING — PLANNED
- Full user cycle: register → training → deposit → play
- Warmup timer verification
- Bot rotation testing
- Deposit/withdrawal flow

**ОБЩИЙ БЮДЖЕТ: $0/мес (все free tier)**