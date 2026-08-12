(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  let refreshTimer = null;

  const EVENT_TYPES = [
    "Náuseas",
    "Vómitos",
    "Fiebre",
    "Dolor",
    "Somnolencia",
    "Irritabilidad",
    "Falta de apetito",
    "Diarrea",
    "Estreñimiento",
    "Convulsión",
    "Cambios de presión",
    "Cambios de saturación",
    "Otro",
  ];

  function patientId() {
    return Number($("#patientSelect")?.value || 0) || null;
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function toast(message, error = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", error);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3400);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) {
      headers.set("X-CSRF-Token", csrf);
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  function ensureEditDialog() {
    let dialog = $("#chemoEventEditDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "chemoEventEditDialog";
    dialog.innerHTML = `
      <form id="chemoEventEditForm" class="dialog-form">
        <div class="dialog-head">
          <h2>Modificar evento de quimioterapia</h2>
          <button type="button" class="icon-btn" data-close-chemo-event-edit aria-label="Cerrar">×</button>
        </div>
        <input type="hidden" name="chemo_id">
        <input type="hidden" name="event_id">
        <label>Fecha y hora<input name="occurred_at" type="datetime-local" required></label>
        <label>Tipo de evento
          <select name="event_type">${EVENT_TYPES.map(value => `<option>${esc(value)}</option>`).join("")}</select>
        </label>
        <label>Descripción / observación<textarea name="description"></textarea></label>
        <button type="submit" class="primary">Guardar cambios</button>
      </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-chemo-event-edit]")) dialog.close();
    });
    $("#chemoEventEditForm", dialog).addEventListener("submit", saveEdit);
    return dialog;
  }

  function openEdit(chemoId, event) {
    const dialog = ensureEditDialog();
    const form = $("#chemoEventEditForm", dialog);
    form.reset();
    form.elements.chemo_id.value = String(chemoId);
    form.elements.event_id.value = String(event.id);
    form.elements.occurred_at.value = String(event.occurred_at || "").slice(0, 16);
    form.elements.event_type.value = EVENT_TYPES.includes(event.event_type) ? event.event_type : "Otro";
    form.elements.description.value = event.description || "";
    dialog.showModal();
  }

  async function saveEdit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const chemoId = Number(form.elements.chemo_id.value);
    const eventId = Number(form.elements.event_id.value);
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${chemoId}/events/${eventId}`, {
        method: "PUT",
        body: JSON.stringify({
          occurred_at: form.elements.occurred_at.value,
          event_type: form.elements.event_type.value,
          description: form.elements.description.value.trim() || null,
        }),
      });
      form.closest("dialog")?.close();
      toast("Evento de quimioterapia modificado correctamente.");
      await refreshChemo(chemoId);
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function removeEvent(chemoId, eventId) {
    if (!confirm("¿Eliminar este evento de quimioterapia?")) return;
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${chemoId}/events/${eventId}`, { method: "DELETE" });
      toast("Evento de quimioterapia eliminado correctamente.");
      await refreshChemo(chemoId);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function renderEvents(card, chemoId, events) {
    const root = $(".chemo-evolution-list", card);
    if (!root) return;
    root.innerHTML = events.length ? events.map(item => `
      <div class="chemo-event" data-chemo-event-id="${item.id}">
        <strong>${esc(item.event_type)} · ${esc(new Date(item.occurred_at).toLocaleString("es-CL"))}</strong>
        ${item.description ? `<span>${esc(item.description)}</span>` : ""}
        <div class="record-action-buttons">
          <button type="button" class="text-btn chemo-event-edit" data-id="${item.id}">Editar</button>
          <button type="button" class="text-btn danger-text chemo-event-delete" data-id="${item.id}">Eliminar</button>
        </div>
      </div>`).join("") : `<span class="muted">Sin eventos posteriores registrados.</span>`;

    $$(".chemo-event-edit", root).forEach(button => {
      const item = events.find(row => Number(row.id) === Number(button.dataset.id));
      if (item) button.addEventListener("click", () => openEdit(chemoId, item));
    });
    $$(".chemo-event-delete", root).forEach(button => {
      button.addEventListener("click", () => removeEvent(chemoId, Number(button.dataset.id)));
    });
  }

  async function refreshChemo(chemoId) {
    const card = $(`#chemoList .stable-care-card.chemo[data-id="${chemoId}"]`);
    if (!card || !$(".chemo-evolution-list", card)) return;
    try {
      const events = await api(`/api/v2/patients/${patientId()}/chemo/${chemoId}/events`);
      renderEvents(card, chemoId, events);
    } catch (_) {}
  }

  async function enhanceAll() {
    const pid = patientId();
    if (!pid) return;
    const cards = $$("#chemoList .stable-care-card.chemo");
    for (const card of cards) {
      const chemoId = Number(card.dataset.id || 0);
      if (!chemoId || !$(".chemo-evolution-list", card)) continue;
      await refreshChemo(chemoId);
    }
  }

  function scheduleEnhance() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(enhanceAll, 120);
  }

  function init() {
    ensureEditDialog();
    const root = $("#chemoList");
    if (root) new MutationObserver(scheduleEnhance).observe(root, { childList: true, subtree: true });
    $("#patientSelect")?.addEventListener("change", () => setTimeout(enhanceAll, 200));
    document.addEventListener("click", event => {
      if (event.target.closest('[data-app-nav="chemo"]')) setTimeout(enhanceAll, 180);
    });
    setTimeout(enhanceAll, 500);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
