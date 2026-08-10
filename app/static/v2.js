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

  loadScript("/static/v2-core.js?v=2.0.8")
    .then(() => loadScript("/static/v2-nav.js?v=2.0.8"))
    .then(() => loadScript("/static/v2-visual.js?v=2.0.8"))
    .then(() => loadScript("/static/v2-bugfixes.js?v=2.0.8"))
    .then(() => loadScript("/static/v2-patient-actions.js?v=2.0.8"))
    .then(() => loadScript("/static/v2-record-actions.js?v=2.0.8"))
    .then(() => loadScript("/static/v2-local-date-fix.js?v=2.0.8"))
    .then(() => loadScript("/static/v2-dialog-chemo-fixes.js?v=2.0.8"))
    .catch(error => console.error("No se pudo cargar IkerCare 2", error));
})();
