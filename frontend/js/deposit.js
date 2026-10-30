async function loadDepositMethods() {
  const geos = await window.api("/meta/geos");
  const container = document.getElementById("deposit-methods");
  if (!container) return;
  container.innerHTML = "";
  (geos.methods || geos || []).forEach((m) => {
    const btn = document.createElement("button");
    btn.textContent = m.name || m.method;
    btn.addEventListener("click", () => createDeposit(m.method));
    container.appendChild(btn);
  });
}

async function createDeposit(method) {
  const amount = parseFloat(document.getElementById("dep-amount").value) || 100;
  const res = await window.api("/payments/deposit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method, amount }),
  });
  const qrDiv = document.getElementById("qr");
  if (qrDiv) {
    qrDiv.innerHTML = "";
    if (res.qr_string) {
      new QRCode(qrDiv, res.qr_string);
    } else if (res.redirect_url) {
      const a = document.createElement("a");
      a.href = res.redirect_url;
      a.textContent = "Pay";
      a.target = "_blank";
      qrDiv.appendChild(a);
    }
  }
  // poll status
  const pid = res.payment_id || res.id;
  if (pid) {
    const interval = setInterval(async () => {
      const st = await window.api(`/payments/${pid}/status`);
      if (st.status === "completed" || st.status === "succeeded" || st.status === "failed") {
        clearInterval(interval);
        const statusEl = document.getElementById("dep-status");
        if (statusEl) statusEl.textContent = st.status;
      }
    }, 3000);
  }
}

window.loadDepositMethods = loadDepositMethods;
window.createDeposit = createDeposit;