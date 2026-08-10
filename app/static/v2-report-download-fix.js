(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);

  function toast(message, isError = false) {
    const el = $("#toast");
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3600);
  }

  function patientId() {
    const value = $("#patientSelect")?.value;
    return value ? Number(value) : null;
  }

  function payload() {
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

  function localDate() {
    const now = new Date();
    const shifted = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return shifted.toISOString().slice(0, 10);
  }

  async function readError(response) {
    const contentType = response.headers.get("content-type") || "";
    try {
      if (contentType.includes("application/json")) {
        const body = await response.json();
        if (typeof body?.detail === "string") return body.detail;
        if (Array.isArray(body?.detail) && body.detail.length) return body.detail[0]?.msg || "No se pudo generar el PDF.";
      }
      const text = await response.text();
      if (text && text.length < 300) return text;
    } catch (_) {}
    return `No se pudo generar el PDF (${response.status}).`;
  }

  function downloadInBrowser(blob, fileName) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  function saveWithAndroid(blob, fileName) {
    return new Promise((resolve, reject) => {
      if (!window.IkerCareDownloads?.savePdf) {
        reject(new Error("native_bridge_unavailable"));
        return;
      }
      const reader = new FileReader();
      reader.onerror = () => reject(new Error("No se pudo preparar el PDF para guardarlo."));
      reader.onload = () => {
        try {
          const dataUrl = String(reader.result || "");
          const comma = dataUrl.indexOf(",");
          if (comma < 0) throw new Error("PDF inválido");
          window.IkerCareDownloads.savePdf(fileName, dataUrl.slice(comma + 1));
          resolve();
        } catch (error) {
          reject(error);
        }
      };
      reader.readAsDataURL(blob);
    });
  }

  async function downloadReport(button) {
    const id = patientId();
    if (!id) {
      toast("Selecciona un paciente antes de descargar el informe.", true);
      return;
    }

    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Preparando PDF…";

    try {
      const query = new URLSearchParams();
      Object.entries(payload()).forEach(([key, value]) => {
        if (value !== null && value !== "") query.set(key, String(value));
      });
      const response = await fetch(`/api/v2/patients/${id}/reports/pdf?${query}`, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/pdf" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(await readError(response));

      const blob = await response.blob();
      if (!blob.size) throw new Error("El servidor generó un PDF vacío.");
      const fileName = `IkerCare-informe-${localDate()}.pdf`;

      if (window.IkerCareDownloads?.savePdf) {
        await saveWithAndroid(blob, fileName);
        toast("PDF generado. Se está guardando en Descargas/IkerCare.");
      } else {
        downloadInBrowser(blob, fileName);
        toast("PDF generado correctamente.");
      }
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
    event.stopImmediatePropagation();
    downloadReport(button);
  }, true);
})();
