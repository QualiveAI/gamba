# WINDROP (roblox-case-platform) — хостинг вне твоего ПК

Процесс сохранён, чтобы деплой повторялся одним проходом. Всё бесплатно, без карты.
Состав: **Cloudflare Pages** (статика) + **Vercel** (API serverless, опционально зеркало статики)
+ **Neon** (Postgres) + **Upstash** (Redis). Остальные проекты — на ПК до покупки сервера.

## 0. Что где живёт

| Слой | Куда | Что нужно |
|---|---|---|
| frontend + landing (статика) | Cloudflare Pages (основной) + Vercel (зеркало) | `deploy/hosting/cloudflare/`, корневой `vercel.json` |
| API FastAPI | Vercel Python serverless ИЛИ Hax/Woiden VPS (systemd) | `deploy/hosting/vercel/api/` |
| Postgres | Neon (free 0.5 ГБ) | миграции `backend/migrations/*.sql` через `deploy/hosting/neon/` |
| Redis | Upstash (free) | `REDIS_URL` в env |
| Авто-pause job (раз в 10 мин) | Vercel Cron → `api/cron/auto_pause.py` ИЛИ systemd-timer на VPS | advisory lock сохранён |
| Полигон тестов | Hax + Woiden VPS (IPv6/NAT) | init-скрипт ниже |

## 1. Neon (база)

1. neon.tech → регистрация (email; из РФ — через VPN).
2. Create project → скопируй `DATABASE_URL` (pooled endpoint).
3. Примени миграции по порядку:
   - Git Bash: `bash deploy/hosting/neon/apply-migrations.sh "$DATABASE_URL"`
   - PowerShell: `powershell -File deploy/hosting/neon/apply-migrations.ps1 -DatabaseUrl "$env:DATABASE_URL"`
4. Проверь: `psql "$DATABASE_URL" -c "\dt"` — таблицы из 0001…000N на месте.

## 2. Upstash (Redis)

1. upstash.com → Console → Create database (Regional: EU-Central ближе всего).
2. Скопируй `REDIS_URL` (rediss://… с TLS). Больше ничего.

## 3. Cloudflare Pages (статика)

Сборка использует только `landing/` и `frontend/`; локальные node_modules и тестовые
артефакты в dist не попадают. Это deployment-artifact, его можно удалять после upload.


1. Собери dist: `bash deploy/hosting/cloudflare/build-dist.sh` (или PowerShell-вариант рядом).
2. `npx wrangler pages deploy deploy/hosting/cloudflare/dist --project-name windrop-app`
   (первый запуск попросит логин Cloudflare — email-only).
3. Домен по умолчанию: `windrop-app.pages.dev`. Кастомный домен — в настройках проекта.

## 4. Vercel (API + зеркало статики)

Для API wrapper/cron подготовлены файлы в `deploy/hosting/vercel/api/`. Vercel-проект
не должен получать `.env`, SQLite/локальные media или Docker volumes. Хендлеры используют
только Environment Variables и внешние Neon/Upstash endpoints.


1. Регистрируйся через VPN. В 2022 Vercel блокировал РФ-аккаунты — риск бана остаётся,
   поэтому CF Pages является основной статикой, Vercel — API/зеркало.
2. Импортируй репо (или `npx vercel` из корня). Framework preset: **Other**.
3. В dashboard → Settings → Environment Variables добавь всё из
   `deploy/hosting/env.windrop.example` (значения — свои, НЕ коммитить).
4. Root `api/` уже подготовлен в репозитории (шаблон также лежит в
   `deploy/hosting/vercel/api/`). Vercel поднимет FastAPI-функцию на `/api` и cron-handler
   на `/api/cron/auto_pause`; `.vercelignore` не отправляет локальные базы, backups и secrets.
5. В корневом `vercel.json` уже добавлен cron `*/10 * * * *`. В Vercel Environment Variables
   обязательно добавь `CRON_SECRET`; без `Authorization: Bearer <CRON_SECRET>` handler отвечает 404.

## 5. Если API не на Vercel, а на Hax/Woiden VPS

Готовые unit-файлы: `deploy/hosting/systemd/windrop-api.service` и
`deploy/hosting/systemd/windrop-scheduler.service`.

1. `apt update && apt install -y python3-venv postgresql-client`
2. `git clone <repo> && cd roblox-case-platform/backend`
3. `python3 -m venv .venv && .venv/bin/pip install -e .`
4. env в `/etc/windrop.env` (chmod 600) → systemd-юнит:
   `ExecStart=/opt/roblox-case-platform/backend/.venv/bin/uvicorn app.main:app --host :: --port 8000`
5. Scheduler отдельным юнитом: `python -m app.ops.scheduler` (advisory lock сам разрулит одиночество).
6. Установи unit-файлы в `/etc/systemd/system/`, затем `systemctl daemon-reload && systemctl enable --now windrop-api windrop-scheduler`.
7. Наружу — только через Cloudflare Tunnel / телеграм-webhook (NAT/IPv6-хостинг портов наружу не даёт).

## 6. env-переменные (шаблон)

`deploy/hosting/env.windrop.example`. Секреты: bot_token, jwt_secret, fernet_key,
paymento-ключи — не коммитить, хранить в .env/dashboard переменных.

## 7. Напоминания о продлениях (когда создашь VPS)

| Площадка | Окно | Действие |
|---|---|---|
| Woiden | последние 3 дня цикла (3+2 дня) | продлить на woiden.id/vps-renew |
| Hax | последние 3 дня перед expiry | hax.co.id/vps-renew (ввести адрес сайта) |

Заведу cron-напоминания в этом чате, когда скажешь ID/даты серверов.

## Известные грабли

- **Vercel × РФ**: регистрация через VPN; при бане — API переезжает на VPS за один вечер (см. §5).
- **Neon free**: БД засыпает после 5 дней неактивности — для прод-проекта с трафиком не проблема,
  для теста — первый запрос после сна медленный.
- **Serverless и lifespan**: у FastAPI `lifespan` выполняется на каждом холодном старте функции —
  тяжёлое туда не выносить.
- **Scheduler на serverless**: `app.ops.scheduler` рассчитан на постоянный процесс с advisory lock.
  Вариант Vercel Cron использует ту же семантику (lock на короткой сессии), но если появятся
  многозадачные джобы — переносить scheduler на VPS.
- **CF Pages _redirects**: прокси-правила с кодом 200 уже включены в `build-dist.sh`; если будешь
  править — код 200 обязателен для SPA-роутов.

## Проверка после деплоя

1. `curl -s https://<cf-domain>/` — landing открывается.
2. `curl -s https://<cf-domain>/app/` — фронт.
3. `curl -s https://<vercel-domain>/api/health` (если роут есть) или любой meta-роут — 200.
4. Telegram: выставить webhook бота на `https://<vercel-domain>/bot/webhook/<secret>`.
5. `webapp_url` и `public_base_url` в env — на публичные домены, иначе кнопки бота поведут на localhost.
