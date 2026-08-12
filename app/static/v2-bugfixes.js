(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  let medicationManagerLoading = false;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

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
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  function patientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function ensureMedicationManager() {
    if ($("#medicationManagerDialog")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "medicationManagerDialog";
    dialog.innerHTML = `
      <div class="dialog-form">
        <div class="dialog-head"><h2>Administrar medicamentos</h2><button type="button" class="icon-btn" data-close-manager>×</button></div>
        <div id="configuredMedicationList" class="stack compact"></div>
      </div>`;
    document.body.appendChild(dialog);

    const editDialog = document.createElement("dialog");
    editDialog.id = "medicationEditDialog";
    editDialog.innerHTML = `
      <form id="medicationEditForm" class="dialog-form">
        <div class="dialog-head"><h2>Editar medicamento</h2><button type="button" class="icon-btn" data-close-edit>×</button></div>
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
        <button class="primary" type="submit">Guardar cambios</button>
      </form>`;
    document.body.appendChild(editDialog);

    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-manager]")) dialog.close();
    });
    editDialog.addEventListener("click", event => {
      if (event.target === editDialog || event.target.closest("[data-close-edit]")) editDialog.close();
    });

    $("#medicationEditForm").addEventListener("submit", saveMedicationEdit);
  }

  async function openMedicationManager() {
    const id = patientId();
    if (!id || medicationManagerLoading) return;
    ensureMedicationManager();
    const dialog = $("#medicationManagerDialog");
    const root = $("#configuredMedicationList");
    const button = $("#manageMedicationsBtn");
    medicationManagerLoading = true;
    if (button) button.disabled = true;
    root.innerHTML = `<p class="empty">Cargando…</p>`;
    if (!dialog.open) dialog.showModal();
    try {
      const medications = await api(`/api/v2/patients/${id}/medications`);
      const active = medications.filter(item => item.active !== false);
      root.innerHTML = active.length ? active.map(item => `
        <article class="card" style="margin-bottom:10px">
          <div class="card-head">
            <div><strong>${esc(item.name)}</strong><div class="muted">${esc([item.dose, item.route, item.frequency].filter(Boolean).join(" · "))}</div></div>
          </div>
          <div class="button-row">
            <button type="button" class="secondary edit-managed-med" data-id="${item.id}">Editar</button>
            <button type="button" class="danger delete-managed-med" data-id="${item.id}" data-name="${esc(item.name)}">Eliminar</button>
          </div>
        </article>`).join("") : `<p class="empty">No hay medicamentos activos.</p>`;

      $$(".edit-managed-med", root).forEach(button => button.addEventListener("click", () => {
        const med = medications.find(item => item.id === Number(button.dataset.id));
        if (med) openMedicationEdit(med);
      }));
      $$(".delete-managed-med", root).forEach(button => button.addEventListener("click", () => deleteMedication(button)));
    } catch (error) {
      root.innerHTML = `<p class="empty">${esc(error.message)}</p>`;
    } finally {
      medicationManagerLoading = false;
      if (button) button.disabled = false;
    }
  }

  function openMedicationEdit(med) {
    ensureMedicationManager();
    const form = $("#medicationEditForm");
    form.elements.id.value = med.id;
    form.elements.name.value = med.name || "";
    form.elements.medication_type.value = med.medication_type || "";
    form.elements.purpose.value = med.purpose || "";
    form.elements.dose.value = med.dose || "";
    form.elements.route.value = med.route || "";
    form.elements.frequency.value = med.frequency || "";
    form.elements.times.value = (med.times || []).join(",");
    form.elements.instructions.value = med.instructions || "";
    $("#medicationManagerDialog")?.close();
    $("#medicationEditDialog")?.showModal();
  }

  async function saveMedicationEdit(event) {
    event.preventDefault();
    const id = patientId();
    const form = event.currentTarget;
    const medicationId = Number(form.elements.id.value);
    const payload = {
      name: form.elements.name.value.trim(),
      generic_name: null,
      medication_type: form.elements.medication_type.value.trim() || "Medicamento",
      purpose: form.elements.purpose.value.trim() || null,
      dose: form.elements.dose.value.trim() || null,
      route: form.elements.route.value.trim() || null,
      frequency: form.elements.frequency.value.trim() || null,
      instructions: form.elements.instructions.value.trim() || null,
      times: form.elements.times.value.split(",").map(v => v.trim()).filter(Boolean),
      active: true,
    };
    try {
      await api(`/api/v2/patients/${id}/medications/${medicationId}`, { method: "PUT", body: JSON.stringify(payload) });
      $("#medicationEditDialog")?.close();
      location.reload();
    } catch (error) {
      alert(error.message);
    }
  }

  async function deleteMedication(button) {
    const id = patientId();
    const medicationId = Number(button.dataset.id);
    const name = button.dataset.name || "este medicamento";
    if (!confirm(`¿Eliminar ${name} del esquema activo? El historial de administraciones se conservará.`)) return;
    try {
      await api(`/api/v2/patients/${id}/medications/${medicationId}`, { method: "DELETE" });
      location.reload();
    } catch (error) {
      alert(error.message);
    }
  }

  function ensureNewPatientDialog() {
    if ($("#newPatientDialog")) return;
    const dialog = document.createElement("dialog");
    dialog.id = "newPatientDialog";
    dialog.innerHTML = `
      <form id="newPatientForm" class="dialog-form">
        <div class="dialog-head"><h2>Agregar paciente</h2><button type="button" class="icon-btn" data-close-patient>×</button></div>
        <label>Nombre<input name="name" required></label>
        <label>Fecha de nacimiento<input name="birth_date" type="date"></label>
        <label>Sexo al nacer<input name="sex_at_birth"></label>
        <label>Hospital principal<input name="primary_hospital"></label>
        <label>Ficha / identificador<input name="medical_record"></label>
        <label>Alergias<textarea name="allergies"></textarea></label>
        <label>Diagnósticos registrados<textarea name="diagnoses"></textarea></label>
        <label>Notas<textarea name="notes"></textarea></label>
        <button class="primary" type="submit">Crear paciente</button>
      </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-patient]")) dialog.close();
    });
    $("#newPatientForm").addEventListener("submit", async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const value = name => form.elements[name].value.trim() || null;
      const payload = {
        name: value("name"),
        birth_date: value("birth_date"),
        sex_at_birth: value("sex_at_birth"),
        primary_hospital: value("primary_hospital"),
        medical_record: value("medical_record"),
        allergies: value("allergies"),
        diagnoses: value("diagnoses"),
        notes: value("notes"),
      };
      try {
        const created = await api("/api/v2/patients", { method: "POST", body: JSON.stringify(payload) });
        localStorage.setItem("ikercare_patient_id", String(created.id));
        dialog.close();
        location.reload();
      } catch (error) {
        alert(error.message);
      }
    });
  }

  function addRequestedButtons() {
    const medSection = $("#medicationList")?.closest(".card");
    const medHead = medSection?.querySelector(".card-head");
    if (medHead && !$("#manageMedicationsBtn")) {
      const button = document.createElement("button");
      button.id = "manageMedicationsBtn";
      button.type = "button";
      button.className = "small secondary";
      button.textContent = "Administrar";
      button.addEventListener("click", openMedicationManager);
      medHead.appendChild(button);
    }

    const accountTitle = $('[data-screen="account"] .screen-title');
    if (accountTitle && !$("#newPatientBtn")) {
      const button = document.createElement("button");
      button.id = "newPatientBtn";
      button.type = "button";
      button.className = "secondary";
      button.textContent = "+ Paciente";
      button.addEventListener("click", () => {
        ensureNewPatientDialog();
        $("#newPatientForm")?.reset();
        $("#newPatientDialog")?.showModal();
      });
      accountTitle.appendChild(button);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", addRequestedButtons, { once: true });
  } else {
    addRequestedButtons();
  }
})();
