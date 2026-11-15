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
const REQUEST_HEADERS = ['authorization', 'content-type', 'accept', 'accept-language', 'x-request-id'];
// Заголовки ответа, которые клиенту полезны. set-cookie не переносим:
// сессия живёт в JWT, cookie не используются.
const RESPONSE_HEADERS = ['content-type', 'retry-after', 'x-request-id'];

// Холодный старт Render free занимает до минуты; ждём дольше обычного,
// но меньше лимита самой функции, чтобы вернуть внятную ошибку, а не зависнуть.
const UPSTREAM_TIMEOUT_MS = 25000;

function jsonError(detail, status) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
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

  const method = request.method.toUpperCase();
  const withBody = method !== 'GET' && method !== 'HEAD';
  // Тела маленькие (JSON с init_data), поэтому читаем целиком: это надёжнее,
  // чем потоковая передача тела в подзапрос.
  const body = withBody ? await request.arrayBuffer() : undefined;

  let upstream;
  try {
    upstream = await fetch(target.toString(), {
      method,
      headers,
      body,
      redirect: 'manual',
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (_) {
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
