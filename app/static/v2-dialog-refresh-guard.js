(() => {
  "use strict";

  function notifyNative() {
    const hasOpenDialog = Boolean(document.querySelector("dialog[open]"));
    if (window.IkerCareNative?.setSwipeRefreshEnabled) {
      window.IkerCareNative.setSwipeRefreshEnabled(!hasOpenDialog);
    }
  }

  const observer = new MutationObserver(mutations => {
    if (mutations.some(mutation => mutation.type === "attributes" && mutation.attributeName === "open")) {
      notifyNative();
    }
  });

  document.querySelectorAll("dialog").forEach(dialog => {
    observer.observe(dialog, { attributes: true, attributeFilter: ["open"] });
    dialog.addEventListener("close", notifyNative);
    dialog.addEventListener("cancel", notifyNative);
  });

  document.addEventListener("click", event => {
    if (event.target.closest("[data-open]")) setTimeout(notifyNative, 0);
  });

  notifyNative();
})();
