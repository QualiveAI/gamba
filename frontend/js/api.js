const API_BASE = window.location.origin.replace(/:\d+$/, "") + ":8000";
let jwtToken = sessionStorage.getItem("jwt") || "";

async function ensureAuth() {
  if (jwtToken) return jwtToken;
  const tg = (window.Telegram && window.Telegram.WebApp) || { ready() {}, expand() {}, initData: "" };
  const res = await fetch(API_BASE + "/auth/telegram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ init_data: tg.initData || "" }),
  });
  if (!res.ok) throw new Error("auth failed");
  const data = await res.json();
  jwtToken = data.access_token;
  sessionStorage.setItem("jwt", jwtToken);
  return jwtToken;
}

async function api(path, opts = {}) {
  const token = await ensureAuth();
  const headers = Object.assign({ Authorization: "Bearer " + token }, opts.headers || {});
  let res = await fetch(API_BASE + path, Object.assign({}, opts, { headers }));
  if (res.status === 401) {
    jwtToken = "";
    sessionStorage.removeItem("jwt");
    const newToken = await ensureAuth();
    const retryHeaders = Object.assign({ Authorization: "Bearer " + newToken }, opts.headers || {});
    res = await fetch(API_BASE + path, Object.assign({}, opts, { headers: retryHeaders }));
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

window.api = api;