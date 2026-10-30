const tg = window.Telegram.WebApp;
tg.ready(); tg.expand();
let jwtToken = sessionStorage.getItem("jwt") || "";
async function api(path, options = {}) {
  if (!jwtToken) {
    const res = await fetch(window.location.origin.replace(/:\d+$/, "") + ":8000" + "/auth/telegram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ init_data: tg.initData || "" }) });
    const data = await res.json();
    jwtToken = data.access_token;
    sessionStorage.setItem("jwt", jwtToken);
  }
  const API_BASE = window.location.origin.replace(/:\d+$/, "") + ":8000";
  const headers = Object.assign({ "Authorization": "Bearer " + jwtToken }, options.headers || {});
  const res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  const el = document.getElementById("screen-" + name);
  if (el) el.classList.add("active");
  if (name === "deposit" && window.loadDepositMethods) window.loadDepositMethods();
  if (name === "wallet" && window.renderWallet) window.renderWallet();
  if (name === "withdraw" && window.loadWithdrawLimits) window.loadWithdrawLimits();
  if (name === "upgrade" && window.loadUpgradeCatalog) window.loadUpgradeCatalog();
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showScreen(b.dataset.screen)));
window.api = api;
window.showScreen = showScreen;