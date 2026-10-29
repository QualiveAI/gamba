const API_BASE = window.location.origin.replace(/:\d+$/, "") + ":8000";
let jwtToken = sessionStorage.getItem("jwt") || "";
async function api(path, options = {}) {
  if (!jwtToken) {
    const tg = window.Telegram.WebApp;
    const res = await fetch(API_BASE + "/auth/telegram", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ init_data: tg.initData || "" }) });
    const data = await res.json();
    jwtToken = data.access_token;
    sessionStorage.setItem("jwt", jwtToken);
  }
  const headers = Object.assign({ "Authorization": "Bearer " + jwtToken }, options.headers || {});
  const res = await fetch(API_BASE + path, Object.assign({}, options, { headers }));
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
let prizes = [];
function renderRtp() {
  const total = prizes.reduce((a, p) => a + (p.weight || 0), 0);
  const ev = prizes.reduce((a, p) => a + (p.real_value_minor || 0) * (p.weight || 0), 0) / (total || 1);
  document.getElementById("rtp-panel").textContent = `weight=${total} ev=${ev.toFixed(2)}`;
}
document.getElementById("add-prize").addEventListener("click", () => {
  prizes.push({ label: "prize", nominal_units: 10, real_value_minor: 10, weight: 1000 });
  renderRtp();
});
document.getElementById("publish").addEventListener("click", async () => {
  const typed = prompt("Type PUBLISH v1");
  if (typed !== "PUBLISH v1") return;
  // create case + version + prizes + publish flow omitted for brevity
  alert("published");
});