(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
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

  function nullable(value) {
    const text = String(value ?? "").trim();
    return text === "" ? null : text;
  }

  function patientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
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
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      let detail = typeof payload === "object" ? payload.detail : payload;
      if (Array.isArray(detail)) detail = detail[0]?.msg || "Revisa los datos ingresados.";
      throw new Error(detail || `Error ${response.status}`);
    }
    return payload;
  }

  function showMessage(message, error = false) {
    const toast = $("#toast");
    if (!toast) {
      alert(message);
      return;
    }
    toast.textContent = message;
    toast.classList.toggle("error", error);
    toast.classList.remove("hidden");
    clearTimeout(showMessage.timer);
    showMessage.timer = setTimeout(() => toast.classList.add("hidden"), 3400);
  }

  function ensureMedicationManager() {
    const account = $('[data-screen="account"]');
    if (!account || $("#medicationManager")) return;

    const panel = document.createElement("article");
    panel.id = "medicationManager";
    panel.className = "card targeted-fix-card";
    panel.innerHTML = `
      <div class="card-head">
        <div>
          <h2>Medicamentos configurados</h2>
          <p>Modifica o elimina medicamentos del paciente seleccionado.</p>
        </div>
      </div>
      <div id="medicationManagerList" class="targeted-med-list"><p class="empty">Cargando…</p></div>`;

    const firstGrid = $(".grid2", account);
    if (firstGrid) firstGrid.insertAdjacentElement("beforebegin", panel);
    else account.appendChild(panel);
  }

  function ensureMedicationDialog() {
    if ($("#medicationEditDialog")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "medicationEditDialog";
    dialog.innerHTML = `
      <form method="dialog" id="medicationEditForm" class="dialog-form">
        <div class="dialog-head"><h2>Editar medicamento</h2><button value="cancel" class="icon-btn" aria-label="Cerrar">×</button></div>
        <input type="hidden" name="id">
        <label>Nombre<input name="name" required></label>
        <label>Tipo<input name="medication_type"></label>
        <label>Para qué sirve<textarea name="purpose"></textarea></label>
        <div class="form-grid">
          <label>Dosis<input name="dose"></label>
          <label>Vía<input name="route"></label>
          <label>Frecuencia<input name="frequency"></label>
          <label>Horas (coma)<input name="times" placeholder="07:00,15:00,23:00"></label>
        </div>
        <label>Indicaciones<textarea name="instructions"></textarea></label>
        <button class="primary" value="default">Guardar cambios</button>
      </form>`;
    document.body.appendChild(dialog);

    $("#medicationEditForm").addEventListener("submit", async event => {
      if (event.submitter?.value === "cancel") return;
      event.preventDefault();
      const form = event.currentTarget;
      const pid = patientId();
      if (!pid) return;
      const id = Number(form.elements.id.value);
      const payload = {
        name: form.elements.name.value.trim(),
        generic_name: null,
        medication_type: form.elements.medication_type.value.trim() || "Medicamento",
        purpose: nullable(form.elements.purpose.value),
        dose: nullable(form.elements.dose.value),
        route: nullable(form.elements.route.value),
        frequency: nullable(form.elements.frequency.value),
        instructions: nullable(form.elements.instructions.value),
        times: form.elements.times.value.split(",").map(v => v.trim()).filter(Boolean),
        active: true,
      };
      try {
        await api(`/api/v2/patients/${pid}/medications/${id}`, { method: "PUT", body: JSON.stringify(payload) });
        dialog.close();
        await loadMedicationManager();
        $("#selectedDate")?.dispatchEvent(new Event("change", { bubbles: true }));
        showMessage("Medicamento actualizado.");
      } catch (error) {
        showMessage(error.message, true);
      }
    });
  }

  function fillMedicationDialog(medication) {
    ensureMedicationDialog();
    const form = $("#medicationEditForm");
    form.elements.id.value = medication.id;
    form.elements.name.value = medication.name || "";
    form.elements.medication_type.value = medication.medication_type || "";
    form.elements.purpose.value = medication.purpose || "";
    form.elements.dose.value = medication.dose || "";
    form.elements.route.value = medication.route || "";
    form.elements.frequency.value = medication.frequency || "";
    form.elements.times.value = (medication.times || []).join(",");
    form.elements.instructions.value = medication.instructions || "";
    $("#medicationEditDialog").showModal();
  }

  async function loadMedicationManager() {
    ensureMedicationManager();
    const root = $("#medicationManagerList");
    const pid = patientId();
    if (!root) return;
    if (!pid) {
      root.innerHTML = `<p class="empty">Selecciona o crea un paciente.</p>`;
      return;
    }
    try {
      const medications = await api(`/api/v2/patients/${pid}/medications`);
      root.innerHTML = medications.length ? medications.map(med => `
        <div class="targeted-med-item" data-med-id="${med.id}">
          <div class="targeted-med-copy">
            <strong>${escapeHtml(med.name)}</strong>
            <div class="targeted-med-tags">
              ${med.medication_type ? `<span>${escapeHtml(med.medication_type)}</span>` : ""}
              ${med.dose ? `<span>${escapeHtml(med.dose)}</span>` : ""}
              ${med.frequency ? `<span>${escapeHtml(med.frequency)}</span>` : ""}
              ${(med.times || []).map(value => `<span>${escapeHtml(value)}</span>`).join("")}
            </div>
          </div>
          <div class="targeted-med-actions">
            <button type="button" class="secondary targeted-edit-med" data-med-id="${med.id}">Editar</button>
            <button type="button" class="danger targeted-delete-med" data-med-id="${med.id}">Eliminar</button>
          </div>
        </div>`).join("") : `<p class="empty">No hay medicamentos configurados.</p>`;

      const byId = new Map(medications.map(item => [Number(item.id), item]));
      $$(".targeted-edit-med", root).forEach(button => button.addEventListener("click", () => {
        const medication = byId.get(Number(button.dataset.medId));
        if (medication) fillMedicationDialog(medication);
      }));
      $$(".targeted-delete-med", root).forEach(button => button.addEventListener("click", async () => {
        const medication = byId.get(Number(button.dataset.medId));
        if (!medication) return;
        if (!confirm(`¿Eliminar ${medication.name}? También se eliminarán sus horarios y registros asociados.`)) return;
        try {
          await api(`/api/v2/patients/${pid}/medications/${medication.id}`, { method: "DELETE" });
          await loadMedicationManager();
          $("#selectedDate")?.dispatchEvent(new Event("change", { bubbles: true }));
          showMessage("Medicamento eliminado.");
        } catch (error) {
          showMessage(error.message, true);
        }
      }));
    } catch (error) {
      root.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
    }
  }

  function ensureNewPatientButton() {
    const account = $('[data-screen="account"]');
    if (!account || $("#newPatientBtn")) return;
    const title = $(".screen-title", account);
    if (!title) return;
    const button = document.createElement("button");
    button.type = "button";
    button.id = "newPatientBtn";
    button.className = "primary targeted-new-patient";
    button.textContent = "+ Nuevo paciente";
    title.appendChild(button);
    button.addEventListener("click", () => $("#newPatientDialog")?.showModal());
  }

  function ensureNewPatientDialog() {
    if ($("#newPatientDialog")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "newPatientDialog";
    dialog.innerHTML = `
      <form method="dialog" id="newPatientForm" class="dialog-form">
        <div class="dialog-head"><h2>Agregar paciente</h2><button value="cancel" class="icon-btn" aria-label="Cerrar">×</button></div>
        <label>Nombre<input name="name" required></label>
        <div class="form-grid">
          <label>Fecha de nacimiento<input name="birth_date" type="date"></label>
          <label>Sexo al nacer<input name="sex_at_birth"></label>
          <label>Hospital principal<input name="primary_hospital"></label>
          <label>Ficha / identificador<input name="medical_record"></label>
        </div>
        <label>Alergias<textarea name="allergies"></textarea></label>
        <label>Diagnósticos registrados<textarea name="diagnoses"></textarea></label>
        <label>Notas<textarea name="notes"></textarea></label>
        <button class="primary" value="default">Crear paciente</button>
      </form>`;
    document.body.appendChild(dialog);

    $("#newPatientForm").addEventListener("submit", async event => {
      if (event.submitter?.value === "cancel") return;
      event.preventDefault();
      const form = event.currentTarget;
      const payload = {
        name: form.elements.name.value.trim(),
        birth_date: nullable(form.elements.birth_date.value),
        sex_at_birth: nullable(form.elements.sex_at_birth.value),
        primary_hospital: nullable(form.elements.primary_hospital.value),
        medical_record: nullable(form.elements.medical_record.value),
        allergies: nullable(form.elements.allergies.value),
        diagnoses: nullable(form.elements.diagnoses.value),
        notes: nullable(form.elements.notes.value),
      };
      try {
        const created = await api("/api/v2/patients", { method: "POST", body: JSON.stringify(payload) });
        const select = $("#patientSelect");
        const option = document.createElement("option");
        option.value = created.id;
        option.textContent = created.name;
        select.appendChild(option);
        select.value = String(created.id);
        dialog.close();
        form.reset();
        select.dispatchEvent(new Event("change", { bubbles: true }));
        showMessage("Paciente creado.");
      } catch (error) {
        showMessage(error.message, true);
      }
    });
  }

  function setup() {
    ensureMedicationManager();
    ensureMedicationDialog();
    ensureNewPatientButton();
    ensureNewPatientDialog();
    loadMedicationManager();

    $("#patientSelect")?.addEventListener("change", () => setTimeout(loadMedicationManager, 180));
    document.addEventListener("click", event => {
      if (event.target.closest('[data-more-nav="account"], [data-nav="account"]')) {
        setTimeout(loadMedicationManager, 120);
      }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", setup, { once: true });
  else setup();
})();
