
(() => {
  "use strict";

  const app = document.getElementById("app");
  const csrf = app.dataset.csrf;
  const state = {
    me: null,
    patients: [],
    patient: null,
    patientId: null,
    date: new Date().toISOString().slice(0, 10),
    serverTime: null,
    medSearchTimer: null,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3200);
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
    if (response.status === 401) {
      location.href = "/login";
      throw new Error("Sesión finalizada");
    }
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? (payload.detail || JSON.stringify(payload)) : payload;
      throw new Error(detail || `Error ${response.status}`);
    }
    return payload;
  }

  function canEdit() {
    return state.patient && ["owner", "editor"].includes(state.patient.role);
  }

  function localDateTimeValue(date = new Date()) {
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function formToObject(form) {
    const fd = new FormData(form);
    return Object.fromEntries(fd.entries());
  }

  function nullable(value) {
    const v = String(value ?? "").trim();
    return v === "" ? null : v;
  }

  function numberOrNull(value) {
    return value === "" || value == null ? null : Number(value);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function displayTime(value) {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value.replace("T", " ");
    return d.toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" });
  }

  async function init() {
    $("#selectedDate").value = state.date;
    setDefaultDateTimes();
    bindNavigation();
    bindDialogs();
    bindForms();
    bindActions();

    try {
      state.me = await api("/api/v2/auth/me");
      updateLegal();
      await loadPatients();
      startPolling();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function updateLegal() {
    const banner = $("#legalBanner");
    banner.classList.toggle("hidden", state.me?.privacy_current);
  }

  async function loadPatients() {
    state.patients = await api("/api/v2/patients");
    const select = $("#patientSelect");
    select.innerHTML = "";
    if (!state.patients.length) {
      select.innerHTML = `<option value="">Crear paciente</option>`;
      state.patientId = null;
      state.patient = null;
      showScreen("account");
      clearPatientForm();
      return;
    }

    for (const patient of state.patients) {
      const option = document.createElement("option");
      option.value = patient.id;
      option.textContent = `${patient.name}${patient.role === "viewer" ? " · lectura" : ""}`;
      select.appendChild(option);
    }

    const previous = Number(localStorage.getItem("ikercare_patient_id"));
    const chosen = state.patients.find(p => p.id === previous) || state.patients[0];
    select.value = String(chosen.id);
    await selectPatient(chosen.id);
  }

  async function selectPatient(patientId) {
    state.patientId = Number(patientId);
    localStorage.setItem("ikercare_patient_id", String(state.patientId));
    state.patient = await api(`/api/v2/patients/${state.patientId}`);
    $("#patientSelect").value = String(state.patientId);
    fillPatientForm(state.patient);
    await Promise.all([
      loadDay(),
      loadTeam(),
      loadMembers(),
      loadTimeline(),
      loadDocuments(),
      loadShares(),
    ]);
    syncNativeNotifications();
  }

  function clearPatientForm() {
    $("#patientForm").reset();
    $("#patientPhoto").classList.add("hidden");
  }

  function fillPatientForm(patient) {
    const form = $("#patientForm");
    for (const name of ["name", "birth_date", "sex_at_birth", "primary_hospital", "medical_record", "allergies", "diagnoses", "notes"]) {
      form.elements[name].value = patient[name] || "";
    }
    const photo = $("#patientPhoto");
    if (patient.has_photo) {
      photo.src = `/api/v2/patients/${patient.id}/photo?t=${Date.now()}`;
      photo.classList.remove("hidden");
    } else {
      photo.classList.add("hidden");
      photo.removeAttribute("src");
    }
  }

  function bindNavigation() {
    $$(".bottom-nav button").forEach(button => {
      button.addEventListener("click", () => showScreen(button.dataset.nav));
    });
    $("#patientSelect").addEventListener("change", event => {
      if (event.target.value) selectPatient(event.target.value).catch(err => toast(err.message, true));
    });
    $("#selectedDate").addEventListener("change", event => {
      state.date = event.target.value;
      loadDay().catch(err => toast(err.message, true));
    });
  }

  function showScreen(name) {
    $$(".screen").forEach(section => section.classList.toggle("active", section.dataset.screen === name));
    $$(".bottom-nav button").forEach(button => button.classList.toggle("active", button.dataset.nav === name));
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (name === "history" && state.patientId) loadTimeline();
    if (name === "documents" && state.patientId) loadDocuments();
    if (name === "share" && state.patientId) loadShares();
  }

  function bindDialogs() {
    $$("[data-open]").forEach(button => {
      button.addEventListener("click", () => {
        if (!state.patientId) {
          toast("Primero crea un paciente.", true);
          return;
        }
        if (!canEdit() && !["documentDialog"].includes(button.dataset.open)) {
          toast("Tu acceso es de solo lectura.", true);
          return;
        }
        const dialog = document.getElementById(button.dataset.open);
        dialog?.showModal();
      });
    });
    $$("dialog form").forEach(form => {
      form.addEventListener("submit", event => {
        if (event.submitter?.value === "cancel") event.preventDefault();
      });
    });
  }

  function setDefaultDateTimes() {
    $$('input[type="datetime-local"]').forEach(input => {
      if (!input.value) input.value = localDateTimeValue();
    });
  }

  async function loadDay() {
    if (!state.patientId) return;
    const data = await api(`/api/v2/patients/${state.patientId}/day?date=${encodeURIComponent(state.date)}`);
    renderMedications(data.medications);
    renderElimination(data.elimination);
    renderFood(data.food);
    renderVitals(data.vitals);
    renderCrises(data.crises);
    renderChemo(data.chemo);
    $("#dailyNote").value = data.daily_note || "";
  }

  function renderMedications(items) {
    const root = $("#medicationList");
    if (!items.length) {
      root.innerHTML = `<p class="empty">No hay medicamentos con horario para este día.</p>`;
      return;
    }
    root.innerHTML = items.map(item => {
      const med = item.medication;
      const taken = item.status === "taken";
      const skipped = item.status === "skipped";
      return `<div class="med-row ${taken ? "done" : skipped ? "skipped" : ""}">
        <button class="check-btn" data-schedule="${item.schedule_id}" data-status="${taken ? "pending" : "taken"}" ${canEdit() ? "" : "disabled"} aria-label="${taken ? "Desmarcar" : "Marcar tomado"}">${taken ? "✓" : ""}</button>
        <div class="med-main">
          <div class="med-title"><strong>${escapeHtml(item.time)}</strong> ${escapeHtml(med.name)} ${med.dose ? `<span>${escapeHtml(med.dose)}</span>` : ""}</div>
          <div class="muted">${escapeHtml([med.route, med.frequency, med.purpose].filter(Boolean).join(" · "))}</div>
          ${item.actual_time ? `<small>Registrado ${displayTime(item.actual_time)}</small>` : ""}
        </div>
        <button class="text-btn skip-btn" data-schedule="${item.schedule_id}" ${canEdit() ? "" : "disabled"}>${skipped ? "Pendiente" : "Omitido"}</button>
      </div>`;
    }).join("");

    $$(".check-btn", root).forEach(button => button.addEventListener("click", async () => {
      await toggleMedication(Number(button.dataset.schedule), button.dataset.status);
    }));
    $$(".skip-btn", root).forEach(button => button.addEventListener("click", async () => {
      const row = button.closest(".med-row");
      await toggleMedication(Number(button.dataset.schedule), row.classList.contains("skipped") ? "pending" : "skipped");
    }));
  }

  async function toggleMedication(scheduleId, status) {
    try {
      await api(`/api/v2/patients/${state.patientId}/medication-logs/toggle`, {
        method: "POST",
        body: JSON.stringify({ schedule_id: scheduleId, log_date: state.date, status, notes: null }),
      });
      await loadDay();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function renderElimination(items) {
    const labels = { dry: "Seco", wet: "Pipí", soiled: "Deposición", wet_and_soiled: "Pipí + deposición" };
    $("#eliminationList").innerHTML = items.length ? items.map(item =>
      `<div class="mini-row"><div><strong>${displayTime(item.occurred_at)}</strong><br>${escapeHtml(labels[item.diaper_status] || item.diaper_status)}${item.urine_amount ? ` · ${escapeHtml(item.urine_amount)}` : ""}${item.stool_description ? `<br><span class="muted">${escapeHtml(item.stool_description)}</span>` : ""}</div>${canEdit() ? `<button class="text-btn delete-elim" data-id="${item.id}">Eliminar</button>` : ""}</div>`
    ).join("") : `<p class="empty">Sin registros.</p>`;
    $$(".delete-elim").forEach(btn => btn.addEventListener("click", () => deleteSimple("elimination", btn.dataset.id, loadDay)));
  }

  function renderFood(items) {
    $("#foodList").innerHTML = items.length ? items.map(item =>
      `<div class="mini-row"><div><strong>${displayTime(item.occurred_at)}</strong><br>${escapeHtml(item.item)} ${item.amount != null ? `· ${escapeHtml(item.amount)} ${escapeHtml(item.unit || "")}` : ""}<br><span class="muted">${item.vomiting ? "⚠️ vómito" : item.tolerated === false ? "No toleró" : item.tolerated === true ? "Toleró" : ""}</span></div>${canEdit() ? `<button class="text-btn delete-food" data-id="${item.id}">Eliminar</button>` : ""}</div>`
    ).join("") : `<p class="empty">Sin registros.</p>`;
    $$(".delete-food").forEach(btn => btn.addEventListener("click", () => deleteSimple("food", btn.dataset.id, loadDay)));
  }

  function renderVitals(items) {
    $("#vitalList").innerHTML = items.length ? items.map(item => {
      const values = [
        item.temperature_c != null ? `${item.temperature_c} °C` : null,
        item.systolic && item.diastolic ? `${item.systolic}/${item.diastolic} mmHg` : null,
        item.heart_rate ? `FC ${item.heart_rate}` : null,
        item.oxygen_saturation != null ? `SatO₂ ${item.oxygen_saturation}%` : null,
      ].filter(Boolean);
      return `<div class="mini-row"><div><strong>${displayTime(item.recorded_at)}</strong><br>${escapeHtml(values.join(" · "))}${item.notes ? `<br><span class="muted">${escapeHtml(item.notes)}</span>` : ""}</div></div>`;
    }).join("") : `<p class="empty">Sin signos registrados.</p>`;
  }

  function renderCrises(items) {
    $("#crisisList").innerHTML = items.length ? items.map(item =>
      `<div class="mini-row"><div><strong>${escapeHtml(item.event_type)}</strong> · ${displayTime(item.occurred_at)}${item.duration_seconds != null ? ` · ${item.duration_seconds}s` : ""}<br><span class="muted">${escapeHtml(item.description)}</span></div></div>`
    ).join("") : `<p class="empty">Sin eventos registrados.</p>`;
  }

  function renderChemo(items) {
    $("#chemoList").innerHTML = items.length ? items.map(item =>
      `<div class="mini-row"><div><strong>${escapeHtml(item.name)}</strong> · ${displayTime(item.scheduled_at)}<br><span class="muted">${escapeHtml([item.protocol, item.cycle, item.status].filter(Boolean).join(" · "))}</span></div></div>`
    ).join("") : `<p class="empty">Sin quimioterapia registrada para este día.</p>`;
  }

  async function deleteSimple(resource, id, callback) {
    if (!confirm("¿Eliminar este registro?")) return;
    try {
      await api(`/api/v2/patients/${state.patientId}/${resource}/${id}`, { method: "DELETE" });
      await callback();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function loadTeam() {
    if (!state.patientId) return;
    const items = await api(`/api/v2/patients/${state.patientId}/team`);
    $("#teamList").innerHTML = items.length ? items.map(item => `
      <article class="card person-card">
        <div><strong>${escapeHtml(item.name)}</strong>${item.is_primary ? `<span class="badge">Principal</span>` : ""}</div>
        <div>${escapeHtml(item.specialty || item.role || "Profesional")}</div>
        <div class="muted">${escapeHtml(item.hospital || "")}</div>
        ${item.phone ? `<a href="tel:${escapeHtml(item.phone)}">${escapeHtml(item.phone)}</a>` : ""}
        ${item.email ? `<a href="mailto:${escapeHtml(item.email)}">${escapeHtml(item.email)}</a>` : ""}
        ${canEdit() ? `<button class="text-btn delete-team" data-id="${item.id}">Eliminar</button>` : ""}
      </article>
    `).join("") : `<p class="empty">Aún no has agregado profesionales.</p>`;
    $$(".delete-team").forEach(btn => btn.addEventListener("click", () => deleteSimple("team", btn.dataset.id, loadTeam)));
  }

  async function loadMembers() {
    if (!state.patientId) return;
    const items = await api(`/api/v2/patients/${state.patientId}/members`);
    $("#memberList").innerHTML = items.map(item =>
      `<div class="mini-row"><div><strong>${escapeHtml(item.display_name)}</strong> <span class="muted">@${escapeHtml(item.username)}</span><br>${escapeHtml(item.role)}</div></div>`
    ).join("");
  }

  async function loadTimeline() {
    if (!state.patientId) return;
    const items = await api(`/api/v2/patients/${state.patientId}/timeline?limit=250`);
    $("#timeline").innerHTML = items.length ? items.map(item => `
      <article class="timeline-item">
        <div class="timeline-dot"></div>
        <div class="card">
          <small>${displayTime(item.occurred_at)} · ${escapeHtml(item.category)}</small>
          <h3>${escapeHtml(item.title)}</h3>
          ${item.hospital ? `<div class="muted">${escapeHtml(item.hospital)}</div>` : ""}
          ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}
          ${item.document_id ? `<button class="text-btn open-doc" data-id="${item.document_id}">Ver documento</button>` : ""}
        </div>
      </article>
    `).join("") : `<p class="empty">Aún no hay hitos en la línea temporal.</p>`;
    $$(".open-doc").forEach(btn => btn.addEventListener("click", () => {
      window.open(`/api/v2/patients/${state.patientId}/documents/${btn.dataset.id}/download`, "_blank", "noopener");
    }));
  }

  async function loadDocuments() {
    if (!state.patientId) return;
    const items = await api(`/api/v2/patients/${state.patientId}/documents`);
    $("#documentList").innerHTML = items.length ? items.map(item => `
      <article class="card document-card">
        <div class="card-head">
          <div><strong>${escapeHtml(item.exam_name || item.filename)}</strong><br><small>${escapeHtml(item.document_type)} · ${escapeHtml(item.event_date || "")}</small></div>
          <span class="badge">${escapeHtml(item.extraction_status)}</span>
        </div>
        <div class="muted">${escapeHtml(item.hospital || "")} · ${(item.size_bytes / 1024).toFixed(0)} KB</div>
        ${item.extracted_text ? `<details><summary>Texto extraído</summary><pre>${escapeHtml(item.extracted_text.slice(0, 6000))}</pre></details>` : ""}
        <div class="button-row">
          <a class="button-link secondary" href="/api/v2/patients/${state.patientId}/documents/${item.id}/download">Abrir</a>
          ${canEdit() ? `<button class="text-btn delete-doc" data-id="${item.id}">Eliminar</button>` : ""}
        </div>
      </article>
    `).join("") : `<p class="empty">No hay documentos.</p>`;
    $$(".delete-doc").forEach(btn => btn.addEventListener("click", async () => {
      if (!confirm("¿Eliminar el documento? Esta acción no se puede deshacer.")) return;
      try {
        await api(`/api/v2/patients/${state.patientId}/documents/${btn.dataset.id}`, { method: "DELETE" });
        await Promise.all([loadDocuments(), loadTimeline()]);
      } catch (error) {
        toast(error.message, true);
      }
    }));
  }

  async function loadShares() {
    if (!state.patientId) return;
    const items = await api(`/api/v2/patients/${state.patientId}/shares`);
    $("#shareList").innerHTML = items.length ? items.map(item =>
      `<div class="mini-row"><div><strong>${escapeHtml(item.detail)} · ${escapeHtml(item.language)}</strong><br><span class="muted">Vence ${displayTime(item.expires_at)} · accesos ${item.access_count}${item.revoked ? " · revocado" : ""}</span></div>${!item.revoked && canEdit() ? `<button class="text-btn revoke-share" data-id="${item.id}">Revocar</button>` : ""}</div>`
    ).join("") : `<p class="empty">No has creado enlaces.</p>`;
    $$(".revoke-share").forEach(btn => btn.addEventListener("click", async () => {
      try {
        await api(`/api/v2/patients/${state.patientId}/shares/${btn.dataset.id}`, { method: "DELETE" });
        await loadShares();
      } catch (error) {
        toast(error.message, true);
      }
    }));
  }

  function bindForms() {
    $("#medicationForm").addEventListener("submit", async event => {
      if (event.submitter?.value === "cancel") return;
      event.preventDefault();
      const data = formToObject(event.currentTarget);
      const payload = {
        name: data.name,
        generic_name: null,
        medication_type: data.medication_type || "Medicamento",
        purpose: nullable(data.purpose),
        dose: nullable(data.dose),
        route: nullable(data.route),
        frequency: nullable(data.frequency),
        instructions: nullable(data.instructions),
        times: String(data.times || "").split(",").map(v => v.trim()).filter(Boolean),
      };
      try {
        await api(`/api/v2/patients/${state.patientId}/medications`, { method: "POST", body: JSON.stringify(payload) });
        event.currentTarget.closest("dialog").close();
        event.currentTarget.reset();
        await loadDay();
        syncNativeNotifications();
        toast("Medicamento agregado.");
      } catch (error) { toast(error.message, true); }
    });

    $("#eliminationForm").addEventListener("submit", event => submitJsonDialog(event, "elimination", data => ({
      occurred_at: data.occurred_at,
      diaper_status: data.diaper_status,
      urine_amount: nullable(data.urine_amount),
      urine_color: nullable(data.urine_color),
      stool_description: nullable(data.stool_description),
      notes: nullable(data.notes),
    }), loadDay));

    $("#foodForm").addEventListener("submit", event => submitJsonDialog(event, "food", data => ({
      occurred_at: data.occurred_at,
      meal_type: nullable(data.meal_type),
      item: data.item,
      amount: numberOrNull(data.amount),
      unit: nullable(data.unit),
      tolerated: event.currentTarget.elements.tolerated.checked,
      vomiting: event.currentTarget.elements.vomiting.checked,
      notes: nullable(data.notes),
    }), loadDay));

    $("#teamForm").addEventListener("submit", event => submitJsonDialog(event, "team", data => ({
      name: data.name,
      specialty: nullable(data.specialty),
      role: nullable(data.role),
      hospital: nullable(data.hospital),
      phone: nullable(data.phone),
      email: nullable(data.email),
      notes: nullable(data.notes),
      is_primary: event.currentTarget.elements.is_primary.checked,
    }), loadTeam));

    $("#memberForm").addEventListener("submit", async event => {
      if (event.submitter?.value === "cancel") return;
      event.preventDefault();
      const data = formToObject(event.currentTarget);
      try {
        await api(`/api/v2/patients/${state.patientId}/members`, { method: "POST", body: JSON.stringify({ username: data.username, role: data.role }) });
        event.currentTarget.closest("dialog").close();
        event.currentTarget.reset();
        await loadMembers();
        toast("Acceso actualizado.");
      } catch (error) { toast(error.message, true); }
    });

    $("#hospitalizationForm").addEventListener("submit", event => submitJsonDialog(event, "hospitalizations", data => ({
      hospital: data.hospital,
      service: nullable(data.service),
      admission_at: data.admission_at,
      discharge_at: nullable(data.discharge_at),
      reason: nullable(data.reason),
      diagnosis: nullable(data.diagnosis),
      summary: nullable(data.summary),
      epicrisis_text: nullable(data.epicrisis_text),
    }), loadTimeline));

    $("#historyForm").addEventListener("submit", event => submitJsonDialog(event, "history", data => ({
      occurred_at: data.occurred_at,
      category: data.category,
      title: data.title,
      description: nullable(data.description),
      hospital: nullable(data.hospital),
      clinician_name: nullable(data.clinician_name),
      document_id: null,
    }), loadTimeline));

    $("#documentForm").addEventListener("submit", async event => {
      if (event.submitter?.value === "cancel") return;
      event.preventDefault();
      const fd = new FormData(event.currentTarget);
      try {
        toast("Procesando documento…");
        await api(`/api/v2/patients/${state.patientId}/documents`, { method: "POST", body: fd });
        event.currentTarget.closest("dialog").close();
        event.currentTarget.reset();
        await Promise.all([loadDocuments(), loadTimeline()]);
        toast("Documento guardado y procesado.");
      } catch (error) { toast(error.message, true); }
    });

    $("#vitalForm").addEventListener("submit", event => submitQueryDialog(event, "vitals", data => ({
      recorded_at: data.recorded_at,
      temperature_c: nullable(data.temperature_c),
      systolic: nullable(data.systolic),
      diastolic: nullable(data.diastolic),
      heart_rate: nullable(data.heart_rate),
      oxygen_saturation: nullable(data.oxygen_saturation),
      respiratory_rate: nullable(data.respiratory_rate),
      weight_kg: nullable(data.weight_kg),
      notes: nullable(data.notes),
    }), loadDay));

    $("#crisisForm").addEventListener("submit", event => submitQueryDialog(event, "crises", data => ({
      occurred_at: data.occurred_at,
      event_type: data.event_type,
      description: data.description,
      duration_seconds: nullable(data.duration_seconds),
      consciousness: nullable(data.consciousness),
      actions_taken: nullable(data.actions_taken),
      team_notified: event.currentTarget.elements.team_notified.checked,
      notes: nullable(data.notes),
    }), loadDay));

    $("#chemoForm").addEventListener("submit", event => submitQueryDialog(event, "chemo", data => ({
      scheduled_at: data.scheduled_at,
      name: data.name,
      protocol: nullable(data.protocol),
      cycle: nullable(data.cycle),
      purpose: nullable(data.purpose),
      status_value: data.status_value,
      notes: nullable(data.notes),
      adverse_effects: nullable(data.adverse_effects),
    }), loadDay));

    $("#patientForm").addEventListener("submit", async event => {
      event.preventDefault();
      const data = formToObject(event.currentTarget);
      const payload = {
        name: data.name,
        birth_date: nullable(data.birth_date),
        sex_at_birth: nullable(data.sex_at_birth),
        primary_hospital: nullable(data.primary_hospital),
        medical_record: nullable(data.medical_record),
        allergies: nullable(data.allergies),
        diagnoses: nullable(data.diagnoses),
        notes: nullable(data.notes),
      };
      try {
        if (state.patientId) {
          state.patient = await api(`/api/v2/patients/${state.patientId}`, { method: "PUT", body: JSON.stringify(payload) });
          toast("Paciente actualizado.");
          await loadPatients();
        } else {
          const created = await api("/api/v2/patients", { method: "POST", body: JSON.stringify(payload) });
          toast("Paciente creado.");
          await loadPatients();
          await selectPatient(created.id);
          showScreen("today");
        }
      } catch (error) { toast(error.message, true); }
    });
  }

  async function submitJsonDialog(event, resource, mapper, callback) {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const data = formToObject(event.currentTarget);
    try {
      await api(`/api/v2/patients/${state.patientId}/${resource}`, { method: "POST", body: JSON.stringify(mapper(data)) });
      event.currentTarget.closest("dialog").close();
      event.currentTarget.reset();
      setDefaultDateTimes();
      await callback();
      toast("Registro guardado.");
    } catch (error) { toast(error.message, true); }
  }

  async function submitQueryDialog(event, resource, mapper, callback) {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    const data = mapper(formToObject(event.currentTarget));
    const params = new URLSearchParams();
    Object.entries(data).forEach(([key, value]) => {
      if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
    });
    try {
      await api(`/api/v2/patients/${state.patientId}/${resource}?${params}`, { method: "POST" });
      event.currentTarget.closest("dialog").close();
      event.currentTarget.reset();
      setDefaultDateTimes();
      await callback();
      toast("Registro guardado.");
    } catch (error) { toast(error.message, true); }
  }

  function bindActions() {
    $("#saveNoteBtn").addEventListener("click", async () => {
      if (!state.patientId || !canEdit()) return;
      const params = new URLSearchParams({ note_date: state.date, text: $("#dailyNote").value });
      try {
        await api(`/api/v2/patients/${state.patientId}/daily-note?${params}`, { method: "PUT" });
        toast("Nota guardada.");
      } catch (error) { toast(error.message, true); }
    });

    $("#acceptLegalBtn").addEventListener("click", async () => {
      if (!$("#privacyCheck").checked || !$("#guardianCheck").checked) {
        toast("Debes aceptar ambas declaraciones.", true);
        return;
      }
      try {
        await api("/api/v2/legal/accept", { method: "POST", body: JSON.stringify({ consent_type: "privacy", granted: true, metadata: { source: "v2_web" } }) });
        await api("/api/v2/legal/accept", { method: "POST", body: JSON.stringify({ consent_type: "guardian", granted: true, metadata: { source: "v2_web" } }) });
        state.me = await api("/api/v2/auth/me");
        updateLegal();
        toast("Preferencias de privacidad guardadas.");
      } catch (error) { toast(error.message, true); }
    });

    $("#uploadPhotoBtn").addEventListener("click", async () => {
      const file = $("#patientPhotoInput").files[0];
      if (!file || !state.patientId) return toast("Selecciona una foto.", true);
      const fd = new FormData();
      fd.append("file", file);
      try {
        await api(`/api/v2/patients/${state.patientId}/photo`, { method: "POST", body: fd });
        state.patient = await api(`/api/v2/patients/${state.patientId}`);
        fillPatientForm(state.patient);
        toast("Foto actualizada.");
      } catch (error) { toast(error.message, true); }
    });

    $("#generateSummaryBtn").addEventListener("click", generateSummary);
    $("#createShareBtn").addEventListener("click", createShare);
    $("#copyShareBtn").addEventListener("click", async () => {
      await navigator.clipboard.writeText($("#shareUrl").value);
      toast("Enlace copiado.");
    });

    $("#logoutBtn").addEventListener("click", async () => {
      await fetch("/logout", { method: "POST", credentials: "same-origin" });
      location.href = "/login";
    });

    $("#deleteAccountBtn").addEventListener("click", async () => {
      if ($("#deleteConfirm").value !== "ELIMINAR") return toast("Escribe ELIMINAR para confirmar.", true);
      if (!confirm("Esta acción puede eliminar permanentemente información. ¿Continuar?")) return;
      try {
        await api("/api/v2/account/delete", {
          method: "POST",
          body: JSON.stringify({ password: $("#deletePassword").value, confirm: "ELIMINAR" }),
        });
        location.href = "/login";
      } catch (error) { toast(error.message, true); }
    });

    $("#medName").addEventListener("input", event => {
      clearTimeout(state.medSearchTimer);
      const q = event.target.value.trim();
      if (q.length < 2) return hideMedSuggestions();
      state.medSearchTimer = setTimeout(() => loadMedSuggestions(q), 250);
    });
  }

  async function loadMedSuggestions(q) {
    try {
      const items = await api(`/api/v2/medications/search?q=${encodeURIComponent(q)}`);
      const root = $("#medSuggestions");
      if (!items.length) return hideMedSuggestions();
      root.innerHTML = items.map((item, index) =>
        `<button type="button" data-index="${index}"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.type)}</span></button>`
      ).join("");
      root.classList.remove("hidden");
      $$("button", root).forEach((button, index) => button.addEventListener("click", () => {
        const item = items[index];
        $("#medName").value = item.name;
        $("#medType").value = item.type;
        $("#medPurpose").value = item.purpose;
        hideMedSuggestions();
      }));
    } catch (_) { hideMedSuggestions(); }
  }

  function hideMedSuggestions() {
    $("#medSuggestions").classList.add("hidden");
    $("#medSuggestions").innerHTML = "";
  }

  async function generateSummary() {
    if (!state.patientId) return;
    const params = summaryParams();
    try {
      const result = await api(`/api/v2/patients/${state.patientId}/summary?${params}`);
      $("#summaryText").textContent = result.plain_text;
    } catch (error) { toast(error.message, true); }
  }

  function summaryParams() {
    const params = new URLSearchParams({
      language: $("#summaryLanguage").value,
      detail: $("#summaryDetail").value,
    });
    if ($("#summaryStart").value) params.set("start_date", $("#summaryStart").value);
    if ($("#summaryEnd").value) params.set("end_date", $("#summaryEnd").value);
    return params;
  }

  async function createShare() {
    if (!state.patientId || !canEdit()) return;
    const payload = {
      language: $("#summaryLanguage").value,
      detail: $("#summaryDetail").value,
      start_date: nullable($("#summaryStart").value),
      end_date: nullable($("#summaryEnd").value),
      hospitalization_id: null,
      include_documents: $("#summaryDetail").value === "complete",
      expires_hours: 24,
    };
    if (!confirm("Se creará un enlace temporal de solo lectura. Compártelo únicamente con personas autorizadas. ¿Continuar?")) return;
    try {
      const result = await api(`/api/v2/patients/${state.patientId}/shares`, { method: "POST", body: JSON.stringify(payload) });
      $("#shareQr").src = result.qr_data_uri;
      $("#shareUrl").value = result.url;
      $("#shareExpiry").textContent = `Vence: ${displayTime(result.expires_at)}`;
      $("#shareResult").classList.remove("hidden");
      await loadShares();
    } catch (error) { toast(error.message, true); }
  }

  async function syncNativeNotifications() {
    if (!state.patientId || !window.IkerCareNative?.syncMedicationReminders) return;
    try {
      const schedule = await api(`/api/v2/patients/${state.patientId}/notification-schedule`);
      window.IkerCareNative.syncMedicationReminders(JSON.stringify(schedule));
    } catch (_) {}
  }

  function startPolling() {
    setInterval(async () => {
      if (!state.patientId) return;
      try {
        const params = state.serverTime ? `?since=${encodeURIComponent(state.serverTime)}` : "";
        const result = await api(`/api/v2/patients/${state.patientId}/changes${params}`);
        const hadBaseline = Boolean(state.serverTime);
        state.serverTime = result.server_time;
        if (hadBaseline && result.changed) {
          $("#syncNotice").classList.remove("hidden");
          await Promise.all([loadDay(), loadTimeline(), loadDocuments(), loadTeam()]);
          setTimeout(() => $("#syncNotice").classList.add("hidden"), 1800);
          syncNativeNotifications();
        }
      } catch (_) {}
    }, 15000);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.patientId) {
      loadDay().catch(() => {});
      syncNativeNotifications();
    }
  });

  init();
})();


if ("serviceWorker" in navigator && !window.IkerCareNative) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(() => {}));
}
