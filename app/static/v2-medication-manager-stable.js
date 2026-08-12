(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  let managerLoading = false;
  let managerLoadedPatientId = null;
  let medications = new Map();

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
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3600);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) {
      headers.set("X-CSRF-Token", csrf);
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers,
    });
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

  function statusLabel(value) {
    return ({
      active: "Activo",
      suspended: "Suspendido",
      finished: "Finalizado",
      paused: "Pausado",
      resumed: "Reanudado",
    })[value] || value || "Activo";
  }

  function isSosFrequency(value) {
    return /\b(sos|rescate|seg[uú]n necesidad|si es necesario)\b/i.test(String(value || ""));
  }

  function normalizeHistory(payload) {
    if (Array.isArray(payload)) {
      return {
        history: payload,
        status: payload.at(-1)?.status || "active",
        reason: payload.at(-1)?.reason || null,
      };
    }
    const history = Array.isArray(payload?.history) ? payload.history : [];
    return {
      history,
      status: payload?.status || history.at(-1)?.status || "active",
      reason: payload?.reason || history.at(-1)?.reason || null,
    };
  }

  function ensureDialogs() {
    let manager = $("#medicationManagerDialog");
    if (!manager) {
      manager = document.createElement("dialog");
      manager.id = "medicationManagerDialog";
      manager.innerHTML = `
        <div class="dialog-form">
          <div class="dialog-head">
            <h2>Administrar medicamentos</h2>
            <button type="button" class="icon-btn" data-close-stable-med-manager aria-label="Cerrar">×</button>
          </div>
          <div id="configuredMedicationList" class="stack compact"></div>
        </div>`;
      document.body.appendChild(manager);
    }

    let edit = $("#medicationEditDialog");
    if (!edit) {
      edit = document.createElement("dialog");
      edit.id = "medicationEditDialog";
      edit.innerHTML = `
        <form id="medicationEditForm" class="dialog-form">
          <div class="dialog-head">
            <h2>Editar medicamento</h2>
            <button type="button" class="icon-btn" data-close-stable-med-edit aria-label="Cerrar">×</button>
          </div>
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
      document.body.appendChild(edit);
    }

    return { manager, edit };
  }

  function ensureEditExtras(form) {
    if (!form) return;

    if (!form.elements.is_sos) {
      const frequency = form.elements.frequency;
      const times = form.elements.times;
      const grid = frequency?.closest(".form-grid");
      if (frequency && times && grid) {
        const label = document.createElement("label");
        label.dataset.sosField = "edit";
        label.className = "wide";
        label.innerHTML = `<span><input type="checkbox" name="is_sos"> Medicamento SOS / solo si se necesita</span><small class="field-help">No crea horarios fijos. No modifica dosis ni indicaciones clínicas.</small>`;
        grid.insertAdjacentElement("afterend", label);
      }
    }

    if (!form.elements.treatment_status) {
      const submit = form.querySelector('button[type="submit"]');
      if (submit) {
        const block = document.createElement("div");
        block.className = "med-status-row";
        block.innerHTML = `
          <label>Estado del tratamiento
            <select name="treatment_status">
              <option value="active">Activo</option>
              <option value="suspended">Suspendido</option>
              <option value="finished">Finalizado</option>
              <option value="paused">Pausado</option>
              <option value="resumed">Reanudado</option>
            </select>
          </label>
          <label>Fecha/hora efectiva<input name="effective_at" type="datetime-local"></label>
          <label class="med-status-reason">Motivo del cambio / suspensión<textarea name="status_reason" placeholder="Opcional"></textarea></label>`;
        submit.before(block);
      }
    }

    if (!$("#medTreatmentHistory", form)) {
      const submit = form.querySelector('button[type="submit"]');
      if (submit) {
        const box = document.createElement("div");
        box.id = "medTreatmentHistory";
        box.className = "treatment-history-box";
        box.innerHTML = "<h4>Historial de tratamiento</h4><div class='history-content muted'>Cargando…</div>";
        submit.after(box);
      }
    }

    const sos = form.elements.is_sos;
    if (sos && sos.dataset.stableBound !== "1") {
      sos.dataset.stableBound = "1";
      sos.addEventListener("change", () => {
        const frequency = form.elements.frequency;
        const times = form.elements.times;
        if (!frequency || !times) return;
        if (sos.checked) {
          if (!isSosFrequency(frequency.value)) frequency.dataset.beforeSos = frequency.value || "";
          frequency.value = "SOS / según necesidad";
          times.dataset.beforeSos = times.value || "";
          times.value = "";
          times.disabled = true;
        } else {
          if (isSosFrequency(frequency.value)) frequency.value = frequency.dataset.beforeSos || "";
          times.disabled = false;
          if (!times.value && times.dataset.beforeSos) times.value = times.dataset.beforeSos;
        }
      });
    }
  }

  function renderHistory(rows) {
    const root = $("#medTreatmentHistory .history-content");
    if (!root) return;
    root.innerHTML = rows.length ? rows.map(row => `
      <div class="treatment-history-item" data-history-id="${row.id || ""}" data-event-type="${esc(row.event_type || "")}">
        <time>${esc(new Date(row.occurred_at).toLocaleString("es-CL"))}</time>
        <div><strong>${esc(statusLabel(row.status))}</strong>${row.changed_fields?.length ? ` · cambio: ${esc(row.changed_fields.join(", "))}` : ""}</div>
        <div>${esc([row.dose, row.route, row.frequency, (row.times || []).join(", ")].filter(Boolean).join(" · "))}</div>
        ${row.reason ? `<small>Motivo: ${esc(row.reason)}</small>` : ""}
      </div>`).join("") : "<span class='muted'>Sin cambios registrados.</span>";
  }

  function renderManager(items) {
    const root = $("#configuredMedicationList");
    if (!root) return;

    root.innerHTML = items.length ? items.map(med => {
      const status = med.treatment_status || (med.active === false ? "suspended" : "active");
      const active = med.active !== false;
      const sos = isSosFrequency(med.frequency);
      return `
        <article class="card" data-medication-id="${med.id}" data-is-sos="${sos ? "1" : "0"}" style="margin-bottom:10px">
          <div class="card-head">
            <div>
              <strong>${esc(med.name)}</strong>
              <div class="muted">${esc([med.dose, med.route, med.frequency].filter(Boolean).join(" · "))}</div>
              <span class="badge">${esc(statusLabel(status))}</span>
              ${sos ? `<span class="badge sos-med-badge">SOS</span>` : ""}
            </div>
          </div>
          <div class="button-row">
            <button type="button" class="secondary edit-managed-med" data-id="${med.id}">Editar / historial</button>
            ${active ? `<button type="button" class="danger stable-delete-managed-med" data-id="${med.id}" data-name="${esc(med.name)}">Eliminar</button>` : ""}
          </div>
        </article>`;
    }).join("") : `<p class="empty">No hay medicamentos configurados.</p>`;
  }

  async function loadManager() {
    const pid = patientId();
    if (!pid || managerLoading) return;

    ensureDialogs();
    const manager = $("#medicationManagerDialog");
    const root = $("#configuredMedicationList");
    const button = $("#manageMedicationsBtn");

    if (managerLoadedPatientId === pid) {
      renderManager([...medications.values()]);
      if (manager && !manager.open) manager.showModal();
      return;
    }

    managerLoading = true;
    if (button) button.disabled = true;
    if (root) root.innerHTML = `<p class="empty">Cargando…</p>`;
    if (manager && !manager.open) manager.showModal();

    try {
      const items = await api(`/api/v2/patients/${pid}/medications`);
      medications = new Map(items.map(item => [Number(item.id), item]));
      managerLoadedPatientId = pid;
      renderManager(items);
    } catch (error) {
      if (root) root.innerHTML = `<p class="empty">${esc(error.message)}</p>`;
    } finally {
      managerLoading = false;
      if (button) button.disabled = false;
    }
  }

  async function openEdit(medicationId) {
    const pid = patientId();
    if (!pid) return;
    ensureDialogs();

    let medication = medications.get(Number(medicationId));
    if (!medication || managerLoadedPatientId !== pid) {
      const items = await api(`/api/v2/patients/${pid}/medications`);
      medications = new Map(items.map(item => [Number(item.id), item]));
      managerLoadedPatientId = pid;
      medication = medications.get(Number(medicationId));
    }
    if (!medication) return toast("Medicamento no encontrado.", true);

    const editDialog = $("#medicationEditDialog");
    const currentForm = $("#medicationEditForm");
    ensureEditExtras(currentForm);
    $("#medicationManagerDialog")?.close();
    if (editDialog && !editDialog.open) editDialog.showModal();

    try {
      const [historyPayload, sosPayload] = await Promise.all([
        api(`/api/v2/patients/${pid}/medications/${medication.id}/treatment-history`),
        api(`/api/v2/patients/${pid}/medications/${medication.id}/sos`).catch(() => ({ is_sos: false })),
      ]);
      const historyData = normalizeHistory(historyPayload);

      const form = $("#medicationEditForm");
      ensureEditExtras(form);
      form.reset();
      form.elements.id.value = String(medication.id);
      for (const name of ["name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"]) {
        if (form.elements[name]) form.elements[name].value = medication[name] || "";
      }
      if (form.elements.times) {
        form.elements.times.disabled = false;
        form.elements.times.value = (medication.times || []).join(",");
      }
      if (form.elements.treatment_status) form.elements.treatment_status.value = historyData.status || medication.treatment_status || "active";
      if (form.elements.effective_at) form.elements.effective_at.value = localDateTimeValue();
      if (form.elements.status_reason) form.elements.status_reason.value = "";

      const isSos = Boolean(sosPayload?.is_sos);
      if (form.elements.is_sos) {
        form.elements.is_sos.checked = isSos;
        if (isSos && form.elements.times) {
          form.elements.times.dataset.beforeSos = (medication.times || []).join(",");
          form.elements.times.value = "";
          form.elements.times.disabled = true;
        }
      }

      form.dataset.previousStatus = historyData.status || medication.treatment_status || "active";
      form.dataset.previousSos = isSos ? "1" : "0";
      renderHistory(historyData.history);
    } catch (error) {
      editDialog?.close();
      toast(error.message, true);
    }
  }

  async function saveEdit(event) {
    event.preventDefault();
    event.stopImmediatePropagation();

    const form = event.target;
    const pid = patientId();
    if (!pid || !(form instanceof HTMLFormElement)) return;

    const medicationId = Number(form.elements.id?.value || 0);
    if (!medicationId) return toast("Medicamento no válido.", true);

    const name = String(form.elements.name?.value || "").trim();
    if (!name) return toast("Escribe el nombre del medicamento.", true);

    const effectiveAt = form.elements.effective_at?.value || localDateTimeValue();
    const isSos = Boolean(form.elements.is_sos?.checked);
    const times = isSos
      ? []
      : String(form.elements.times?.value || "").split(",").map(value => value.trim()).filter(Boolean);

    const payload = {
      name,
      generic_name: null,
      medication_type: String(form.elements.medication_type?.value || "").trim() || "Medicamento",
      purpose: String(form.elements.purpose?.value || "").trim() || null,
      dose: String(form.elements.dose?.value || "").trim() || null,
      route: String(form.elements.route?.value || "").trim() || null,
      frequency: String(form.elements.frequency?.value || "").trim() || null,
      instructions: String(form.elements.instructions?.value || "").trim() || null,
      times,
      effective_at: effectiveAt,
    };

    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;

    try {
      await api(`/api/v2/patients/${pid}/medications/${medicationId}/history-update`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });

      const previousStatus = form.dataset.previousStatus || "active";
      const nextStatus = form.elements.treatment_status?.value || previousStatus;
      if (nextStatus !== previousStatus) {
        await api(`/api/v2/patients/${pid}/medications/${medicationId}/status`, {
          method: "POST",
          body: JSON.stringify({
            status: nextStatus,
            occurred_at: effectiveAt,
            reason: String(form.elements.status_reason?.value || "").trim() || null,
          }),
        });
      }

      const previousSos = form.dataset.previousSos === "1";
      if (isSos !== previousSos) {
        await api(`/api/v2/patients/${pid}/medications/${medicationId}/sos`, {
          method: "PUT",
          body: JSON.stringify({ is_sos: isSos }),
        });
      }

      const previous = medications.get(medicationId) || {};
      medications.set(medicationId, {
        ...previous,
        ...payload,
        id: medicationId,
        times,
        treatment_status: nextStatus,
        active: ["active", "resumed"].includes(nextStatus),
      });
      managerLoadedPatientId = pid;
      form.dataset.previousStatus = nextStatus;
      form.dataset.previousSos = isSos ? "1" : "0";

      $("#medicationEditDialog")?.close();
      toast("Medicamento actualizado.");
      const date = $("#selectedDate");
      date?.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function softDelete(button) {
    const pid = patientId();
    const medicationId = Number(button.dataset.id || 0);
    const name = button.dataset.name || "este medicamento";
    if (!pid || !medicationId) return;
    if (!confirm(`¿Eliminar ${name} del esquema activo? El historial de administraciones se conservará.`)) return;

    button.disabled = true;
    try {
      await api(`/api/v2/patients/${pid}/medications/${medicationId}`, { method: "DELETE" });
      toast("Medicamento retirado del esquema activo.");
      medications.delete(medicationId);
      managerLoadedPatientId = pid;
      renderManager([...medications.values()]);
      const date = $("#selectedDate");
      date?.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  document.addEventListener("click", event => {
    const manage = event.target.closest("#manageMedicationsBtn");
    if (manage) {
      event.preventDefault();
      event.stopImmediatePropagation();
      loadManager();
      return;
    }

    const edit = event.target.closest("#configuredMedicationList .edit-managed-med");
    if (edit) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openEdit(Number(edit.dataset.id)).catch(error => toast(error.message, true));
      return;
    }

    const remove = event.target.closest("#configuredMedicationList .stable-delete-managed-med");
    if (remove) {
      event.preventDefault();
      event.stopImmediatePropagation();
      softDelete(remove);
      return;
    }

    if (event.target.closest("[data-close-stable-med-manager]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      $("#medicationManagerDialog")?.close();
      return;
    }

    if (event.target.closest("[data-close-stable-med-edit]")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      $("#medicationEditDialog")?.close();
    }
  }, true);

  document.addEventListener("submit", event => {
    if (event.target?.id !== "medicationEditForm") return;
    saveEdit(event);
  }, true);

  $("#patientSelect")?.addEventListener("change", () => {
    medications.clear();
    managerLoadedPatientId = null;
    $("#medicationManagerDialog")?.close();
    $("#medicationEditDialog")?.close();
  });
})();
