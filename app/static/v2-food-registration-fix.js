(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);

  function patientId() {
    return Number($("#patientSelect")?.value || 0) || null;
  }

  function toast(message, error = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", error);
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
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo guardar el registro de comida.");
    }
    return payload;
  }

  function numberOrNull(value) {
    const text = String(value ?? "").trim();
    if (!text) return null;
    const number = Number(text);
    return Number.isFinite(number) ? number : null;
  }

  async function saveFood(event) {
    if (event.submitter?.value === "cancel") return;
    event.preventDefault();
    event.stopImmediatePropagation();

    const form = event.currentTarget;
    const pid = patientId();
    if (!pid) {
      toast("Selecciona un paciente antes de registrar comida.", true);
      return;
    }

    const item = String(form.elements.item?.value || "").trim();
    const occurredAt = String(form.elements.occurred_at?.value || "").trim();
    if (!item || !occurredAt) {
      toast("Completa la fecha, hora y alimento o bebida.", true);
      return;
    }

    const editId = Number(form.dataset.editId || 0) || null;
    const payload = {
      occurred_at: occurredAt,
      meal_type: String(form.elements.meal_type?.value || "").trim() || null,
      item,
      amount: numberOrNull(form.elements.amount?.value),
      unit: String(form.elements.unit?.value || "").trim() || null,
      portion: String(form.elements.portion?.value || "").trim() || null,
      tolerated: Boolean(form.elements.tolerated?.checked),
      vomiting: Boolean(form.elements.vomiting?.checked),
      notes: String(form.elements.notes?.value || "").trim() || null,
    };

    const submit = form.querySelector('button[type="submit"], button.primary:not([value="cancel"])');
    if (submit) submit.disabled = true;

    try {
      await api(
        `/api/v2/patients/${pid}/food-enhanced${editId ? `/${editId}` : ""}`,
        { method: editId ? "PUT" : "POST", body: JSON.stringify(payload) },
      );

      form.closest("dialog")?.close();
      form.reset();
      delete form.dataset.editId;

      const selectedDate = $("#selectedDate");
      selectedDate?.dispatchEvent(new Event("change", { bubbles: true }));
      toast(editId ? "Registro de comida actualizado." : "Registro de comida agregado.");
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  function bindFoodForm() {
    const current = $("#foodForm");
    if (!current || current.dataset.foodRegistrationFix === "1") return;

    // Reemplazamos únicamente el formulario de comida para retirar listeners
    // antiguos que quedaron superpuestos tras las mejoras recientes.
    const fresh = current.cloneNode(true);
    fresh.dataset.foodRegistrationFix = "1";
    current.replaceWith(fresh);
    fresh.addEventListener("submit", saveFood, true);
  }

  function init() {
    bindFoodForm();

    document.addEventListener("click", event => {
      if (!event.target.closest('[data-open="foodDialog"]')) return;
      setTimeout(() => {
        bindFoodForm();
        const form = $("#foodForm");
        if (!form || form.dataset.editId) return;
        if (!form.elements.occurred_at?.value) {
          const now = new Date();
          const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
          form.elements.occurred_at.value = local.toISOString().slice(0, 16);
        }
      }, 0);
    }, true);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
