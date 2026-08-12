(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

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

  function localDateTimeValue(date = new Date()) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
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
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo modificar el medicamento.");
    }
    return payload;
  }

  function normalizeHistory(payload) {
    if (Array.isArray(payload)) {
      return {
        history: payload,
        status: payload.at(-1)?.status || "active",
        reason: payload.at(-1)?.reason || null,
      };
    }
    return {
      history: Array.isArray(payload?.history) ? payload.history : [],
      status: payload?.status || payload?.history?.at?.(-1)?.status || "active",
      reason: payload?.reason || null,
    };
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

  function ensureStatusFields(form) {
    if (!form || form.elements.treatment_status) return;
    const submit = form.querySelector('button[type="submit"]');
    if (!submit) return;
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

  function ensureHistoryBox(form) {
    let root = $("#medTreatmentHistory", form);
    if (root) return root;
    const submit = form?.querySelector('button[type="submit"]');
    if (!submit) return null;
    root = document.createElement("div");
    root.id = "medTreatmentHistory";
    root.className = "treatment-history-box";
    root.innerHTML = "<h4>Historial de tratamiento</h4><div class='history-content muted'>Cargando…</div>";
    submit.after(root);
    return root;
  }

  function renderHistory(rows) {
    const root = $("#medTreatmentHistory .history-content");
    if (!root) return;
    root.innerHTML = rows.length ? rows.map(row => `
      <div class="treatment-history-item">
        <time>${esc(new Date(row.occurred_at).toLocaleString("es-CL"))}</time>
        <div><strong>${esc(statusLabel(row.status))}</strong>${row.changed_fields?.length ? ` · cambio: ${esc(row.changed_fields.join(", "))}` : ""}</div>
        <div>${esc([row.dose, row.route, row.frequency, (row.times || []).join(", ")].filter(Boolean).join(" · "))}</div>
        ${row.reason ? `<small>Motivo: ${esc(row.reason)}</small>` : ""}
      </div>`).join("") : "<span class='muted'>Sin cambios registrados.</span>";
  }

  async function openMedicationEdit(medicationId) {
    const pid = patientId();
    const form = $("#medicationEditForm");
    if (!pid || !form) return;

    ensureStatusFields(form);
    ensureHistoryBox(form);

    try {
      const medications = await api(`/api/v2/patients/${pid}/medications`);
      const medication = medications.find(item => Number(item.id) === Number(medicationId));
      if (!medication) throw new Error("Medicamento no encontrado.");

      const [historyPayload, sosPayload] = await Promise.all([
        api(`/api/v2/patients/${pid}/medications/${medication.id}/treatment-history`),
        api(`/api/v2/patients/${pid}/medications/${medication.id}/sos`).catch(() => ({ is_sos: false })),
      ]);
      const historyData = normalizeHistory(historyPayload);

      form.elements.id.value = medication.id;
      for (const name of ["name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"]) {
        if (form.elements[name]) form.elements[name].value = medication[name] || "";
      }
      if (form.elements.times) {
        form.elements.times.disabled = false;
        form.elements.times.value = (medication.times || []).join(",");
      }
      if (form.elements.treatment_status) form.elements.treatment_status.value = historyData.status || medication.treatment_status || (medication.active ? "active" : "suspended");
      if (form.elements.effective_at) form.elements.effective_at.value = localDateTimeValue();
      if (form.elements.status_reason) form.elements.status_reason.value = "";

      const sos = form.elements.is_sos;
      if (sos) {
        sos.checked = Boolean(sosPayload?.is_sos);
        if (sos.checked && form.elements.times) {
          form.elements.times.value = "";
          form.elements.times.disabled = true;
        }
      }

      renderHistory(historyData.history);
      $("#medicationManagerDialog")?.close();
      $("#medicationEditDialog")?.showModal();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function saveMedicationEdit(event) {
    event.preventDefault();
    event.stopImmediatePropagation();

    const pid = patientId();
    const form = event.target;
    if (!pid || !(form instanceof HTMLFormElement)) return;

    const medicationId = Number(form.elements.id?.value || 0);
    if (!medicationId) return toast("Medicamento no válido.", true);

    const effectiveAt = form.elements.effective_at?.value || localDateTimeValue();
    const times = form.elements.times?.disabled
      ? []
      : String(form.elements.times?.value || "").split(",").map(value => value.trim()).filter(Boolean);

    const payload = {
      name: String(form.elements.name?.value || "").trim(),
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

    if (!payload.name) return toast("Escribe el nombre del medicamento.", true);

    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;

    try {
      const currentHistory = normalizeHistory(
        await api(`/api/v2/patients/${pid}/medications/${medicationId}/treatment-history`),
      );
      const previousStatus = currentHistory.status || "active";

      await api(`/api/v2/patients/${pid}/medications/${medicationId}/history-update`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });

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

      $("#medicationEditDialog")?.close();
      toast("Medicamento actualizado.");
      setTimeout(() => location.reload(), 250);
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("#configuredMedicationList .ext-edit-med, #configuredMedicationList .edit-managed-med");
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    openMedicationEdit(Number(button.dataset.id));
  }, true);

  document.addEventListener("submit", event => {
    if (event.target?.id !== "medicationEditForm") return;
    saveMedicationEdit(event);
  }, true);
})();
