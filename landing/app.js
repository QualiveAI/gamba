/* Только локальные взаимодействия; переходы строятся отдельным чистым модулем. */
(function () {
  "use strict";

  const config = window.WINDROP_CONFIG || {};
  const links = window.WindropLinks;
  const botLink = links ? links.buildTelegramLink(config, window.location.search) : "";
  const supportLink = links ? links.buildSupportLink(config) : "";
  const dialog = document.getElementById("notice-dialog");
  const noticeTitle = document.getElementById("notice-title");
  const noticeBody = document.getElementById("notice-body");
  let dialogTrigger = null;

  function showNotice(kind, trigger) {
    const support = kind === "support";
    noticeTitle.textContent = support ? "O suporte ainda não está configurado." : "O acesso ainda está desativado.";
    noticeBody.textContent = support
      ? "O contato de suporte ainda precisa ser configurado e confirmado. Nenhuma conversa foi aberta. Nunca envie senhas, tokens ou códigos de login por este site."
      : "O endereço do bot principal ainda não foi configurado e confirmado. Nenhuma conversa foi aberta. Você pode continuar explorando esta página.";
    dialogTrigger = trigger;
    if (typeof dialog.showModal === "function") {
      if (!dialog.open) dialog.showModal();
      document.body.classList.add("dialog-open");
      dialog.querySelector(".dialog-dismiss").focus();
    } else {
      const target = document.getElementById(support ? "support-status" : "access-status");
      target.setAttribute("tabindex", "-1");
      target.focus();
    }
  }

  function configureLinks(selector, href, kind) {
    document.querySelectorAll(selector).forEach((anchor) => {
      if (href) {
        anchor.href = href;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        anchor.referrerPolicy = "no-referrer";
        anchor.dataset.state = "configured";
        anchor.setAttribute("aria-label", kind === "support" ? "Falar com o suporte no Telegram (abre em nova aba)" : "Abrir no Telegram (abre em nova aba)");
      } else {
        anchor.dataset.state = "unconfigured";
        if (typeof dialog.showModal === "function") anchor.setAttribute("aria-haspopup", "dialog");
        anchor.addEventListener("click", (event) => {
          event.preventDefault();
          showNotice(kind, anchor);
        });
      }
    });
  }

  configureLinks("[data-telegram-cta]", botLink, "bot");
  configureLinks("[data-support-link]", supportLink, "support");
  if (botLink) {
    document.querySelectorAll("[data-bot-status]").forEach((element) => {
      element.textContent = "Link configurado · abre o bot principal no Telegram em uma nova aba. Confira o destinatário antes de continuar.";
    });
  }
  if (supportLink) {
    document.querySelectorAll("[data-support-status]").forEach((element) => {
      element.textContent = "O link abre o contato configurado no Telegram em uma nova aba. Não compartilhe senhas ou tokens.";
    });
  }

  dialog.querySelectorAll(".dialog-close, .dialog-dismiss").forEach((button) => {
    button.addEventListener("click", () => dialog.close());
  });
  dialog.addEventListener("close", () => {
    document.body.classList.remove("dialog-open");
    if (dialogTrigger && dialogTrigger.isConnected) dialogTrigger.focus();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
      dialog.close();
    }
  });

  const menuToggle = document.querySelector(".menu-toggle");
  const nav = document.getElementById("primary-nav");
  function closeMenu(returnFocus = false) {
    nav.classList.remove("is-open");
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Abrir menu");
    if (returnFocus) menuToggle.focus();
  }
  menuToggle.hidden = false;
  document.documentElement.classList.add("menu-ready");
  menuToggle.addEventListener("click", () => {
    if (nav.classList.contains("is-open")) {
      closeMenu();
    } else {
      nav.classList.add("is-open");
      menuToggle.setAttribute("aria-expanded", "true");
      menuToggle.setAttribute("aria-label", "Fechar menu");
      nav.querySelector("a").focus();
    }
  });
  nav.querySelectorAll("a").forEach((anchor) => {
    anchor.addEventListener("click", () => {
      if (!nav.classList.contains("is-open")) return;
      closeMenu();
      const target = document.getElementById(anchor.hash.slice(1));
      if (target) {
        target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      }
    });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && nav.classList.contains("is-open") && !dialog.open) closeMenu(true);
  });
  document.addEventListener("click", (event) => {
    if (nav.classList.contains("is-open") && !nav.contains(event.target) && !menuToggle.contains(event.target)) closeMenu();
  });

  const tablist = document.querySelector(".experience-tabs");
  const tabs = Array.from(tablist.querySelectorAll("[role='tab']"));
  function selectTab(selected, moveFocus = false) {
    tabs.forEach((tab) => {
      const active = tab === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      const panel = document.getElementById(tab.getAttribute("aria-controls"));
      panel.hidden = !active;
      panel.setAttribute("role", "tabpanel");
      panel.tabIndex = 0;
    });
    if (moveFocus) selected.focus();
  }
  tablist.hidden = false;
  selectTab(tabs[window.location.hash === "#panel-games" ? 1 : 0]);
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      if (next !== undefined) {
        event.preventDefault();
        selectTab(tabs[next], true);
      }
    });
  });

  function revealHashTarget() {
    const hash = window.location.hash;
    if (hash === "#privacidade" || hash === "#termos") {
      const details = document.getElementById(hash.slice(1));
      details.open = true;
      details.scrollIntoView({ block: "start" });
    }
    if (hash === "#panel-games" || hash === "#panel-cases") {
      const target = hash === "#panel-games" ? 1 : 0;
      selectTab(tabs[target]);
      document.getElementById(hash.slice(1)).scrollIntoView({ block: "start" });
    }
  }
  window.addEventListener("hashchange", revealHashTarget);
  revealHashTarget();
})();
