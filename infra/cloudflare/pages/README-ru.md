# Mini App на Cloudflare Pages

Зачем переносить статику с Vercel: домены `*.vercel.app` и `*.onrender.com` из части
сетей (в частности из РФ) недоступны — соединение обрывается на TLS, страница не грузится.
Cloudflare Pages из этих сетей открывается. Плюс уходит риск некоммерческой лицензии
Vercel Hobby для gambling-проекта.

Схема после переноса:

```
Mini App: https://<project>.pages.dev/        ← Cloudflare Pages (статика)
           https://<project>.pages.dev/api/*   ← Pages Function → https://windrop-api.onrender.com
Render windrop-api                             ← API + worker + scheduler (источник истины)
```

Статика и API живут на одном origin, поэтому CORS в браузере не участвует вовсе:
`frontend/js/api-config.js` подставляет `location.origin + "/api"`, а функция
`frontend/functions/api/[[path]].js` переадресует запрос в Render, сохраняя метод,
тело и заголовок `Authorization`.

## Создание проекта

1. dashboard.cloudflare.com → **Workers & Pages** → **Create application** → **Pages**
   → **Connect to Git** → GitHub → репозиторий **`QualiveAI/gamba`** → ветка `production`?
   — нет, **`main`** → **Create**.
   Репозиторий приватный: если Cloudflare его не показывает, открой настройки GitHub-приложения
   Cloudflare (github.com/settings/installations) и выдай ему доступ к `QualiveAI/gamba`.
2. Build settings у проекта:

   | Параметр | Значение |
   |---|---|
   | Framework preset | None |
   | Root directory | `frontend` |
   | Build command | `node build-pages.mjs` |
   | Build output directory | `dist` |
   | Environment variables | пусто (секретов на статике не бывает) |

   Build command обязателен: в `frontend/` лежат node_modules, скриншоты и ~300 МБ
   экспериментальных ассетов, а Pages принимает только собранный `dist/` (4–5 МБ).
3. **Save and Deploy**. Домен проекта: `https://<project>.pages.dev` — его и укажи
   в Render (`WEBAPP_URL`) и пришли сюда.

## Проверка

| Что | Ожидание |
|---|---|
| `https://<project>.pages.dev/` | открывается Mini App (вне Telegram покажет требование открыть из Telegram) |
| `https://<project>.pages.dev/api/health` | `{"status":"ok","db":"ok","schema":"ok","outbox":"ok","redis":"ok"}` — функция проксирует Render |
| `https://<project>.pages.dev/api/health/live` | `{"status":"ok"}` |

`/api/health` — самая честная проверка: она доказывает, что статика, функция и Render
говорят друг с другом.

## Что где лежит

| Файл | Роль |
|---|---|
| `frontend/build-pages.mjs` | сборка `frontend/dist/` для Pages (без зависимостей, только Node) |
| `frontend/functions/api/[[path]].js` | Pages Function: `/api/*` → Render API, с CORS и таймаутом |
| `frontend/js/api-config.js` | публичный origin API для Mini App (тот же origin + `/api`) |

Upstream функции задан константой `UPSTREAM_ORIGIN` в `frontend/functions/api/[[path]].js`.
Если адрес Render поменяется — правится там же и в `render.yaml`.

## Ограничения

- Функция — только прокси: никакой логики, никаких секретов, никакого хранения.
- Запросы, которые идут дольше 25 секунд, обрываются (`service_unavailable`): холодный
  старт Render free длится до минуты. Клиент повторяет идемпотентный запрос один раз,
  поэтому второй заход попадает в уже прогретый контейнер.
- Webhook Telegram идёт напрямую в Render (`api.telegram.org` → `windrop-api.onrender.com`),
  мимо Pages: так доставка не зависит от лимитов Pages Functions.
