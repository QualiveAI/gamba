let crashInterval = null;
let crashMultiplier = 1.0;

async function startCrash() {
  const res = await window.api("/games/crash/session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
  const sessionId = res.session_id || res.id;
  crashMultiplier = 1.0;
  const display = document.getElementById("crash-multiplier");
  if (display) display.textContent = crashMultiplier.toFixed(2) + "x";

  if (crashInterval) clearInterval(crashInterval);
  crashInterval = setInterval(async () => {
    try {
      const state = await window.api(`/games/crash/session/${sessionId}`);
      crashMultiplier = state.multiplier || crashMultiplier;
      if (display) display.textContent = crashMultiplier.toFixed(2) + "x";
      if (state.crashed) {
        clearInterval(crashInterval);
        crashInterval = null;
        const btn = document.getElementById("crash-cashout");
        if (btn) btn.disabled = true;
        const status = document.getElementById("crash-status");
        if (status) status.textContent = "Crashed!";
      }
    } catch (e) {
      console.error(e);
    }
  }, 200);
}

async function cashoutCrash() {
  // confirm
  if (!confirm("Cash out now?")) return;
  // session id stored globally
  console.log("cashout requested");
}

window.startCrash = startCrash;
window.cashoutCrash = cashoutCrash;