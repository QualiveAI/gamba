// Check-in diário: календарь месяца + прогресс серий (7 дней -> Semanal, 30 -> Mensal)
const MESES_PT = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"];

function renderCalendar(st) {
  const cal = document.getElementById("cal-grid");
  const head = document.getElementById("cal-head");
  if (!cal) return;
  const now = new Date();
  if (head) head.textContent = `${MESES_PT[now.getMonth()]} ${now.getFullYear()}`;
  cal.innerHTML = "";
  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const firstDow = new Date(now.getFullYear(), now.getMonth(), 1).getDay(); // 0=dom
  for (let i = 0; i < firstDow; i++) {
    const pad = document.createElement("div");
    pad.className = "day-cell empty";
    cal.appendChild(pad);
  }
  const marked = new Set(st.claimed_dates || []);
  for (let d = 1; d <= days; d++) {
    const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const cell = document.createElement("div");
    const isMarked = marked.has(iso);
    const isToday = d === now.getDate();
    cell.className = "day-cell" + (isMarked ? " marked" : "") + (isToday ? " today" : "");
    cell.textContent = isMarked ? "✓" : d;
    cal.appendChild(cell);
  }
  // Прогресс серий
  const week = Math.min(7, st.streak || 0);
  const month = Math.min(30, st.streak || 0);
  const setBar = (barId, lblId, val, max) => {
    const bar = document.getElementById(barId);
    if (bar) bar.style.width = Math.round((val / max) * 100) + "%";
    const lbl = document.getElementById(lblId);
    if (lbl) lbl.textContent = `${val}/${max}`;
  };
  setBar("sp-week", "sp-week-lbl", week, 7);
  setBar("sp-month", "sp-month-lbl", month, 30);
}

async function loadDaily() {
  let st = { can_claim: true, streak: 0, claimed_dates: [] };
  try {
    st = await window.api("/rewards/daily/status");
  } catch (e) { /* дефолт */ }
  renderCalendar(st);
  const btn = document.getElementById("daily-btn");
  const statusEl = document.getElementById("daily-status");
  if (btn) {
    if (st.can_claim) {
      btn.disabled = false;
      btn.textContent = "Resgatar +500 🥉";
    } else {
      btn.disabled = true;
      btn.textContent = "✓ Resgatado hoje";
    }
  }
  if (statusEl) statusEl.textContent = st.can_claim ? "" : "Volte amanhã para mais 500 🥉";
}

async function claimDaily() {
  const statusEl = document.getElementById("daily-status");
  try {
    const r = await window.api("/rewards/daily/claim", { method: "POST" });
    if (statusEl) statusEl.textContent = `Recebido: +${r.amount} 🥉 (sequência: ${r.streak})`;
    if (window.renderWallet) window.renderWallet();
  } catch (e) {
    const msg = String(e.message).includes("cooldown")
      ? "Já resgatado hoje. Volte amanhã!"
      : "Erro: " + e.message;
    if (statusEl) statusEl.textContent = msg;
  }
  loadDaily(); // перерисовать календарь с отметкой
}

window.loadDaily = loadDaily;
window.claimDaily = claimDaily;
