// Crash: ставка с заранее заданным авто-cashout.
// Бэкенд: POST /games/crash {bet, cashout_at, client_seed} -> {crash, cashout_at, win}.
// Раунд мгновенный на сервере — множитель анимируем на клиенте до результата.

async function startCrash() {
  const bet = parseInt(document.getElementById("crash-bet").value, 10) || 100;
  const cashoutAt = parseFloat(document.getElementById("crash-target").value) || 2.0;
  const display = document.getElementById("crash-multiplier");
  const status = document.getElementById("crash-status");
  if (status) status.textContent = "";
  try {
    const res = await window.api("/games/crash", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bet, cashout_at: cashoutAt, client_seed: crypto.randomUUID() }),
    });
    animateCrash(res, display, status);
  } catch (e) {
    if (status) status.textContent = "Ошибка: " + e.message;
  }
}

function animateCrash(res, display, status) {
  const crashPoint = res.crash || 1.0;
  const cashoutAt = res.cashout_at || 1.0;
  const finalShown = Math.max(1.0, Math.min(crashPoint, cashoutAt));
  let m = 1.0;
  const step = Math.max(0.02, (finalShown - 1.0) / 20);
  if (crashInterval) clearInterval(crashInterval);
  crashInterval = setInterval(() => {
    m = Math.min(m + step, finalShown);
    if (display) display.innerHTML = '🚀 <span id="crash-rocket">' + m.toFixed(2) + "x</span>";
    if (m >= finalShown) {
      clearInterval(crashInterval);
      crashInterval = null;
      if (status) {
        status.textContent =
          res.win ? "Победа: " + crashPoint.toFixed(2) + "x" : "Краш на " + crashPoint.toFixed(2) + "x";
      }
      if (window.showReaction)
        window.showReaction("crash-reaction", res.win ? "victory" : "tilt");
    }
  }, 50);
}

let crashInterval = null;

window.startCrash = startCrash;
