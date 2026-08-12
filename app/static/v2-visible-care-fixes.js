(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = app.dataset.csrf || "";
  let busyCare = false;
  let busyChemo = false;
  let careTimer = null;
  let chemoTimer = null;

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function patientId() {
    return Number($("#patientSelect")?.value || 0) || null;
  }

  function selectedDate() {
    return $("#selectedDate")?.value || new Date().toLocaleDateString("sv-SE");
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
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  function localDateTimeValue(date = new Date()) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function displayDateTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace("T", " ");
    return date.toLocaleString("es-CL", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function displayTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).slice(11, 16);
    return date.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
  }

  function toast(message, error = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", error);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3300);
  }

  async function renderFoodAndElimination() {
    const id = patientId();
    const foodRoot = $("#foodList");
    const eliminationRoot = $("#eliminationList");
    if (!id || !foodRoot || !eliminationRoot || busyCare) return;
    busyCare = true;
    try {
      const [day, metadata] = await Promise.all([
        api(`/api/v2/patients/${id}/day?date=${encodeURIComponent(selectedDate())}`),
        api(`/api/v2/patients/${id}/food-metadata`).catch(() => ({})),
      ]);
      renderFoodCards(foodRoot, day.food || [], metadata || {});
      renderEliminationCards(eliminationRoot, day.elimination || []);
    } catch (_) {
      // El render base sigue disponible si falla este realce visual.
    } finally {
      busyCare = false;
    }
  }

  function renderFoodCards(root, items, metadata) {
    const order = ["Desayuno", "Colación", "Almuerzo", "Once/Merienda", "Cena", "Alimentación nocturna", "Lactancia/Leche", "Líquidos", "Otro"];
    const groups = new Map();
    for (const item of items) {
      const key = item.meal_type || "Otro";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    }
    const keys = order.filter(key => groups.has(key)).concat([...groups.keys()].filter(key => !order.includes(key)));
    root.innerHTML = items.length ? keys.map(key => `
      <section class="meal-group persistent-care-group">
        <h3 class="meal-group-title">${esc(key)}</h3>
        ${groups.get(key).map(item => `
          <article class="care-detail-card food persistent-care-card">
            <div class="care-card-top">
              <div>
                <span class="care-card-title">${esc(item.item)}</span>
                <small class="care-card-date">${esc(displayDateTime(item.occurred_at))}</small>
              </div>
              <time>${esc(displayTime(item.occurred_at))}</time>
            </div>
            <div class="care-tags">
              ${item.amount != null ? `<span>${esc(item.amount)} ${esc(item.unit || "")}</span>` : ""}
              ${metadata[String(item.id)]?.portion ? `<span>${esc(metadata[String(item.id)].portion)}</span>` : ""}
              ${item.vomiting ? `<span class="care-alert-chip">Vómito</span>` : item.tolerated === false ? `<span class="care-alert-chip">No toleró</span>` : item.tolerated === true ? `<span>Toleró</span>` : ""}
            </div>
            ${item.notes ? `<p><strong>Observación:</strong> ${esc(item.notes)}</p>` : ""}
            <div class="record-action-buttons">
              <button type="button" class="text-btn ext-edit-food" data-id="${item.id}">Editar</button>
              <button type="button" class="text-btn danger-text ext-delete-food" data-id="${item.id}">Eliminar</button>
            </div>
          </article>`).join("")}
      </section>`).join("") : `<p class="empty">Sin registros.</p>`;
  }

  function renderEliminationCards(root, items) {
    const labels = { dry: "Seco", wet: "Pipí", soiled: "Deposición", wet_and_soiled: "Pipí + deposición" };
    const amounts = { small: "Poca", medium: "Media", large: "Mucha", none: "Nada" };
    root.innerHTML = items.length ? items.map(item => `
      <article class="care-detail-card elimination persistent-care-card">
        <div class="care-card-top">
          <div>
            <span class="care-card-title">${esc(labels[item.diaper_status] || item.diaper_status || "Registro")}</span>
            <small class="care-card-date">${esc(displayDateTime(item.occurred_at))}</small>
          </div>
          <time>${esc(displayTime(item.occurred_at))}</time>
        </div>
        <div class="care-tags">
          ${item.urine_amount ? `<span><strong>Orina:</strong> ${esc(amounts[item.urine_amount] || item.urine_amount)}</span>` : ""}
          ${item.urine_color ? `<span><strong>Color:</strong> ${esc(item.urine_color)}</span>` : ""}
          ${item.stool_description ? `<span><strong>Deposición:</strong> ${esc(item.stool_description)}</span>` : ""}
        </div>
        ${item.notes ? `<p><strong>Observación:</strong> ${esc(item.notes)}</p>` : ""}
        <div class="record-action-buttons">
          <button type="button" class="text-btn record-edit-btn" data-kind="elimination" data-id="${item.id}">Editar</button>
          <button type="button" class="text-btn danger-text ext-delete-elim" data-id="${item.id}">Eliminar</button>
        </div>
      </article>`).join("") : `<p class="empty">Sin registros.</p>`;
  }

  function ensureChemoEventDialog() {
    if ($("#chemoEventDialog")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "chemoEventDialog";
    dialog.innerHTML = `
      <form id="chemoEventForm" class="dialog-form">
        <div class="dialog-head">
          <h2>Evolución posterior a quimioterapia</h2>
          <button type="button" class="icon-btn" data-close-chemo-event aria-label="Cerrar">×</button>
        </div>
        <input type="hidden" name="chemo_id">
        <label>Fecha y hora<input name="occurred_at" type="datetime-local" required></label>
        <label>Tipo de evento
          <select name="event_type">
            ${["Náuseas","Vómitos","Fiebre","Dolor","Somnolencia","Irritabilidad","Falta de apetito","Diarrea","Estreñimiento","Convulsión","Cambios de presión","Cambios de saturación","Otro"].map(value => `<option>${value}</option>`).join("")}
          </select>
        </label>
        <label>Descripción / observación<textarea name="description"></textarea></label>
        <button class="primary" type="submit">Guardar evento</button>
      </form>`;
    document.body.appendChild(dialog);
    dialog.querySelector("[data-close-chemo-event]").addEventListener("click", () => dialog.close());
    dialog.querySelector("form").addEventListener("submit", saveChemoEvent);
  }

  async function saveChemoEvent(event) {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${form.elements.chemo_id.value}/events`, {
        method: "POST",
        body: JSON.stringify({
          occurred_at: form.elements.occurred_at.value,
          event_type: form.elements.event_type.value,
          description: form.elements.description.value.trim() || null,
        }),
      });
      form.closest("dialog")?.close();
      toast("Evolución de quimioterapia registrada.");
      await renderChemoWithEvolution();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function renderChemoWithEvolution() {
    const id = patientId();
    const root = $("#chemoList");
    if (!id || !root || busyChemo) return;
    busyChemo = true;
    ensureChemoEventDialog();
    try {
      const chemo = await api(`/api/v2/patients/${id}/chemo/all`);
      const rows = await Promise.all(chemo.map(async item => {
        let events = [];
        try { events = await api(`/api/v2/patients/${id}/chemo/${item.id}/events`); } catch (_) {}
        return { item, events };
      }));
      root.innerHTML = rows.length ? rows.map(({ item, events }) => `
        <article class="care-record-card stable-care-card chemo persistent-chemo-card" data-kind="chemo" data-id="${item.id}">
          <div class="care-record-accent"></div>
          <div class="care-record-body">
            <div class="care-record-top">
              <div>
                <strong>${esc(item.name)}</strong>
                <small class="chemo-date-full">${esc(displayDateTime(item.scheduled_at))}</small>
              </div>
              <time>${esc(displayTime(item.scheduled_at))}</time>
            </div>
            <div class="care-record-chips">
              ${item.protocol ? `<span>Protocolo: ${esc(item.protocol)}</span>` : ""}
              ${item.cycle ? `<span>Ciclo: ${esc(item.cycle)}</span>` : ""}
              ${item.status ? `<span>Estado: ${esc(item.status)}</span>` : ""}
            </div>
            ${item.purpose ? `<p><strong>Objetivo:</strong> ${esc(item.purpose)}</p>` : ""}
            ${item.notes ? `<p>${esc(item.notes)}</p>` : ""}
            ${item.adverse_effects ? `<p><strong>Efectos registrados:</strong> ${esc(item.adverse_effects)}</p>` : ""}
            <div class="chemo-evolution">
              <div class="chemo-evolution-head">
                <strong>Evolución posterior</strong>
                <button type="button" class="small secondary add-chemo-event" data-id="${item.id}">+ Registrar evolución</button>
              </div>
              <div class="chemo-evolution-list">
                ${events.length ? events.map(entry => `
                  <div class="chemo-event">
                    <strong>${esc(entry.event_type)}</strong>
                    <time>${esc(displayDateTime(entry.occurred_at))}</time>
                    ${entry.description ? `<span>${esc(entry.description)}</span>` : ""}
                  </div>`).join("") : `<span class="muted">Sin eventos posteriores registrados.</span>`}
              </div>
            </div>
          </div>
          <div class="record-action-buttons">
            <button type="button" class="text-btn stable-edit" data-kind="chemo" data-id="${item.id}">Editar</button>
            <button type="button" class="text-btn danger-text stable-delete" data-kind="chemo" data-id="${item.id}">Eliminar</button>
          </div>
        </article>`).join("") : `<p class="empty">Sin quimioterapia registrada.</p>`;
      $$(".add-chemo-event", root).forEach(button => button.addEventListener("click", () => {
        const form = $("#chemoEventForm");
        form.reset();
        form.elements.chemo_id.value = button.dataset.id;
        form.elements.occurred_at.value = localDateTimeValue();
        $("#chemoEventDialog")?.showModal();
      }));
    } catch (_) {
      // Mantiene el render base si el endpoint no responde.
    } finally {
      busyChemo = false;
    }
  }

  function scheduleCare() {
    clearTimeout(careTimer);
    careTimer = setTimeout(renderFoodAndElimination, 120);
  }

  function scheduleChemo() {
    clearTimeout(chemoTimer);
    chemoTimer = setTimeout(renderChemoWithEvolution, 150);
  }

  function bindActionDelegates() {
    document.addEventListener("click", async event => {
      const foodDelete = event.target.closest(".ext-delete-food");
      if (foodDelete) {
        event.preventDefault();
        if (!confirm("¿Eliminar este registro de comida?")) return;
        try {
          await api(`/api/v2/patients/${patientId()}/food/${foodDelete.dataset.id}`, { method: "DELETE" });
          toast("Registro de comida eliminado.");
          scheduleCare();
        } catch (error) { toast(error.message, true); }
        return;
      }
      const eliminationDelete = event.target.closest(".ext-delete-elim");
      if (eliminationDelete) {
        event.preventDefault();
        if (!confirm("¿Eliminar este registro de pañal/pipí?")) return;
        try {
          await api(`/api/v2/patients/${patientId()}/elimination/${eliminationDelete.dataset.id}`, { method: "DELETE" });
          toast("Registro de pañal/pipí eliminado.");
          scheduleCare();
        } catch (error) { toast(error.message, true); }
      }
    }, true);
  }

  function observeRoots() {
    const food = $("#foodList");
    const elimination = $("#eliminationList");
    const chemo = $("#chemoList");
    if (food) new MutationObserver(() => {
      if (!busyCare && food.querySelector(".mini-row")) scheduleCare();
    }).observe(food, { childList: true });
    if (elimination) new MutationObserver(() => {
      if (!busyCare && elimination.querySelector(".mini-row")) scheduleCare();
    }).observe(elimination, { childList: true });
    if (chemo) new MutationObserver(() => {
      if (!busyChemo && !chemo.querySelector(".chemo-evolution")) scheduleChemo();
    }).observe(chemo, { childList: true, subtree: false });
  }

  function init() {
    ensureChemoEventDialog();
    bindActionDelegates();
    observeRoots();
    $("#selectedDate")?.addEventListener("change", () => setTimeout(renderFoodAndElimination, 180));
    $("#patientSelect")?.addEventListener("change", () => setTimeout(() => {
      renderFoodAndElimination();
      renderChemoWithEvolution();
    }, 420));
    document.addEventListener("click", event => {
      if (event.target.closest('[data-app-nav="today"]')) setTimeout(renderFoodAndElimination, 180);
      if (event.target.closest('[data-app-nav="chemo"]')) setTimeout(renderChemoWithEvolution, 180);
    });
    setTimeout(() => {
      renderFoodAndElimination();
      renderChemoWithEvolution();
    }, 700);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
