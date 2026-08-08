(() => {
  "use strict";

  const MORE_SCREENS = new Set(["team", "documents", "share", "account"]);

  const icons = {
    today: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.8 10.6 12 3.8l8.2 6.8v8.7a1.9 1.9 0 0 1-1.9 1.9H5.7a1.9 1.9 0 0 1-1.9-1.9z"/><path d="M9.2 21.2v-6.4h5.6v6.4"/></svg>`,
    chemo: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.2 3.5h5.6v5.7h5.7v5.6h-5.7v5.7H9.2v-5.7H3.5V9.2h5.7z"/></svg>`,
    care: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3.2 12h4l1.8-4.4 3.2 9 2.1-4.6h6.5"/><path d="M20.1 5.6a5.2 5.2 0 0 0-7.4 0L12 6.3l-.7-.7a5.2 5.2 0 1 0-7.4 7.4l.7.7L12 21l7.4-7.3.7-.7a5.2 5.2 0 0 0 0-7.4z"/></svg>`,
    history: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.7"/><path d="M12 7.4v5.1l3.6 2.1"/></svg>`,
    more: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>`,
    team: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3.2"/><path d="M3.4 19c.5-3.6 2.4-5.4 5.6-5.4s5.1 1.8 5.6 5.4"/><circle cx="17.2" cy="9" r="2.4"/><path d="M15.8 14.2c2.8-.4 4.4 1.2 4.8 4"/></svg>`,
    documents: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8.1l4 4v13H6z"/><path d="M14 3.7v4.2h4.1M9 12h6M9 15.5h6"/></svg>`,
    share: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="18" cy="5.5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="18.5" r="2.5"/><path d="m8.2 10.8 7.6-4.1M8.2 13.2l7.6 4.1"/></svg>`,
    account: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M4.8 20c.7-4.2 3.1-6.3 7.2-6.3s6.5 2.1 7.2 6.3"/></svg>`,
  };

  function setup() {
    const legacyNav = document.querySelector(".bottom-nav");
    const careScreen = document.querySelector('[data-screen="care"]');
    const chemoList = document.getElementById("chemoList");
    if (!legacyNav || !careScreen || !chemoList || document.querySelector(".app-bottom-nav")) return;

    legacyNav.classList.add("legacy-nav");
    splitChemoScreen(careScreen, chemoList);
    const nav = buildNavigation();
    const more = buildMoreSheet();
    document.body.appendChild(nav);
    document.body.appendChild(more);

    bindNavigation(nav, legacyNav, more);
    observeScreenChanges(nav);
    syncActiveNavigation(nav);
  }

  function splitChemoScreen(careScreen, chemoList) {
    if (document.querySelector('[data-screen="chemo"]')) return;
    const chemoCard = chemoList.closest("article.card");
    if (!chemoCard) return;

    chemoCard.classList.add("chemo-feature-card");
    const chemoScreen = document.createElement("section");
    chemoScreen.className = "screen chemo-screen";
    chemoScreen.dataset.screen = "chemo";
    chemoScreen.innerHTML = `
      <div class="screen-title chemo-title">
        <div>
          <span class="section-kicker">Acceso rápido</span>
          <h1>Quimioterapia</h1>
          <p class="muted">Ciclos, horarios, estado y efectos registrados.</p>
        </div>
      </div>`;
    chemoScreen.appendChild(chemoCard);
    careScreen.parentNode.insertBefore(chemoScreen, careScreen);

    const careTitle = careScreen.querySelector(".screen-title h1");
    const careCopy = careScreen.querySelector(".screen-title p");
    if (careTitle) careTitle.textContent = "Cuidados";
    if (careCopy) careCopy.textContent = "Signos vitales y crisis o eventos del paciente.";
  }

  function navButton(name, label, icon, extra = "") {
    return `<button type="button" class="app-nav-btn ${extra}" data-app-nav="${name}" aria-label="${label}">
      <span class="app-nav-icon">${icon}</span>
      <span class="app-nav-label">${label}</span>
    </button>`;
  }

  function buildNavigation() {
    const nav = document.createElement("nav");
    nav.className = "app-bottom-nav";
    nav.setAttribute("aria-label", "Navegación principal");
    nav.innerHTML = [
      navButton("today", "Hoy", icons.today),
      navButton("chemo", "Quimio", icons.chemo, "chemo-nav-btn"),
      navButton("care", "Cuidados", icons.care),
      navButton("history", "Historia", icons.history),
      navButton("more", "Más", icons.more),
    ].join("");
    return nav;
  }

  function moreItem(screen, title, subtitle, icon) {
    return `<button type="button" class="more-item" data-more-nav="${screen}">
      <span class="more-item-icon">${icon}</span>
      <span class="more-item-copy"><strong>${title}</strong><small>${subtitle}</small></span>
      <span class="more-item-arrow" aria-hidden="true">›</span>
    </button>`;
  }

  function buildMoreSheet() {
    const dialog = document.createElement("dialog");
    dialog.id = "moreNavigationSheet";
    dialog.className = "more-sheet";
    dialog.setAttribute("aria-labelledby", "moreNavigationTitle");
    dialog.innerHTML = `
      <div class="more-sheet-inner">
        <div class="sheet-handle" aria-hidden="true"></div>
        <div class="more-sheet-head">
          <div>
            <span class="section-kicker">IkerCare</span>
            <h2 id="moreNavigationTitle">Más opciones</h2>
          </div>
          <button type="button" class="more-close" data-close-more aria-label="Cerrar">×</button>
        </div>
        <div class="more-grid">
          ${moreItem("team", "Equipo tratante", "Médicos, especialidades y cuidadores", icons.team)}
          ${moreItem("documents", "Exámenes e informes", "PDF, imágenes y texto extraído", icons.documents)}
          ${moreItem("share", "Resumen y compartir", "QR temporal y resumen clínico", icons.share)}
          ${moreItem("account", "Paciente y cuenta", "Perfil, privacidad y seguridad", icons.account)}
        </div>
        <p class="more-sheet-foot">Los accesos se mantienen separados por paciente y permisos.</p>
      </div>`;
    return dialog;
  }

  function bindNavigation(nav, legacyNav, more) {
    nav.addEventListener("click", event => {
      const button = event.target.closest("[data-app-nav]");
      if (!button) return;
      const name = button.dataset.appNav;
      if (name === "more") {
        if (!more.open) more.showModal();
        syncActiveNavigation(nav, "more");
        return;
      }
      navigate(name, legacyNav, nav, more);
    });

    more.addEventListener("click", event => {
      const item = event.target.closest("[data-more-nav]");
      if (item) {
        navigate(item.dataset.moreNav, legacyNav, nav, more);
        return;
      }
      if (event.target.closest("[data-close-more]")) more.close();
    });

    more.addEventListener("click", event => {
      if (event.target === more) more.close();
    });

    more.addEventListener("close", () => syncActiveNavigation(nav));
  }

  function navigate(name, legacyNav, nav, more) {
    if (name === "chemo") {
      document.querySelectorAll(".screen").forEach(screen => {
        screen.classList.toggle("active", screen.dataset.screen === "chemo");
      });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } else {
      const legacyButton = legacyNav.querySelector(`[data-nav="${name}"]`);
      if (legacyButton) legacyButton.click();
      else {
        document.querySelectorAll(".screen").forEach(screen => {
          screen.classList.toggle("active", screen.dataset.screen === name);
        });
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    }
    if (more.open) more.close();
    localStorage.setItem("ikercare_v2_screen", name);
    syncActiveNavigation(nav, name);
  }

  function activeScreenName() {
    return document.querySelector(".screen.active")?.dataset.screen || "today";
  }

  function syncActiveNavigation(nav, forcedName = null) {
    const activeName = forcedName || activeScreenName();
    nav.querySelectorAll(".app-nav-btn").forEach(button => {
      const name = button.dataset.appNav;
      const isMore = name === "more";
      const active = isMore ? MORE_SCREENS.has(activeName) || activeName === "more" : name === activeName;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
  }

  function observeScreenChanges(nav) {
    let scheduled = false;
    const observer = new MutationObserver(mutations => {
      if (!mutations.some(m => m.type === "attributes" && m.attributeName === "class")) return;
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        syncActiveNavigation(nav);
      });
    });
    document.querySelectorAll(".screen").forEach(screen => observer.observe(screen, { attributes: true }));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setup, { once: true });
  } else {
    setup();
  }
})();
