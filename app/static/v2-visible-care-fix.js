(() => {
  "use strict";
  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  let busy = false;
  let refreshTimer = null;

  function pid() { return Number($("#patientSelect")?.value || 0) || null; }
  function selectedDate() { return $("#selectedDate")?.value || new Date().toLocaleDateString("sv-SE"); }
  function esc(v) { return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
  function when(v) { const d = new Date(v); return Number.isNaN(d.getTime()) ? String(v || "") : d.toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" }); }
  function toast(message, error = false) { const el = $("#toast"); if (!el) return; el.textContent = message; el.classList.toggle("error", error); el.classList.remove("hidden"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.add("hidden"), 3300); }
  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const r = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const ct = r.headers.get("content-type") || "";
    const payload = ct.includes("application/json") ? await r.json() : await r.text();
    if (!r.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }

  function addLocalStyle() {
    if ($("#visibleCareFixStyle")) return;
    const style = document.createElement("style");
    style.id = "visibleCareFixStyle";
    style.textContent = `
      #foodList,#eliminationList{display:grid;gap:10px}
      .visible-care-card{position:relative;overflow:hidden;border:1px solid #dce4ef;border-radius:18px;background:#fff;box-shadow:0 4px 14px rgba(31,55,91,.07);padding:14px 14px 14px 18px}
      .visible-care-card:before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px}
      .visible-care-card.food:before{background:#d78a22}.visible-care-card.elimination:before{background:#4487aa}
      .visible-care-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.visible-care-top strong{font-size:1.02rem;color:#182230}.visible-care-top time{font-weight:700;color:#315b96}
      .visible-care-meta{display:flex;flex-wrap:wrap;gap:6px;margin:9px 0}.visible-care-meta span{padding:4px 8px;border-radius:999px;background:#eef3fb;color:#385270;font-size:.85rem}
      .visible-care-card p{margin:8px 0 0}.visible-care-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
      .visible-chemo-evolution{margin-top:14px;padding-top:12px;border-top:1px solid #e4e9f0}.visible-chemo-head{display:flex;justify-content:space-between;gap:8px;align-items:center}.visible-chemo-events{display:grid;gap:8px;margin-top:8px}
      .visible-chemo-event{padding:9px 10px;border-radius:12px;background:#f7f2ff;border-left:4px solid #7c4dcc}.visible-chemo-event strong{display:block;color:#412b70}.visible-chemo-event span{display:block;margin-top:3px}
      @media(max-width:520px){.visible-care-top{flex-direction:column}.visible-care-top time{white-space:normal}.visible-chemo-head{align-items:flex-start;flex-direction:column}}
    `;
    document.head.appendChild(style);
  }

  async function renderTodayCards() {
    const id = pid();
    if (!id || busy) return;
    busy = true;
    try {
      const [day, meta] = await Promise.all([
        api(`/api/v2/patients/${id}/day?date=${encodeURIComponent(selectedDate())}`),
        api(`/api/v2/patients/${id}/food-metadata`).catch(() => ({})),
      ]);
      renderFood(day.food || [], meta || {});
      renderElimination(day.elimination || []);
      await enhanceChemo();
    } catch (_) {
      // El renderer base ya muestra errores; este parche visual no debe romper otras pantallas.
    } finally {
      busy = false;
    }
  }

  function renderFood(items, meta) {
    const root = $("#foodList"); if (!root) return;
    const order = ["Desayuno","Colación","Almuerzo","Once/Merienda","Cena","Alimentación nocturna","Lactancia/Leche","Líquidos","Otro"];
    const groups = new Map();
    items.forEach(item => { const key = item.meal_type || "Otro"; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(item); });
    if (!items.length) { root.innerHTML = '<p class="empty">Sin registros.</p>'; return; }
    const keys = order.filter(k => groups.has(k)).concat([...groups.keys()].filter(k => !order.includes(k)));
    root.innerHTML = keys.map(key => `<section class="meal-group"><h3 class="meal-group-title">${esc(key)}</h3>${groups.get(key).map(item => {
      const portion = meta[String(item.id)]?.portion;
      return `<article class="visible-care-card food" data-id="${item.id}">
        <div class="visible-care-top"><strong>${esc(item.item)}</strong><time>${esc(when(item.occurred_at))}</time></div>
        <div class="visible-care-meta">
          ${item.amount != null ? `<span>Cantidad: ${esc(item.amount)} ${esc(item.unit || "")}</span>` : ""}
          ${portion ? `<span>${esc(portion)}</span>` : ""}
          ${item.vomiting ? '<span>Vómito</span>' : item.tolerated === false ? '<span>No toleró</span>' : item.tolerated === true ? '<span>Toleró</span>' : ""}
        </div>
        ${item.notes ? `<p>${esc(item.notes)}</p>` : ""}
        <div class="visible-care-actions"><button type="button" class="text-btn vc-edit-food" data-id="${item.id}">Editar</button><button type="button" class="text-btn danger-text vc-delete-food" data-id="${item.id}">Eliminar</button></div>
      </article>`;
    }).join("")}</section>`).join("");
    $$(".vc-edit-food", root).forEach(b => b.onclick = () => editFood(Number(b.dataset.id), meta));
    $$(".vc-delete-food", root).forEach(b => b.onclick = () => deleteRecord("food", Number(b.dataset.id)));
  }

  function renderElimination(items) {
    const root = $("#eliminationList"); if (!root) return;
    const labels = { dry: "Seco", wet: "Pipí", soiled: "Deposición", wet_and_soiled: "Pipí + deposición" };
    root.innerHTML = items.length ? items.map(item => `<article class="visible-care-card elimination" data-id="${item.id}">
      <div class="visible-care-top"><strong>${esc(labels[item.diaper_status] || item.diaper_status || "Registro")}</strong><time>${esc(when(item.occurred_at))}</time></div>
      <div class="visible-care-meta">
        ${item.urine_amount ? `<span>Orina: ${esc(item.urine_amount)}</span>` : ""}
        ${item.urine_color ? `<span>Color: ${esc(item.urine_color)}</span>` : ""}
        ${item.stool_description ? `<span>Deposición: ${esc(item.stool_description)}</span>` : ""}
      </div>
      ${item.notes ? `<p>${esc(item.notes)}</p>` : ""}
      <div class="visible-care-actions"><button type="button" class="text-btn vc-edit-elim" data-id="${item.id}">Editar</button><button type="button" class="text-btn danger-text vc-delete-elim" data-id="${item.id}">Eliminar</button></div>
    </article>`).join("") : '<p class="empty">Sin registros.</p>';
    $$(".vc-edit-elim", root).forEach(b => b.onclick = () => editElimination(Number(b.dataset.id)));
    $$(".vc-delete-elim", root).forEach(b => b.onclick = () => deleteRecord("elimination", Number(b.dataset.id)));
  }

  async function editFood(id, meta) {
    try {
      const item = await api(`/api/v2/patients/${pid()}/food/${id}`), f = $("#foodForm");
      if (!f) return;
      f.reset(); f.dataset.editId = String(id);
      f.elements.occurred_at.value = (item.occurred_at || "").slice(0,16);
      f.elements.meal_type.value = item.meal_type || "Otro"; f.elements.item.value = item.item || "";
      f.elements.amount.value = item.amount ?? ""; f.elements.unit.value = item.unit || "";
      if (f.elements.portion) f.elements.portion.value = meta[String(id)]?.portion || "";
      f.elements.tolerated.checked = item.tolerated !== false; f.elements.vomiting.checked = !!item.vomiting; f.elements.notes.value = item.notes || "";
      $("#foodDialog")?.showModal();
    } catch (e) { toast(e.message, true); }
  }

  async function editElimination(id) {
    try {
      const item = await api(`/api/v2/patients/${pid()}/elimination/${id}`), f = $("#eliminationForm");
      if (!f) return;
      f.reset(); f.dataset.editId = String(id);
      f.elements.occurred_at.value = (item.occurred_at || "").slice(0,16); f.elements.diaper_status.value = item.diaper_status || "wet";
      f.elements.urine_amount.value = item.urine_amount || ""; f.elements.urine_color.value = item.urine_color || ""; f.elements.stool_description.value = item.stool_description || ""; f.elements.notes.value = item.notes || "";
      $("#eliminationDialog")?.showModal();
    } catch (e) { toast(e.message, true); }
  }

  async function deleteRecord(resource, id) {
    if (!confirm("¿Eliminar este registro?")) return;
    try { await api(`/api/v2/patients/${pid()}/${resource}/${id}`, { method: "DELETE" }); toast("Registro eliminado."); await renderTodayCards(); }
    catch (e) { toast(e.message, true); }
  }

  function ensureChemoDialog() {
    if ($("#visibleChemoEventDialog")) return;
    const d = document.createElement("dialog"); d.id = "visibleChemoEventDialog";
    d.innerHTML = `<form id="visibleChemoEventForm" class="dialog-form"><div class="dialog-head"><h2>Evolución posterior a quimioterapia</h2><button type="button" class="icon-btn" data-close-visible-chemo>×</button></div><input type="hidden" name="chemo_id"><label>Fecha y hora<input name="occurred_at" type="datetime-local" required></label><label>Tipo de evento<select name="event_type">${["Náuseas","Vómitos","Fiebre","Dolor","Somnolencia","Irritabilidad","Falta de apetito","Diarrea","Estreñimiento","Convulsión","Cambios de presión","Cambios de saturación","Otro"].map(x => `<option>${x}</option>`).join("")}</select></label><label>Descripción / observación<textarea name="description"></textarea></label><button type="submit" class="primary">Guardar evento</button></form>`;
    document.body.appendChild(d);
    d.querySelector("[data-close-visible-chemo]").onclick = () => d.close();
    d.querySelector("form").onsubmit = async e => {
      e.preventDefault(); const f = e.currentTarget;
      try {
        await api(`/api/v2/patients/${pid()}/chemo/${f.elements.chemo_id.value}/events`, { method: "POST", body: JSON.stringify({ occurred_at: f.elements.occurred_at.value, event_type: f.elements.event_type.value, description: f.elements.description.value.trim() || null }) });
        d.close(); toast("Evolución de quimioterapia registrada."); await enhanceChemo(true);
      } catch (err) { toast(err.message, true); }
    };
  }

  function localDateTimeValue() { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0,16); }

  async function enhanceChemo(force = false) {
    ensureChemoDialog();
    const cards = $$("#chemoList .stable-care-card.chemo");
    for (const card of cards) {
      const chemoId = Number(card.dataset.id); if (!chemoId) continue;
      const existing = card.querySelector(".visible-chemo-evolution"); if (existing && !force) continue; if (existing) existing.remove();
      let events = [];
      try { events = await api(`/api/v2/patients/${pid()}/chemo/${chemoId}/events`); } catch (_) {}
      const box = document.createElement("div"); box.className = "visible-chemo-evolution";
      box.innerHTML = `<div class="visible-chemo-head"><strong>Evolución posterior</strong><button type="button" class="small secondary vc-add-chemo-event">+ Registrar evento</button></div><div class="visible-chemo-events">${events.length ? events.map(ev => `<div class="visible-chemo-event"><strong>${esc(ev.event_type)} · ${esc(when(ev.occurred_at))}</strong>${ev.description ? `<span>${esc(ev.description)}</span>` : ""}</div>`).join("") : '<span class="muted">Sin eventos posteriores registrados.</span>'}</div>`;
      box.querySelector(".vc-add-chemo-event").onclick = () => { const f = $("#visibleChemoEventForm"); f.reset(); f.elements.chemo_id.value = String(chemoId); f.elements.occurred_at.value = localDateTimeValue(); $("#visibleChemoEventDialog").showModal(); };
      card.querySelector(".care-record-body")?.appendChild(box);
    }
  }

  function scheduleRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => renderTodayCards(), 180); }
  function observe() {
    ["#foodList", "#eliminationList"].forEach(sel => { const root = $(sel); if (root) new MutationObserver(mutations => { if (busy) return; if (mutations.some(m => [...m.addedNodes].some(n => n.nodeType === 1 && !n.classList?.contains("visible-care-card") && !n.classList?.contains("meal-group")))) scheduleRefresh(); }).observe(root, { childList: true }); });
    const chemo = $("#chemoList"); if (chemo) new MutationObserver(() => setTimeout(() => enhanceChemo(), 120)).observe(chemo, { childList: true });
  }

  function init() {
    addLocalStyle(); ensureChemoDialog(); observe(); setTimeout(renderTodayCards, 650);
    $("#selectedDate")?.addEventListener("change", () => setTimeout(renderTodayCards, 260));
    $("#patientSelect")?.addEventListener("change", () => setTimeout(renderTodayCards, 600));
    document.addEventListener("click", e => { if (e.target.closest('[data-app-nav="today"],[data-app-nav="chemo"],[data-app-nav="care"]')) setTimeout(renderTodayCards, 320); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) setTimeout(renderTodayCards, 250); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
