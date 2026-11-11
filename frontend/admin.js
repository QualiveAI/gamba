const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const API_BASE = window.location.origin.replace(/:\d+$/, "") + ":8000";
let jwtToken = sessionStorage.getItem("jwt") || "";
async function api(path, options = {}) {
  if (!jwtToken) {
    const res = await fetch(API_BASE + "/auth/telegram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ init_data: tg?.initData || "" }) });
    const data = await res.json();
    if (!res.ok || !data.access_token) throw new Error("Не удалось подтвердить администратора.");
    jwtToken = data.access_token;
    sessionStorage.setItem("jwt", jwtToken);
  }
  const headers = Object.assign({ "Authorization": "Bearer " + jwtToken }, options.headers || {});
  const res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : detail?.message || "Запрос не выполнен. Проверьте права и настройки.");
  }
  return data;
}

function appendRow(tbody, values) {
  const tr = document.createElement("tr");
  values.forEach((value) => {
    const td = document.createElement("td");
    td.textContent = value == null ? "" : String(value);
    tr.appendChild(td);
  });
  tbody.appendChild(tr);
  return tr;
}

const nominal = (card) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: card.card_currency }).format(card.face_value_minor / 100);
const orderStatus = { pending: "Ожидает выдачи", delivering: "Отправка / исход может быть неизвестен", issued: "Выдана", rejected: "Отменён, монеты возвращены", manual_review: "Только ручная проверка" };
function showAdminError(error) {
  let target = document.getElementById("admin-error");
  if (!target) {
    target = document.createElement("p");
    target.id = "admin-error";
    target.setAttribute("role", "alert");
    document.getElementById("app").prepend(target);
  }
  target.textContent = error.message || "Операция не выполнена.";
}

async function loadWithdrawals() {
  const status = document.getElementById("wd-status").value;
  const q = status ? "?status=" + encodeURIComponent(status) : "";
  const rows = await api("/admin/redemptions" + q);
  const tbody = document.querySelector("#wd-table tbody");
  tbody.replaceChildren();
  rows.forEach((w) => {
    const tr = appendRow(tbody, [w.id, w.user_id, `${w.coin_cost} монет — ${w.brand} ${w.region} ${nominal(w)}${w.sandbox ? " [ТЕСТ]" : ""}`, orderStatus[w.status] || w.status, ""]);
    const actions = tr.lastElementChild;
    if (w.status === "pending" && !w.delivery_started_at) {
      const reject = document.createElement("button");
      reject.textContent = "Отменить до отправки";
      reject.addEventListener("click", async () => {
        if (!window.confirm("Отменить заказ до отправки и вернуть монеты?")) return;
        reject.disabled = true;
        try {
          await api(`/admin/redemptions/${w.id}/reject`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "operator_rejected" }) });
          await loadWithdrawals();
        } catch (error) { showAdminError(error); await loadWithdrawals().catch(showAdminError); }
      });
      actions.appendChild(reject);
    } else {
      actions.textContent = w.status === "rejected" ? "Возврат уже учтён" : "Код не раскрывается администратору";
    }
  });
}

const statusSelect = document.getElementById("wd-status");
statusSelect.replaceChildren();
[["", "Все заказы"], ...Object.entries(orderStatus)].forEach(([value, label]) => {
  const option = document.createElement("option"); option.value = value; option.textContent = label; statusSelect.appendChild(option);
});
const orderSection = statusSelect.closest("section");
orderSection.querySelector("h2").textContent = "Обмен монет на gift cards";
["Заказ", "Игрок", "Цена и реальный номинал", "Статус", "Действия"].forEach((text, index) => { document.querySelectorAll("#wd-table th")[index].textContent = text; });
statusSelect.addEventListener("change", () => loadWithdrawals().catch(showAdminError));

