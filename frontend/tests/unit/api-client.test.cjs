const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createClient, ApiError, authBotId, tokenContext, errorMessage } = require('../../js/api-client.js');

const jwt = (sub = '41', bot = 123456, scope = 'primary', salt = '') =>
  `header.${Buffer.from(JSON.stringify({ sub, auth_bot_id: bot, scope, salt })).toString('base64url')}.signature`;
const response = (status, data) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
const sdk = { initData: 'signed-test-data', initDataUnsafe: { user: { id: 999 }, start_param: 'withdraw' } };
const memory = () => {
  const data = new Map([['jwt', 'unsafe-legacy-token']]);
  return { data, getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) };
};

test('пустой SDK не создаёт гостя и не делает auth-запрос', async () => {
  let calls = 0;
  const client = createClient({ fetch: async () => { calls++; }, getTelegram: () => ({ initData: '' }) });
  await assert.rejects(client.request('/wallet'), error => error.code === 'telegram_required');
  await assert.rejects(client.request('/cases'), error => error.code === 'telegram_required');
  assert.equal(calls, 0);
});

test('auth включает только подписанные данные и валидный URL auth_bot_id', async () => {
  const requests = [];
  const client = createClient({ search: '?auth_bot_id=777777&owner_telegram_id=8888&user_id=99', getTelegram: () => sdk,
    fetch: async (path, options) => {
      requests.push([path, options]);
      return path === '/auth/telegram' ? response(200, { access_token: jwt('41', 777777, 'managed') }) : response(200, {});
    } });
  await client.request('/wallet');
  assert.deepEqual(JSON.parse(requests[0][1].body), { init_data: sdk.initData, auth_bot_id: 777777 });
  assert.equal(client.getContext(), 'managed:bot:777777:account:41');
  assert.equal(client.getChannel(), 'telegram');
  assert.equal(requests[1][1].headers.Authorization, `Bearer ${jwt('41', 777777, 'managed')}`);
  assert.equal(requests[1][1].redirect, 'error');
});

test('некорректный или неоднозначный id бота не уходит серверу', async () => {
  for (const query of ['?auth_bot_id=0', '?auth_bot_id=-1', '?auth_bot_id=1.1', '?auth_bot_id=1e3', '?auth_bot_id=9007199254740993', '?auth_bot_id=x', '?auth_bot_id=1&auth_bot_id=2']) {
    assert.throws(() => authBotId(query), error => error.code === 'auth_bot_invalid');
  }
  assert.equal(authBotId('?start=managed'), undefined);
  assert.equal(authBotId('?auth_bot_id=777777'), 777777);
});

test('параллельные API запросы делят один auth promise', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let authCalls = 0, protectedCalls = 0;
  const client = createClient({ getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') { authCalls++; await gate; return response(200, { access_token: jwt() }); }
    protectedCalls++; return response(200, {});
  } });
  const work = Promise.all(['/wallet', '/cases', '/bots/me', '/giftcards/catalog'].map(path => client.request(path)));
  await Promise.resolve(); assert.equal(authCalls, 1); assert.equal(protectedCalls, 0);
  release(); await work;
  assert.equal(authCalls, 1); assert.equal(protectedCalls, 4);
});

test('401 допускает только одну повторную авторизацию и один retry', async () => {
  let authCalls = 0, protectedCalls = 0;
  const client = createClient({ getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') { authCalls++; return response(200, { access_token: jwt('41', 123456, 'primary', String(authCalls)) }); }
    protectedCalls++; return response(401, { detail: 'secret from upstream' });
  } });
  await assert.rejects(client.request('/wallet'), error => error.code === 'invalid_telegram_auth');
  await assert.rejects(client.request('/cases'), error => error.code === 'invalid_telegram_auth');
  assert.equal(authCalls, 2); assert.equal(protectedCalls, 2);
});

test('несколько одновременных 401 не вызывают auth flood', async () => {
  let authCalls = 0;
  const issued = [];
  const client = createClient({ getTelegram: () => sdk, fetch: async (path, options) => {
    if (path === '/auth/telegram') {
      authCalls++; const token = jwt('41', 123456, 'primary', String(authCalls)); issued.push(token);
      return response(200, { access_token: token });
    }
    return options.headers.Authorization === `Bearer ${issued[0]}` ? response(401, {}) : response(200, { ok: true });
  } });
  const results = await Promise.all(Array.from({ length: 10 }, () => client.request('/wallet')));
  assert.equal(authCalls, 2); assert.ok(results.every(row => row.ok));
});

test('повторная авторизация при смене аккаунта останавливает запрос', async () => {
  let authCalls = 0, protectedCalls = 0;
  const client = createClient({ getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') { authCalls++; return response(200, { access_token: jwt(authCalls === 1 ? '41' : '42') }); }
    protectedCalls++; return response(401, {});
  } });
  await assert.rejects(client.request('/deposits'), error => error.code === 'session_changed');
  assert.equal(protectedCalls, 1); assert.equal(authCalls, 2);
});

test('ответ auth для другого бота не используется', async () => {
  const client = createClient({ search: '?auth_bot_id=777777', getTelegram: () => sdk,
    fetch: async () => response(200, { access_token: jwt('41', 123456, 'managed') }) });
  await assert.rejects(client.authenticate(), error => error.code === 'session_changed');
});

test('JWT не сохраняется; старый общий JWT не используется и удаляется', async () => {
  const storage = memory();
  const client = createClient({ storage, getTelegram: () => sdk, fetch: async () => response(200, { access_token: jwt() }) });
  await client.authenticate();
  assert.equal(storage.data.size, 0);
  assert.equal(client.getContext(), 'primary:bot:123456:account:41');
  assert.equal(tokenContext('opaque-token'), null);
  assert.equal(tokenContext(jwt('41', 123456, 'guest')), null);
});

