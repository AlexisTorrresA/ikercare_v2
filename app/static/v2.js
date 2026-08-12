(() => {
  "use strict";

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.defer = true;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  loadScript("/static/v2-core.js?v=2.3.0")
    .then(() => loadScript("/static/v2-nav.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-visual.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-bugfixes.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-patient-actions.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-record-actions.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-local-date-fix.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-dialog-chemo-fixes.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-care-controls.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-care-range-stable.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-history-doc-reports.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-clinical-history.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-clinical-preserve.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-report-download-fix.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-visible-care-fixes.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-visible-care-actions.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-medication-extras.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-sos-today.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-chemo-event-actions.js?v=2.3.6"))
    .then(() => loadScript("/static/v2-chemo-order-report.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-dialog-refresh-guard.js?v=2.3.0"))
    .then(() => loadScript("/static/v2-food-registration-fix.js?v=2.3.4"))
    .then(() => loadScript("/static/v2-medication-manager-stable.js?v=2.3.9"))
    .catch(error => console.error("No se pudo cargar IkerCare 2", error));
})();
