let minesSession = null;
let minesMultiplier = 1.0;

function renderMinesGrid() {
  const grid = document.getElementById("mines-grid");
  if (!grid) return;
  grid.innerHTML = "";
  for (let i = 0; i < 25; i++) {
    const cell = document.createElement("button");
    cell.className = "mine-cell";
    cell.dataset.index = i;
    cell.addEventListener("click", () => revealCell(i));
    grid.appendChild(cell);
  }
}

async function startMines() {
  const bet = parseInt(document.getElementById("mines-bet").value, 10) || 100;
  const res = await window.api("/games/mines/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bet_units: bet }),
  });
  minesSession = res.session_id || res.id;
  minesMultiplier = 1.0;
  renderMinesGrid();
  const multEl = document.getElementById("mines-multiplier");
  if (multEl) multEl.textContent = minesMultiplier.toFixed(2);
}

async function revealCell(index) {
  if (!minesSession) return;
  try {
    const res = await window.api(`/games/mines/session/${minesSession}/reveal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cell: index }),
    });
    const cell = document.querySelector(`.mine-cell[data-index="${index}"]`);
    if (res.hit_mine) {
      if (cell) cell.classList.add("mine");
      document.querySelectorAll(".mine-cell").forEach((c) => (c.disabled = true));
    } else {
      if (cell) cell.classList.add("safe");
      minesMultiplier = res.multiplier || minesMultiplier;
      const multEl = document.getElementById("mines-multiplier");
      if (multEl) multEl.textContent = minesMultiplier.toFixed(2);
    }
  } catch (e) {
    console.error(e);
  }
}

async function cashoutMines() {
  if (!minesSession) return;
  try {
    const res = await window.api(`/games/mines/session/${minesSession}/cashout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const toast = document.getElementById("mines-toast");
    if (toast) toast.textContent = "Cashed out: " + (res.payout || res.payout_multiplier);
    document.querySelectorAll(".mine-cell").forEach((c) => (c.disabled = true));
  } catch (e) {
    console.error(e);
  }
}

window.startMines = startMines;
window.cashoutMines = cashoutMines;