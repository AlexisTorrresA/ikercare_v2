(() => {
  "use strict";
  const app = document.getElementById("app");
  if (!app) return;
  const $ = (s, r = document) => r.querySelector(s);
  const csrf = app.dataset.csrf || "";
  const pid = () => Number($("#patientSelect")?.value || 0) || null;

  async function api(url) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  function toast(message, error = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", error);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3200);
  }

  function setHeading(form, text) {
    const heading = form?.querySelector(".dialog-head h2");
    if (heading) heading.textContent = text;
    const submit = form?.querySelector("button.primary");
    if (submit) submit.textContent = "Guardar cambios";
  }

  async function editFood(id) {
    const form = $("#foodForm");
    if (!form || !pid()) return;
    try {
      const [item, metadata] = await Promise.all([
        api(`/api/v2/patients/${pid()}/food/${id}`),
        api(`/api/v2/patients/${pid()}/food-metadata`).catch(() => ({})),
      ]);
      form.reset();
      form.dataset.editId = String(id);
      form.elements.occurred_at.value = (item.occurred_at || "").slice(0, 16);
      form.elements.meal_type.value = item.meal_type || "Otro";
      form.elements.item.value = item.item || "";
      form.elements.amount.value = item.amount ?? "";
      form.elements.unit.value = item.unit || "";
      if (form.elements.portion) form.elements.portion.value = metadata[String(id)]?.portion || "";
      form.elements.tolerated.checked = item.tolerated !== false;
      form.elements.vomiting.checked = Boolean(item.vomiting);
      form.elements.notes.value = item.notes || "";
      setHeading(form, "Editar comida");
      $("#foodDialog")?.showModal();
    } catch (error) { toast(error.message, true); }
  }

  async function editElimination(id) {
    const form = $("#eliminationForm");
    if (!form || !pid()) return;
    try {
      const item = await api(`/api/v2/patients/${pid()}/elimination/${id}`);
      form.reset();
      form.dataset.editId = String(id);
      form.elements.occurred_at.value = (item.occurred_at || "").slice(0, 16);
      form.elements.diaper_status.value = item.diaper_status || "wet";
      form.elements.urine_amount.value = item.urine_amount || "";
      form.elements.urine_color.value = item.urine_color || "";
      form.elements.stool_description.value = item.stool_description || "";
      form.elements.notes.value = item.notes || "";
      setHeading(form, "Editar pañal / eliminación");
      $("#eliminationDialog")?.showModal();
    } catch (error) { toast(error.message, true); }
  }

  document.addEventListener("click", event => {
    const food = event.target.closest(".persistent-care-card .ext-edit-food");
    if (food) {
      event.preventDefault();
      event.stopPropagation();
      editFood(Number(food.dataset.id));
      return;
    }
    const elimination = event.target.closest(".persistent-care-card .record-edit-btn[data-kind='elimination']");
    if (elimination) {
      event.preventDefault();
      event.stopPropagation();
      editElimination(Number(elimination.dataset.id));
    }
  }, true);
})();
