# Mini App на Cloudflare Pages

Зачем переносить статику с Vercel: домены `*.vercel.app` и `*.onrender.com` из части
сетей (в частности из РФ) недоступны — соединение обрывается на TLS, страница не грузится.
Cloudflare Pages из этих сетей открывается. Плюс уходит риск некоммерческой лицензии
Vercel Hobby для gambling-проекта.

Схема после переноса:

```
Mini App: https://windrop-app.pages.dev/          ← Cloudflare Pages (статика)
          https://windrop-app.pages.dev/api/*     ← Pages Function → https://windrop-api.onrender.com
Render windrop-api                                 ← API + worker + scheduler (источник истины)
```

Статика и API живут на одном origin, поэтому CORS в браузере не участвует вовсе:
`frontend/js/api-config.js` подставляет `location.origin + "/api"`, а функция
`frontend/functions/api/[[path]].js` переадресует запрос в Render, сохраняя метод,
тело и заголовок `Authorization`.

**Проект уже создан:** `windrop-app`, домен `https://windrop-app.pages.dev`,
аккаунт Cloudflare `2710ede6f87b97565fc846d0d6ae2170`.

## Как деплоить

**Автоматически (штатный путь):** workflow `.github/workflows/deploy-pages.yml`
на каждый push в `main`, если менялся `frontend/**`. Нужны GitHub-секреты:

| Секрет | Где взять |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare → My Profile → API Tokens → Create Token → шаблон **Edit Cloudflare Workers** или свой: Account → **Cloudflare Pages: Edit** |
| `CLOUDFLARE_ACCOUNT_ID` | `2710ede6f87b97565fc846d0d6ae2170` (Cloudflare → Workers & Pages, справа) |

Пока секретов нет, workflow просто упадёт на первой проверке и ничего не сломает.

**Вручную** (если нужно залить прямо сейчас):

```bash
cd frontend
node build-pages.mjs
wrangler pages deploy dist --project-name windrop-app --branch main
```

**Ловушка:** wrangler обязательно запускать из `frontend/`. Если запустить из корня
репозитория, статика уедет, а Functions — нет: `/api/*` начнёт отдавать `index.html`
вместо ответа API. Признак успеха в выводе — строка `✨ Uploading Functions bundle`.

## Проверка

| Что | Ожидание |
|---|---|
| `https://windrop-app.pages.dev/` | открывается Mini App (вне Telegram — требование открыть из Telegram) |
| `https://windrop-app.pages.dev/api/health` | `{"status":"ok","db":"ok","schema":"ok","outbox":"ok","redis":"ok"}` |
| `https://windrop-app.pages.dev/api/meta/tenant` | JSON с tenant/brand — значит прокси ходит в Render |
| тот же путь с `Origin: https://evil.example` | `403 origin_not_allowed` |

## Что где лежит

| Файл | Роль |
|---|---|
| `frontend/build-pages.mjs` | сборка `frontend/dist/` для Pages (без зависимостей, только Node) |
| `frontend/functions/api/[[path]].js` | Pages Function: `/api/*` → Render API, с CORS и таймаутом |
| `frontend/js/api-config.js` | публичный origin API для Mini App (тот же origin + `/api`) |
| `.github/workflows/deploy-pages.yml` | автодеплой статики на Pages при push в `main` |

Upstream функции задан константой `UPSTREAM_ORIGIN` в `frontend/functions/api/[[path]].js`.
Если адрес Render поменяется — правится там же и в `render.yaml`.

Git-интеграция Pages (альтернатива автодеплою из Actions) тоже поддерживается:
Root directory `frontend`, Build command `node build-pages.mjs`, Build output `dist`,
Functions подхватываются из `frontend/functions` автоматически.

## Пробуждение Render (важно)

Замерено на живом стенде: **запросы через Cloudflare погашенный инстанс Render не поднимают.**
150 секунд подряд запросов через функцию — сервис остался лежать (в логах Render нет запуска
контейнера, в `bot_registry` нет активности), и всё это время отдавалась его страница
«502 … service is currently unavailable». При этом **обычный браузерный запрос** и **webhook
Telegram** (оба идут в Render напрямую) поднимают сервис за 30–60 секунд.

Поэтому будильник живёт в клиенте: Mini App перед авторизацией отправляет прямой
`no-cors` пинг на `https://windrop-api.onrender.com/health/live` (см. `WINDROP_WAKE_ORIGIN`
в `api-config.js`). Ответ не читается — важен сам факт «живого» запроса. Дальше свою работу
делают повторы: функция (3 попытки, ≈28 с) и клиент (до 4 попыток, ≈90 с в сумме), так что
первое открытие после простоя показывает экран загрузки 30–60 с, а не ошибку.

**Почему нельзя просто держать сервис тёплым.** Пока контейнер запущен, планировщик держит
постоянное соединение с Neon с heartbeat раз в 5 секунд, а worker раз в 5 минут опрашивает
очереди. Значит «тёплый» Render = постоянно активный Neon = 720 ч/мес при бесплатных
**191,9 ч/мес**. Тёплый Render бесплатно невозможен; экономика такая: каждая сессия
пользователя держит контейнер (и БД) до 15 минут после последнего запроса — это и есть
бюджет, который надо тратить осознанно.

Ещё одна мелочь из той же серии: функция теперь **переносит `User-Agent`** (и подставляет свой,
если клиент его не прислал) — полностью анонимный запрос выглядит для Render как не-трафик.

## Ограничения

- Функция — только прокси: никакой логики, никаких секретов, никакого хранения.
- **Холодный старт Render free.** Погашенный инстанс отвечает быстрым `502` и просыпается
  30–50 секунд, поэтому обработка разнесена по двум уровням: функция делает до 3 попыток
  к Render (8 с таймаут + пауза 2 с, всего ≈28 с — внутри лимита самой функции), а клиент
  повторяет идемпотентный запрос до 4 раз с паузой 5 с. Итог: после 15 минут простоя первое
  открытие Mini App занимает 30–60 секунд с экраном загрузки, но без ошибки. Запросы,
  которые всё-таки не прошли, получают компактный `503 {"detail":"service_unavailable"}`
  вместо HTML-страницы Render.
- Webhook Telegram идёт напрямую в Render (`api.telegram.org` → `windrop-api.onrender.com`),
  мимо Pages: так доставка не зависит от лимитов Pages Functions.
