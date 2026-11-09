// Shell: POST /games/shell {bet, guess, client_seed} -> {ball, guess, win}.

async function pickCup(index) {
  const bet = parseInt(document.getElementById("shell-bet").value, 10) || 100;
  try {
    const res = await window.api("/games/shell", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bet, guess: index, client_seed: crypto.randomUUID() }),
    });
    const cups = document.querySelectorAll(".cup");
    cups.forEach((c, i) => {
      c.classList.remove("correct", "wrong", "has-ball", "reveal");
      if (i === res.ball) { c.classList.add("correct", "has-ball", "reveal"); }
      if (i === index && !res.win) c.classList.add("wrong");
    });
    const resultEl = document.getElementById("shell-result");
    if (resultEl) resultEl.textContent = res.win ? "WIN!" : "LOSE";
    if (window.showReaction)
      window.showReaction("shell-reaction", res.win ? "showoff" : "tilt");
  } catch (e) {
    console.error(e);
  }
}

function shuffleCups() {
  const cups = document.querySelectorAll(".cup");
  cups.forEach((c) => c.classList.add("shuffling"));
  setTimeout(() => cups.forEach((c) => c.classList.remove("shuffling")), 800);
}

window.shuffleCups = shuffleCups;
window.pickCup = pickCup;
