(() => {
  "use strict";

  function notifyNative() {
    const hasOpenDialog = Boolean(document.querySelector("dialog[open]"));
    if (window.IkerCareNative?.setSwipeRefreshEnabled) {
      window.IkerCareNative.setSwipeRefreshEnabled(!hasOpenDialog);
    }
  }

  const dialogObserver = new MutationObserver(mutations => {
    if (mutations.some(mutation => mutation.type === "attributes" && mutation.attributeName === "open")) {
      notifyNative();
    }
  });

  function bindDialog(dialog) {
    if (!(dialog instanceof HTMLDialogElement) || dialog.dataset.refreshGuardBound === "true") return;
    dialog.dataset.refreshGuardBound = "true";
    dialogObserver.observe(dialog, { attributes: true, attributeFilter: ["open"] });
    dialog.addEventListener("close", notifyNative);
    dialog.addEventListener("cancel", notifyNative);
  }

  function bindDialogs(root = document) {
    if (root instanceof HTMLDialogElement) bindDialog(root);
    root.querySelectorAll?.("dialog").forEach(bindDialog);
  }

  bindDialogs();

  const dynamicDialogObserver = new MutationObserver(mutations => {
    let foundDialog = false;
    mutations.forEach(mutation => {
      mutation.addedNodes.forEach(node => {
        if (!(node instanceof Element)) return;
        if (node.matches("dialog") || node.querySelector("dialog")) {
          bindDialogs(node);
          foundDialog = true;
        }
      });
    });
    if (foundDialog) notifyNative();
  });
  dynamicDialogObserver.observe(document.body, { childList: true, subtree: true });

  document.addEventListener("click", event => {
    if (event.target.closest("[data-open], #manageMedicationsBtn, .edit-managed-med")) {
      setTimeout(() => {
        bindDialogs();
        notifyNative();
      }, 0);
    }
  });

  notifyNative();
})();
