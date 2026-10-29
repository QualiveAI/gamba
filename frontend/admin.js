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
async function loadWithdrawals() {
  const status = document.getElementById("wd-status").value;
  const q = status ? "?status=" + encodeURIComponent(status) : "";
  const rows = await api("/admin/withdrawals" + q);
  const tbody = document.querySelector("#wd-table tbody");
  tbody.innerHTML = "";
  rows.forEach((w) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${w.id}</td><td>${w.user_id}</td><td>${w.amount_units}</td><td>${w.status}</td><td></td>`;
    const actions = tr.querySelector("td:last-child");
    if (w.status === "pending" || w.status === "frozen") {
      const approve = document.createElement("button");
      approve.textContent = "Approve";
      approve.addEventListener("click", async () => { await api(`/admin/withdrawals/${w.id}/approve`, { method: "POST" }); loadWithdrawals(); });
      const reject = document.createElement("button");
      reject.textContent = "Reject";
      reject.addEventListener("click", async () => { await api(`/admin/withdrawals/${w.id}/reject?reason=rejected`, { method: "POST" }); loadWithdrawals(); });
      actions.appendChild(approve);
      actions.appendChild(reject);
    }
    if (w.status === "frozen") {
      const unfreeze = document.createElement("button");
      unfreeze.textContent = "Unfreeze";
      unfreeze.addEventListener("click", async () => { await api(`/admin/withdrawals/${w.id}/unfreeze`, { method: "POST" }); loadWithdrawals(); });
      actions.appendChild(unfreeze);
    }
    tbody.appendChild(tr);
  });
}
document.getElementById("wd-status").addEventListener("change", loadWithdrawals);
async function loadGiftReviews() {
  const rows = await api("/admin/gift-reviews");
  const tbody = document.querySelector("#gift-table tbody");
  tbody.innerHTML = "";
  rows.forEach((g) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${g.id}</td><td>${g.user_id}</td><td>${g.gift_id}</td><td>${g.status}</td><td>${g.price_rub || ""}</td><td></td>`;
    const actions = tr.querySelector("td:last-child");
    if (g.status !== "credited") {
      const btn = document.createElement("button");
      btn.textContent = "Set price";
      btn.addEventListener("click", async () => {
        const price = parseFloat(prompt("Price RUB"));
        await api(`/admin/gift-reviews/${g.id}/set-price`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ price_rub: price }) });
        loadGiftReviews();
      });
      actions.appendChild(btn);
    }
    tbody.appendChild(tr);
  });
}
async function loadFlags() {
  const flags = await api("/admin/antifraud/flags");
  const ul = document.getElementById("flags-list");
  ul.innerHTML = "";
  flags.forEach((f) => {
    const li = document.createElement("li");
    li.textContent = `${f.id} user=${f.user_id} ${f.rule} score=${f.score}`;
    ul.appendChild(li);
  });
}
document.getElementById("reconcile-btn").addEventListener("click", async () => {
  const r = await api("/admin/ledger/reconcile");
  document.getElementById("reconcile-result").textContent = JSON.stringify(r);
});
document.getElementById("analytics-btn").addEventListener("click", async () => {
  const r = await api("/admin/analytics?days=30");
  document.getElementById("analytics-result").textContent = JSON.stringify(r);
});
loadWithdrawals();
loadGiftReviews();
loadFlags();