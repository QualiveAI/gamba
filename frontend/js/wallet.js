async function renderWallet() {
  let units = 0, freebets = 0, minWithdraw = 100000;
  try {
    const data = await window.api("/wallet");
    units = data.units || 0;
    freebets = data.freebets || 0;
    minWithdraw = data.min_withdraw || 100000;
  } catch (e) {
    console.log("renderWallet error:", e.message);
  }

  const container = document.getElementById("wallet");
  if (container) {
    container.innerHTML = `
      <div class="balance-row"><span>🪙 Ouro</span><span>${units}</span></div>
      <div class="balance-row"><span>🥉 Cobre</span><span>${freebets} <small style="color:var(--muted)">(não sacável)</small></span></div>
    `;
  }

  const headerBal = document.getElementById("balance");
  if (headerBal) headerBal.textContent = String(units);
  const wdBtn = document.getElementById("wd-btn");
  if (wdBtn) {
    if (units < minWithdraw) {
      wdBtn.disabled = true;
      wdBtn.title = `Minimum withdrawal: ${minWithdraw} units`;
      wdBtn.setAttribute("data-disabled-reason", "below_minimum");
    } else {
      wdBtn.disabled = false;
      wdBtn.title = "";
    }
  }

  const freebetWdBtn = document.getElementById("wd-freebets-btn");
  if (freebetWdBtn) {
    freebetWdBtn.disabled = true;
    freebetWdBtn.title = "Freebets are non-withdrawable";
    freebetWdBtn.setAttribute("data-disabled-reason", "non_withdrawable");
  }
}

window.renderWallet = renderWallet;

// Медные монетки (фрибеты) -> золотые, курс 100:1
async function convertFreebets() {
  const statusEl = document.getElementById("conv-status");
  const amount = parseInt(document.getElementById("conv-amount").value, 10) || 0;
  try {
    const res = await window.api("/rewards/convert_freebets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount_copper: amount }),
    });
    if (statusEl) statusEl.textContent = `Convertido: ${res.converted_copper} 🥉 -> ${res.gold} 🪙`;
    if (window.renderWallet) window.renderWallet();
  } catch (e) {
    if (statusEl) statusEl.textContent = "Erro: " + e.message;
  }
}
window.convertFreebets = convertFreebets;
