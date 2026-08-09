(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (selector, root = document) => root.querySelector(selector);

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

  function currentPatientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function exposePatientActions() {
    const accountScreen = $('[data-screen="account"]');
    const title = accountScreen?.querySelector(".screen-title");
    const form = $("#patientForm");
    if (!accountScreen || !title || !form) return;

    const heading = form.closest(".card")?.querySelector("h2");
    if (heading) heading.textContent = "Editar paciente";
    const saveButton = form.querySelector('button[type="submit"]');
    if (saveButton) saveButton.textContent = "Guardar cambios del paciente";

    let newButton = $("#newPatientBtn");
    if (newButton) {
      newButton.textContent = "+ Agregar paciente";
    }

    if (!$("#editPatientBtn")) {
      const editButton = document.createElement("button");
      editButton.id = "editPatientBtn";
      editButton.type = "button";
      editButton.className = "secondary";
      editButton.textContent = "Editar paciente";
      editButton.addEventListener("click", () => {
        form.scrollIntoView({ behavior: "smooth", block: "start" });
        form.elements.name?.focus();
      });
      title.appendChild(editButton);
    }

    if (!$("#deletePatientBtn")) {
      const deleteButton = document.createElement("button");
      deleteButton.id = "deletePatientBtn";
      deleteButton.type = "button";
      deleteButton.className = "danger";
      deleteButton.textContent = "Eliminar paciente";
      deleteButton.addEventListener("click", async () => {
        const patientId = currentPatientId();
        if (!patientId) {
          alert("Selecciona un paciente primero.");
          return;
        }
        try {
          const patient = await api(`/api/v2/patients/${patientId}`);
          if (patient.role !== "owner") {
            alert("Solo el propietario del paciente puede eliminarlo.");
            return;
          }
          const confirmation = prompt(`Para eliminar a ${patient.name}, escribe exactamente su nombre:`);
          if (confirmation === null) return;
          if (confirmation.trim().toLowerCase() !== String(patient.name).trim().toLowerCase()) {
            alert("El nombre no coincide. No se eliminó el paciente.");
            return;
          }
          const secondCheck = confirm(`¿Eliminar definitivamente a ${patient.name} y sus registros asociados? Esta acción no se puede deshacer.`);
          if (!secondCheck) return;
          await api(`/api/v2/patients/${patientId}`, {
            method: "DELETE",
            body: JSON.stringify({ confirm_name: confirmation.trim() }),
          });
          localStorage.removeItem("ikercare_patient_id");
          location.reload();
        } catch (error) {
          alert(error.message);
        }
      });
      title.appendChild(deleteButton);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", exposePatientActions, { once: true });
  } else {
    exposePatientActions();
  }
})();
