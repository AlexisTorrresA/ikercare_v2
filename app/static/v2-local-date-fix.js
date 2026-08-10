(() => {
  "use strict";

  function localDateValue(date = new Date()) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  function utcDateValue(date = new Date()) {
    return date.toISOString().slice(0, 10);
  }

  function correctIfNeeded() {
    const input = document.getElementById("selectedDate");
    if (!input) return;

    const localToday = localDateValue();
    const utcToday = utcDateValue();

    if (localToday !== utcToday && (!input.value || input.value === utcToday)) {
      input.value = localToday;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", correctIfNeeded, { once: true });
  } else {
    correctIfNeeded();
  }

  document.addEventListener("click", event => {
    if (event.target.closest("[data-app-nav], .bottom-nav button")) {
      window.setTimeout(correctIfNeeded, 0);
    }
  });
})();
