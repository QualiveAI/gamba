const API_BASE = window.location.origin.replace(/:\d+$/, "") + ":8000";
let jwtToken = sessionStorage.getItem("jwt") || "";
const tg = (window.Telegram && window.Telegram.WebApp) || { ready() {}, expand() {}, initData: "" };
tg.ready(); tg.expand();

async function api(path, options = {}) {
  if (!jwtToken) {
    const res = await fetch(API_BASE + "/auth/telegram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ init_data: tg.initData || "" }) });
    const data = await res.json();
    jwtToken = data.access_token;
    sessionStorage.setItem("jwt", jwtToken);
  }
  const headers = Object.assign({ "Authorization": "Bearer " + jwtToken }, options.headers || {});
  const res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  if (!res.ok) {
    const err = new Error(await res.text());
    err.status = res.status;
    throw err;
  }
  return res.json();
}

let prizes = [];
let currentCaseId = null;
let currentVersionId = null;
let currentVersionNo = 1;

function renderRtp() {
  const total = prizes.reduce((a, p) => a + (p.weight || 0), 0);
  const ev = total > 0 ? prizes.reduce((a, p) => a + (p.real_value_minor || 0) * (p.weight || 0), 0) / total : 0;
  const rtp = Math.round(ev * 100);
  const target = 9000;
  const weightOk = total === 10000;
  const rtpOk = Math.abs(rtp - target) <= 50;

  const weightEl = document.getElementById("weight-total");
  if (weightEl) {
    weightEl.textContent = `${total} / 10000`;
    weightEl.className = weightOk ? "green" : "red";
  }
  const rtpEl = document.getElementById("rtp-panel");
  if (rtpEl) {
    rtpEl.textContent = `RTP: ${rtp} (target ${target}) ${rtpOk ? "OK" : "DRIFT"}`;
    rtpEl.className = rtpOk ? "green" : "red";
  }

  const publishBtn = document.getElementById("publish");
  if (publishBtn) {
    publishBtn.disabled = !(weightOk && rtpOk && prizes.length > 0);
  }
}

function addPrizeRow(prize = {}) {
  const container = document.getElementById("prizes");
  const row = document.createElement("div");
  row.className = "prize-row";
  row.innerHTML = `
    <input class="label" placeholder="label" value="${prize.label || ""}" />
    <input class="nominal" type="number" placeholder="nominal_units" value="${prize.nominal_units || 100}" />
    <input class="realvalue" type="number" placeholder="real_value_minor" value="${prize.real_value_minor || 90}" />
    <input class="weight" type="number" placeholder="weight" value="${prize.weight || 1000}" min="0" max="10000" step="1" />
  `;
  const weightInput = row.querySelector(".weight");
  weightInput.addEventListener("input", () => {
    const idx = Array.from(container.children).indexOf(row);
    if (prizes[idx]) prizes[idx].weight = parseInt(weightInput.value, 10) || 0;
    if (prizes[idx]) prizes[idx].weight_bp = prizes[idx].weight;
    renderRtp();
  });
  row.querySelector(".label").addEventListener("input", (e) => {
    const idx = Array.from(container.children).indexOf(row);
    if (prizes[idx]) prizes[idx].label = e.target.value;
  });
  row.querySelector(".nominal").addEventListener("input", (e) => {
    const idx = Array.from(container.children).indexOf(row);
    if (prizes[idx]) prizes[idx].nominal_units = parseInt(e.target.value, 10) || 0;
    renderRtp();
  });
  row.querySelector(".realvalue").addEventListener("input", (e) => {
    const idx = Array.from(container.children).indexOf(row);
    if (prizes[idx]) prizes[idx].real_value_minor = parseInt(e.target.value, 10) || 0;
    renderRtp();
  });
  container.appendChild(row);
  prizes.push({
    label: prize.label || "prize",
    nominal_units: prize.nominal_units || 100,
    real_value_minor: prize.real_value_minor || 90,
    weight: prize.weight || 1000,
    weight_bp: prize.weight || 1000,
  });
  renderRtp();
}

function renderCaseList(cases) {
  const list = document.getElementById("case-list");
  list.innerHTML = "";
  (cases || []).forEach((c) => {
    const card = document.createElement("div");
    card.className = "case-card";
    card.innerHTML = `<span class="badge ${c.status}">${c.status}</span> <strong>${c.title || c.slug}</strong>`;
    list.appendChild(card);
  });
}

async function loadCases() {
  try {
    const cases = await api("/admin/cases");
    renderCaseList(cases);
  } catch (e) {
    console.error("loadCases error", e);
  }
}

document.getElementById("new-case").addEventListener("click", () => {
  document.getElementById("editor").style.display = "block";
  prizes = [];
  document.getElementById("prizes").innerHTML = "";
  currentCaseId = null;
  currentVersionId = null;
});

document.getElementById("add-prize").addEventListener("click", () => addPrizeRow());
document.getElementById("publish").addEventListener("click", async () => {
  const confirmInput = document.getElementById("confirm-input").value;
  if (confirmInput !== `PUBLISH v${currentVersionNo}`) {
    document.getElementById("publish").disabled = true;
    const banner = document.getElementById("error-banner");
    banner.textContent = `type exactly PUBLISH v${currentVersionNo}`;
    banner.style.display = "block";
    return;
  }
  try {
    const title = document.getElementById("title").value;
    const slug = document.getElementById("slug").value;
    const gameKey = document.getElementById("game").value;
    const currency = document.getElementById("currency").value;
    const caseRes = await api("/admin/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, slug, game_key: gameKey, currency }),
    });
    currentCaseId = caseRes.id;
    const verRes = await api(`/admin/cases/${currentCaseId}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rtp_target_bp: 9000, changelog: "v1" }),
    });
    currentVersionId = verRes.version_id;
    currentVersionNo = verRes.version_no;
    const prizePayload = prizes.map((p) => ({
      label: p.label,
      nominal_units: p.nominal_units,
      real_value_minor: p.real_value_minor,
      weight_bp: p.weight,
    }));
    await api(`/admin/cases/${currentCaseId}/versions/${currentVersionId}/prizes`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prizes: prizePayload }),
    });
    await api(`/admin/cases/${currentCaseId}/versions/${currentVersionId}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ changelog: "publish", confirm: `PUBLISH v${currentVersionNo}` }),
    });
    document.getElementById("error-banner").style.display = "none";
    document.getElementById("immutable-banner").style.display = "none";
    await loadCases();
  } catch (e) {
    if (e.status === 409) {
      document.getElementById("immutable-banner").style.display = "block";
    } else {
      const banner = document.getElementById("error-banner");
      banner.textContent = e.message;
      banner.style.display = "block";
    }
  }
});

document.getElementById("confirm-input").addEventListener("input", () => {
  const val = document.getElementById("confirm-input").value;
  const btn = document.getElementById("publish");
  const total = prizes.reduce((a, p) => a + (p.weight || 0), 0);
  const weightOk = total === 10000;
  if (val === `PUBLISH v${currentVersionNo}` && weightOk) {
    btn.disabled = false;
  } else {
    btn.disabled = true;
  }
});

loadCases();