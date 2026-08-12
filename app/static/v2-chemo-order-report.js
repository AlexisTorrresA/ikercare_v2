(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  let sortTimer = null;

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
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3500);
  }

  function chemoDate(card) {
    const text = $(".chemo-date-full", card)?.textContent?.trim();
    if (!text) return 0;
    const match = text.match(/(\d{2})\/(\d{2})\/(\d{4}).*?(\d{2}):(\d{2})/);
    if (!match) return 0;
    const [, day, month, year, hour, minute] = match;
    return new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute)).getTime();
  }

  function sortLatestFirst() {
    const root = $("#chemoList");
    if (!root) return;
    const current = $$(".stable-care-card.chemo", root);
    if (current.length < 2) return;

    const sorted = [...current].sort((a, b) => chemoDate(b) - chemoDate(a));
    const alreadySorted = sorted.every((card, index) => card === current[index]);
    if (alreadySorted) return;

    const fragment = document.createDocumentFragment();
    sorted.forEach(card => fragment.appendChild(card));
    root.appendChild(fragment);
  }

  function scheduleSort(delay = 50) {
    clearTimeout(sortTimer);
    sortTimer = setTimeout(sortLatestFirst, delay);
  }

  function ensurePdfButton() {
    if ($("#chemoPdfBtn")) return;
    const screen = $('[data-screen="care"]');
    const chemoRoot = $("#chemoList");
    const article = chemoRoot?.closest("article.card");
    const head = article?.querySelector(".card-head");
    if (!screen || !head) return;

    const button = document.createElement("button");
    button.id = "chemoPdfBtn";
    button.type = "button";
    button.className = "small secondary";
    button.textContent = "PDF quimios";
    button.addEventListener("click", downloadChemoPdf);
    head.appendChild(button);
  }

  async function downloadChemoPdf(event) {
    const button = event.currentTarget;
    const id = patientId();
    if (!id) return toast("Selecciona un paciente primero.", true);

    const url = `/api/v2/patients/${id}/chemo-report.pdf`;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = "Generando PDF…";
    try {
      const response = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/pdf" },
      });
      if (!response.ok) throw new Error("No se pudo generar el PDF de quimioterapia.");
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/pdf")) throw new Error("El servidor no devolvió un PDF válido.");

      const filename = `IkerCare-quimioterapia-${new Date().toLocaleDateString("sv-SE")}.pdf`;
      if (window.IkerCareNative?.downloadAuthenticatedFile) {
        window.IkerCareNative.downloadAuthenticatedFile(new URL(url, window.location.origin).toString(), filename, "application/pdf");
        toast("Descarga del PDF iniciada.");
        return;
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 3000);
      toast("PDF de quimioterapia descargado.");
    } catch (error) {
      toast(error?.message || "No se pudo descargar el PDF.", true);
    } finally {
      button.disabled = false;
      button.textContent = original || "PDF quimios";
    }
  }

  function init() {
    ensurePdfButton();
    scheduleSort(0);
    const root = $("#chemoList");
    if (root) new MutationObserver(() => scheduleSort()).observe(root, { childList: true });
    $("#patientSelect")?.addEventListener("change", () => scheduleSort(250));
    document.addEventListener("click", event => {
      if (event.target.closest('[data-app-nav="chemo"], [data-nav="care"]')) {
        setTimeout(() => {
          ensurePdfButton();
          scheduleSort(0);
        }, 180);
      }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