function buildGiftcardInventory() {
  const section = document.createElement("section");
  section.innerHTML = `
    <h2>Склад gift cards Roblox / BR / BRL</h2>
    <p>Нет закупок и курса по умолчанию. Номинал карты и цена в целых монетах задаются оператором. Новые SKU выключены; ключи и общий режим настраиваются вне этой панели.</p>
    <form id="gc-sku-form">
      <label>SKU оператора <input name="operator_sku" required maxlength="80" pattern="[A-Za-z0-9._:-]+"></label>
      <label>Номинал карты, BRL minor (centavos) <input name="face_value_minor" type="number" min="1" step="1" required></label>
      <label>Цена, целых монет <input name="coin_cost" type="number" min="1" step="1" required></label>
      <label><input name="sandbox" type="checkbox" checked> Только тестовая карта (TEST-ONLY-)</label>
      <button type="submit">Создать выключенный SKU</button>
    </form>
    <table id="gc-skus"><thead><tr><th>SKU</th><th>Номинал</th><th>Монеты</th><th>Режим</th><th>Каталог</th></tr></thead><tbody></tbody></table>
    <form id="gc-import-form">
      <h3>Импорт уже закупленной партии</h3>
      <label>Явный SKU <select name="sku_id" required></select></label>
      <label>Фактический поставщик <input name="supplier_name" required maxlength="120" autocomplete="off"></label>
      <label>Номер партии <input name="batch_reference" required maxlength="160" autocomplete="off"></label>
      <label>Ссылка на документ закупки <input name="provenance_reference" required maxlength="240" autocomplete="off"></label>
      <label>Ссылка на договор распространения (обязательна для live) <input name="distribution_agreement_reference" maxlength="240" autocomplete="off"></label>
      <label>CSV: только столбец code, до 1 MiB / 2000 строк <input name="codes" type="file" accept=".csv,text/csv" required></label>
      <p>Не вставляйте коды в названия, ссылки или заметки. Повтор кода отменяет всю загрузку; коды не показываются в ответе.</p>
      <button type="submit">Импортировать без покупки</button>
    </form>
    <p id="gc-result" role="status"></p>
    <details><summary>Старые заявки: только просмотр и ручная проверка</summary><table id="gc-legacy"><thead><tr><th>Заявка</th><th>Игрок</th><th>Историческая сумма</th><th>Статус</th></tr></thead><tbody></tbody></table></details>`;
  orderSection.after(section);
  document.getElementById("gc-sku-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    const data = new FormData(form);
    const faceValue = Number(data.get("face_value_minor"));
    const coinCost = Number(data.get("coin_cost"));
    if (!Number.isSafeInteger(faceValue) || faceValue <= 0 || !Number.isSafeInteger(coinCost) || coinCost <= 0) { showAdminError(new Error("Номинал и цена должны быть положительными целыми числами.")); return; }
    button.disabled = true;
    try {
      await api("/admin/giftcards/skus", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operator_sku: data.get("operator_sku"), brand: "Roblox", region: "BR", card_currency: "BRL", face_value_minor: faceValue, coin_cost: coinCost, sandbox: data.has("sandbox") }) });
      form.reset();
      document.getElementById("gc-result").textContent = "SKU создан выключенным. Проверьте mapping перед включением.";
      await loadGiftcardSkus();
    } catch (error) { showAdminError(error); } finally { button.disabled = false; }
  });
  document.getElementById("gc-import-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    const data = new FormData(form);
    const file = data.get("codes");
    if (!(file instanceof File) || !file.size || file.size > 1048576) { showAdminError(new Error("Выберите CSV размером до 1 MiB.")); return; }
    const query = new URLSearchParams();
    ["sku_id", "supplier_name", "batch_reference", "provenance_reference", "distribution_agreement_reference"].forEach((key) => { const value = String(data.get(key) || "").trim(); if (value) query.set(key, value); });
    button.disabled = true;
    try {
      const result = await api("/admin/giftcards/import?" + query.toString(), { method: "POST", headers: { "Content-Type": "text/csv" }, body: file });
      document.getElementById("gc-result").textContent = `Партия ${result.batch_id}: безопасно импортировано ${result.imported} карт.`;
      form.reset();
      await loadGiftcardSkus();
    } catch (error) { showAdminError(error); } finally { button.disabled = false; form.elements.codes.value = ""; }
  });
}

async function loadGiftcardSkus() {
  const rows = await api("/admin/giftcards/skus");
  const tbody = document.querySelector("#gc-skus tbody");
  const select = document.querySelector("#gc-import-form select");
  tbody.replaceChildren(); select.replaceChildren();
  const empty = document.createElement("option"); empty.value = ""; empty.textContent = "Выберите настроенный SKU"; select.appendChild(empty);
  rows.forEach((sku) => {
    const tr = appendRow(tbody, [`${sku.id}: ${sku.operator_sku}`, `${sku.brand} / ${sku.region} / ${nominal(sku)}`, sku.coin_cost, sku.sandbox ? "Только тест" : "Реальная карта", ""]);
    const button = document.createElement("button"); button.textContent = sku.active ? "Выключить SKU" : "Включить SKU";
    button.addEventListener("click", async () => {
      if (!sku.active && !window.confirm(`Подтвердите mapping: ${nominal(sku)} = ${sku.coin_cost} целых монет. ${sku.sandbox ? "ТЕСТОВАЯ карта." : "Нужны закупка и права на распространение."}`)) return;
      button.disabled = true;
      try { await api(`/admin/giftcards/skus/${sku.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: !sku.active }) }); await loadGiftcardSkus(); } catch (error) { showAdminError(error); button.disabled = false; }
    });
    tr.lastElementChild.appendChild(button);
    const option = document.createElement("option"); option.value = sku.id; option.textContent = `${sku.operator_sku}: ${nominal(sku)} / ${sku.coin_cost} монет${sku.sandbox ? " [ТЕСТ]" : " [LIVE]"}`; select.appendChild(option);
  });
  if (!rows.length) document.getElementById("gc-result").textContent = "Каталог пуст до явной настройки SKU оператором.";
}

async function loadLegacyWithdrawals() {
  const rows = await api("/admin/withdrawals");
  const tbody = document.querySelector("#gc-legacy tbody"); tbody.replaceChildren();
  rows.forEach((row) => appendRow(tbody, [row.id, row.user_id, row.amount_units, `${row.status} — без автоматического remap/выдачи/возврата`]));
}

buildGiftcardInventory();
async function loadGiftReviews() {
  const rows = await api("/admin/gift-reviews");
  const tbody = document.querySelector("#gift-table tbody");
  tbody.innerHTML = "";
  rows.forEach((g) => {
    const tr = appendRow(tbody, [g.id, g.user_id, g.gift_id, g.status, g.price_rub || "", ""]);
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
loadWithdrawals().catch(showAdminError);
loadGiftcardSkus().catch(showAdminError);
loadLegacyWithdrawals().catch(showAdminError);
loadGiftReviews().catch(showAdminError);
loadFlags().catch(showAdminError);