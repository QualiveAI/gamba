"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync, existsSync, readdirSync, statSync } = require("node:fs");
const { resolve, join, relative } = require("node:path");
const vm = require("node:vm");
const links = require("../link-builder.js");
const root = resolve(__dirname, "..");
const html = readFileSync(join(root, "index.html"), "utf8");
const css = readFileSync(join(root, "styles.css"), "utf8");
const app = readFileSync(join(root, "app.js"), "utf8");
// Синтетические значения существуют только в тестах; сеть и Telegram не вызываются.
const fixtureConfig = Object.freeze({ botUsername: "LandingFixture_bot", supportUsername: "LandingFixtureHelp" });

function expectTrustedUrl(href, username, payload) {
  const url = new URL(href);
  assert.equal(url.origin, "https://t.me");
  assert.equal(url.pathname, `/${username}`);
  assert.equal(url.username, "");
  assert.equal(url.password, "");
  assert.equal(url.hash, "");
  assert.deepEqual([...url.searchParams.keys()], payload ? ["start"] : []);
  if (payload) assert.equal(url.searchParams.get("start"), payload);
}

test("Публичный конфиг не содержит получателей по умолчанию", () => {
  const context = { window: {} };
  vm.runInNewContext(readFileSync(join(root, "config.js"), "utf8"), context);
  assert.equal(context.window.WINDROP_CONFIG.botUsername, "");
  assert.equal(context.window.WINDROP_CONFIG.supportUsername, "");
  assert.equal(Object.isFrozen(context.window.WINDROP_CONFIG), true);
  assert.equal(links.buildTelegramLink(context.window.WINDROP_CONFIG), "");
  assert.equal(links.buildSupportLink(context.window.WINDROP_CONFIG), "");
});

test("Пустые, отсутствующие и неверные конфиги закрывают переход", () => {
  const invalid = [null, undefined, false, "", [], {}, { botUsername: 12 }, { botUsername: {} }, { botUsername: "" }];
  for (const config of invalid) {
    assert.equal(links.buildTelegramLink(config, "?utm_campaign=telegram"), "");
    assert.equal(links.buildSupportLink(config), "");
  }
  assert.equal(links.buildTelegramLink(Object.create(fixtureConfig)), "");
  assert.equal(links.buildSupportLink(Object.create(fixtureConfig)), "");
});

test("Username поддерживает только ASCII, длину 5–32 и один необязательный @", () => {
  assert.equal(links.normalizeUsername("Ab_bot", true), "Ab_bot");
  assert.equal(links.normalizeUsername("@LandingFixture_bot", true), "LandingFixture_bot");
  assert.equal(links.normalizeUsername("@LandingFixtureHelp"), "LandingFixtureHelp");
  assert.equal(links.normalizeUsername("A" + "a".repeat(28) + "bot", true).length, 32);
  assert.equal(links.normalizeUsername("@" + "A" + "a".repeat(28) + "bot", true).length, 32);
  assert.equal(links.normalizeUsername("A" + "a".repeat(29) + "bot", true), "");
  assert.equal(links.normalizeUsername("Abot", true), "");
  assert.equal(links.normalizeUsername("valid_name", true), "");
  assert.equal(links.normalizeUsername("valid_name"), "valid_name");
  assert.equal(links.normalizeUsername("UPPER_BOT", true), "UPPER_BOT");
});

test("Username отвергает URL, редиректы, HTML, Unicode, переносы и секреты", () => {
  const invalid = [
    "https://t.me/LandingFixture_bot", "//evil.invalid/attack_bot", "javascript:alert(1)",
    "data:text/html,attack_bot", "LandingFixture_bot?start=evil", "LandingFixture_bot#evil",
    "LandingFixture_bot/else", "LandingFixture_bot\\evil", "evil.invalid@LandingFixture_bot",
    "@@LandingFixture_bot", " LandingFixture_bot", "LandingFixture_bot ", "LandingFixture_bot\n",
    "LandingFixture_bot\r", "LandingFixture_bot\t", "LandingFixture_bot\u2028", "LandingFixture_bot\u2029",
    "LandingFixture_bot\u0000", "LandingFixture_bot%0a", "<script>bad_bot</script>",
    "a\" onclick=\"evil_bot", "1bad_bot", "_bad_bot", "bad-name_bot", "чужой_bot",
    "ｌａｎｄｉｎｇ_bot", "123456:secret", "a".repeat(5000)
  ];
  for (const name of invalid) {
    assert.equal(links.buildTelegramLink({ botUsername: name }), "", name);
    assert.equal(links.buildSupportLink({ supportUsername: name }), "", name);
  }
});

