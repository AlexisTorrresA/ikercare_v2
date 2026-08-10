(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  let chemoRefreshTimer = null;

  function toast(message, isError = false) {
    const el = $("#toast");
    if (!el) return;
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

  function selectedDate() {
    return $("#selectedDate")?.value || "";
  }

  function resetDialogScroll(dialog) {
    if (!dialog) return;
    dialog.scrollTop = 0;
    const form = dialog.querySelector(".dialog-form");
    if (form) form.scrollTop = 0;
    requestAnimationFrame(() => {
      dialog.scrollTop = 0;
      if (form) form.scrollTop = 0;
    });
  }

  function fixDialogCloseButtonsAndScroll() {
    $$("dialog").forEach(dialog => {
      const closeButton = dialog.querySelector(".dialog-head .icon-btn");
      if (closeButton) {
        closeButton.type = "button";
        closeButton.removeAttribute("value");
        closeButton.addEventListener("click", event => {
          event.preventDefault();
          event.stopPropagation();
          dialog.close();
          resetDialogScroll(dialog);
        });
      }

      const observer = new MutationObserver(() => {
        if (dialog.hasAttribute("open")) resetDialogScroll(dialog);
      });
      observer.observe(dialog, { attributes: true, attributeFilter: ["open"] });
      dialog.addEventListener("close", () => resetDialogScroll(dialog));
    });

    $$('[data-open]').forEach(button => {
      button.addEventListener("click", () => {
        const dialog = document.getElementById(button.dataset.open);
        if (dialog) resetDialogScroll(dialog);
      }, true);
    });
  }

  function resetChemoFormMode() {
    const form = $("#chemoForm");
    if (!form) return;
    delete form.dataset.editId;
    const title = form.querySelector(".dialog-head h2");
    if (title) title.textContent = "Quimioterapia";
    const submit = form.querySelector("button.primary");
    if (submit) submit.textContent = "Guardar";
  }

  function fillChemoForm(item) {
    const form = $("#chemoForm");
    if (!form) return;
    form.reset();
    form.dataset.editId = String(item.id);
    form.elements.scheduled_at.value = (item.scheduled_at || "").slice(0, 16);
    form.elements.name.value = item.name || "";
    form.elements.protocol.value = item.protocol || "";
    form.elements.cycle.value = item.cycle || "";
    form.elements.purpose.value = item.purpose || "";
    form.elements.status_value.value = item.status_value || "scheduled";
    form.elements.notes.value = item.notes || "";
    form.elements.adverse_effects.value = item.adverse_effects || "";
    const title = form.querySelector(".dialog-head h2");
    if (title) title.textContent = "Modificar quimioterapia";
    const submit = form.querySelector("button.primary");
    if (submit) submit.textContent = "Guardar cambios";
  }

  async function openChemoEdit(itemId) {
    try {
      const item = await api(`/api/v2/patients/${patientId()}/chemo/${itemId}`);
      fillChemoForm(item);
      const dialog = $("#chemoDialog");
      resetDialogScroll(dialog);
      dialog?.showModal();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function deleteChemo(itemId, name) {
    if (!confirm(`¿Eliminar el registro de quimioterapia${name ? ` "${name}"` : ""}? Esta acción no se puede deshacer.`)) return;
    try {
      await api(`/api/v2/patients/${patientId()}/chemo/${itemId}`, { method: "DELETE" });
      refreshCurrentDay();
      toast("Registro de quimioterapia eliminado correctamente.");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function refreshCurrentDay() {
    const dateInput = $("#selectedDate");
    if (dateInput) dateInput.dispatchEvent(new Event("change", { bubbles: true }));
    window.setTimeout(scheduleChemoActions, 250);
  }

  async function enhanceChemoActions() {
    const id = patientId();
    const root = $("#chemoList");
    if (!id || !root) return;

    try {
      const data = await api(`/api/v2/patients/${id}/day?date=${encodeURIComponent(selectedDate())}`);
      const rows = $$(".mini-row", root);
      (data.chemo || []).forEach((item, index) => {
        const row = rows[index];
        if (!row || row.querySelector(".chemo-record-actions")) return;
        const actions = document.createElement("div");
        actions.className = "chemo-record-actions";

        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "text-btn";
        edit.textContent = "Editar";
        edit.addEventListener("click", () => openChemoEdit(item.id));

        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "text-btn";
        remove.textContent = "Eliminar";
        remove.addEventListener("click", () => deleteChemo(item.id, item.name));

        actions.append(edit, remove);
        row.appendChild(actions);
      });
    } catch (_) {}
  }

  function scheduleChemoActions() {
    clearTimeout(chemoRefreshTimer);
    chemoRefreshTimer = setTimeout(enhanceChemoActions, 100);
  }

  function bindChemoForm() {
    const form = $("#chemoForm");
    if (!form) return;

    $$('[data-open="chemoDialog"]').forEach(button => {
      button.addEventListener("click", () => {
        form.reset();
        resetChemoFormMode();
      }, true);
    });

    form.addEventListener("submit", async event => {
      const editId = form.dataset.editId;
      if (!editId) return;
      event.preventDefault();
      event.stopImmediatePropagation();

      const data = Object.fromEntries(new FormData(form).entries());
      const payload = {
        scheduled_at: data.scheduled_at,
        name: data.name,
        protocol: data.protocol || null,
        cycle: data.cycle || null,
        purpose: data.purpose || null,
        status_value: data.status_value,
        notes: data.notes || null,
        adverse_effects: data.adverse_effects || null,
      };

      try {
        await api(`/api/v2/patients/${patientId()}/chemo/${editId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        form.closest("dialog")?.close();
        form.reset();
        resetChemoFormMode();
        refreshCurrentDay();
        toast("Registro de quimioterapia modificado correctamente.");
      } catch (error) {
        toast(error.message, true);
      }
    }, true);
  }

  function observeChemoList() {
    const root = $("#chemoList");
    if (!root) return;
    new MutationObserver(scheduleChemoActions).observe(root, { childList: true });
  }

  fixDialogCloseButtonsAndScroll();
  bindChemoForm();
  observeChemoList();
  scheduleChemoActions();
})();
