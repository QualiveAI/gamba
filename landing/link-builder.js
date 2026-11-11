/* Чистый построитель ссылок: никаких запросов, DOM, хранилища или секретов. */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    Object.defineProperty(root, "WindropLinks", { value: api });
  }
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";

  const MAX_QUERY_LENGTH = 1024;
  const MAX_QUERY_PARAMETERS = 20;
  const MAX_UTM_VALUE_LENGTH = 32;
  const UTM_KEYS = Object.freeze([
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"
  ]);
  const CAMPAIGNS = Object.freeze(["organic", "telegram", "social", "creator", "launch-br"]);
  const SOURCE_CAMPAIGNS = Object.freeze({
    telegram: "telegram",
    instagram: "social",
    facebook: "social",
    youtube: "social",
    tiktok: "social",
    creator: "creator"
  });
  const USERNAME = /^[A-Za-z][A-Za-z0-9_]{4,31}$/;
  const UTM_VALUE = /^[a-z0-9][a-z0-9_-]{0,31}$/i;
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

  function normalizeUsername(value, requireBot = false) {
    if (typeof value !== "string" || value.length > 33) return "";
    const username = value.startsWith("@") ? value.slice(1) : value;
    if (username.trim() !== username || !USERNAME.test(username)) return "";
    if (requireBot && !/bot$/i.test(username)) return "";
    return username;
  }

  function readUtm(search = "") {
    const empty = () => Object.freeze({});
    if (typeof search !== "string" || search.length > MAX_QUERY_LENGTH) return empty();
    if ((search && !search.startsWith("?")) || search.includes("#")) return empty();

    const accepted = {};
    const seen = new Set();
    const duplicated = new Set();
    let count = 0;
    for (const [key, raw] of new URLSearchParams(search)) {
      count += 1;
      if (count > MAX_QUERY_PARAMETERS) return empty();
      if (!UTM_KEYS.includes(key)) continue;
      if (seen.has(key)) {
        duplicated.add(key);
        delete accepted[key];
        continue;
      }
      seen.add(key);
      if (duplicated.has(key) || raw.length > MAX_UTM_VALUE_LENGTH) continue;
      // Не обрезаем и не нормализуем Unicode: неизвестное значение не станет разрешённым.
      if (raw.trim() !== raw || !UTM_VALUE.test(raw)) continue;
      accepted[key] = raw.toLowerCase();
    }
    return Object.freeze(accepted);
  }

  function resolveCampaign(search = "") {
    const utm = readUtm(search);
    if (CAMPAIGNS.includes(utm.utm_campaign)) return utm.utm_campaign;
    if (own(SOURCE_CAMPAIGNS, utm.utm_source)) return SOURCE_CAMPAIGNS[utm.utm_source];
    return "organic";
  }

  function buildStartPayload(search = "") {
    // Контракт бота: lp_<slug>, <= 32 ASCII-символов. Только фиксированные коды выше.
    return `lp_${resolveCampaign(search)}`;
  }

  function configValue(config, key) {
    if (!config || typeof config !== "object" || Array.isArray(config) || !own(config, key)) return "";
    return config[key];
  }

  function buildTelegramLink(config, search = "") {
    const username = normalizeUsername(configValue(config, "botUsername"), true);
    if (!username) return "";
    return `https://t.me/${username}?start=${buildStartPayload(search)}`;
  }

  function buildSupportLink(config) {
    const username = normalizeUsername(configValue(config, "supportUsername"));
    if (!username) return "";
    return `https://t.me/${username}`;
  }

  return Object.freeze({
    MAX_QUERY_LENGTH,
    MAX_QUERY_PARAMETERS,
    MAX_UTM_VALUE_LENGTH,
    UTM_KEYS,
    CAMPAIGNS,
    normalizeUsername,
    readUtm,
    resolveCampaign,
    buildStartPayload,
    buildTelegramLink,
    buildSupportLink
  });
});
