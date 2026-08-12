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
    card.className = "card sos-medication-section hidden";
    card.innerHTML = `
      <div class="card-head sos-section-head">
        <div>
          <h2>Medicamentos SOS</h2>
          <p class="muted">Solo se registran cuando se administran.</p>
        </div>
      </div>
      <div id="sosMedicationList" class="sos-medication-list"></div>`;
    regularCard.insertAdjacentElement("afterend", card);
    return card;
  }

  function ensureSosDialog() {
    let dialog = $("#sosUseDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "sosUseDialog";
    dialog.innerHTML = `
      <form id="sosUseForm" class="dialog-form">
        <div class="dialog-head">
          <div>
            <h2>Registrar medicamento SOS</h2>
            <p id="sosUseMedicationName" class="muted" style="margin:4px 0 0"></p>
          </div>
          <button type="button" class="icon-btn" data-close-sos-use aria-label="Cerrar">×</button>
        </div>
        <input type="hidden" name="medication_id">
        <label>Fecha y hora
          <input name="occurred_at" type="datetime-local" required>
        </label>
        <label>Observación opcional
          <textarea name="notes" rows="4" placeholder="Ej.: motivo del uso, cómo estaba el paciente o alguna observación."></textarea>
        </label>
        <div class="button-row">
          <button type="button" class="secondary" data-close-sos-use>Cancelar</button>
          <button type="submit" class="primary">Registrar uso</button>
        </div>
      </form>`;
    document.body.appendChild(dialog);

    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-sos-use]")) dialog.close();
    });
    $("#sosUseForm", dialog)?.addEventListener("submit", submitSosUse);
    return dialog;
  }

  function openSosDialog(medicationId, name) {
    const dialog = ensureSosDialog();
    const form = $("#sosUseForm", dialog);
    form.reset();
    form.elements.medication_id.value = String(medicationId);
    form.elements.occurred_at.value = localDateTimeForSelectedDay();
    $("#sosUseMedicationName", dialog).textContent = name;
    dialog.showModal();
    requestAnimationFrame(() => form.elements.occurred_at.focus());
  }

  async function submitSosUse(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const medicationId = Number(form.elements.medication_id.value);
    const occurredAt = form.elements.occurred_at.value;
    if (!medicationId || !occurredAt) {
      toast("Selecciona la fecha y hora del uso SOS.", true);
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await api(`/api/v2/patients/${patientId()}/medications/${medicationId}/sos-use`, {
        method: "POST",
        body: JSON.stringify({
          occurred_at: occurredAt,
          notes: form.elements.notes.value.trim() || null,
        }),
      });
      form.closest("dialog")?.close();
      toast("Uso SOS registrado correctamente.");
      await render();
    } catch (error) {
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
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
        const uses = item.uses || [];
        const usedToday = uses.length > 0;
        const usesHtml = uses.map(use => `
          <div class="sos-use-entry">
            <strong>Usado ${escapeHtml(timeOnly(use.occurred_at))}</strong>
            ${use.notes && use.notes !== "Administración SOS registrada" ? `<span>${escapeHtml(use.notes)}</span>` : ""}
          </div>`).join("");
        return `<article class="sos-med-card" data-sos-medication="${item.id}">
          <div class="sos-accent-rail"><span>SOS</span></div>
          <div class="sos-med-content">
            <div class="sos-med-top">
              <div class="sos-med-copy">
                <h3>${escapeHtml(item.name)}</h3>
                <div class="sos-med-pills">
                  ${item.dose ? `<span class="sos-pill dose">Dosis: ${escapeHtml(item.dose)}</span>` : ""}
                  ${item.route ? `<span class="sos-pill route">${escapeHtml(item.route)}</span>` : ""}
                  <span class="sos-pill sos-label">SOS / según necesidad</span>
                </div>
              </div>
              <span class="sos-state ${usedToday ? "used" : "unused"}">${usedToday ? "Usado hoy" : "Sin uso hoy"}</span>
            </div>
            ${item.purpose ? `<p class="sos-purpose"><strong>Para qué sirve:</strong> ${escapeHtml(item.purpose)}</p>` : ""}
            <div class="sos-uses">${usesHtml || `<span class="sos-empty-use">Sin uso registrado este día.</span>`}</div>
            ${data.can_edit ? `<button type="button" class="register-sos-use" data-id="${item.id}" data-name="${escapeHtml(item.name)}">Registrar uso</button>` : ""}
          </div>
        </article>`;
      }).join("");

      root.querySelectorAll(".register-sos-use").forEach(button => {
        button.addEventListener("click", () => openSosDialog(Number(button.dataset.id), button.dataset.name || "medicamento"));
      });
    } catch (error) {
      card.classList.remove("hidden");
      root.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
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
    ensureSosDialog();
    bindRefreshes();
    setTimeout(render, 450);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
