// Mines: POST /games/mines/start {bet, mine_count} -> {session_id, grid_size, mine_count};
// POST /games/mines/reveal {session_id, cell} -> {hit_mine, revealed, bias_applied};
// POST /games/mines/cashout?session_id=N -> {payout, revealed}.

let minesSession = null;
let minesGridSize = 25;

function renderMinesGrid() {
  const grid = document.getElementById("mines-grid");
  if (!grid) return;
  grid.innerHTML = "";
  grid.style.gridTemplateColumns = `repeat(${Math.ceil(Math.sqrt(minesGridSize))},1fr)`;
  for (let i = 0; i < minesGridSize; i++) {
    const cell = document.createElement("button");
    cell.className = "mine-cell";
    cell.dataset.index = i;
    cell.addEventListener("click", () => revealCell(i));
    grid.appendChild(cell);
  }
}

async function startMines() {
  const bet = parseInt(document.getElementById("mines-bet").value, 10) || 100;
  const mineCount = parseInt(document.getElementById("mines-count").value, 10) || 3;
  const toast = document.getElementById("mines-toast");
  try {
    const res = await window.api("/games/mines/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bet, mine_count: mineCount }),
    });
    minesSession = res.session_id;
    minesGridSize = res.grid_size || 25;
    renderMinesGrid();
    const multEl = document.getElementById("mines-multiplier");
    if (multEl) multEl.textContent = "1.00";
    if (toast) toast.textContent = "";
  } catch (e) {
    if (toast) toast.textContent = "Ошибка: " + e.message;
  }
}

async function revealCell(index) {
  if (!minesSession) return;
  try {
    const res = await window.api("/games/mines/reveal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: minesSession, cell: index }),
    });
    const cell = document.querySelector(`.mine-cell[data-index="${index}"]`);
    if (res.hit_mine) {
      if (cell) { cell.classList.add("mine", "reveal"); }
      document.querySelectorAll(".mine-cell").forEach((c) => (c.disabled = true));
      minesSession = null;
      const toast = document.getElementById("mines-toast");
      if (toast) toast.textContent = "Mina! Rodada perdida";
      if (window.showReaction) window.showReaction("mines-reaction", "tilt");
    } else {
      if (cell) { cell.classList.add("safe", "reveal"); }
      // Потенциальный множитель: классическая формула fair-mines
      const mc = parseInt(document.getElementById("mines-count").value, 10) || 3;
      const n = res.revealed || 0;
      let mult = 1;
      for (let i = 0; i < n; i++) mult *= (25 - i) / (25 - mc - i);
      mult *= 0.95; // house edge
      const multEl = document.getElementById("mines-multiplier");
      if (multEl) multEl.textContent = mult.toFixed(2) + "x";
    }
  } catch (e) {
    console.error(e);
  }
}

async function cashoutMines() {
  if (!minesSession) return;
  try {
    const res = await window.api(`/games/mines/cashout?session_id=${minesSession}`, {
      method: "POST",
    });
    const toast = document.getElementById("mines-toast");
    if (toast) toast.textContent = "Retirada: " + (res.payout ?? 0);
    if (window.showReaction && (res.payout ?? 0) > 0)
      window.showReaction("mines-reaction", "victory");
    document.querySelectorAll(".mine-cell").forEach((c) => (c.disabled = true));
    minesSession = null;
  } catch (e) {
    console.error(e);
  }
}

window.startMines = startMines;
window.cashoutMines = cashoutMines;
