/* Авторизация только через Telegram SDK; JWT остаётся в памяти вкладки. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WindropApi = api;
})(globalThis, function () {
  'use strict';

  const MESSAGES = {
    telegram_required: 'Abra a Mini App pelo bot principal no Telegram usando /start.',
    invalid_telegram_auth: 'A sessão do Telegram expirou ou não pertence a este bot. Abra novamente pelo bot principal.',
    auth_bot_invalid: 'O link deste bot é inválido. Abra novamente pelo bot principal no Telegram.',
    session_changed: 'A conta ou o bot mudou. Feche e abra a Mini App novamente antes de continuar.',
    network_timeout: 'O servidor demorou a responder. O resultado ainda não foi confirmado.',
    network_unavailable: 'Não foi possível conectar ao servidor. O resultado ainda não foi confirmado.',
    service_unavailable: 'Serviço indisponível no momento. Nenhuma confirmação foi recebida.',
    invalid_response: 'O serviço ainda não oferece uma resposta segura. Tente mais tarde.',
    request_rejected: 'A solicitação não foi aceita. Confira os dados e tente novamente.',
    access_denied: 'Esta ação não está disponível para esta conta. Abra o bot principal no Telegram.',
    rate_limited: 'Muitas solicitações. Aguarde antes de tentar novamente.',
    payments_disabled: 'Os pagamentos estão desativados.',
    method_disabled: 'Esta forma de pagamento está indisponível.',
    provider_not_configured: 'Esta forma de pagamento ainda não está configurada.',
    provider_unavailable: 'O provedor de pagamento está indisponível.',
    stars_transport_unavailable: 'A fatura Stars está indisponível. Abra o bot principal no Telegram.',
    quote_expired: 'A cotação expirou. Solicite uma nova prévia antes de confirmar.',
    quote_not_found: 'A cotação não está disponível. Solicite uma nova prévia.',
    invalid_coins: 'Informe uma quantidade inteira de pelo menos 100 moedas.',
    amount_out_of_range: 'A quantidade está fora do limite permitido.',
    idempotency_conflict: 'Esta solicitação já está em análise. Não crie outra tentativa de pagamento.',
    giftcards_disabled: 'A troca por gift cards está desativada.',
    disabled: 'A troca por gift cards está desativada ou ainda não foi configurada.',
    storage_not_configured: 'O serviço de gift cards ainda não está configurado.',
    no_inventory: 'Este gift card está sem estoque. Nenhuma moeda foi gasta nesta solicitação.',
    not_found: 'A solicitação não foi encontrada. Consulte o bot principal antes de tentar novamente.',
    owner_mismatch: 'Esta solicitação não pertence à conta autenticada.',
    ledger_error: 'A troca precisa de revisão. Não repita o pedido; consulte o bot principal.',
    storage_error: 'Não foi possível confirmar a troca com segurança. Consulte o bot principal.',
    sku_unavailable: 'Este gift card não está disponível. Nenhuma nova troca foi confirmada.',
    out_of_stock: 'Este gift card está sem estoque. Nenhuma nova troca foi confirmada.',
    insufficient_balance: 'Saldo de ouro insuficiente para esta troca.',
    telegram_auth_required: 'Abra a Mini App pelo bot principal no Telegram usando /start.',
    invalid_request: 'Confira os dados da solicitação antes de continuar.',
  };

  // Холодный старт Render free идёт до минуты: запрос упирается в таймаут или
  // в 503 от прокси. Идемпотентные запросы и авторизация повторяются один раз.
  const NETWORK_RETRY_CODES = new Set(['network_timeout', 'network_unavailable', 'service_unavailable']);

  class ApiError extends Error {
    constructor(code, status = 0) {
      const known = Object.hasOwn(MESSAGES, code) ? code : 'request_rejected';
      super(MESSAGES[known]);
      this.name = 'ApiError';
      this.code = known;
      this.status = status;
      this.retryable = status >= 500 || ['network_timeout', 'network_unavailable', 'invalid_response'].includes(known);
    }
  }

  function errorMessage(error) {
    return error instanceof ApiError ? error.message : MESSAGES.service_unavailable;
  }

  function authBotId(search = '') {
    const values = new URLSearchParams(search).getAll('auth_bot_id');
    if (!values.length) return undefined;
    if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) throw new ApiError('auth_bot_invalid');
    const value = Number(values[0]);
    if (!Number.isSafeInteger(value) || value <= 0) throw new ApiError('auth_bot_invalid');
    return value;
  }

  // Эти claims используются ТОЛЬКО для изоляции локального состояния, не для проверки доступа.
  function tokenContext(token) {
    try {
      const part = token.split('.')[1];
      if (!part || part.length > 8192) return null;
      const claims = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/')));
      if (!/^[1-9]\d{0,19}$/.test(claims.sub) || typeof claims.sub !== 'string') return null;
      if (!['primary', 'managed'].includes(claims.scope)) return null;
      if (!Number.isSafeInteger(claims.auth_bot_id) || claims.auth_bot_id <= 0) return null;
      return { account: claims.sub, bot: claims.auth_bot_id, scope: claims.scope,
        key: `${claims.scope}:bot:${claims.auth_bot_id}:account:${claims.sub}` };
    } catch (_) { return null; }
  }

  function responseError(status, data) {
    const detail = data && data.detail;
    const code = typeof detail === 'string' ? detail : detail && detail.code || data && data.code;
    if (typeof code === 'string' && Object.hasOwn(MESSAGES, code)) return new ApiError(code, status);
    const fallback = status === 401 ? 'invalid_telegram_auth' : status === 403 ? 'access_denied'
      : status === 429 ? 'rate_limited' : status === 404 || status >= 500 ? 'service_unavailable' : 'request_rejected';
    return new ApiError(fallback, status);
  }

  function createClient({ fetch: transport = globalThis.fetch.bind(globalThis), origin = '', search = '',
    getTelegram = () => globalThis.Telegram && globalThis.Telegram.WebApp,
    storage, timeoutMs = 45000 } = {}) {
    let token = '', context = null, authPromise = null, authFailure = null;
    // Старый общий ключ нельзя переносить между аккаунтами/ботами. Новые JWT не сохраняются.
    try { storage && storage.removeItem('jwt'); } catch (_) {}

    async function send(path, options = {}) {
      if (!/^\/(?!\/)/.test(path)) throw new ApiError('invalid_request');
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), timeoutMs);
      try {
        const response = await transport(origin + path, { ...options, signal: abort.signal,
          redirect: 'error', cache: 'no-store', credentials: 'same-origin' });
        let data = null;
        try { data = await response.json(); }
        catch (_) {
          if (response.ok) throw new ApiError('invalid_response', response.status);
        }
        if (!response.ok) throw responseError(response.status, data);
        return data;
      } catch (error) {
        if (error instanceof ApiError) throw error;
        throw new ApiError(abort.signal.aborted ? 'network_timeout' : 'network_unavailable');
      } finally { clearTimeout(timer); }
    }

    function authenticate() {
      if (authFailure) return Promise.reject(authFailure);
      if (token) return Promise.resolve(token);
      if (authPromise) return authPromise;
      authPromise = (async () => {
        const botId = authBotId(search);
        const sdk = getTelegram();
        const initData = sdk && sdk.initData;
        if (typeof initData !== 'string' || !initData.trim() || initData.length > 16384) {
          throw new ApiError('telegram_required', 401);
        }
        const body = { init_data: initData };
        if (botId !== undefined) body.auth_bot_id = botId;
        const options = { method: 'POST',
          headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
        let data;
        try {
          data = await send('/auth/telegram', options);
        } catch (error) {
          // ensure_telegram_user идемпотентен, поэтому сетевой сбой можно повторить.
          if (!(error instanceof ApiError) || !NETWORK_RETRY_CODES.has(error.code)) throw error;
          data = await send('/auth/telegram', options);
        }
        if (!data || typeof data.access_token !== 'string' || !data.access_token || data.access_token.length > 8192) {
          throw new ApiError('invalid_response');
        }
        const nextContext = tokenContext(data.access_token);
        if (nextContext && botId !== undefined && nextContext.bot !== botId) throw new ApiError('session_changed', 401);
        if (context && (!nextContext || context.key !== nextContext.key)) throw new ApiError('session_changed', 401);
        context = nextContext;
        token = data.access_token;
        return token;
      })().catch(error => {
        token = '';
        const failure = error instanceof ApiError ? error : new ApiError('invalid_telegram_auth', 401);
        // Сетевой сбой не фиксируем как auth-failure: иначе холодный старт Render
        // выглядит как «неправильный Telegram» и повторная авторизация заблокирована.
        if (!NETWORK_RETRY_CODES.has(failure.code)) authFailure = failure;
        throw failure;
      }).finally(() => { authPromise = null; });
      return authPromise;
    }

    async function request(path, options = {}) {
      await authenticate();
      const method = String((options && options.method) || 'GET').toUpperCase();
      // Повторяем только идемпотентные запросы: POST с игрой или обменом монет
      // backend сам защищает идемпотентностью, но лишний повтор всё равно не нужен.
      let networkRetries = method === 'GET' || method === 'HEAD' ? 1 : 0;
      let authRetries = 1;
      for (let attempt = 0; attempt < 3; attempt++) {
        const sentToken = token;
        try {
          return await send(path, { ...options,
            headers: { ...options.headers, Authorization: 'Bearer ' + sentToken } });
        } catch (error) {
          if (error.status === 401) {
            if (authRetries <= 0) {
              token = '';
              authFailure = new ApiError('invalid_telegram_auth', 401);
              throw authFailure;
            }
            authRetries -= 1;
            // Параллельный 401 от старого JWT не запускает новую авторизацию после её завершения.
            if (token === sentToken) token = '';
            await authenticate();
            continue;
          }
          if (networkRetries > 0 && error instanceof ApiError && NETWORK_RETRY_CODES.has(error.code)) {
            networkRetries -= 1;
            continue;
          }
          throw error;
        }
      }
      throw new ApiError('service_unavailable');
    }

    return {
      request, authenticate,
      getContext: () => context && context.key,
      getChannel: () => context && ['primary', 'managed'].includes(context.scope) || getTelegram()?.initData ? 'telegram' : 'web',
      retryAuthentication() { authFailure = null; return authenticate(); },
    };
  }

  return { ApiError, errorMessage, authBotId, tokenContext, createClient };
});
