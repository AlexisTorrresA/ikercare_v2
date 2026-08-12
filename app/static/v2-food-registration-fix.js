(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);

  function patientId() {
    return Number($("#patientSelect")?.value || 0) || null;
  }

  function field(form, name) {
    return form.elements.namedItem(name);
  }

  function value(form, name) {
    const control = field(form, name);
    return control && "value" in control ? String(control.value || "").trim() : "";
  }

  function checked(form, name) {
    const control = field(form, name);
    return Boolean(control && "checked" in control && control.checked);
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

  function numberOrNull(raw) {
    const text = String(raw ?? "").trim();
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

    // El control se llama "item". En HTMLFormControlsCollection, .item es también
    // un método nativo, por eso debe obtenerse explícitamente con namedItem().
    const foodItem = value(form, "item");
    const occurredAt = value(form, "occurred_at");
    if (!foodItem || !occurredAt) {
      toast("Completa la fecha, hora y alimento o bebida.", true);
      return;
    }

    const editId = Number(form.dataset.editId || 0) || null;
    const payload = {
      occurred_at: occurredAt,
      meal_type: value(form, "meal_type") || null,
      item: foodItem,
      amount: numberOrNull(value(form, "amount")),
      unit: value(form, "unit") || null,
      portion: value(form, "portion") || null,
      tolerated: checked(form, "tolerated"),
      vomiting: checked(form, "vomiting"),
      notes: value(form, "notes") || null,
    };

    const submit = form.querySelector('button.primary:not([value="cancel"])');
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

    // Reemplaza solo el formulario de comida para retirar listeners duplicados
    // que quedaron superpuestos por las mejoras anteriores.
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
        const occurredAt = field(form, "occurred_at");
        if (occurredAt && "value" in occurredAt && !occurredAt.value) {
          const now = new Date();
          const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
          occurredAt.value = local.toISOString().slice(0, 16);
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