test("Основной бот и поддержка строятся только на https://t.me", () => {
  expectTrustedUrl(links.buildTelegramLink(fixtureConfig), fixtureConfig.botUsername, "lp_organic");
  expectTrustedUrl(links.buildSupportLink(fixtureConfig), fixtureConfig.supportUsername);
  assert.equal(links.buildTelegramLink({ botUsername: "@LandingFixture_bot" }), links.buildTelegramLink(fixtureConfig));
  expectTrustedUrl(links.buildTelegramLink({ ...fixtureConfig, url: "https://evil.invalid", redirect: "https://evil.invalid" }), fixtureConfig.botUsername, "lp_organic");
});

test("Список UTM ограничен пятью ключами и не передаёт чужие параметры", () => {
  const result = links.readUtm("?utm_source=Instagram&utm_medium=Paid_Social&utm_campaign=launch-br&utm_content=Hero-A&utm_term=adult&username=attacker_bot&token=secret&redirect=https://evil.invalid&start=ref_5");
  assert.deepEqual(result, { utm_source: "instagram", utm_medium: "paid_social", utm_campaign: "launch-br", utm_content: "hero-a", utm_term: "adult" });
  assert.equal(Object.isFrozen(result), true);
  assert.equal(links.buildStartPayload("?utm_campaign=launch-br&start=ref_5"), "lp_launch-br");
});

test("URL-декодирование выполняется один раз; латинские percent-encoded UTM допустимы", () => {
  assert.equal(links.buildStartPayload("?%75tm_campaign=%6c%61%75%6e%63%68%2d%62%72"), "lp_launch-br");
  assert.equal(links.buildStartPayload("?utm_campaign=%2574elegram"), "lp_organic");
  assert.deepEqual(links.readUtm("?utm_campaign=launch+br&utm_source=paid%20social"), {});
  assert.deepEqual(links.readUtm("?utm_campaign=%E0%A4%A&utm_source=%zz"), {});
});

test("UTM инъекции и контрольные символы отбрасываются, а не обрезаются", () => {
  const invalid = [
    "<img src=x onerror=alert(1)>", "<script>alert(1)</script>", "telegram\n", "telegram\r",
    "telegram\u2028", "telegram\u2029", "telegram\u0000", " telegram", "telegram ",
    "telegram/../../evil", "telegram?x=1", "telegram&start=ref_1", "telegram#x",
    "https://evil.invalid", "'onclick='bad", "a+b", "a@b.com", "ТЕЛЕГРАМ", "ＬＡＵＮＣＨ", "Key"
  ];
  for (const input of invalid) {
    const query = `?utm_campaign=${encodeURIComponent(input)}`;
    assert.deepEqual(links.readUtm(query), {}, JSON.stringify(input));
    assert.equal(links.buildStartPayload(query), "lp_organic");
  }
});

test("Каждое UTM-значение ограничено 32 декодированными символами", () => {
  assert.equal(links.readUtm("?utm_content=" + "a".repeat(32)).utm_content.length, 32);
  assert.deepEqual(links.readUtm("?utm_content=" + "a".repeat(33)), {});
  assert.equal(links.buildStartPayload("?utm_campaign=telegram" + "a".repeat(40)), "lp_organic");
  assert.equal(links.readUtm("?utm_content=" + "%61".repeat(32)).utm_content.length, 32);
  assert.deepEqual(links.readUtm("?utm_content=" + "%61".repeat(33)), {});
});

test("Общий query и количество параметров ограничены до разбора атрибуции", () => {
  const prefix = "?utm_campaign=telegram&ignored=";
  const exact = prefix + "x".repeat(links.MAX_QUERY_LENGTH - prefix.length);
  assert.equal(exact.length, 1024);
  assert.equal(links.buildStartPayload(exact), "lp_telegram");
  assert.equal(links.buildStartPayload(exact + "x"), "lp_organic");
  const atLimit = "?utm_campaign=telegram" + "&x=1".repeat(19);
  assert.equal(links.buildStartPayload(atLimit), "lp_telegram");
  assert.equal(links.buildStartPayload(atLimit + "&x=1"), "lp_organic");
  assert.equal(links.buildStartPayload("?utm_campaign=telegram" + "&x=1".repeat(50000)), "lp_organic");
});

