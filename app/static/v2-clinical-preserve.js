(() => {
  "use strict";
  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function patientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function message(text, error = false) {
    const toast = $("#toast");
    if (!toast) return;
    toast.textContent = text;
    toast.classList.toggle("error", error);
    toast.classList.remove("hidden");
    clearTimeout(message.timer);
    message.timer = setTimeout(() => toast.classList.add("hidden"), 3200);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) headers.set("X-CSRF-Token", csrf);
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  async function preserveDeleteButtons() {
    const root = $("#configuredMedicationList");
    const id = patientId();
    if (!root || !id || !root.querySelector(".ext-edit-med")) return;
    let medications;
    try {
      medications = await api(`/api/v2/patients/${id}/medications`);
    } catch (_) {
      return;
    }
    const byId = new Map(medications.map(item => [Number(item.id), item]));
    $$(".ext-edit-med", root).forEach(editButton => {
      const medicationId = Number(editButton.dataset.id);
      const medication = byId.get(medicationId);
      const row = editButton.closest(".button-row");
      if (!row || row.querySelector(`.preserved-delete-med[data-id="${medicationId}"]`)) return;
      if (!medication || medication.active === false) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "danger preserved-delete-med";
      button.dataset.id = String(medicationId);
      button.textContent = "Eliminar";
      button.addEventListener("click", async () => {
        if (!confirm(`¿Eliminar ${medication.name} del esquema activo? El historial de administraciones se conservará.`)) return;
        try {
          await api(`/api/v2/patients/${id}/medications/${medicationId}`, { method: "DELETE" });
          message("Medicamento retirado del esquema activo. El historial se conservó.");
          location.reload();
        } catch (error) {
          message(error.message, true);
        }
      });
      row.appendChild(button);
    });
  }

  const root = $("#configuredMedicationList");
  if (root) new MutationObserver(() => setTimeout(preserveDeleteButtons, 40)).observe(root, { childList: true, subtree: true });
  document.addEventListener("click", event => {
    if (event.target.closest("#manageMedicationsBtn")) setTimeout(preserveDeleteButtons, 350);
  });
})();
