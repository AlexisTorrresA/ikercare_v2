(() => {
  "use strict";

  const app = document.getElementById("app");
  const csrf = app?.dataset.csrf || "";
  const medicationRoot = document.getElementById("medicationList");
  if (!app || !medicationRoot) return;

  let observer = null;
  let scheduled = false;
  let refreshToken = 0;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function displayTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace("T", " ");
    return date.toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" });
  }

  function currentPatientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function currentDate() {
    return $("#selectedDate")?.value || new Date().toISOString().slice(0, 10);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) {
      headers.set("X-CSRF-Token", csrf);
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function ensureSummaryRoot() {
    let root = $("#visualDaySummary");
    if (root) return root;
    root = document.createElement("section");
    root.id = "visualDaySummary";
    root.className = "visual-day-summary";
    const syncNotice = $("#syncNotice");
    const screenTitle = $('[data-screen="today"] .screen-title');
    (syncNotice || screenTitle)?.insertAdjacentElement("afterend", root);
    return root;
  }

  function renderSummary(data) {
    const root = ensureSummaryRoot();
    if (!root) return;

    const medications = data.medications || [];
    const taken = medications.filter(item => item.status === "taken").length;
    const skipped = medications.filter(item => item.status === "skipped").length;
    const pending = Math.max(medications.length - taken - skipped, 0);
    const chemo = (data.chemo || []).length;
    const vitals = (data.vitals || []).length;
    const crises = (data.crises || []).length;
    const percent = medications.length ? Math.round((taken / medications.length) * 100) : 0;
    const patientName = $("#patientSelect")?.selectedOptions?.[0]?.textContent?.split(" · ")[0] || "Paciente";

    root.innerHTML = `
      <article class="visual-summary-card">
        <div class="visual-summary-head">
          <div>
            <span class="visual-summary-kicker">Resumen del día</span>
            <h2>${escapeHtml(patientName)}</h2>
            <p><strong>${taken} de ${medications.length}</strong> medicamentos administrados</p>
          </div>
          <div class="visual-progress" style="--progress:${percent}%" aria-label="${percent}% completado">
            <div><strong>${percent}%</strong><span>completado</span></div>
          </div>
        </div>

        <div class="visual-status-strip">
          <span class="status-chip meds">${taken}/${medications.length} tomados</span>
          <span class="status-chip pending">${pending} pendientes</span>
          <span class="status-chip skipped">${skipped} omitidos</span>
        </div>

        <div class="visual-metrics-grid">
          <button type="button" class="visual-metric medication" data-summary-target="medications">
            <span class="metric-icon">Rx</span><strong>${taken}/${medications.length}</strong><small>Medicamentos</small>
          </button>
          <button type="button" class="visual-metric chemo" data-summary-target="chemo">
            <span class="metric-icon">✚</span><strong>${chemo}</strong><small>Quimios</small>
          </button>
          <button type="button" class="visual-metric vital" data-summary-target="care">
            <span class="metric-icon">♥</span><strong>${vitals}</strong><small>Signos</small>
          </button>
          <button type="button" class="visual-metric event" data-summary-target="care">
            <span class="metric-icon">!</span><strong>${crises}</strong><small>Eventos</small>
          </button>
        </div>
      </article>`;
  }

  function pill(text, kind) {
    if (!text) return "";
    return `<span class="visual-med-pill ${kind}">${escapeHtml(text)}</span>`;
  }

  function enhanceMedicationRows(data) {
    const rows = $$(".med-row", medicationRoot);
    const items = data.medications || [];
    if (!rows.length || !items.length) return;

    rows.forEach((row, index) => {
      const item = items[index];
      if (!item) return;

      const checkButton = $(".check-btn", row);
      const skipButton = $(".skip-btn", row);
      if (!checkButton || !skipButton) return;

      const med = item.medication || {};
      const taken = item.status === "taken";
      const skipped = item.status === "skipped";
      const pending = !taken && !skipped;
      const statusLabel = taken ? "Tomado" : skipped ? "Omitido" : "Pendiente";
      const helper = taken && item.actual_time
        ? `Registrado: ${displayTime(item.actual_time)}`
        : skipped
          ? "Marcado como omitido"
          : "Aún no registrado";

      row.classList.add("visual-med-card");
      row.classList.toggle("done", taken);
      row.classList.toggle("skipped", skipped);
      row.classList.toggle("pending", pending);
      row.dataset.visualEnhanced = String(item.schedule_id || index);

      const rail = document.createElement("div");
      rail.className = "visual-time-rail";
      rail.innerHTML = `<span>${escapeHtml(item.time || "--:--")}</span>`;

      const content = document.createElement("div");
      content.className = "visual-med-content";
      content.innerHTML = `
        <div class="visual-med-top">
          <div class="visual-med-copy">
            <h3>${escapeHtml(med.name || "Medicamento")}</h3>
            <div class="visual-med-pills">
              ${pill(med.medication_type, "type")}
              ${pill(med.dose ? `Dosis: ${med.dose}` : "", "dose")}
              ${pill(med.route, "route")}
              ${pill(med.frequency, "frequency")}
            </div>
          </div>
          <div class="visual-check-slot"></div>
        </div>
        <div class="visual-med-status-row">
          <span class="visual-med-status ${taken ? "taken" : skipped ? "skipped" : "pending"}">${statusLabel}</span>
          <span class="visual-med-helper">${escapeHtml(helper)}</span>
        </div>
        ${med.purpose ? `<p class="visual-med-purpose"><strong>Para qué sirve:</strong> ${escapeHtml(med.purpose)}</p>` : ""}
        ${med.instructions ? `<p class="visual-med-instructions">${escapeHtml(med.instructions)}</p>` : ""}
        <div class="visual-med-actions"></div>`;

      row.replaceChildren(rail, content);
      $(".visual-check-slot", content).appendChild(checkButton);
      $(".visual-med-actions", content).appendChild(skipButton);
    });

    medicationRoot.closest(".card")?.classList.add("visual-medications-section");
  }

  async function refreshVisuals() {
    const patientId = currentPatientId();
    if (!patientId) return;
    const date = currentDate();
    const token = ++refreshToken;

    try {
      const data = await api(`/api/v2/patients/${patientId}/day?date=${encodeURIComponent(date)}`);
      if (token !== refreshToken) return;

      observer?.disconnect();
      renderSummary(data);
      enhanceMedicationRows(data);
      observeMedicationRoot();
    } catch (_) {
      observeMedicationRoot();
    }
  }

  function scheduleRefresh(delay = 60) {
    if (scheduled) return;
    scheduled = true;
    window.setTimeout(() => {
      scheduled = false;
      refreshVisuals();
    }, delay);
  }

  function observeMedicationRoot() {
    if (!observer) {
      observer = new MutationObserver(() => scheduleRefresh());
    }
    observer.observe(medicationRoot, { childList: true, subtree: true });
  }

  function bindSummaryNavigation() {
    document.addEventListener("click", event => {
      const button = event.target.closest("[data-summary-target]");
      if (!button) return;
      const target = button.dataset.summaryTarget;
      if (target === "medications") {
        medicationRoot.scrollIntoView({ behavior: "smooth", block: "start" });
        return;
      }
      const navTarget = target === "chemo" ? "chemo" : "care";
      const navButton = document.querySelector(`[data-app-nav="${navTarget}"]`);
      if (navButton) navButton.click();
    });
  }

  $("#patientSelect")?.addEventListener("change", () => scheduleRefresh(180));
  $("#selectedDate")?.addEventListener("change", () => scheduleRefresh(180));
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleRefresh(120);
  });

  bindSummaryNavigation();
  observeMedicationRoot();
  scheduleRefresh(220);
})();
