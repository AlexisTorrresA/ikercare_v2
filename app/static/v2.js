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

  loadScript("/static/v2-core.js?v=2.0.1")
    .then(() => loadScript("/static/v2-nav.js?v=2.0.1"))
    .catch(error => console.error("No se pudo cargar IkerCare 2", error));
})();
