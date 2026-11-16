/**
 * Cloudflare Pages Function: /api/* → Render API (windrop-api.onrender.com).
 *
 * Зачем: домены *.onrender.com и *.vercel.app недоступны из части сетей
 * (в частности из РФ — обрыв на TLS), а Cloudflare Pages/Workers доступны.
 * Функция отдаёт статику и API с одного origin: CORS не нужен вовсе,
 * cookie/credentials не используются — авторизация идёт заголовком
 * Authorization: Bearer.
 *
 * Функция ничего не решает за API: только переадресует запрос, сохраняя
 * метод, тело, Authorization и ответ. Секретов здесь нет и быть не должно.
 */

const UPSTREAM_ORIGIN = 'https://windrop-api.onrender.com';

// Заголовки запроса, которые имеет смысл переносить. Остальное (Host,
// cookie, cf-*) не пересылаем: они относятся к Cloudflare, а не к API.
// User-Agent переносим обязательно: без него запрос выглядит как анонимный бот,
// а Render free поднимает погашенный инстанс только под «живой» трафик.
const REQUEST_HEADERS = ['authorization', 'content-type', 'accept', 'accept-language', 'user-agent', 'x-request-id'];
// Заголовки ответа, которые клиенту полезны. set-cookie не переносим:
// сессия живёт в JWT, cookie не используются.
const RESPONSE_HEADERS = ['content-type', 'retry-after', 'x-request-id'];

// Погашенный free-инстанс Render отвечает быстрым 502 и просыпается 30–50 с.
// Поэтому один запрос клиента превращается в несколько попыток внутри функции:
// 3 × 8 с + 2 паузы по 2 с ≈ 28 с — меньше 30-секундного лимита самой функции,
// и достаточное окно, чтобы контейнер успел подняться. Если не получилось —
// отдаём понятный 503, а клиент повторит запрос целиком.
const UPSTREAM_TIMEOUT_MS = 8000;
const UPSTREAM_ATTEMPTS = 3;
const UPSTREAM_RETRY_DELAY_MS = 2000;
// 502/503/504 от Render в этом контексте означают «инстанс просыпается».
const RETRYABLE_UPSTREAM_STATUSES = new Set([502, 503, 504]);

function jsonError(detail, status) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryDelayMs(env) {
  const value = Number(env && env.UPSTREAM_RETRY_DELAY_MS);
  return Number.isFinite(value) && value >= 0 ? value : UPSTREAM_RETRY_DELAY_MS;
}

async function fetchUpstream(target, options, env) {
  for (let attempt = 1; attempt <= UPSTREAM_ATTEMPTS; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
    try {
      const response = await fetch(target, { ...options, signal: controller.signal });
      if (!RETRYABLE_UPSTREAM_STATUSES.has(response.status)) return response;
      // Последняя попытка тоже неудачна: отдаём свой компактный 503, а не
      // HTML-страницу Render.
      if (attempt === UPSTREAM_ATTEMPTS) return null;
    } catch (_) {
      if (attempt === UPSTREAM_ATTEMPTS) return null;
    } finally {
      clearTimeout(timer);
    }
    await sleep(retryDelayMs(env));
  }
  return null;
}

function allowedOrigin(request, env) {
  const origin = request.headers.get('Origin');
  if (!origin) return null; // не браузерный клиент (curl, health-check)
  const own = new URL(request.url).origin;
  if (origin === own) return origin;
  const extra = String((env && env.ALLOWED_ORIGINS) || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  return extra.includes(origin) ? origin : false;
}

export async function onRequest(context) {
  const { request, env } = context;

  const origin = allowedOrigin(request, env);
  if (origin === false) return jsonError('origin_not_allowed', 403);

  const url = new URL(request.url);
  // /api/* → /* на upstream.
  const target = new URL(UPSTREAM_ORIGIN + url.pathname.replace(/^\/api/, '') + url.search);

  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  // Если клиент не прислал User-Agent (curl, health-check), подставляем свой:
  // полностью анонимные запросы Render считает не трафиком и не будит сервис.
  if (!headers.has('user-agent')) headers.set('user-agent', 'WindropApiProxy/1.0');

  const method = request.method.toUpperCase();
  const withBody = method !== 'GET' && method !== 'HEAD';
  // Тела маленькие (JSON с init_data), поэтому читаем целиком: это надёжнее,
  // чем потоковая передача тела в подзапрос.
  const body = withBody ? await request.arrayBuffer() : undefined;

  let upstream;
  try {
    upstream = await fetchUpstream(target.toString(), {
      method,
      headers,
      body,
      redirect: 'manual',
    }, env);
  } catch (_) {
    upstream = null;
  }
  if (!upstream) {
    // Детали не пишем: в лог уходит только факт недоступности upstream.
    return jsonError('service_unavailable', 503);
  }

  const out = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) out.set(name, value);
  }
  out.set('cache-control', 'no-store');
  if (origin) {
    out.set('access-control-allow-origin', origin);
    out.set('vary', 'Origin');
  }
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: out,
  });
}
