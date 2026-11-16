/* Публичный конфиг источника API. Значение видно каждому посетителю.
 * Пустая строка = same-origin без префикса (локальная разработка).
 * Cloudflare Pages: статика и /api/* (Pages Function) живут на одном origin,
 * поэтому CORS в браузере не участвует, а домены *.onrender.com не светятся.
 * Vercel (переходный период): прямой вызов Render API.
 * Секретов здесь не бывает: токены, DSN и ключи живут только на сервере.
 */
(function () {
  const host = window.location.hostname || '';
  const origin = window.location.origin;
  const usable = typeof origin === 'string' && origin.startsWith('http') && origin !== 'null';
  if (!usable || host === 'localhost' || host === '127.0.0.1' || host === '::1') {
    window.WINDROP_API_ORIGIN = '';
    window.WINDROP_WAKE_ORIGIN = '';
    return;
  }
  window.WINDROP_API_ORIGIN = host.endsWith('.pages.dev')
    ? origin + '/api'
    : 'https://windrop-api.onrender.com';
  // Render free засыпает и просыпается только от «живого» запроса: запросы через
  // Cloudflare его не поднимают, а браузер клиента — поднимает. Поэтому Mini App
  // перед авторизацией шлёт прямой пинг на API. Ответ не читается, важен сам факт.
  window.WINDROP_WAKE_ORIGIN = 'https://windrop-api.onrender.com';
})();
