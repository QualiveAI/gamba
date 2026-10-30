async function renderWallet() {
  const data = await window.api("/wallet");
  const units = data.units || 0;
  const freebets = data.freebets || 0;
  const minWithdraw = data.min_withdraw || 100000;

  const container = document.getElementById("wallet");
  if (!container) return;
  container.innerHTML = `
    <div class="balance-row"><span>Units</span><span>${units}</span></div>
    <div class="balance-row"><span>Freebets</span><span>${freebets} <span class="badge">non-withdrawable</span></span></div>
  `;

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