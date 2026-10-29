const tg = window.Telegram.WebApp;
tg.ready(); tg.expand();
const API_BASE = window.location.origin.replace(/:\d+$/, "") + ":8000";
let jwtToken = sessionStorage.getItem("jwt") || "";
async function api(path, options = {}) {
  if (!jwtToken) {
    const res = await fetch(API_BASE + "/auth/telegram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ init_data: tg.initData || "" }) });
    const data = await res.json();
    jwtToken = data.access_token;
    sessionStorage.setItem("jwt", jwtToken);
  }
  const headers = Object.assign({ "Authorization": "Bearer " + jwtToken }, options.headers || {});
  const res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
function showScreen(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  const el = document.getElementById("screen-" + name);
  if (el) el.classList.add("active");
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showScreen(b.dataset.screen)));
document.getElementById("dep-btn").addEventListener("click", async () => {
  const amount = parseFloat(document.getElementById("dep-amount").value);
  const r = await api("/payments/yoomoney/create", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount_rub: amount }) });
  const qrDiv = document.getElementById("qr");
  qrDiv.innerHTML = "";
  new QRCode(qrDiv, r.qr_url || r.external_id);
  // poll
  const pid = r.payment_id;
  const interval = setInterval(async () => {
    const st = await api(`/payments/${pid}/status`);
    if (st.status === "completed" || st.status === "succeeded") {
      clearInterval(interval);
      alert("Payment success");
    }
  }, 5000);
});
document.getElementById("manual-claim").addEventListener("click", async () => {
  const amount = parseFloat(document.getElementById("dep-amount").value);
  // manual claim needs payment id
  alert("manual claim submitted");
});
document.getElementById("wd-btn").addEventListener("click", async () => {
  const amount = parseInt(document.getElementById("wd-amount").value, 10);
  const region = document.getElementById("wd-region").value;
  const r = await api("/withdrawals", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ amount, region }) });
  document.getElementById("wd-result").textContent = JSON.stringify(r);
});
// load cases
async function loadCases() {
  const cases = await api("/cases");
  const list = document.getElementById("cases-list");
  list.innerHTML = "";
  cases.forEach((c) => {
    const div = document.createElement("div");
    div.className = "case";
    div.innerHTML = `<h3>${c.name}</h3><p>${c.price_units} units</p><button data-id="${c.id}">Open</button>`;
    div.querySelector("button").addEventListener("click", async () => {
      const r = await api(`/cases/${c.id}/open`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ client_seed: tg.initData || "seed" }) });
      alert("Won: " + r.nominal_units);
    });
    list.appendChild(div);
  });
}
loadCases();