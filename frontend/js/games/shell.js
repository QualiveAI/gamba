let shellBallPosition = 0;

function shuffleCups() {
  const cups = document.querySelectorAll(".cup");
  cups.forEach((c) => c.classList.add("shuffling"));
  setTimeout(() => {
    shellBallPosition = Math.floor(Math.random() * 3);
    cups.forEach((c, i) => {
      c.classList.remove("shuffling");
      c.classList.remove("has-ball");
      if (i === shellBallPosition) c.classList.add("has-ball");
    });
  }, 1000);
}

async function pickCup(index) {
  try {
    const res = await window.api("/games/shell/pick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cup: index }),
    });
    const cups = document.querySelectorAll(".cup");
    cups.forEach((c, i) => {
      if (i === (res.ball_position || shellBallPosition)) c.classList.add("correct");
      if (i === index && !res.win) c.classList.add("wrong");
    });
    const resultEl = document.getElementById("shell-result");
    if (resultEl) resultEl.textContent = res.win ? "WIN!" : "LOSE";
  } catch (e) {
    console.error(e);
  }
}

window.shuffleCups = shuffleCups;
window.pickCup = pickCup;