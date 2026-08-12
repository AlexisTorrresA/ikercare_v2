(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  let refreshTimer = null;
  let pendingForce = false;
  const eventCache = new Map();

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

  function localDateTimeValue(date = new Date()) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
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

  function chemoCard(chemoId) {
    const root = $("#chemoList");
    if (!root) return null;
    return root.querySelector(`[data-kind="chemo"][data-id="${chemoId}"], .stable-care-card.chemo[data-id="${chemoId}"], .persistent-chemo-card[data-id="${chemoId}"]`);
  }

  function ensureCreateDialog() {
    let dialog = $("#chemoEvolutionCreateDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "chemoEvolutionCreateDialog";
    dialog.innerHTML = `
      <form id="chemoEvolutionCreateForm" class="dialog-form">
        <div class="dialog-head">
          <h2>Registrar evolución posterior</h2>
          <button type="button" class="icon-btn" data-close-chemo-evolution-create aria-label="Cerrar">×</button>
        </div>
        <input type="hidden" name="chemo_id">
        <label>Fecha y hora<input name="occurred_at" type="datetime-local" required></label>
        <label>Tipo de evento
          <select name="event_type">${EVENT_TYPES.map(value => `<option>${esc(value)}</option>`).join("")}</select>
        </label>
        <label>Descripción / observación<textarea name="description"></textarea></label>
        <button type="submit" class="primary">Guardar evento</button>
      </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-chemo-evolution-create]")) dialog.close();
    });
    $("#chemoEvolutionCreateForm", dialog).addEventListener("submit", saveCreate);
    return dialog;
  }

  function openCreate(chemoId) {
    const dialog = ensureCreateDialog();
    const form = $("#chemoEvolutionCreateForm", dialog);
    form.reset();
    form.elements.chemo_id.value = String(chemoId);
    form.elements.occurred_at.value = localDateTimeValue();
    dialog.showModal();
  }

  async function saveCreate(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const chemoId = Number(form.elements.chemo_id.value);
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${chemoId}/events`, {
        method: "POST",
        body: JSON.stringify({
          occurred_at: form.elements.occurred_at.value,
          event_type: form.elements.event_type.value,
          description: form.elements.description.value.trim() || null,
        }),
      });
      form.closest("dialog")?.close();
      toast("Evolución de quimioterapia registrada.");
      await refreshChemo(chemoId, true);
    } catch (error) {
      toast(error.message, true);
    }
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
      await refreshChemo(chemoId, true);
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function removeEvent(chemoId, eventId) {
    if (!confirm("¿Eliminar este evento de quimioterapia?")) return;
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${chemoId}/events/${eventId}`, { method: "DELETE" });
      toast("Evento de quimioterapia eliminado correctamente.");
      await refreshChemo(chemoId, true);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function ensureEvolutionBlock(card, chemoId) {
    let root = $(".chemo-evolution-list", card);
    if (root) return root;

    const body = $(".care-record-body", card);
    if (!body) return null;

    const section = document.createElement("div");
    section.className = "chemo-evolution";
    section.innerHTML = `
      <div class="chemo-evolution-head">
        <strong>Evolución posterior</strong>
        <button type="button" class="small secondary chemo-evolution-add-persistent">+ Registrar evolución</button>
      </div>
      <div class="chemo-evolution-list"><span class="muted">Cargando evolución…</span></div>`;
    body.appendChild(section);
    $(".chemo-evolution-add-persistent", section)?.addEventListener("click", () => openCreate(chemoId));
    return $(".chemo-evolution-list", section);
  }

  function renderEvents(card, chemoId, events) {
    const root = ensureEvolutionBlock(card, chemoId);
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

  async function refreshChemo(chemoId, force = false) {
    let card = chemoCard(chemoId);
    if (!card) return;

    const cached = eventCache.get(chemoId);
    if (cached) renderEvents(card, chemoId, cached);
    else ensureEvolutionBlock(card, chemoId);

    if (cached && !force) return;

    try {
      const events = await api(`/api/v2/patients/${patientId()}/chemo/${chemoId}/events`);
      eventCache.set(chemoId, events);
      card = chemoCard(chemoId);
      if (card) renderEvents(card, chemoId, events);
    } catch (error) {
      card = chemoCard(chemoId);
      const root = card ? ensureEvolutionBlock(card, chemoId) : null;
      if (root && !eventCache.has(chemoId)) {
        root.innerHTML = `<span class="muted">No se pudo cargar la evolución.</span>`;
      }
    }
  }

  async function enhanceAll(force = false) {
    const pid = patientId();
    if (!pid) return;
    const cards = $$("#chemoList [data-kind='chemo'][data-id], #chemoList .stable-care-card.chemo[data-id]");
    const ids = [...new Set(cards.map(card => Number(card.dataset.id || 0)).filter(Boolean))];
    await Promise.all(ids.map(chemoId => refreshChemo(chemoId, force)));
  }

  function scheduleEnhance(delay = 120, force = false) {
    pendingForce = pendingForce || force;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      const doForce = pendingForce;
      pendingForce = false;
      enhanceAll(doForce);
    }, delay);
  }

  function init() {
    ensureCreateDialog();
    ensureEditDialog();
    const root = $("#chemoList");
    if (root) {
      new MutationObserver(mutations => {
        const changedChemoCards = mutations.some(mutation =>
          [...mutation.addedNodes].some(node =>
            node instanceof Element &&
            (node.matches?.("[data-kind='chemo'][data-id], .stable-care-card.chemo[data-id]") ||
              node.querySelector?.("[data-kind='chemo'][data-id], .stable-care-card.chemo[data-id]"))
          )
        );
        if (changedChemoCards) scheduleEnhance(100, false);
      }).observe(root, { childList: true });
    }

    $("#patientSelect")?.addEventListener("change", () => {
      eventCache.clear();
      scheduleEnhance(350, true);
    });

    document.addEventListener("click", event => {
      if (event.target.closest('[data-app-nav="chemo"], [data-app-nav="care"], [data-nav="care"]')) {
        scheduleEnhance(430, false);
      }
    });

    scheduleEnhance(500, true);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
