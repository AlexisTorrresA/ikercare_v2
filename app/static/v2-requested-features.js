(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const selectedDocumentFiles = [];
  let careData = null;
  let timelineTimer = null;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function toast(message, isError = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3600);
  }

  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  const patientId = () => Number($("#patientSelect")?.value || 0) || null;
  const currentDate = () => $("#selectedDate")?.value || new Date().toLocaleDateString("sv-SE");

  function formatDateTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).replace("T", " ");
    return date.toLocaleString("es-CL", { dateStyle: "medium", timeStyle: "short" });
  }

  function ensureCareTools() {
    const screen = $('[data-screen="care"]');
    if (!screen || $("#careRangeTools")) return;
    const title = screen.querySelector(".screen-title");
    const tools = document.createElement("section");
    tools.id = "careRangeTools";
    tools.className = "care-range-tools";
    const today = currentDate();
    tools.innerHTML = `
      <div class="care-filter-head">
        <div><strong>Periodo de cuidados</strong><span>Filtra signos, eventos y quimioterapia.</span></div>
      </div>
      <div class="care-filter-grid">
        <label>Desde<input id="careStartDate" type="date" value="${escapeHtml(today)}"></label>
        <label>Hasta<input id="careEndDate" type="date" value="${escapeHtml(today)}"></label>
        <button id="applyCareRange" type="button" class="primary">Aplicar</button>
        <button id="showAllCare" type="button" class="secondary">Mostrar todo</button>
      </div>
      <div class="care-chart-card">
        <div class="care-chart-head">
          <div><strong>Evolución de signos vitales</strong><span id="careChartCount"></span></div>
          <select id="careChartMetric" aria-label="Signo vital del gráfico">
            <option value="temperature_c">Temperatura</option>
            <option value="heart_rate">Frecuencia cardíaca</option>
            <option value="oxygen_saturation">SatO₂</option>
            <option value="blood_pressure">Presión arterial</option>
            <option value="respiratory_rate">Frecuencia respiratoria</option>
            <option value="weight_kg">Peso</option>
          </select>
        </div>
        <div id="careVitalChart" class="care-vital-chart"><p class="empty">Sin datos para graficar.</p></div>
      </div>`;
    title?.insertAdjacentElement("afterend", tools);
    $("#applyCareRange").addEventListener("click", loadCareRange);
    $("#showAllCare").addEventListener("click", () => {
      $("#careStartDate").value = "";
      $("#careEndDate").value = "";
      loadCareRange();
    });
    $("#careChartMetric").addEventListener("change", renderVitalChart);
  }

  async function loadCareRange() {
    const id = patientId();
    if (!id) return;
    const params = new URLSearchParams();
    const start = $("#careStartDate")?.value;
    const end = $("#careEndDate")?.value;
    if (start) params.set("start_date", start);
    if (end) params.set("end_date", end);
    try {
      careData = await api(`/api/v2/patients/${id}/care-range?${params}`);
      renderCareLists(careData);
      renderVitalChart();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function careCard(kind, title, time, details, notes = "") {
    return `<article class="care-record-card ${kind}">
      <div class="care-record-accent"></div>
      <div class="care-record-body">
        <div class="care-record-top"><strong>${escapeHtml(title)}</strong><time>${escapeHtml(time)}</time></div>
        ${details ? `<div class="care-record-chips">${details}</div>` : ""}
        ${notes ? `<p>${escapeHtml(notes)}</p>` : ""}
      </div>
    </article>`;
  }

  function chip(value, label = "") {
    if (value === null || value === undefined || value === "") return "";
    return `<span>${label ? `${escapeHtml(label)}: ` : ""}${escapeHtml(value)}</span>`;
  }

  function renderCareLists(data) {
    const vitalRoot = $("#vitalList");
    const crisisRoot = $("#crisisList");
    const chemoRoot = $("#chemoList");
    if (vitalRoot) {
      vitalRoot.innerHTML = data.vitals.length ? data.vitals.map(item => {
        const details = [
          chip(item.temperature_c != null ? `${item.temperature_c} °C` : ""),
          chip(item.systolic && item.diastolic ? `${item.systolic}/${item.diastolic} mmHg` : ""),
          chip(item.heart_rate, "FC"),
          chip(item.oxygen_saturation != null ? `${item.oxygen_saturation}%` : "", "SatO₂"),
          chip(item.respiratory_rate, "FR"),
          chip(item.weight_kg != null ? `${item.weight_kg} kg` : ""),
        ].join("");
        return careCard("vital", "Signos vitales", formatDateTime(item.recorded_at), details, item.notes || "");
      }).join("") : `<p class="empty">Sin signos vitales en el periodo.</p>`;
    }
    if (crisisRoot) {
      crisisRoot.innerHTML = data.crises.length ? data.crises.map(item => careCard(
        "event",
        item.event_type,
        formatDateTime(item.occurred_at),
        [chip(item.duration_seconds != null ? `${item.duration_seconds}s` : "", "Duración"), chip(item.consciousness, "Conciencia")].join(""),
        item.description || item.notes || ""
      )).join("") : `<p class="empty">Sin crisis o eventos en el periodo.</p>`;
    }
    if (chemoRoot) renderChemoCards(data.chemo, chemoRoot);
    scheduleExistingActionEnhancers();
  }

  function renderChemoCards(items, root = $("#chemoList")) {
    if (!root) return;
    root.innerHTML = items.length ? items.map(item => `
      <article class="care-record-card chemo mini-row" data-chemo-id="${item.id}">
        <div class="care-record-accent"></div>
        <div class="care-record-body">
          <div class="care-record-top"><strong>${escapeHtml(item.name)}</strong><time>${escapeHtml(formatDateTime(item.scheduled_at))}</time></div>
          <div class="care-record-chips">
            ${chip(item.protocol, "Protocolo")}${chip(item.cycle, "Ciclo")}${chip(item.status, "Estado")}
          </div>
          ${item.purpose ? `<p><strong>Objetivo:</strong> ${escapeHtml(item.purpose)}</p>` : ""}
          ${item.notes ? `<p>${escapeHtml(item.notes)}</p>` : ""}
          ${item.adverse_effects ? `<p><strong>Efectos registrados:</strong> ${escapeHtml(item.adverse_effects)}</p>` : ""}
        </div>
      </article>`).join("") : `<p class="empty">Sin quimioterapia registrada.</p>`;
  }

  function scheduleExistingActionEnhancers() {
    window.setTimeout(() => {
      const vital = $("#vitalList");
      const crises = $("#crisisList");
      if (vital || crises) {
        const date = $("#selectedDate");
        date?.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }, 0);
  }

  function renderVitalChart() {
    const root = $("#careVitalChart");
    if (!root || !careData) return;
    const metric = $("#careChartMetric")?.value || "temperature_c";
    const vitalRows = [...careData.vitals].sort((a, b) => String(a.recorded_at).localeCompare(String(b.recorded_at)));
    $("#careChartCount").textContent = vitalRows.length ? `${vitalRows.length} registros` : "Sin registros";
    const series = [];
    if (metric === "blood_pressure") {
      series.push({ name: "Sistólica", key: "systolic", values: vitalRows.map(v => v.systolic) });
      series.push({ name: "Diastólica", key: "diastolic", values: vitalRows.map(v => v.diastolic) });
    } else {
      series.push({ name: $("#careChartMetric")?.selectedOptions?.[0]?.textContent || metric, key: metric, values: vitalRows.map(v => v[metric]) });
    }
    const numeric = series.flatMap(s => s.values).filter(v => v !== null && v !== undefined && Number.isFinite(Number(v))).map(Number);
    if (!numeric.length) {
      root.innerHTML = `<p class="empty">No hay valores de este signo vital en el periodo.</p>`;
      return;
    }
    const min = Math.min(...numeric);
    const max = Math.max(...numeric);
    const spread = Math.max(max - min, 1);
    const width = 720, height = 240, padX = 42, padY = 28;
    const xFor = index => vitalRows.length <= 1 ? width / 2 : padX + index * ((width - padX * 2) / (vitalRows.length - 1));
    const yFor = value => height - padY - ((Number(value) - min) / spread) * (height - padY * 2);
    const palettes = ["chart-series-a", "chart-series-b"];
    const lines = series.map((s, si) => {
      const points = s.values.map((v, i) => v === null || v === undefined ? null : `${xFor(i)},${yFor(v)}`).filter(Boolean).join(" ");
      const dots = s.values.map((v, i) => v === null || v === undefined ? "" : `<circle class="${palettes[si]}" cx="${xFor(i)}" cy="${yFor(v)}" r="4"><title>${escapeHtml(s.name)}: ${escapeHtml(v)} · ${escapeHtml(formatDateTime(vitalRows[i].recorded_at))}</title></circle>`).join("");
      return `<polyline class="chart-line ${palettes[si]}" points="${points}" />${dots}`;
    }).join("");
    const labels = vitalRows.map((v, i) => {
      if (vitalRows.length > 8 && i % Math.ceil(vitalRows.length / 6) !== 0 && i !== vitalRows.length - 1) return "";
      const d = new Date(v.recorded_at);
      return `<text x="${xFor(i)}" y="${height - 5}" text-anchor="middle">${escapeHtml(d.toLocaleDateString("es-CL", { day: "2-digit", month: "2-digit" }))}</text>`;
    }).join("");
    const legend = series.map((s, i) => `<span><i class="${palettes[i]}"></i>${escapeHtml(s.name)}</span>`).join("");
    root.innerHTML = `<div class="chart-legend">${legend}<span>mín ${min} · máx ${max}</span></div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Evolución de signos vitales"><line class="chart-axis" x1="${padX}" y1="${padY}" x2="${padX}" y2="${height-padY}"/><line class="chart-axis" x1="${padX}" y1="${height-padY}" x2="${width-padX}" y2="${height-padY}"/>${lines}${labels}</svg>`;
  }

  async function loadAllChemo() {
    const id = patientId();
    if (!id) return;
    try {
      const items = await api(`/api/v2/patients/${id}/chemo/all`);
      renderChemoCards(items);
      window.setTimeout(() => document.dispatchEvent(new CustomEvent("ikercare:chemo-rendered")), 0);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function clarifyChemoForm() {
    const form = $("#chemoForm");
    if (!form || $("#chemoNameHelp")) return;
    const input = form.elements.name;
    if (!input) return;
    const label = input.closest("label");
    if (label?.firstChild) label.firstChild.textContent = "Medicamento / agente ";
    const help = document.createElement("small");
    help.id = "chemoNameHelp";
    help.className = "field-help";
    help.textContent = "Aquí va el nombre del medicamento o agente administrado. Registra cada agente como un registro separado para conservar fecha y hora.";
    label?.appendChild(help);
  }

  function enhanceChemoScreenNavigation() {
    document.addEventListener("click", event => {
      const nav = event.target.closest('[data-app-nav="chemo"]');
      if (nav) window.setTimeout(loadAllChemo, 80);
    });
    const chemoRoot = $("#chemoList");
    if (chemoRoot) new MutationObserver(() => {
      const chemoScreen = $('[data-screen="chemo"]');
      if (chemoScreen?.classList.contains("active") && !chemoRoot.dataset.loadingAll) {
        window.clearTimeout(enhanceChemoScreenNavigation.timer);
        enhanceChemoScreenNavigation.timer = window.setTimeout(loadAllChemo, 180);
      }
    }).observe(chemoRoot, { childList: true });
  }

  function bindTimelineActions() {
    const root = $("#timeline");
    if (!root) return;
    new MutationObserver(() => {
      clearTimeout(timelineTimer);
      timelineTimer = setTimeout(enhanceTimeline, 100);
    }).observe(root, { childList: true, subtree: false });
    document.addEventListener("click", event => {
      if (event.target.closest('[data-app-nav="history"], [data-nav="history"]')) setTimeout(enhanceTimeline, 250);
    });
  }

  async function enhanceTimeline() {
    const id = patientId();
    const root = $("#timeline");
    if (!id || !root) return;
    try {
      const [patient, items] = await Promise.all([api(`/api/v2/patients/${id}`), api(`/api/v2/patients/${id}/timeline?limit=250`)]);
      if (!["owner", "editor"].includes(patient.role)) return;
      const cards = $$(".timeline-item .card", root);
      items.forEach((item, index) => {
        const card = cards[index];
        if (!card || card.querySelector(".history-record-actions") || String(item.id).startsWith("document-")) return;
        const actions = document.createElement("div");
        actions.className = "history-record-actions button-row";
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "text-btn";
        edit.textContent = "Editar";
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "text-btn danger-text";
        remove.textContent = "Eliminar";
        if (item.hospitalization_id) {
          edit.onclick = () => editHospitalization(item.hospitalization_id);
          remove.onclick = () => deleteHistoryResource("hospitalizations", item.hospitalization_id, "hospitalización");
        } else if (String(item.id).startsWith("history-")) {
          const historyId = Number(String(item.id).replace("history-", ""));
          edit.onclick = () => editHistoryEvent(historyId);
          remove.onclick = () => deleteHistoryResource("history", historyId, "hito");
        } else return;
        actions.append(edit, remove);
        card.appendChild(actions);
      });
    } catch (_) {}
  }

  async function editHospitalization(itemId) {
    try {
      const item = await api(`/api/v2/patients/${patientId()}/hospitalizations/${itemId}`);
      const form = $("#hospitalizationForm");
      form.reset();
      form.dataset.editId = String(itemId);
      form.elements.hospital.value = item.hospital || "";
      form.elements.service.value = item.service || "";
      form.elements.admission_at.value = (item.admission_at || "").slice(0, 16);
      form.elements.discharge_at.value = (item.discharge_at || "").slice(0, 16);
      form.elements.reason.value = item.reason || "";
      form.elements.diagnosis.value = item.diagnosis || "";
      form.elements.summary.value = item.summary || "";
      form.elements.epicrisis_text.value = item.epicrisis_text || "";
      form.querySelector(".dialog-head h2").textContent = "Modificar hospitalización";
      form.querySelector("button.primary").textContent = "Guardar cambios";
      $("#hospitalizationDialog")?.showModal();
    } catch (error) { toast(error.message, true); }
  }

  async function editHistoryEvent(itemId) {
    try {
      const item = await api(`/api/v2/patients/${patientId()}/history/${itemId}`);
      const form = $("#historyForm");
      form.reset();
      form.dataset.editId = String(itemId);
      for (const field of ["category", "title", "description", "hospital", "clinician_name"]) form.elements[field].value = item[field] || "";
      form.elements.occurred_at.value = (item.occurred_at || "").slice(0, 16);
      form.querySelector(".dialog-head h2").textContent = "Modificar hito";
      form.querySelector("button.primary").textContent = "Guardar cambios";
      $("#historyDialog")?.showModal();
    } catch (error) { toast(error.message, true); }
  }

  function resetHistoryForm(form, title) {
    delete form.dataset.editId;
    form.querySelector(".dialog-head h2").textContent = title;
    form.querySelector("button.primary").textContent = "Guardar";
  }

  function bindHistoryEditSubmissions() {
    const hospitalization = $("#hospitalizationForm");
    hospitalization?.addEventListener("submit", async event => {
      const id = hospitalization.dataset.editId;
      if (!id) return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.submitter?.value === "cancel") return;
      const data = Object.fromEntries(new FormData(hospitalization).entries());
      try {
        await api(`/api/v2/patients/${patientId()}/hospitalizations/${id}`, { method: "PUT", body: JSON.stringify(data) });
        hospitalization.closest("dialog")?.close(); hospitalization.reset(); resetHistoryForm(hospitalization, "Hospitalización");
        triggerHistoryReload(); toast("Hospitalización modificada correctamente.");
      } catch (error) { toast(error.message, true); }
    }, true);
    const history = $("#historyForm");
    history?.addEventListener("submit", async event => {
      const id = history.dataset.editId;
      if (!id) return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.submitter?.value === "cancel") return;
      const data = Object.fromEntries(new FormData(history).entries());
      try {
        await api(`/api/v2/patients/${patientId()}/history/${id}`, { method: "PUT", body: JSON.stringify(data) });
        history.closest("dialog")?.close(); history.reset(); resetHistoryForm(history, "Agregar hito");
        triggerHistoryReload(); toast("Hito modificado correctamente.");
      } catch (error) { toast(error.message, true); }
    }, true);
    $$('[data-open="hospitalizationDialog"]').forEach(btn => btn.addEventListener("click", () => resetHistoryForm(hospitalization, "Hospitalización"), true));
    $$('[data-open="historyDialog"]').forEach(btn => btn.addEventListener("click", () => resetHistoryForm(history, "Agregar hito"), true));
  }

  async function deleteHistoryResource(resource, itemId, label) {
    if (!confirm(`¿Eliminar esta ${label}? Esta acción no se puede deshacer.`)) return;
    try {
      await api(`/api/v2/patients/${patientId()}/${resource}/${itemId}`, { method: "DELETE" });
      triggerHistoryReload(); toast(`${label.charAt(0).toUpperCase() + label.slice(1)} eliminado correctamente.`);
    } catch (error) { toast(error.message, true); }
  }

  function triggerHistoryReload() {
    const legacy = $('.bottom-nav [data-nav="history"]');
    if (legacy) legacy.click();
    setTimeout(enhanceTimeline, 250);
  }

  function setupDocumentUpload() {
    const form = $("#documentForm");
    const input = form?.elements.file;
    if (!form || !input || $("#documentUploadTools")) return;
    input.multiple = true;
    input.accept = "application/pdf,image/jpeg,image/png,image/webp,image/*";
    const tools = document.createElement("div");
    tools.id = "documentUploadTools";
    tools.className = "document-upload-tools";
    tools.innerHTML = `<div class="button-row"><button id="chooseDocumentsBtn" type="button" class="secondary">Elegir fotos / archivos</button><button id="takePhotoBtn" type="button" class="secondary">Tomar foto</button></div><small id="documentSelectionStatus" class="field-help">Puedes seleccionar hasta 10 elementos.</small>`;
    input.style.display = "none";
    input.closest("label")?.appendChild(tools);
    const camera = document.createElement("input");
    camera.type = "file";
    camera.accept = "image/*";
    camera.setAttribute("capture", "environment");
    camera.style.display = "none";
    form.appendChild(camera);

    const updateSelection = files => {
      for (const file of files) {
        if (selectedDocumentFiles.length >= 10) break;
        const duplicate = selectedDocumentFiles.some(item => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified);
        if (!duplicate) selectedDocumentFiles.push(file);
      }
      $("#documentSelectionStatus").textContent = selectedDocumentFiles.length ? `${selectedDocumentFiles.length} de 10 seleccionados: ${selectedDocumentFiles.map(f => f.name).join(", ")}` : "Puedes seleccionar hasta 10 elementos.";
    };
    input.addEventListener("change", () => updateSelection([...input.files]));
    camera.addEventListener("change", () => updateSelection([...camera.files]));
    $("#chooseDocumentsBtn").onclick = () => input.click();
    $("#takePhotoBtn").onclick = () => camera.click();

    form.addEventListener("submit", async event => {
      event.preventDefault(); event.stopImmediatePropagation();
      if (event.submitter?.value === "cancel") return;
      if (!selectedDocumentFiles.length) {
        toast("Selecciona al menos una foto, PDF o informe.", true);
        return;
      }
      if (selectedDocumentFiles.length > 10) {
        toast("El máximo es 10 elementos por carga.", true);
        return;
      }
      const base = new FormData(form);
      base.delete("file");
      let uploaded = 0;
      try {
        for (const file of selectedDocumentFiles) {
          const fd = new FormData();
          for (const [key, value] of base.entries()) fd.append(key, value);
          fd.append("file", file, file.name);
          toast(`Procesando ${uploaded + 1} de ${selectedDocumentFiles.length}…`);
          await api(`/api/v2/patients/${patientId()}/documents`, { method: "POST", body: fd });
          uploaded += 1;
        }
        selectedDocumentFiles.length = 0;
        form.reset();
        $("#documentSelectionStatus").textContent = "Puedes seleccionar hasta 10 elementos.";
        form.closest("dialog")?.close();
        const legacy = $('.bottom-nav [data-nav="documents"]'); legacy?.click();
        toast(`${uploaded} elemento${uploaded === 1 ? "" : "s"} guardado${uploaded === 1 ? "" : "s"} correctamente.`);
      } catch (error) {
        toast(`Se guardaron ${uploaded}; error: ${error.message}`, true);
      }
    }, true);
  }

  function createReportsScreen() {
    if ($('[data-screen="reports"]')) return;
    const main = $("main");
    const account = $('[data-screen="account"]');
    if (!main) return;
    const screen = document.createElement("section");
    screen.className = "screen reports-screen";
    screen.dataset.screen = "reports";
    screen.innerHTML = `
      <div class="screen-title"><div><h1>Reportes</h1><p class="muted">Informes construidos desde los datos registrados en IkerCare.</p></div></div>
      <article class="card report-builder">
        <div class="form-grid report-filter-grid">
          <label>Tipo de informe<select id="reportScope"><option value="all">Historia completa</option><option value="hospitalization">Hospitalización</option><option value="oncology">Oncológico / tratamiento</option><option value="medication">Medicamento / tratamiento</option></select></label>
          <label>Hospitalización<select id="reportHospitalization"><option value="">Todas / ninguna específica</option></select></label>
          <label>Desde<input id="reportStart" type="date"></label>
          <label>Hasta<input id="reportEnd" type="date"></label>
          <label>Hospital / centro<input id="reportHospital" placeholder="Ej. Calvo Mackenna"></label>
          <label>Medicamento / tratamiento<input id="reportMedication" placeholder="Ej. Levetiracetam"></label>
        </div>
        <label class="report-ai-option"><input id="reportUseAi" type="checkbox"> Usar OpenAI solo para redactar la narrativa cronológica a partir de los datos registrados</label>
        <p class="field-help">La IA no decide diagnósticos ni tratamientos y no puede agregar hechos que no estén en la base de datos.</p>
        <div class="button-row"><button id="generateReportBtn" class="primary" type="button">Generar informe</button><button id="downloadReportBtn" class="secondary" type="button" disabled>Descargar PDF</button></div>
      </article>
      <section id="reportResult" class="report-result hidden">
        <article class="card"><div class="card-head"><h2>Narrativa del paciente</h2><span id="reportAiBadge" class="badge"></span></div><div id="reportNarrative" class="report-narrative"></div></article>
        <article class="card"><h2>Análisis estadístico</h2><div id="reportStats" class="report-stats-grid"></div></article>
        <article class="card"><h2>Información incluida</h2><div id="reportFacts" class="report-facts"></div></article>
      </section>`;
    if (account) main.insertBefore(screen, account); else main.appendChild(screen);
    $("#generateReportBtn").addEventListener("click", generateReport);
    $("#downloadReportBtn").addEventListener("click", downloadReport);
    loadReportHospitalizations();
    injectReportsMenuItem();
  }

  async function loadReportHospitalizations() {
    const id = patientId();
    const select = $("#reportHospitalization");
    if (!id || !select) return;
    try {
      const rows = await api(`/api/v2/patients/${id}/hospitalizations`);
      select.innerHTML = `<option value="">Todas / ninguna específica</option>` + rows.map(item => `<option value="${item.id}">${escapeHtml(item.hospital)} · ${escapeHtml(item.admission_at.slice(0,10))}${item.discharge_at ? ` → ${escapeHtml(item.discharge_at.slice(0,10))}` : ""}</option>`).join("");
    } catch (_) {}
  }

  function injectReportsMenuItem() {
    const sheet = $("#moreNavigationSheet .more-grid");
    if (!sheet || sheet.querySelector('[data-more-nav="reports"]')) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "more-item";
    button.dataset.moreNav = "reports";
    button.innerHTML = `<span class="more-item-icon report-menu-icon">▤</span><span class="more-item-copy"><strong>Reportes</strong><small>PDF, filtros y estadísticas</small></span><span class="more-item-arrow" aria-hidden="true">›</span>`;
    sheet.appendChild(button);
    button.addEventListener("click", () => {
      $$(".screen").forEach(section => section.classList.toggle("active", section.dataset.screen === "reports"));
      $("#moreNavigationSheet")?.close();
      window.scrollTo({ top: 0, behavior: "smooth" });
      loadReportHospitalizations();
    }, true);
  }

  function reportPayload() {
    return {
      scope: $("#reportScope")?.value || "all",
      hospitalization_id: $("#reportHospitalization")?.value ? Number($("#reportHospitalization").value) : null,
      start_date: $("#reportStart")?.value || null,
      end_date: $("#reportEnd")?.value || null,
      hospital: $("#reportHospital")?.value.trim() || null,
      medication: $("#reportMedication")?.value.trim() || null,
      use_ai: Boolean($("#reportUseAi")?.checked),
    };
  }

  async function generateReport() {
    const id = patientId();
    if (!id) return;
    const button = $("#generateReportBtn");
    button.disabled = true; button.textContent = "Generando…";
    try {
      const result = await api(`/api/v2/patients/${id}/reports/preview`, { method: "POST", body: JSON.stringify(reportPayload()) });
      renderReport(result);
      $("#downloadReportBtn").disabled = false;
      toast("Informe generado correctamente.");
    } catch (error) { toast(error.message, true); }
    finally { button.disabled = false; button.textContent = "Generar informe"; }
  }

  function statCard(label, value, detail = "") {
    return `<div class="report-stat"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? 0)}</strong>${detail ? `<small>${escapeHtml(detail)}</small>` : ""}</div>`;
  }

  function renderReport(result) {
    $("#reportResult").classList.remove("hidden");
    $("#reportNarrative").innerHTML = result.narrative.split(/\n+/).filter(Boolean).map(p => `<p>${escapeHtml(p)}</p>`).join("");
    $("#reportAiBadge").textContent = result.ai_used ? "Redacción IA" : (result.ai_message ? "Redacción local" : "Datos IkerCare");
    const s = result.statistics || {};
    const rangeDetail = metric => metric?.avg == null ? "Sin datos" : `mín ${metric.min} · prom ${metric.avg} · máx ${metric.max}`;
    $("#reportStats").innerHTML = [
      statCard("Hospitalizaciones", s.hospitalizations), statCard("Quimioterapias", s.chemotherapy_sessions), statCard("Crisis/eventos", s.crises_events), statCard("Documentos", s.documents),
      statCard("Medicamentos tomados", s.medication_taken), statCard("Omitidos", s.medication_skipped), statCard("Signos vitales", s.vitals_count),
      statCard("Temperatura", s.temperature?.avg ?? "—", rangeDetail(s.temperature)), statCard("FC", s.heart_rate?.avg ?? "—", rangeDetail(s.heart_rate)), statCard("SatO₂", s.oxygen_saturation?.avg ?? "—", rangeDetail(s.oxygen_saturation)),
      statCard("PA sistólica", s.systolic?.avg ?? "—", rangeDetail(s.systolic)), statCard("PA diastólica", s.diastolic?.avg ?? "—", rangeDetail(s.diastolic)),
    ].join("");
    const f = result.facts || {};
    const sections = [];
    if (f.hospitalizations?.length) sections.push(`<h3>Hospitalizaciones</h3>${f.hospitalizations.map(x => `<div class="report-row"><strong>${escapeHtml(x.hospital)}</strong><span>${escapeHtml(x.admission_at)} → ${escapeHtml(x.discharge_at || "sin alta registrada")}</span>${x.diagnosis ? `<p>${escapeHtml(x.diagnosis)}</p>` : ""}</div>`).join("")}`);
    if (f.chemotherapy?.length) sections.push(`<h3>Quimioterapia</h3>${f.chemotherapy.map(x => `<div class="report-row"><strong>${escapeHtml(x.name)}</strong><span>${escapeHtml(formatDateTime(x.scheduled_at))} · ${escapeHtml([x.protocol,x.cycle,x.status].filter(Boolean).join(" · "))}</span></div>`).join("")}`);
    if (f.medications?.length) sections.push(`<h3>Medicamentos</h3>${f.medications.map(x => `<div class="report-row"><strong>${escapeHtml(x.name)}</strong><span>${escapeHtml([x.dose,x.route,x.frequency].filter(Boolean).join(" · "))}</span></div>`).join("")}`);
    if (f.history?.length) sections.push(`<h3>Hitos</h3>${f.history.map(x => `<div class="report-row"><strong>${escapeHtml(x.title)}</strong><span>${escapeHtml(formatDateTime(x.occurred_at))}${x.hospital ? ` · ${escapeHtml(x.hospital)}` : ""}</span></div>`).join("")}`);
    if (f.documents?.length) sections.push(`<h3>Exámenes e informes</h3>${f.documents.map(x => `<div class="report-row"><strong>${escapeHtml(x.name)}</strong><span>${escapeHtml(x.event_date || "Sin fecha")}${x.hospital ? ` · ${escapeHtml(x.hospital)}` : ""}</span></div>`).join("")}`);
    $("#reportFacts").innerHTML = sections.join("") || `<p class="empty">No hay datos para los filtros seleccionados.</p>`;
  }

  function downloadReport() {
    const id = patientId();
    if (!id) return;
    const payload = reportPayload();
    const params = new URLSearchParams();
    Object.entries(payload).forEach(([key, value]) => { if (value !== null && value !== "") params.set(key, String(value)); });
    window.location.href = `/api/v2/patients/${id}/reports/pdf?${params}`;
  }

  function bindPatientRefreshes() {
    $("#patientSelect")?.addEventListener("change", () => {
      setTimeout(() => { loadCareRange(); loadAllChemo(); loadReportHospitalizations(); }, 350);
    });
    document.addEventListener("ikercare:chemo-rendered", () => {});
  }

  function init() {
    ensureCareTools();
    clarifyChemoForm();
    enhanceChemoScreenNavigation();
    bindTimelineActions();
    bindHistoryEditSubmissions();
    setupDocumentUpload();
    createReportsScreen();
    bindPatientRefreshes();
    loadCareRange();
    loadAllChemo();
    setTimeout(enhanceTimeline, 350);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
