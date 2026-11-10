// WINDROP mini-app: навигация, deep-links, инициализация экранов
try {
  const tg = (window.Telegram && window.Telegram.WebApp) || { ready() {}, expand() {}, initData: "" };
  tg.ready(); tg.expand();
  let jwtToken = sessionStorage.getItem("jwt") || "";

  async function api(path, options = {}) {
    if (!jwtToken) {
      const res = await fetch(window.location.origin + "/auth/telegram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ init_data: tg.initData || "" }),
      });
      if (!res.ok) throw new Error("auth failed");
      const data = await res.json();
      jwtToken = data.access_token;
      sessionStorage.setItem("jwt", jwtToken);
    }
    const headers = Object.assign({ Authorization: "Bearer " + jwtToken }, options.headers || {});
    const res = await fetch(window.location.origin + path, Object.assign({}, options, { headers }));
    if (res.status === 401) {
      jwtToken = "";
      sessionStorage.removeItem("jwt");
      return api(path, options); // повторная авторизация
    }
    if (!res.ok) throw new Error((await res.text()).slice(0, 140));
    return res.json();
  }
  window.api = api;

  // ---------- Навигация ----------
  function showScreen(name) {
    document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
    const el = document.getElementById("screen-" + name);
    if (el) el.classList.add("active");
    document.querySelectorAll(".bn-item").forEach((b) =>
      b.classList.toggle("active", b.dataset.screen === name)
    );
    window.scrollTo(0, 0);
    if (name === "saldo") initSaldo();
    if (name === "mochila" && window.loadInventory) window.loadInventory();
    if (name === "upgrade" && window.fillUpgradeSelect) window.fillUpgradeSelect();
    if (name === "cases" && window.loadCases) window.loadCases();
  }
  window.showScreen = showScreen;

  // Перейти на Saldo и проскроллить к блоку (blk-deposito / blk-saque)
  function gotoSaldo(blockId) {
    showScreen("saldo");
    setTimeout(() => {
      const blk = document.getElementById(blockId);
      if (blk) blk.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 60);
  }
  window.gotoSaldo = gotoSaldo;

  // Под-вкладки игр
  function switchGame(name) {
    document.querySelectorAll(".game-card").forEach((b) =>
      b.classList.toggle("active", b.dataset.g === name)
    );
    document.querySelectorAll(".game-pane").forEach((g) => (g.hidden = g.id !== "game-" + name));
  }
  window.switchGame = switchGame;

  function setDep(v) {
    const el = document.getElementById("dep-amount");
    if (el) el.value = String((parseInt(el.value, 10) || 0) + v);
  }
  window.setDep = setDep;

  async function initSaldo() {
    if (window.renderWallet) window.renderWallet();
    if (window.loadDepositMethods) window.loadDepositMethods();
    if (window.loadDaily) window.loadDaily();
    if (window.loadReferrals) window.loadReferrals();
    if (window.updateWithdrawPreview) window.updateWithdrawPreview();
  }

  // ---------- White-label бренд ----------
  async function applyTenantBrand() {
    try {
      const t = await api("/meta/tenant");
      if (t.brand && t.brand.name) document.title = t.brand.name;
      if (t.brand && t.brand.primary_color)
        document.documentElement.style.setProperty("--primary-color", t.brand.primary_color);
      const header = document.querySelector("header h1");
      if (header && t.brand && t.brand.name) header.textContent = t.brand.name;
    } catch (e) { /* дефолтный бренд */ }
  }

  function initApp() {
    document.querySelectorAll(".bn-item").forEach((b) =>
      b.addEventListener("click", () => showScreen(b.dataset.screen))
    );
    applyTenantBrand();
    if (window.renderWallet) window.renderWallet();
    if (window.loadCases) window.loadCases();
    // Deep-link из бота: start_param или #hash (deposit/withdraw -> блоки Saldo)
    const sp = tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    const hash = (window.location.hash || "").replace("#", "");
    const target = sp || hash;
    const aliases = { deposit: "blk-deposito", deposito: "blk-deposito", withdraw: "blk-saque", saque: "blk-saque" };
    if (target && aliases[target]) gotoSaldo(aliases[target]);
    else if (target && document.getElementById("screen-" + target)) showScreen(target);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
} catch (e) {
  console.error("app.js error:", e.message);
}
