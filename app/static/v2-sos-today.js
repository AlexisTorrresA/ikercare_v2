(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const escapeHtml = value => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function patientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function selectedDate() {
    return $("#selectedDate")?.value || "";
  }

  function localDateTimeForSelectedDay() {
    const date = selectedDate();
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    return `${date}T${hh}:${mm}`;
  }

  function timeOnly(value) {
    if (!value) return "";
    const match = String(value).match(/T(\d{2}:\d{2})/);
    return match ? match[1] : value;
  }

  function toast(message, error = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", error);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  function ensureContainer() {
    let card = $("#sosMedicationCard");
    if (card) return card;
    const medicationList = $("#medicationList");
    const regularCard = medicationList?.closest("article.card");
    if (!regularCard) return null;
    card = document.createElement("article");
    card.id = "sosMedicationCard";
    card.className = "card hidden";
    card.innerHTML = `
      <div class="card-head">
        <div>
          <h2>Medicamentos SOS</h2>
          <p class="muted" style="margin:4px 0 0">Solo se registran cuando se administran.</p>
        </div>
      </div>
      <div id="sosMedicationList" class="stack"></div>`;
    regularCard.insertAdjacentElement("afterend", card);
    return card;
  }

  async function render() {
    const pid = patientId();
    const date = selectedDate();
    const card = ensureContainer();
    if (!pid || !date || !card) return;
    const root = $("#sosMedicationList", card);
    try {
      const data = await api(`/api/v2/patients/${pid}/medications-sos-day?date=${encodeURIComponent(date)}`);
      const items = data.medications || [];
      card.classList.toggle("hidden", items.length === 0);
      if (!items.length) {
        root.innerHTML = "";
        return;
      }
      root.innerHTML = items.map(item => {
        const details = [item.dose, item.route, item.purpose].filter(Boolean).join(" · ");
        const uses = (item.uses || []).map(use => `
          <div class="muted" style="margin-top:6px"><strong>Usado ${escapeHtml(timeOnly(use.occurred_at))}</strong>${use.notes && use.notes !== "Administración SOS registrada" ? ` · ${escapeHtml(use.notes)}` : ""}</div>`).join("");
        return `<div class="med-row" data-sos-medication="${item.id}">
          <div class="med-main">
            <div class="med-title"><strong>${escapeHtml(item.name)}</strong>${item.dose ? ` <span>${escapeHtml(item.dose)}</span>` : ""} <span class="badge">SOS</span></div>
            <div class="muted">${escapeHtml(details)}</div>
            ${uses || `<small class="muted">Sin uso registrado este día.</small>`}
          </div>
          ${data.can_edit ? `<button type="button" class="secondary small register-sos-use" data-id="${item.id}" data-name="${escapeHtml(item.name)}">Registrar uso</button>` : ""}
        </div>`;
      }).join("");

      root.querySelectorAll(".register-sos-use").forEach(button => {
        button.addEventListener("click", () => registerUse(Number(button.dataset.id), button.dataset.name || "medicamento"));
      });
    } catch (error) {
      card.classList.remove("hidden");
      root.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
    }
  }

  async function registerUse(medicationId, name) {
    const note = prompt(`Registrar uso SOS de ${name}.\n\nObservación opcional:`, "");
    if (note === null) return;
    try {
      await api(`/api/v2/patients/${patientId()}/medications/${medicationId}/sos-use`, {
        method: "POST",
        body: JSON.stringify({
          occurred_at: localDateTimeForSelectedDay(),
          notes: note.trim() || null,
        }),
      });
      toast("Uso SOS registrado correctamente.");
      await render();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function bindRefreshes() {
    $("#selectedDate")?.addEventListener("change", () => setTimeout(render, 80));
    $("#patientSelect")?.addEventListener("change", () => setTimeout(render, 180));
    document.addEventListener("click", event => {
      if (event.target.closest('[data-nav="today"]')) setTimeout(render, 120);
    });
    const medicationList = $("#medicationList");
    if (medicationList) new MutationObserver(() => setTimeout(render, 80)).observe(medicationList, { childList: true, subtree: true });
  }

  function init() {
    ensureContainer();
    bindRefreshes();
    setTimeout(render, 450);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
