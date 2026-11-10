// Депозит: выбор способа оплаты (рельса) -> создание инвойса -> оплата -> статус.
// Рельсы приходят из /meta/geos: "card" (PayGate: карта/платёжная страница), "crypto" (Coinso: USDT).
// Комиссия рельса оплачивается клиентом: платим gross, на баланс падает net.

const RAIL_LABELS = {
  card: "Cartão / PIX",
  crypto: "Cripto (USDT)",
  pix: "PIX",
  qrph: "QR Ph",
  spei: "SPEI",
  qris: "QRIS",
};

const RAIL_TO_ENDPOINT = {
  card: "paygate",
  crypto: "coinso",
  pix: "paygate",
  qrph: "paygate",
  spei: "paygate",
  qris: "paygate",
};

let selectedMethod = null;

function fmtMinor(minor) {
  return (minor / 100).toFixed(2);
}

async function loadDepositMethods() {
  const container = document.getElementById("deposit-methods");
  if (!container) return;
  container.innerHTML = "";
  let methods = [];
  try {
    const geos = await window.api("/meta/geos");
    const list = Array.isArray(geos) ? geos : [geos];
    const seen = new Set();
    list.forEach((g) => (g.methods || []).forEach((m) => seen.add(m)));
    methods = [...seen];
  } catch (e) {
    // мета недоступна — показываем оба базовых способа
    methods = ["card", "crypto"];
  }
  if (methods.length === 0) methods = ["card", "crypto"];
  methods.forEach((m) => {
    const btn = document.createElement("button");
    btn.className = "deposit-method-btn";
    btn.dataset.method = m;
    btn.textContent = RAIL_LABELS[m] || m;
    btn.addEventListener("click", () => selectMethod(m));
    container.appendChild(btn);
  });
  selectMethod(methods[0]);
}

function selectMethod(m) {
  selectedMethod = m;
  document.querySelectorAll(".deposit-method-btn").forEach((b) => {
    b.classList.toggle("selected", b.dataset.method === m);
  });
}

async function createDeposit() {
  const statusEl = document.getElementById("dep-status");
  const amount = parseFloat(document.getElementById("dep-amount").value) || 100;
  if (!selectedMethod) {
    if (statusEl) statusEl.textContent = "Escolha a forma de pagamento";
    return;
  }
  if (statusEl) statusEl.textContent = "Criando pagamento...";
  try {
    const res = await window.api("/deposits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rail: RAIL_TO_ENDPOINT[selectedMethod] || selectedMethod,
        amount_minor: Math.round(amount * 100),
        currency: "units",
      }),
    });
    const p = res.client_payload || {};
    if (statusEl && res.amount_gross_minor) {
      const grossCoins = res.amount_gross_minor / 100;
      statusEl.textContent =
        `Depósito: ${amount} 🪙 • pagamento $${(grossCoins * 0.015).toFixed(2)}`;
    }
    showPayment(p, res.intent_id);
  } catch (e) {
    if (statusEl) statusEl.textContent = "Ошибка: " + e.message;
  }
}

function showPayment(payload, intentId) {
  const qrDiv = document.getElementById("qr");
  if (!qrDiv) return;
  qrDiv.innerHTML = "";
  if (payload.payment_url) {
    const a = document.createElement("a");
    a.href = payload.payment_url;
    a.textContent = "Ir para o pagamento";
    a.target = "_blank";
    a.rel = "noopener";
    qrDiv.appendChild(a);
  } else if (payload.address) {
    if (window.QRCode) new QRCode(qrDiv, payload.address);
    const code = document.createElement("code");
    code.textContent = payload.address;
    qrDiv.appendChild(code);
  }
  if (intentId) pollDepositStatus(intentId);
}

function pollDepositStatus(intentId) {
  const statusEl = document.getElementById("dep-status");
  const interval = setInterval(async () => {
    try {
      const st = await window.api(`/deposits/${intentId}`);
      if (st.status === "succeeded" || st.status === "failed") {
        clearInterval(interval);
        if (statusEl)
          statusEl.textContent =
            st.status === "succeeded" ? "Depósito creditado" : "Pagamento falhou";
      }
    } catch (e) {
      clearInterval(interval);
    }
  }, 3000);
}

window.loadDepositMethods = loadDepositMethods;
window.createDeposit = createDeposit;
