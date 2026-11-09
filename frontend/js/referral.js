// Экран «Друзья»: реферальная ссылка и статистика
async function loadReferrals() {
  try {
    const r = await window.api("/referrals/my");
    const linkEl = document.getElementById("ref-link");
    if (linkEl) linkEl.textContent = r.link;
    const inv = document.getElementById("ref-invited");
    if (inv) inv.textContent = String(r.invited);
    const conf = document.getElementById("ref-confirmed");
    if (conf) conf.textContent = String(r.confirmed);
  } catch (e) {
    const linkEl = document.getElementById("ref-link");
    if (linkEl) linkEl.textContent = "Не удалось загрузить: " + e.message;
  }
}

function copyRefLink() {
  const link = document.getElementById("ref-link").textContent;
  if (navigator.clipboard) navigator.clipboard.writeText(link);
  if (window.Telegram && window.Telegram.WebApp) {
    window.Telegram.WebApp.HapticFeedback.notificationOccurred("success");
  }
  if (window.showReaction) window.showReaction("ref-reaction", "letsgo");
}

window.loadReferrals = loadReferrals;
window.copyRefLink = copyRefLink;
