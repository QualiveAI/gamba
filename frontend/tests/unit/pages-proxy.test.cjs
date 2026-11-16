const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const MODULE = pathToFileURL(
  path.join(__dirname, '..', '..', 'functions', 'api', '[[path]].js'),
).href;

async function loadModule() {
  return import(MODULE);
}

function context({ url, method = 'GET', headers = {}, body = null, env = {} }) {
  return {
    request: {
      url,
      method,
      headers: new Headers(headers),
      arrayBuffer: async () => (body ? new TextEncoder().encode(body).buffer : new ArrayBuffer(0)),
    },
    env,
  };
}

test('путь /api/* переписывается в путь upstream и сохраняется query', async () => {
  const { onRequest } = await loadModule();
  let seen = null;
  const original = globalThis.fetch;
  globalThis.fetch = async (target, options) => {
    seen = { target, options };
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const res = await onRequest(context({ url: 'https://windrop.pages.dev/api/wallet?x=1' }));
    assert.equal(res.status, 200);
    assert.equal(seen.target, 'https://windrop-api.onrender.com/wallet?x=1');
    assert.equal(await res.json().then((d) => d.ok), true);
  } finally {
    globalThis.fetch = original;
  }
});

test('Authorization и тело переносятся, а чужие заголовки — нет', async () => {
  const { onRequest } = await loadModule();
  let seen = null;
  const original = globalThis.fetch;
  globalThis.fetch = async (target, options) => {
    seen = options;
    return new Response('{}', { status: 200 });
  };
  try {
    await onRequest(context({
      url: 'https://windrop.pages.dev/api/auth/telegram',
      method: 'POST',
      headers: { authorization: 'Bearer jwt', 'content-type': 'application/json', cookie: 'secret=1' },
      body: '{"init_data":"x"}',
    }));
    assert.equal(seen.headers.get('authorization'), 'Bearer jwt');
    assert.equal(seen.headers.get('content-type'), 'application/json');
    assert.equal(seen.headers.get('cookie'), null);
    assert.equal(seen.method, 'POST');
    assert.ok(seen.body);
  } finally {
    globalThis.fetch = original;
  }
});

test('тот же origin получает CORS-заголовки, чужой — 403', async () => {
  const { onRequest } = await loadModule();
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response('{}', { status: 200 });
  try {
    const same = await onRequest(context({
      url: 'https://windrop.pages.dev/api/wallet',
      headers: { origin: 'https://windrop.pages.dev' },
    }));
    assert.equal(same.status, 200);
    assert.equal(same.headers.get('access-control-allow-origin'), 'https://windrop.pages.dev');

    const foreign = await onRequest(context({
      url: 'https://windrop.pages.dev/api/wallet',
      headers: { origin: 'https://evil.example' },
    }));
    assert.equal(foreign.status, 403);
  } finally {
    globalThis.fetch = original;
  }
});

test('недоступный upstream даёт 503 без деталей', async () => {
  const { onRequest } = await loadModule();
  const original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('upstream 10.0.0.5:5432 refused'); };
  try {
    const res = await onRequest(context({ url: 'https://windrop.pages.dev/api/wallet', env: { UPSTREAM_RETRY_DELAY_MS: '0' } }));
    assert.equal(res.status, 503);
    const body = await res.text();
    assert.ok(!body.includes('10.0.0.5'));
  } finally {
    globalThis.fetch = original;
  }
});

test('502 от просыпающегося Render повторяется внутри функции и заканчивается успехом', async () => {
  const { onRequest } = await loadModule();
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    if (calls < 3) return new Response('gateway', { status: 502 });
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'content-type': 'application/json' } });
  };
  try {
    const res = await onRequest(context({ url: 'https://windrop.pages.dev/api/health', env: { UPSTREAM_RETRY_DELAY_MS: '0' } }));
    assert.equal(res.status, 200);
    assert.equal(calls, 3);
  } finally {
    globalThis.fetch = original;
  }
});

test('Render недоступен совсем: после всех попыток — 503 и никаких деталей', async () => {
  const { onRequest } = await loadModule();
  const original = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('bad gateway', { status: 502 }); };
  try {
    const res = await onRequest(context({ url: 'https://windrop.pages.dev/api/health', env: { UPSTREAM_RETRY_DELAY_MS: '0' } }));
    assert.equal(res.status, 503);
    assert.equal(calls, 3);
    const body = await res.text();
    assert.ok(!body.includes('bad gateway'));
  } finally {
    globalThis.fetch = original;
  }
});
