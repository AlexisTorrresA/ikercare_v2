(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  let aiTimer = null;
  let aiSequence = 0;

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
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const ct = response.headers.get("content-type") || "";
    const payload = ct.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  const patientId = () => Number($("#patientSelect")?.value || 0) || null;
  const normalize = value => String(value || "").trim().toLocaleLowerCase("es").replace(/\s+/g, " ");
  const isSosFrequency = value => /\b(sos|rescate|seg[uú]n necesidad|si es necesario)\b/i.test(String(value || ""));

  function ensureStatusLine() {
    const name = $("#medName");
    if (!name || $("#medAiStatus")) return;
    const line = document.createElement("small");
    line.id = "medAiStatus";
    line.className = "field-help";
    line.style.display = "block";
    line.style.marginTop = "6px";
    name.closest("label")?.appendChild(line);
  }

  function setAiStatus(text, error = false) {
    ensureStatusLine();
    const line = $("#medAiStatus");
    if (!line) return;
    line.textContent = text || "";
    line.style.color = error ? "#a12622" : "";
  }

  async function enrichUnknownMedication(sequence) {
    const input = $("#medName");
    const name = input?.value.trim();
    if (!name || name.length < 4) return;
    try {
      const suggestions = await api(`/api/v2/medications/search?q=${encodeURIComponent(name)}`);
      if (sequence !== aiSequence || input.value.trim() !== name) return;
      const exact = suggestions.find(item => normalize(item.name) === normalize(name));
      if (exact) {
        setAiStatus("Medicamento encontrado en el catálogo.");
        return;
      }

      const box = $("#medSuggestions");
      if (box) { box.classList.add("hidden"); box.innerHTML = ""; }
      setAiStatus("No está en el catálogo. Completando categoría y uso con IA…");
      const result = await api("/api/v2/medications/ai-enrich", {
        method: "POST",
        body: JSON.stringify({ name }),
      });
      if (sequence !== aiSequence || input.value.trim() !== name) return;
      if (result.medication_type && $("#medType")) $("#medType").value = result.medication_type;
      if (result.purpose && $("#medPurpose")) $("#medPurpose").value = result.purpose;
      const route = $("#medicationForm")?.elements.route;
      if (route && !route.value && result.usual_route) route.value = result.usual_route;
      setAiStatus(result.source === "openai" ? "Información general completada con IA. Revisa antes de guardar." : "Información completada desde el catálogo.");
    } catch (error) {
      if (sequence !== aiSequence) return;
      setAiStatus(error.message, true);
    }
  }

  function bindAiFallback() {
    const input = $("#medName");
    if (!input || input.dataset.aiFallback === "1") return;
    input.dataset.aiFallback = "1";
    ensureStatusLine();
    const schedule = delay => {
      clearTimeout(aiTimer);
      aiSequence += 1;
      const sequence = aiSequence;
      setAiStatus("");
      aiTimer = setTimeout(() => enrichUnknownMedication(sequence), delay);
    };
    input.addEventListener("input", () => schedule(950));
    input.addEventListener("blur", () => schedule(180));
  }

  function addSosField(form, id) {
    if (!form || form.querySelector(`[data-sos-field="${id}"]`)) return;
    const frequency = form.elements.frequency;
    const times = form.elements.times;
    if (!frequency || !times) return;
    const label = document.createElement("label");
    label.dataset.sosField = id;
    label.className = "wide";
    label.innerHTML = `<span><input type="checkbox" name="is_sos"> Medicamento SOS / solo si se necesita</span><small class="field-help">No crea horarios fijos. No modifica dosis ni indicaciones clínicas.</small>`;
    const grid = frequency.closest(".form-grid");
    (grid || frequency.closest("label"))?.insertAdjacentElement("afterend", label);
    const checkbox = label.querySelector('input[name="is_sos"]');
    checkbox.addEventListener("change", () => applySos(form, checkbox.checked));
  }

  function applySos(form, checked) {
    const frequency = form.elements.frequency;
    const times = form.elements.times;
    if (!frequency || !times) return;
    if (checked) {
      if (!isSosFrequency(frequency.value)) frequency.dataset.beforeSos = frequency.value;
      frequency.value = "SOS / según necesidad";
      times.dataset.beforeSos = times.value;
      times.value = "";
      times.disabled = true;
    } else {
      if (isSosFrequency(frequency.value)) frequency.value = frequency.dataset.beforeSos || "";
      times.disabled = false;
      if (!times.value && times.dataset.beforeSos) times.value = times.dataset.beforeSos;
    }
  }

  function syncEditSos() {
    const form = $("#medicationEditForm");
    if (!form) return;
    addSosField(form, "edit");
    const checkbox = form.elements.is_sos;
    if (!checkbox) return;
    const sos = isSosFrequency(form.elements.frequency?.value);
    checkbox.checked = sos;
    if (sos) { form.elements.times.value = ""; form.elements.times.disabled = true; }
    else form.elements.times.disabled = false;
  }

  function setupSos() {
    const addForm = $("#medicationForm");
    addSosField(addForm, "add");
    document.addEventListener("click", event => {
      if (event.target.closest('[data-open="medicationDialog"]')) {
        setTimeout(() => {
          const form = $("#medicationForm");
          const checkbox = form?.elements.is_sos;
          if (checkbox) { checkbox.checked = false; form.elements.times.disabled = false; }
          setAiStatus("");
        }, 50);
      }
      if (event.target.closest(".ext-edit-med,.edit-managed-med")) setTimeout(syncEditSos, 120);
    });
    new MutationObserver(syncEditSos).observe(document.body, { childList: true, subtree: true });
  }

  function ensurePermanentDeleteDialog() {
    let dialog = $("#permanentDeleteMedicationDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "permanentDeleteMedicationDialog";
    dialog.innerHTML = `
      <form id="permanentDeleteMedicationForm" class="dialog-form">
        <div class="dialog-head">
          <div>
            <h2>Eliminar medicamento definitivamente</h2>
            <p class="muted" style="margin:4px 0 0">Esta acción es irreversible.</p>
          </div>
          <button type="button" class="icon-btn" data-close-permanent-delete aria-label="Cerrar">×</button>
        </div>
        <input type="hidden" name="medication_id">
        <input type="hidden" name="medication_name">
        <div class="notice">
          Se eliminarán el medicamento, sus horarios, administraciones e historial asociado.
        </div>
        <label>Para confirmar, escribe exactamente <strong id="permanentDeleteMedicationName"></strong>
          <input name="confirmation" autocomplete="off" required>
        </label>
        <div class="button-row">
          <button type="button" class="secondary" data-close-permanent-delete>Cancelar</button>
          <button type="submit" class="danger">Eliminar definitivamente</button>
        </div>
      </form>`;
    document.body.appendChild(dialog);
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-permanent-delete]")) dialog.close();
    });
    $("#permanentDeleteMedicationForm", dialog).addEventListener("submit", submitPermanentDelete);
    return dialog;
  }

  function openPermanentDeleteDialog(med) {
    const dialog = ensurePermanentDeleteDialog();
    const form = $("#permanentDeleteMedicationForm", dialog);
    form.reset();
    form.elements.medication_id.value = String(med.id);
    form.elements.medication_name.value = med.name;
    $("#permanentDeleteMedicationName", dialog).textContent = med.name;
    dialog.showModal();
    requestAnimationFrame(() => form.elements.confirmation.focus());
  }

  async function submitPermanentDelete(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const id = Number(form.elements.medication_id.value);
    const name = form.elements.medication_name.value;
    const typed = form.elements.confirmation.value;
    if (typed !== name) {
      toast("El nombre escrito no coincide con el medicamento.", true);
      form.elements.confirmation.focus();
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      await api(`/api/v2/patients/${patientId()}/medications/${id}/permanent`, { method: "DELETE" });
      form.closest("dialog")?.close();
      toast("Medicamento eliminado definitivamente.");
      setTimeout(() => location.reload(), 350);
    } catch (error) {
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  }

  async function addPermanentDeleteButtons() {
    const root = $("#configuredMedicationList");
    const pid = patientId();
    if (!root || !pid) return;
    let meds;
    try { meds = await api(`/api/v2/patients/${pid}/medications`); } catch (_) { return; }
    const byId = new Map(meds.map(m => [Number(m.id), m]));
    $$(".ext-edit-med,.edit-managed-med", root).forEach(edit => {
      const id = Number(edit.dataset.id);
      const med = byId.get(id);
      const row = edit.closest(".button-row");
      if (!med || !row || row.querySelector(`.permanent-delete-med[data-id="${id}"]`)) return;
      if (isSosFrequency(med.frequency) && !edit.closest("article")?.querySelector(".sos-med-badge")) {
        const badge = document.createElement("span");
        badge.className = "badge sos-med-badge";
        badge.textContent = "SOS";
        edit.closest("article")?.querySelector(".card-head > div")?.appendChild(badge);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "danger permanent-delete-med";
      button.dataset.id = String(id);
      button.textContent = "Eliminar definitivamente";
      button.onclick = () => openPermanentDeleteDialog(med);
      row.appendChild(button);
    });
  }

  async function addHistoryDeleteButtons() {
    const form = $("#medicationEditForm");
    const root = $("#medTreatmentHistory .history-content");
    const pid = patientId();
    const medId = Number(form?.elements.id?.value || 0);
    if (!root || !pid || !medId) return;
    let rows;
    try { rows = await api(`/api/v2/patients/${pid}/medications/${medId}/treatment-history`); } catch (_) { return; }
    const rendered = $$(".treatment-history-item", root);
    rendered.forEach((element, index) => {
      const item = rows[index];
      if (!item || item.event_type === "initial" || element.querySelector(".delete-history-item")) return;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-btn danger-text delete-history-item";
      button.textContent = "Eliminar este registro";
      button.onclick = async () => {
        if (!confirm("¿Eliminar este cambio del historial? Úsalo solo si fue registrado por error.")) return;
        try {
          await api(`/api/v2/patients/${pid}/medications/${medId}/treatment-history/${item.id}`, { method: "DELETE" });
          element.remove();
          toast("Registro del historial eliminado.");
        } catch (error) { toast(error.message, true); }
      };
      element.appendChild(button);
    });
  }

  function observeMedicationUi() {
    const observer = new MutationObserver(() => {
      setTimeout(addPermanentDeleteButtons, 80);
      setTimeout(addHistoryDeleteButtons, 100);
      bindAiFallback();
      syncEditSos();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    document.addEventListener("click", event => {
      if (event.target.closest("#manageMedicationsBtn")) setTimeout(addPermanentDeleteButtons, 350);
      if (event.target.closest(".ext-edit-med,.edit-managed-med")) setTimeout(addHistoryDeleteButtons, 250);
    });
  }

  function init() {
    bindAiFallback();
    setupSos();
    ensurePermanentDeleteDialog();
    observeMedicationUi();
    setTimeout(addPermanentDeleteButtons, 500);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