test("Повтор одного UTM-ключа аннулирует весь этот ключ", () => {
  assert.deepEqual(links.readUtm("?utm_campaign=telegram&utm_campaign=creator"), {});
  assert.equal(links.buildStartPayload("?utm_campaign=telegram&%75tm_campaign=telegram"), "lp_organic");
  assert.equal(links.buildStartPayload("?utm_campaign=telegram&utm_campaign=creator&utm_campaign=social"), "lp_organic");
  assert.equal(links.buildStartPayload("?utm_campaign=telegram&utm_campaign=creator&utm_source=instagram"), "lp_social");
  assert.equal(links.buildStartPayload("?utm_source=telegram&utm_source=instagram"), "lp_organic");
});

test("Внешние URL, fragments и нестроковые входы не интерпретируются как query", () => {
  for (const input of [null, undefined, {}, [], 1, "utm_campaign=telegram", "https://evil.invalid/?utm_campaign=telegram", "?utm_campaign=telegram#hash"]) {
    assert.equal(links.buildStartPayload(input), "lp_organic");
  }
  assert.deepEqual(links.readUtm("?UTM_CAMPAIGN=telegram"), {});
});

test("Campaign-контракт содержит только пять согласованных lp-кодов", () => {
  assert.deepEqual(links.CAMPAIGNS, ["organic", "telegram", "social", "creator", "launch-br"]);
  for (const campaign of links.CAMPAIGNS) {
    const token = links.buildStartPayload(`?utm_campaign=${campaign}`);
    assert.equal(token, `lp_${campaign}`);
    assert.match(token, /^lp_[a-z0-9](?:[a-z0-9-]{0,27}[a-z0-9])?$/);
    assert.ok(Buffer.byteLength(token, "utf8") <= 32);
    expectTrustedUrl(links.buildTelegramLink(fixtureConfig, `?utm_campaign=${campaign}`), fixtureConfig.botUsername, token);
  }
  assert.equal(links.buildStartPayload("?utm_campaign=new-ad-campaign"), "lp_organic");
  assert.equal(links.buildStartPayload("?utm_campaign=ref_42"), "lp_organic");
});

test("Явная кампания имеет приоритет; source используется только из карты", () => {
  assert.equal(links.buildStartPayload("?utm_campaign=organic&utm_source=telegram"), "lp_organic");
  assert.equal(links.buildStartPayload("?utm_campaign=launch-br&utm_source=telegram"), "lp_launch-br");
  assert.equal(links.buildStartPayload("?utm_campaign=unknown&utm_source=telegram"), "lp_telegram");
  assert.equal(links.buildStartPayload("?utm_source=creator"), "lp_creator");
  for (const source of ["instagram", "facebook", "youtube", "tiktok"]) {
    assert.equal(links.buildStartPayload(`?utm_source=${source}`), "lp_social");
  }
  for (const source of ["google", "__proto__", "constructor", "toString", "telegram_bot"]) {
    assert.equal(links.buildStartPayload(`?utm_source=${source}`), "lp_organic");
  }
});

test("Полный query, рекламные метки и секреты не копируются в Telegram URL", () => {
  const query = "?utm_campaign=launch-br&utm_source=instagram&utm_medium=paid&utm_content=private&utm_term=secret&token=very-secret&redirect=https://evil.invalid&botUsername=attacker_bot&ref=123";
  const href = links.buildTelegramLink(fixtureConfig, query);
  assert.equal(href, "https://t.me/LandingFixture_bot?start=lp_launch-br");
  assert.doesNotMatch(href, /private|secret|redirect|attacker|ref=|utm_/);
});

test("Детерминированная проверка 1000 произвольных query сохраняет доверенный origin", () => {
  const fragments = ["telegram", "social", "launch-br", "%00", "%0a", "<script>", "https://evil.invalid", "&start=ref_9", "__proto__", "🔥", "a".repeat(35), "%2574elegram"];
  const allowed = new Set(links.CAMPAIGNS.map((campaign) => `lp_${campaign}`));
  for (let index = 0; index < 1000; index += 1) {
    const query = `?utm_campaign=${fragments[index % fragments.length]}&utm_source=${fragments[Math.floor(index / fragments.length) % fragments.length]}&redirect=${index}`;
    const token = links.buildStartPayload(query);
    assert.ok(allowed.has(token));
    expectTrustedUrl(links.buildTelegramLink(fixtureConfig, query), fixtureConfig.botUsername, token);
  }
});

test("Модуль доступен в браузерном режиме без Node и не меняется после загрузки", () => {
  const sandbox = { URLSearchParams };
  vm.runInNewContext(readFileSync(join(root, "link-builder.js"), "utf8"), sandbox);
  assert.equal(sandbox.WindropLinks.buildStartPayload("?utm_campaign=telegram"), "lp_telegram");
  assert.equal(Object.isFrozen(sandbox.WindropLinks), true);
  assert.equal(Object.getOwnPropertyDescriptor(sandbox, "WindropLinks").writable, false);
});

