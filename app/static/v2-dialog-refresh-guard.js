(() => {
  "use strict";

  let medicationRefreshCooldownUntil = 0;
  let cooldownTimer = null;

  function isMedicationDialog(dialog) {
    return dialog instanceof HTMLDialogElement && [
      "medicationManagerDialog",
      "medicationEditDialog",
      "permanentDeleteMedicationDialog",
    ].includes(dialog.id);
  }

  function nativeSwipeEnabled() {
    const hasOpenDialog = Boolean(document.querySelector("dialog[open]"));
    const inMedicationCooldown = Date.now() < medicationRefreshCooldownUntil;
    return !hasOpenDialog && !inMedicationCooldown;
  }

  function notifyNative() {
    if (window.IkerCareNative?.setSwipeRefreshEnabled) {
      window.IkerCareNative.setSwipeRefreshEnabled(nativeSwipeEnabled());
    }
  }

  function startMedicationCooldown() {
    medicationRefreshCooldownUntil = Date.now() + 1600;
    clearTimeout(cooldownTimer);
    notifyNative();
    cooldownTimer = setTimeout(() => {
      medicationRefreshCooldownUntil = 0;
      notifyNative();
    }, 1650);
  }

  const dialogObserver = new MutationObserver(mutations => {
    for (const mutation of mutations) {
      if (mutation.type !== "attributes" || mutation.attributeName !== "open") continue;
      const dialog = mutation.target;
      if (isMedicationDialog(dialog) && !dialog.open) {
        startMedicationCooldown();
        continue;
      }
      notifyNative();
    }
  });

  function bindDialog(dialog) {
    if (!(dialog instanceof HTMLDialogElement) || dialog.dataset.refreshGuardBound === "true") return;
    dialog.dataset.refreshGuardBound = "true";
    dialogObserver.observe(dialog, { attributes: true, attributeFilter: ["open"] });
    dialog.addEventListener("close", () => {
      if (isMedicationDialog(dialog)) startMedicationCooldown();
      else notifyNative();
    });
    dialog.addEventListener("cancel", () => {
      if (isMedicationDialog(dialog)) startMedicationCooldown();
      else notifyNative();
    });
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
