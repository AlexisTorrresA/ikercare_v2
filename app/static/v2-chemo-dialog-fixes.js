(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  let enhanceTimer = null;

  function toast(message, isError = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3400);
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
      const detail = typeof payload === "object" ? payload.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  const patientId = () => Number($("#patientSelect")?.value || 0) || null;
  const selectedDate = () => $("#selectedDate")?.value || "";
  const nullable = value => String(value ?? "").trim() || null;

  function resetDialogScroll(dialog) {
    if (!dialog) return;
    const form = dialog.querySelector(".dialog-form");
    dialog.scrollTop = 0;
    form?.scrollTo({ top: 0, left: 0, behavior: "instant" });
    requestAnimationFrame(() => {
      dialog.scrollTop = 0;
      form?.scrollTo({ top: 0, left: 0, behavior: "instant" });
    });
  }

  function closeDialogWithoutValidation(button) {
    const dialog = button.closest("dialog");
    if (!dialog) return;
    button.type = "button";
    dialog.close();
    resetDialogScroll(dialog);
  }

  function bindDialogCloseAndScrollFixes() {
    $$("dialog").forEach(dialog => {
      const closeButton = dialog.querySelector(".dialog-head .icon-btn");
      if (closeButton && !closeButton.dataset.safeCloseBound) {
        closeButton.dataset.safeCloseBound = "1";
        closeButton.type = "button";
        closeButton.addEventListener("click", event => {
          event.preventDefault();
          event.stopImmediatePropagation();
          closeDialogWithoutValidation(closeButton);
        }, true);
      }

      if (!dialog.dataset.scrollResetBound) {
        dialog.dataset.scrollResetBound = "1";
        dialog.addEventListener("close", () => resetDialogScroll(dialog));
      }
    });

    $$('[data-open]').forEach(button => {
      if (button.dataset.scrollOpenBound) return;
      button.dataset.scrollOpenBound = "1";
      button.addEventListener("click", () => {
        const dialog = document.getElementById(button.dataset.open);
        if (dialog?.id === "chemoDialog") resetChemoFormForCreate();
        setTimeout(() => resetDialogScroll(dialog), 0);
      }, true);
    });
  }

  function resetChemoFormForCreate() {
    const form = $("#chemoForm");
    if (!form) return;
    delete form.dataset.editId;
    const heading = form.querySelector(".dialog-head h2");
    if (heading) heading.textContent = "Quimioterapia";
    const submit = form.querySelector("button.primary");
    if (submit) submit.textContent = "Guardar";
  }

  function chemoPayload(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    return {
      scheduled_at: data.scheduled_at,
      name: data.name,
      protocol: nullable(data.protocol),
      cycle: nullable(data.cycle),
      purpose: nullable(data.purpose),
      status_value: data.status_value || "scheduled",
      notes: nullable(data.notes),
      adverse_effects: nullable(data.adverse_effects),
    };
  }

  function bindChemoEditSubmit() {
    const form = $("#chemoForm");
    if (!form || form.dataset.chemoEditSubmitBound) return;
    form.dataset.chemoEditSubmitBound = "1";
    form.addEventListener("submit", async event => {
      const editId = form.dataset.editId;
      if (!editId) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      try {
        await api(`/api/v2/patients/${patientId()}/chemo/${editId}`, {
          method: "PUT",
          body: JSON.stringify(chemoPayload(form)),
        });
        form.closest("dialog")?.close();
        form.reset();
        resetChemoFormForCreate();
        refreshDay();
        toast("Quimioterapia modificada correctamente.");
      } catch (error) {
        toast(error.message, true);
      }
    }, true);
  }

  async function openChemoEdit(id) {
    try {
      const item = await api(`/api/v2/patients/${patientId()}/chemo/${id}`);
      const form = $("#chemoForm");
      const dialog = $("#chemoDialog");
      if (!form || !dialog) return;

      form.reset();
      form.dataset.editId = String(id);
      form.elements.scheduled_at.value = item.scheduled_at?.slice(0, 16) || "";
      form.elements.name.value = item.name || "";
      form.elements.protocol.value = item.protocol || "";
      form.elements.cycle.value = item.cycle || "";
      form.elements.purpose.value = item.purpose || "";
      form.elements.status_value.value = item.status_value || "scheduled";
      form.elements.notes.value = item.notes || "";
      form.elements.adverse_effects.value = item.adverse_effects || "";

      const heading = form.querySelector(".dialog-head h2");
      if (heading) heading.textContent = "Editar quimioterapia";
      const submit = form.querySelector("button.primary");
      if (submit) submit.textContent = "Guardar cambios";

      dialog.showModal();
      resetDialogScroll(dialog);
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function deleteChemo(id) {
    if (!confirm("¿Eliminar este registro de quimioterapia? Esta acción no se puede deshacer.")) return;
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${id}`, { method: "DELETE" });
      refreshDay();
      toast("Quimioterapia eliminada correctamente.");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function actionButtons(id) {
    const wrapper = document.createElement("div");
    wrapper.className = "record-action-buttons chemo-record-actions";

    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "text-btn";
    edit.textContent = "Editar";
    edit.addEventListener("click", () => openChemoEdit(id));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-btn";
    remove.textContent = "Eliminar";
    remove.addEventListener("click", () => deleteChemo(id));

    wrapper.append(edit, remove);
    return wrapper;
  }

  async function enhanceChemoList() {
    const id = patientId();
    const root = $("#chemoList");
    if (!id || !root) return;
    try {
      const [patient, day] = await Promise.all([
        api(`/api/v2/patients/${id}`),
        api(`/api/v2/patients/${id}/day?date=${encodeURIComponent(selectedDate())}`),
      ]);
      if (!["owner", "editor"].includes(patient.role)) return;
      const rows = $$(".mini-row", root);
      const items = day.chemo || [];
      rows.forEach((row, index) => {
        const item = items[index];
        if (!item || row.querySelector(".chemo-record-actions")) return;
        row.appendChild(actionButtons(item.id));
      });
    } catch (_) {}
  }

  function scheduleEnhance() {
    clearTimeout(enhanceTimer);
    enhanceTimer = setTimeout(enhanceChemoList, 100);
  }

  function refreshDay() {
    const date = $("#selectedDate");
    if (date) date.dispatchEvent(new Event("change", { bubbles: true }));
    setTimeout(scheduleEnhance, 250);
  }

  function observeChemoList() {
    const root = $("#chemoList");
    if (!root) return;
    new MutationObserver(scheduleEnhance).observe(root, { childList: true });
  }

  bindDialogCloseAndScrollFixes();
  bindChemoEditSubmit();
  observeChemoList();
  scheduleEnhance();
})();