test("Все script, stylesheet и image ресурсы существуют внутри самостоятельного root", () => {
  const resources = [];
  for (const tag of html.matchAll(/<(?:script|img|link)\b[^>]*>/g)) {
    const attribute = /\b(?:src|href)="([^"]+)"/.exec(tag[0]);
    if (!attribute) continue;
    const path = attribute[1];
    assert.doesNotMatch(path, /^(?:https?:|\/|\.\.)/);
    assert.doesNotMatch(path, /frontend|node_modules/);
    const full = resolve(root, path);
    assert.ok(!relative(root, full).startsWith(".."));
    assert.ok(existsSync(full), path);
    resources.push(path);
  }
  assert.ok(resources.includes("config.js"));
  assert.ok(resources.includes("link-builder.js"));
  assert.ok(resources.includes("app.js"));
  assert.ok(resources.includes("styles.css"));
  assert.match(html, /<html lang="pt-BR">/);
});

test("Все внутренние ссылки и ARIA-ссылки ссылаются на уникальные ID", () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(ids.length, new Set(ids).size);
  for (const match of html.matchAll(/\bhref="#([^"]+)"/g)) assert.ok(ids.includes(match[1]), match[1]);
  for (const match of html.matchAll(/\b(?:aria-controls|aria-labelledby|aria-describedby)="([^"]+)"/g)) {
    for (const id of match[1].split(/\s+/)) assert.ok(ids.includes(id), id);
  }
  assert.equal((html.match(/<h1\b/g) || []).length, 1);
});

test("Базовая HTML-версия CTA имеет только локальные адреса и никаких получателей", () => {
  const ctas = [...html.matchAll(/<a\b[^>]*data-(?:telegram-cta|support-link)[^>]*>/g)];
  assert.ok(ctas.length >= 5);
  for (const [tag] of ctas) assert.match(tag, /href="#(?:acesso|suporte)"/);
  assert.doesNotMatch(html, /href="(?:https?:)?\/\//);
  assert.doesNotMatch(html, /@windrop_bot|@robloxcasebot|t\.me\//);
  assert.match(html, /Endereço do bot ainda não configurado/);
  assert.doesNotMatch(html, /\bDEMO\b|Demonstração|data-state="demo"/);
  assert.match(html, /<noscript>/);
});

test("Нет сетевых SDK, пикселей, хранилища, eval, вставки HTML и бесконечных анимаций", () => {
  const scripts = app + readFileSync(join(root, "config.js"), "utf8") + readFileSync(join(root, "link-builder.js"), "utf8");
  assert.doesNotMatch(scripts, /innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new Function|\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|localStorage|sessionStorage|document\.cookie|setInterval/);
  assert.doesNotMatch(css, /@import|@font-face|https?:\/\/|animation[^;]*infinite/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(css, /:focus-visible/);
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /name="referrer" content="no-referrer"/);
  assert.match(html, /name="robots" content="noindex, nofollow"/);
  assert.match(app, /noopener noreferrer/);
});

test("Дисклеймеры присутствуют, а визуальные примеры не выдают себя за реальные выплаты", () => {
  for (const copy of ["maiores de 18 anos", "Não é investimento", "perder todas as moedas", "conforme as regras", "Não é saque em dinheiro", "Sem vínculo, patrocínio ou endosso da Roblox", "Não é a versão jurídica final"]) {
    assert.ok(html.includes(copy), copy);
  }
  assert.match(html, /Managed Bots/);
  assert.match(html, /estoque/);
  assert.doesNotMatch(html, /<form\b|<input\b/);
});

test("Размер используемых ассетов ограничен; прозрачные логотипы скопированы без изменения", () => {
  const assets = readdirSync(join(root, "assets"));
  assert.deepEqual(assets.sort(), ["cover-blox.webp", "cover-mm2.webp", "cover-rivals.webp", "logo-mark.png", "logo-mark.webp", "windrop-symbol.png", "windrop-symbol.webp"].sort());
  const bytes = assets.reduce((sum, file) => sum + statSync(join(root, "assets", file)).size, 0);
  assert.ok(bytes < 800 * 1024, `Assets: ${bytes}`);
  for (const name of ["windrop-symbol.webp", "logo-mark.webp"]) {
    const file = readFileSync(join(root, "assets", name));
    assert.equal(file.subarray(8, 12).toString(), "WEBP");
    const source = resolve(root, "..", "frontend", "assets", name);
    if (existsSync(source)) assert.deepEqual(file, readFileSync(source));
  }
});
