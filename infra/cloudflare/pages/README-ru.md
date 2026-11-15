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

## Ограничения

- Функция — только прокси: никакой логики, никаких секретов, никакого хранения.
- Запросы, которые идут дольше 25 секунд, обрываются (`service_unavailable`): холодный
  старт Render free длится до минуты. Клиент повторяет идемпотентный запрос один раз,
  поэтому второй заход попадает в уже прогретый контейнер.
- Webhook Telegram идёт напрямую в Render (`api.telegram.org` → `windrop-api.onrender.com`),
  мимо Pages: так доставка не зависит от лимитов Pages Functions.