test('таймаут возвращает безопасную ошибку и не повторяет mutating запрос сам', async () => {
  let protectedCalls = 0;
  const client = createClient({ timeoutMs: 5, getTelegram: () => sdk, fetch: async (path, options) => {
    if (path === '/auth/telegram') return response(200, { access_token: jwt() });
    protectedCalls++;
    return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('provider key SECRET'))));
  } });
  await assert.rejects(client.request('/deposits', { method: 'POST' }), error => error.code === 'network_timeout' && !error.message.includes('SECRET'));
  assert.equal(protectedCalls, 1);
});

test('ошибки API не отражают HTML, ключи или сырые сообщения провайдера', async () => {
  for (const data of [{ detail: '<script>SECRET</script>' }, { detail: { message: 'token=SECRET' } }, { code: 'unknown', key: 'SECRET' }]) {
    const client = createClient({ retryDelayMs: 0, getTelegram: () => sdk, fetch: async path => path === '/auth/telegram'
      ? response(200, { access_token: jwt() }) : response(502, data) });
    await assert.rejects(client.request('/wallet'), error => !error.message.includes('SECRET') && error.code === 'service_unavailable');
  }
  assert.equal(errorMessage(new Error('SECRET')), 'Serviço indisponível no momento. Nenhuma confirmação foi recebida.');
  assert.equal(new ApiError('quote_expired', 409).message, 'A cotação expirou. Solicite uma nova prévia antes de confirmar.');
});

test('ошибка auth кэшируется до явного повторения пользователем', async () => {
  let calls = 0;
  const client = createClient({ getTelegram: () => sdk, fetch: async () => { calls++; return response(401, {}); } });
  const results = await Promise.allSettled([client.authenticate(), client.authenticate(), client.request('/wallet')]);
  assert.ok(results.every(result => result.status === 'rejected')); assert.equal(calls, 1);
  await assert.rejects(client.retryAuthentication()); assert.equal(calls, 2);
});

test('идемпотентный GET повторяется один раз после сетевого сбоя', async () => {
  let calls = 0;
  const client = createClient({ retryDelayMs: 0, getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') return response(200, { access_token: jwt() });
    calls++;
    if (calls === 1) throw new Error('connection reset');
    return response(200, { ok: true });
  } });
  const data = await client.request('/cases');
  assert.equal(calls, 2);
  assert.deepEqual(data, { ok: true });
});

test('mutating POST после сетевого сбоя сам не повторяется', async () => {
  let calls = 0;
  const client = createClient({ getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') return response(200, { access_token: jwt() });
    calls++;
    throw new Error('connection reset');
  } });
  await assert.rejects(client.request('/games/crash/start', { method: 'POST' }), error => error.code === 'network_unavailable');
  assert.equal(calls, 1);
});

test('авторизация повторяется после сетевого сбоя один раз', async () => {
  let authCalls = 0;
  const client = createClient({ retryDelayMs: 0, getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') {
      authCalls++;
      if (authCalls === 1) throw new Error('connection reset');
      return response(200, { access_token: jwt() });
    }
    return response(200, { ok: true });
  } });
  const data = await client.request('/cases');
  assert.equal(authCalls, 2);
  assert.deepEqual(data, { ok: true });
});

test('сетевой сбой авторизации не кэшируется как отказ Telegram', async () => {
  let authCalls = 0;
  const client = createClient({ retryDelayMs: 0, getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') { authCalls++; throw new Error('connection reset'); }
    return response(200, {});
  } });
  await assert.rejects(client.request('/cases'), error => error.code === 'network_unavailable');
  await assert.rejects(client.request('/cases'), error => error.code === 'network_unavailable');
  assert.equal(authCalls, 8);
});

test('холодный старт: несколько 503 подряд, затем успех — клиент дожидается', async () => {
  let calls = 0;
  const client = createClient({ retryDelayMs: 0, getTelegram: () => sdk, fetch: async path => {
    if (path === '/auth/telegram') return response(200, { access_token: jwt() });
    calls++;
    if (calls < 4) return response(503, { detail: 'service_unavailable' });
    return response(200, { ok: true });
  } });
  const data = await client.request('/cases');
  assert.equal(calls, 4);
  assert.deepEqual(data, { ok: true });
});

test('перед авторизацией клиент будит API прямым запросом в браузерном режиме', async () => {
  const calls = [];
  const client = createClient({ retryDelayMs: 0, wakeOrigin: 'https://windrop-api.onrender.com',
    getTelegram: () => sdk, fetch: async (path, options) => {
      calls.push([path, options && options.mode]);
      return path === '/auth/telegram' ? response(200, { access_token: jwt() }) : response(200, {});
    } });
  await client.request('/cases');
  assert.deepEqual(calls[0], ['https://windrop-api.onrender.com/health/live', 'no-cors']);
  assert.equal(calls.filter(call => call[0].endsWith('/health/live')).length, 1);
});

test('без wakeOrigin прямых запросов в Render нет', async () => {
  const calls = [];
  const client = createClient({ retryDelayMs: 0, getTelegram: () => sdk, fetch: async path => {
    calls.push(path);
    return path === '/auth/telegram' ? response(200, { access_token: jwt() }) : response(200, {});
  } });
  await client.request('/cases');
  assert.deepEqual(calls, ['/auth/telegram', '/cases']);
});
