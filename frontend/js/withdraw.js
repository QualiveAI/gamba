async function loadWithdrawLimits() {
  const limits = await window.api("/meta/limits");
  const minEl = document.getElementById("wd-min");
  if (minEl) minEl.textContent = limits.min_withdraw || limits.min || 0;
  const feeEl = document.getElementById("wd-fee");
  if (feeEl) feeEl.textContent = limits.fee_percent || limits.fee || 0;
  const holdEl = document.getElementById("wd-hold");
  if (holdEl) holdEl.textContent = limits.hold_days || limits.hold || 0;
}

async function submitWithdraw() {
  const amount = parseInt(document.getElementById("wd-amount").value, 10);
  const region = document.getElementById("wd-region").value;
  try {
    const r = await window.api("/withdrawals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount, region }),
    });
    const resultEl = document.getElementById("wd-result");
    if (resultEl) resultEl.textContent = JSON.stringify(r);
    const pid = r.id || r.withdrawal_id;
    if (pid) {
      const interval = setInterval(async () => {
        const st = await window.api(`/withdrawals/${pid}/status`);
        const statusEl = document.getElementById("wd-status");
        if (statusEl) statusEl.textContent = st.status;
        if (st.status === "completed" || st.status === "rejected" || st.status === "failed") {
          clearInterval(interval);
        }
      }, 3000);
    }
  } catch (e) {
    const resultEl = document.getElementById("wd-result");
    if (resultEl) resultEl.textContent = e.message;
  }
}

window.loadWithdrawLimits = loadWithdrawLimits;
window.submitWithdraw = submitWithdraw;