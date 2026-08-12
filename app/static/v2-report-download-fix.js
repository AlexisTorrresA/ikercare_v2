(() => {
  "use strict";

  const app = document.getElementById("app");
  if (!app) return;

  const $ = (selector, root = document) => root.querySelector(selector);

  function toast(message, isError = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  function patientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function reportPayload() {
    return {
      scope: $("#reportScope")?.value || "all",
      hospitalization_id: $("#reportHospitalization")?.value ? Number($("#reportHospitalization").value) : null,
      start_date: $("#reportStart")?.value || null,
      end_date: $("#reportEnd")?.value || null,
      hospital: $("#reportHospital")?.value?.trim() || null,
      medication: $("#reportMedication")?.value?.trim() || null,
      use_ai: Boolean($("#reportUseAi")?.checked),
    };
  }

  function reportUrl() {
    const id = patientId();
    if (!id) return null;
    const payload = reportPayload();
    if (payload.scope === "hospitalization" && payload.hospitalization_id) {
      const query = new URLSearchParams({ use_ai: String(payload.use_ai) });
      return `/api/v2/patients/${id}/hospitalizations/${payload.hospitalization_id}/hospital-report.pdf?${query.toString()}`;
    }
    const query = new URLSearchParams();
    Object.entries(payload).forEach(([key, value]) => {
      if (value !== null && value !== "") query.set(key, String(value));
    });
    return `/api/v2/patients/${id}/reports/pdf?${query.toString()}`;
  }

  async function friendlyError(response) {
    try {
      const contentType = response.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        const payload = await response.json();
        if (typeof payload?.detail === "string") return payload.detail;
      }
      const text = await response.text();
      if (text && text.length < 240) return text;
    } catch (_) {}
    return `No se pudo generar el PDF (error ${response.status}).`;
  }

  async function downloadReport(button) {
    const url = reportUrl();
    if (!url) {
      toast("Selecciona un paciente primero.", true);
      return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Preparando PDF…";

    try {
      // Verifica primero que el servidor realmente pueda generar el PDF.
      // Así evitamos que Android descargue una página de error como si fuera un archivo.
      const response = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/pdf" },
      });
      if (!response.ok) throw new Error(await friendlyError(response));

      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/pdf")) {
        throw new Error("El servidor no devolvió un PDF válido.");
      }

      const filename = `IkerCare-informe-${new Date().toLocaleDateString("sv-SE")}.pdf`;

      if (window.IkerCareNative?.downloadAuthenticatedFile) {
        window.IkerCareNative.downloadAuthenticatedFile(
          new URL(url, window.location.origin).toString(),
          filename,
          "application/pdf",
        );
        toast("Descarga del PDF iniciada.");
        return;
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      link.style.display = "none";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 3000);
      toast("PDF descargado correctamente.");
    } catch (error) {
      toast(error?.message || "No se pudo descargar el PDF.", true);
    } finally {
      button.disabled = false;
      button.textContent = originalText || "Descargar PDF";
    }
  }

  document.addEventListener("click", event => {
    const button = event.target.closest("#downloadReportBtn");
    if (!button || button.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    downloadReport(button);
  }, true);
})();
