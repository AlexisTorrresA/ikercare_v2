(() => {
  "use strict";
  const app = document.getElementById("app");
  if (!app) return;
  const csrf = app.dataset.csrf || "";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  let docFiles = [];
  let foodMeta = {};
  let renderingCare = false;

  function esc(v) { return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
  function pid() { return Number($("#patientSelect")?.value || 0) || null; }
  function localDateTimeValue(date = new Date()) { const d = new Date(date.getTime() - date.getTimezoneOffset() * 60000); return d.toISOString().slice(0, 16); }
  function toast(message, error = false) { const el = $("#toast"); if (!el) return; el.textContent = message; el.classList.toggle("error", error); el.classList.remove("hidden"); clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.add("hidden"), 3600); }
  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.method && !["GET", "HEAD"].includes(options.method.toUpperCase())) headers.set("X-CSRF-Token", csrf);
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers });
    const ct = response.headers.get("content-type") || "";
    const payload = ct.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      const detail = typeof payload === "object" ? payload?.detail : payload;
      throw new Error(typeof detail === "string" ? detail : "No se pudo completar la acción.");
    }
    return payload;
  }
  function selectedDate() { return $("#selectedDate")?.value || new Date().toLocaleDateString("sv-SE"); }

  function addStyle() {
    if ($('link[href*="v2-clinical-history.css"]')) return;
    const link = document.createElement("link"); link.rel = "stylesheet"; link.href = "/static/v2-clinical-history.css?v=2.2.0"; document.head.appendChild(link);
  }

  // -------- Medicamentos: historial real y estados --------
  function statusLabel(value) {
    return ({active:"Activo", suspended:"Suspendido", finished:"Finalizado", paused:"Pausado", resumed:"Reanudado"})[value] || value || "Activo";
  }
  async function latestStatus(med) {
    try { const rows = await api(`/api/v2/patients/${pid()}/medications/${med.id}/treatment-history`); return rows.at(-1)?.status || (med.active ? "active" : "suspended"); }
    catch (_) { return med.active ? "active" : "suspended"; }
  }
  function ensureHistoricalEditForm() {
    const current = $("#medicationEditForm");
    if (!current || current.dataset.historyReady === "1") return current;
    const clone = current.cloneNode(true);
    clone.dataset.historyReady = "1";
    current.replaceWith(clone);
    const submit = clone.querySelector('button[type="submit"]');
    const block = document.createElement("div");
    block.className = "med-status-row";
    block.innerHTML = `
      <label>Estado del tratamiento<select name="treatment_status"><option value="active">Activo</option><option value="suspended">Suspendido</option><option value="finished">Finalizado</option><option value="paused">Pausado</option><option value="resumed">Reanudado</option></select></label>
      <label>Fecha/hora efectiva<input name="effective_at" type="datetime-local"></label>
      <label class="med-status-reason">Motivo del cambio / suspensión<textarea name="status_reason" placeholder="Opcional"></textarea></label>`;
    submit.before(block);
    const historyBox = document.createElement("div"); historyBox.id = "medTreatmentHistory"; historyBox.className = "treatment-history-box"; historyBox.innerHTML = "<h4>Historial de tratamiento</h4><div class='history-content muted'>Cargando…</div>"; submit.after(historyBox);
    clone.addEventListener("submit", saveHistoricalMedication);
    return clone;
  }
  async function openHistoricalMedEdit(med) {
    const form = ensureHistoricalEditForm(); if (!form) return;
    form.elements.id.value = med.id;
    for (const name of ["name","medication_type","purpose","dose","route","frequency","instructions"]) if (form.elements[name]) form.elements[name].value = med[name] || "";
    form.elements.times.value = (med.times || []).join(",");
    const rows = await api(`/api/v2/patients/${pid()}/medications/${med.id}/treatment-history`);
    const latest = rows.at(-1);
    form.elements.treatment_status.value = latest?.status || (med.active ? "active" : "suspended");
    form.elements.effective_at.value = localDateTimeValue();
    form.elements.status_reason.value = "";
    renderMedicationHistory(rows);
    $("#medicationManagerDialog")?.close();
    $("#medicationEditDialog")?.showModal();
  }
  function renderMedicationHistory(rows) {
    const root = $("#medTreatmentHistory .history-content"); if (!root) return;
    root.innerHTML = rows.length ? rows.map(row => `<div class="treatment-history-item"><time>${esc(new Date(row.occurred_at).toLocaleString("es-CL"))}</time><div><strong>${esc(statusLabel(row.status))}</strong>${row.changed_fields?.length ? ` · cambio: ${esc(row.changed_fields.join(", "))}` : ""}</div><div>${esc([row.dose, row.route, row.frequency, (row.times || []).join(", ")].filter(Boolean).join(" · "))}</div>${row.reason ? `<small>Motivo: ${esc(row.reason)}</small>` : ""}</div>`).join("") : "<span class='muted'>Sin cambios registrados.</span>";
  }
  async function saveHistoricalMedication(event) {
    event.preventDefault();
    const form = event.currentTarget, medId = Number(form.elements.id.value), effectiveAt = form.elements.effective_at.value || localDateTimeValue();
    const payload = {name:form.elements.name.value.trim(), generic_name:null, medication_type:form.elements.medication_type.value.trim() || "Medicamento", purpose:form.elements.purpose.value.trim() || null, dose:form.elements.dose.value.trim() || null, route:form.elements.route.value.trim() || null, frequency:form.elements.frequency.value.trim() || null, instructions:form.elements.instructions.value.trim() || null, times:form.elements.times.value.split(",").map(v=>v.trim()).filter(Boolean), effective_at:effectiveAt};
    try {
      const history = await api(`/api/v2/patients/${pid()}/medications/${medId}/treatment-history`);
      const previousStatus = history.at(-1)?.status || "active";
      await api(`/api/v2/patients/${pid()}/medications/${medId}/history-update`, {method:"PUT", body:JSON.stringify(payload)});
      const nextStatus = form.elements.treatment_status.value;
      if (nextStatus !== previousStatus) await api(`/api/v2/patients/${pid()}/medications/${medId}/status`, {method:"POST", body:JSON.stringify({status:nextStatus, occurred_at:effectiveAt, reason:form.elements.status_reason.value.trim() || null})});
      $("#medicationEditDialog")?.close(); toast("Medicamento e historial actualizados."); await refreshMedicationManager(); location.reload();
    } catch (e) { toast(e.message, true); }
  }
  async function refreshMedicationManager() {
    const root = $("#configuredMedicationList"); if (!root || !pid()) return;
    try {
      const meds = await api(`/api/v2/patients/${pid()}/medications`);
      const statuses = await Promise.all(meds.map(latestStatus));
      root.innerHTML = meds.length ? meds.map((med,i)=>`<article class="card" style="margin-bottom:10px"><div class="card-head"><div><strong>${esc(med.name)}</strong><div class="muted">${esc([med.dose,med.route,med.frequency].filter(Boolean).join(" · "))}</div><span class="badge">${esc(statusLabel(statuses[i]))}</span></div></div><div class="button-row"><button type="button" class="secondary ext-edit-med" data-id="${med.id}">Editar / historial</button></div></article>`).join("") : "<p class='empty'>No hay medicamentos configurados.</p>";
      $$(".ext-edit-med", root).forEach(btn => btn.addEventListener("click", ()=>openHistoricalMedEdit(meds.find(m=>m.id===Number(btn.dataset.id))).catch(e=>toast(e.message,true))));
    } catch(e) { root.innerHTML = `<p class="empty">${esc(e.message)}</p>`; }
  }
  function bindMedicationManager() {
    document.addEventListener("click", event => { if (event.target.closest("#manageMedicationsBtn")) setTimeout(refreshMedicationManager, 180); });
    new MutationObserver(()=>ensureHistoricalEditForm()).observe(document.body,{childList:true,subtree:true});
  }

  function addMedicationAiHelper() {
    const purpose = $("#medPurpose"); if (!purpose || $("#medAiHelpBtn")) return;
    const row = document.createElement("div"); row.className="med-catalog-help"; row.innerHTML='<button id="medAiHelpBtn" type="button" class="small secondary">Completar categoría/uso</button><small id="medUnitHint"></small>'; purpose.parentElement.appendChild(row);
    $("#medAiHelpBtn").addEventListener("click", async ()=>{
      const name=$("#medName")?.value.trim(); if(!name) return toast("Escribe primero el nombre del medicamento.",true);
      try { const x=await api("/api/v2/medications/ai-enrich",{method:"POST",body:JSON.stringify({name})}); if(x.medication_type)$("#medType").value=x.medication_type;if(x.purpose)$("#medPurpose").value=x.purpose;const route=$("#medicationForm")?.elements.route;if(route&&!route.value&&x.usual_route)route.value=x.usual_route;$("#medUnitHint").textContent=x.usual_unit?`Unidad habitual del catálogo: ${x.usual_unit}. Confirma siempre la indicación clínica.`:"";toast(x.source==="ai"?"Información general completada con IA.":"Información completada desde el catálogo."); } catch(e){toast(e.message,true)}
    });
  }

  // -------- Alimentación y eliminación --------
  function replaceFoodForm() {
    const old=$("#foodForm"); if(!old||old.dataset.enhanced==="1")return;
    const clone=old.cloneNode(true); clone.dataset.enhanced="1"; old.replaceWith(clone);
    const typeLabel=clone.elements.meal_type?.closest("label");
    if(typeLabel){typeLabel.innerHTML='Tipo<select name="meal_type"><option>Desayuno</option><option>Colación</option><option>Almuerzo</option><option>Once/Merienda</option><option>Cena</option><option>Alimentación nocturna</option><option>Lactancia/Leche</option><option>Líquidos</option><option>Otro</option></select>';}
    const itemLabel=clone.elements.item.closest("label");
    const portion=document.createElement("label"); portion.innerHTML='Cantidad aproximada<select name="portion"><option value="">—</option><option>Todo</option><option>Más de la mitad</option><option>La mitad</option><option>Menos de la mitad</option><option>Muy poco</option><option>Nada</option></select><small class="portion-help">Opcional; puedes seguir usando cantidad y unidad si lo prefieres.</small>'; itemLabel.after(portion);
    clone.addEventListener("submit", saveFood, true);
  }
  async function saveFood(event){if(event.submitter?.value==="cancel")return;event.preventDefault();event.stopImmediatePropagation();const f=event.currentTarget,d=Object.fromEntries(new FormData(f).entries()),edit=f.dataset.editId;const body={occurred_at:d.occurred_at,meal_type:d.meal_type||null,item:d.item,amount:d.amount===""?null:Number(d.amount),unit:d.unit||null,portion:d.portion||null,tolerated:f.elements.tolerated.checked,vomiting:f.elements.vomiting.checked,notes:d.notes||null};try{await api(`/api/v2/patients/${pid()}/food-enhanced${edit?`/${edit}`:""}`,{method:edit?"PUT":"POST",body:JSON.stringify(body)});f.closest("dialog")?.close();f.reset();delete f.dataset.editId;toast(edit?"Registro de comida modificado.":"Registro de comida agregado.");await renderCareCards();}catch(e){toast(e.message,true)}}
  async function renderCareCards(){if(renderingCare||!pid())return;renderingCare=true;try{const data=await api(`/api/v2/patients/${pid()}/day?date=${encodeURIComponent(selectedDate())}`);foodMeta=await api(`/api/v2/patients/${pid()}/food-metadata`);renderFoodCards(data.food||[]);renderEliminationCards(data.elimination||[]);}catch(_){}finally{renderingCare=false}}
  function renderFoodCards(items){const root=$("#foodList");if(!root)return;const order=["Desayuno","Colación","Almuerzo","Once/Merienda","Cena","Alimentación nocturna","Lactancia/Leche","Líquidos","Otro"];const groups=new Map();items.forEach(x=>{const k=x.meal_type||"Otro";if(!groups.has(k))groups.set(k,[]);groups.get(k).push(x)});root.innerHTML=items.length?order.filter(k=>groups.has(k)).concat([...groups.keys()].filter(k=>!order.includes(k))).map(k=>`<section class="meal-group"><h3 class="meal-group-title">${esc(k)}</h3>${groups.get(k).map(x=>`<article class="care-detail-card food"><div class="care-card-top"><span class="care-card-title">${esc(x.item)}</span><time>${esc(new Date(x.occurred_at).toLocaleTimeString("es-CL",{hour:"2-digit",minute:"2-digit"}))}</time></div><div class="care-tags">${x.amount!=null?`<span>${esc(x.amount)} ${esc(x.unit||"")}</span>`:""}${foodMeta[String(x.id)]?.portion?`<span>${esc(foodMeta[String(x.id)].portion)}</span>`:""}${x.vomiting?"<span>Vómito</span>":x.tolerated===false?"<span>No toleró</span>":x.tolerated===true?"<span>Toleró</span>":""}</div>${x.notes?`<p>${esc(x.notes)}</p>`:""}<div class="record-action-buttons"><button class="text-btn ext-edit-food" data-id="${x.id}">Editar</button><button class="text-btn danger-text ext-delete-food" data-id="${x.id}">Eliminar</button></div></article>`).join("")}</section>`).join(""):"<p class='empty'>Sin registros.</p>";$$('.ext-edit-food',root).forEach(b=>b.onclick=()=>editFood(Number(b.dataset.id)));$$('.ext-delete-food',root).forEach(b=>b.onclick=()=>deleteRecord("food",Number(b.dataset.id),renderCareCards));}
  async function editFood(id){try{const x=await api(`/api/v2/patients/${pid()}/food/${id}`),f=$("#foodForm");f.reset();f.dataset.editId=String(id);f.elements.occurred_at.value=(x.occurred_at||"").slice(0,16);f.elements.meal_type.value=x.meal_type||"Otro";f.elements.item.value=x.item||"";f.elements.amount.value=x.amount??"";f.elements.unit.value=x.unit||"";f.elements.portion.value=foodMeta[String(id)]?.portion||"";f.elements.tolerated.checked=x.tolerated!==false;f.elements.vomiting.checked=!!x.vomiting;f.elements.notes.value=x.notes||"";f.querySelector('.dialog-head h2').textContent='Editar comida';f.querySelector('button.primary').textContent='Guardar cambios';$("#foodDialog")?.showModal();}catch(e){toast(e.message,true)}}
  function renderEliminationCards(items){const root=$("#eliminationList");if(!root)return;const labels={dry:"Seco",wet:"Pipí",soiled:"Deposición",wet_and_soiled:"Pipí + deposición"};root.innerHTML=items.length?items.map(x=>`<article class="care-detail-card elimination"><div class="care-card-top"><span class="care-card-title">${esc(labels[x.diaper_status]||x.diaper_status)}</span><time>${esc(new Date(x.occurred_at).toLocaleTimeString("es-CL",{hour:"2-digit",minute:"2-digit"}))}</time></div><div class="care-tags">${x.urine_amount?`<span>Orina: ${esc(x.urine_amount)}</span>`:""}${x.urine_color?`<span>Color: ${esc(x.urine_color)}</span>`:""}${x.stool_description?`<span>Deposición: ${esc(x.stool_description)}</span>`:""}</div>${x.notes?`<p>${esc(x.notes)}</p>`:""}<div class="record-action-buttons"><button class="text-btn record-edit-btn" data-kind="elimination" data-id="${x.id}">Editar</button><button class="text-btn danger-text ext-delete-elim" data-id="${x.id}">Eliminar</button></div></article>`).join(""):"<p class='empty'>Sin registros.</p>";$$('.ext-delete-elim',root).forEach(b=>b.onclick=()=>deleteRecord("elimination",Number(b.dataset.id),renderCareCards));}
  async function deleteRecord(resource,id,refresh){if(!confirm("¿Eliminar este registro?"))return;try{await api(`/api/v2/patients/${pid()}/${resource}/${id}`,{method:"DELETE"});toast("Registro eliminado.");await refresh();}catch(e){toast(e.message,true)}}

  // -------- Evolución post quimioterapia --------
  function ensureChemoEventDialog(){if($("#chemoEventDialog"))return;const d=document.createElement("dialog");d.id="chemoEventDialog";d.innerHTML=`<form id="chemoEventForm" class="dialog-form"><div class="dialog-head"><h2>Evolución posterior a quimioterapia</h2><button type="button" class="icon-btn" data-close-chemo-event>×</button></div><input type="hidden" name="chemo_id"><label>Fecha y hora<input name="occurred_at" type="datetime-local" required></label><label>Tipo de evento<select name="event_type">${["Náuseas","Vómitos","Fiebre","Dolor","Somnolencia","Irritabilidad","Falta de apetito","Diarrea","Estreñimiento","Convulsión","Cambios de presión","Cambios de saturación","Otro"].map(x=>`<option>${x}</option>`).join("")}</select></label><label>Descripción / observación<textarea name="description"></textarea></label><button class="primary" type="submit">Guardar evento</button></form>`;document.body.appendChild(d);d.querySelector('[data-close-chemo-event]').onclick=()=>d.close();d.querySelector('form').onsubmit=saveChemoEvent;}
  async function saveChemoEvent(e){e.preventDefault();const f=e.currentTarget;try{await api(`/api/v2/patients/${pid()}/chemo/${f.elements.chemo_id.value}/events`,{method:"POST",body:JSON.stringify({occurred_at:f.elements.occurred_at.value,event_type:f.elements.event_type.value,description:f.elements.description.value.trim()||null})});f.closest('dialog').close();toast("Evolución de quimioterapia registrada.");await enhanceChemoCards();}catch(err){toast(err.message,true)}}
  async function enhanceChemoCards(){ensureChemoEventDialog();const cards=$$("#chemoList .stable-care-card.chemo");for(const card of cards){const chemoId=Number(card.dataset.id);if(!chemoId||card.querySelector('.chemo-evolution'))continue;let events=[];try{events=await api(`/api/v2/patients/${pid()}/chemo/${chemoId}/events`)}catch(_){}const box=document.createElement('div');box.className='chemo-evolution';box.innerHTML=`<div class="chemo-evolution-head"><strong>Evolución posterior</strong><button type="button" class="small secondary add-chemo-event">+ Evento</button></div><div class="chemo-evolution-list">${events.length?events.map(x=>`<div class="chemo-event"><strong>${esc(x.event_type)} · ${esc(new Date(x.occurred_at).toLocaleString("es-CL"))}</strong>${x.description?`<span>${esc(x.description)}</span>`:""}</div>`).join(""):"<span class='muted'>Sin eventos posteriores registrados.</span>"}</div>`;box.querySelector('.add-chemo-event').onclick=()=>{const f=$("#chemoEventForm");f.reset();f.elements.chemo_id.value=chemoId;f.elements.occurred_at.value=localDateTimeValue();$("#chemoEventDialog").showModal()};card.querySelector('.care-record-body')?.appendChild(box)}}

  // -------- Exámenes: múltiples archivos = un examen; edición sin duplicar --------
  function setupDocuments(){const old=$("#documentForm");if(!old||old.dataset.groupReady==="1")return;const form=old.cloneNode(true);form.dataset.groupReady="1";old.replaceWith(form);const input=form.elements.file;input.multiple=true;input.removeAttribute("required");input.style.display="none";let tools=$("#documentUploadTools",form);if(!tools){tools=document.createElement('div');tools.id='documentUploadTools';tools.innerHTML='<div class="button-row"><button id="chooseDocumentsBtn" type="button" class="secondary">Elegir fotos / archivos</button><button id="takePhotoBtn" type="button" class="secondary">Tomar foto</button></div><small id="documentSelectionStatus" class="field-help">Puedes seleccionar hasta 10 elementos del mismo examen.</small>';input.closest('label').appendChild(tools)}const camera=document.createElement('input');camera.type='file';camera.accept='image/*';camera.setAttribute('capture','environment');camera.style.display='none';form.appendChild(camera);const add=files=>{for(const file of files){if(docFiles.length>=10)break;if(!docFiles.some(x=>x.name===file.name&&x.size===file.size&&x.lastModified===file.lastModified))docFiles.push(file)}updateDocStatus()};input.onchange=()=>add([...input.files]);camera.onchange=()=>add([...camera.files]);$("#chooseDocumentsBtn",form).onclick=()=>input.click();$("#takePhotoBtn",form).onclick=()=>camera.click();form.onsubmit=saveDocumentGroup;new MutationObserver(enhanceDocumentCards).observe($("#documentList"),{childList:true});setTimeout(enhanceDocumentCards,250)}
  function updateDocStatus(){const x=$("#documentSelectionStatus");if(x)x.textContent=docFiles.length?`${docFiles.length} de 10 seleccionados: ${docFiles.map(f=>f.name).join(", ")}`:"Puedes seleccionar hasta 10 elementos del mismo examen."}
  async function saveDocumentGroup(e){e.preventDefault();e.stopImmediatePropagation();const f=e.currentTarget,editId=f.dataset.editId;if(editId){const d=Object.fromEntries(new FormData(f).entries());try{await api(`/api/v2/patients/${pid()}/documents/${editId}`,{method:"PUT",body:JSON.stringify({document_type:d.document_type,exam_name:d.exam_name||null,hospital:d.hospital||null,event_date:d.event_date||null,hospitalization_id:d.hospitalization_id?Number(d.hospitalization_id):null})});f.closest('dialog').close();f.reset();delete f.dataset.editId;toast("Examen actualizado sin crear duplicado.");location.reload();}catch(err){toast(err.message,true)}return}if(!docFiles.length)return toast("Selecciona al menos un archivo o foto.",true);const fd=new FormData(),meta=new FormData(f);for(const [k,v] of meta.entries())if(k!=="file")fd.append(k,v);docFiles.forEach(file=>fd.append("files",file,file.name));try{toast(`Procesando ${docFiles.length} archivo${docFiles.length===1?"":"s"} como un solo examen…`);const r=await api(`/api/v2/patients/${pid()}/documents/group`,{method:"POST",body:fd});docFiles=[];updateDocStatus();f.closest('dialog').close();f.reset();toast(`Examen guardado: ${r.assets} archivo${r.assets===1?"":"s"} procesado${r.assets===1?"":"s"}${r.failures?`, ${r.failures} con problemas`:""}.`);location.reload();}catch(err){toast(err.message,true)}}
  async function enhanceDocumentCards(){const cards=$$("#documentList .document-card");if(!cards.length||!pid())return;let docs=[];try{docs=await api(`/api/v2/patients/${pid()}/documents`)}catch(_){return}cards.forEach((card,index)=>{if(card.querySelector('.document-edit-actions'))return;const doc=docs[index];if(!doc)return;const actions=document.createElement('div');actions.className='document-edit-actions';actions.innerHTML=`<button type="button" class="secondary edit-document-meta">Editar datos</button><button type="button" class="secondary show-document-assets">Ver archivos</button>`;card.appendChild(actions);actions.querySelector('.edit-document-meta').onclick=()=>editDocument(doc);actions.querySelector('.show-document-assets').onclick=()=>showAssets(card,doc.id)})}
  function editDocument(doc){const f=$("#documentForm");docFiles=[];updateDocStatus();f.reset();f.dataset.editId=String(doc.id);f.elements.document_type.value=doc.document_type||"exam";f.elements.exam_name.value=doc.exam_name||"";f.elements.hospital.value=doc.hospital||"";f.elements.event_date.value=doc.event_date||"";if(f.elements.hospitalization_id)f.elements.hospitalization_id.value=doc.hospitalization_id||"";f.querySelector('.dialog-head h2').textContent='Editar examen o informe';f.querySelector('button.primary').textContent='Guardar cambios';$("#documentDialog")?.showModal()}
  async function showAssets(card,id){let box=card.querySelector('.document-assets');if(box){box.remove();return}try{const rows=await api(`/api/v2/patients/${pid()}/documents/${id}/assets`);box=document.createElement('div');box.className='document-assets';box.innerHTML=rows.length?`<strong>${rows.length} archivo${rows.length===1?"":"s"} asociados</strong>`+rows.map((x,i)=>`<a href="/api/v2/patients/${pid()}/documents/${id}/assets/${x.id}/download" target="_blank">${i+1}. ${esc(x.filename)}</a>`).join(''):'<span class="muted">Este examen corresponde al formato anterior de un solo archivo.</span>';card.appendChild(box)}catch(e){toast(e.message,true)}}

  // -------- Reporte completo de hospitalización --------
  function setupHospitalReportOverride(){const observer=new MutationObserver(()=>{const b=$("#generateReportBtn");if(!b||b.dataset.hospitalOverride)return;b.dataset.hospitalOverride='1';const original=b.onclick;b.onclick=async event=>{if($("#reportScope")?.value==="hospitalization"&&$("#reportHospitalization")?.value){event?.preventDefault?.();await generateHospitalReport(b);return}if(typeof original==='function')return original.call(b,event)};});observer.observe(document.body,{childList:true,subtree:true});}
  async function generateHospitalReport(button){const hosp=Number($("#reportHospitalization").value),useAi=!!$("#reportUseAi")?.checked;button.disabled=true;button.textContent='Generando…';try{const r=await api(`/api/v2/patients/${pid()}/hospitalizations/${hosp}/hospital-report?use_ai=${useAi}`);$("#reportResult").classList.remove('hidden');$("#reportNarrative").innerHTML=r.narrative.split(/\n+/).filter(Boolean).map(p=>`<p>${esc(p)}</p>`).join('');$("#reportAiBadge").textContent=r.ai_used?'Redacción IA':'Datos IkerCare';const s=r.statistics;$("#reportStats").innerHTML=[['Días',s.days],['Administraciones',s.medication_administrations],['Cambios tratamiento',s.treatment_changes],['Quimioterapias',s.chemotherapy_sessions],['Eventos post quimio',s.chemo_events],['Signos vitales',s.vital_records],['Alimentación',s.food_records],['Pañal/orina/deposición',s.elimination_records],['Exámenes',s.documents]].map(([l,v])=>`<div class="report-stat"><span>${esc(l)}</span><strong>${esc(v)}</strong></div>`).join('');$("#reportFacts").innerHTML=renderHospitalDays(r.facts.days);$("#downloadReportBtn").disabled=false;$("#downloadReportBtn").dataset.hospitalReport=String(hosp);toast("Informe completo de hospitalización generado.")}catch(e){toast(e.message,true)}finally{button.disabled=false;button.textContent='Generar informe'}}
  function renderHospitalDays(days){const labels={medications:'Medicamentos',treatment_changes:'Cambios de tratamiento',chemotherapy:'Quimioterapia',chemo_events:'Evolución post quimioterapia',events:'Eventos clínicos',vitals:'Signos vitales',food:'Alimentación',elimination:'Pañal / orina / deposiciones',documents:'Exámenes',notes:'Observaciones'};const row=(key,x)=>{if(key==='medications')return `${x.time} – <strong>${esc(x.name)}</strong> ${esc(x.dose||'')} ${esc(x.route||'')} · ${esc(x.status||'')}`;if(key==='treatment_changes')return `${x.time} – <strong>${esc(x.medication)}</strong> · ${esc(statusLabel(x.status))} · ${esc([x.dose,x.frequency,x.route].filter(Boolean).join(' · '))}${x.reason?` · Motivo: ${esc(x.reason)}`:''}`;if(key==='vitals')return `${x.time} – ${esc([x.temperature_c!=null?`${x.temperature_c} °C`:null,x.systolic&&x.diastolic?`${x.systolic}/${x.diastolic} mmHg`:null,x.heart_rate?`FC ${x.heart_rate}`:null,x.oxygen_saturation!=null?`SatO₂ ${x.oxygen_saturation}%`:null].filter(Boolean).join(' · '))}`;if(key==='food')return `${x.time} – <strong>${esc(x.meal_type||'Alimentación')}</strong>: ${esc(x.item||'')} ${esc(x.portion||'')} ${esc(x.notes||'')}`;if(key==='elimination')return `${x.time} – ${esc(x.diaper_status||'')} · orina ${esc(x.urine_amount||'')} ${esc(x.urine_color||'')} · deposición ${esc(x.stool_description||'')}`;if(key==='documents')return `<strong>${esc(x.name)}</strong> · ${esc(x.hospital||'')}`;if(key==='notes')return esc(x.text||'');return `${esc(x.time||'')} – <strong>${esc(x.name||x.chemo||x.type||'')}</strong>: ${esc(x.description||x.notes||'')}`};return `<div class="hospital-report-days">${days.map(day=>`<article class="hospital-report-day"><h3>${esc(new Date(day.date+'T12:00:00').toLocaleDateString('es-CL',{day:'numeric',month:'long',year:'numeric'}))}</h3>${Object.entries(labels).map(([key,label])=>day[key]?.length?`<section class="hospital-report-section"><h4>${label}</h4>${day[key].map(x=>`<div class="hospital-report-row">${row(key,x)}</div>`).join('')}</section>`:'').join('')}</article>`).join('')}</div>`}
  function overrideHospitalPdf(){document.addEventListener('click',async event=>{const b=event.target.closest('#downloadReportBtn');if(!b||!b.dataset.hospitalReport)return;event.preventDefault();event.stopImmediatePropagation();const hosp=b.dataset.hospitalReport,useAi=!!$("#reportUseAi")?.checked,url=`/api/v2/patients/${pid()}/hospitalizations/${hosp}/hospital-report.pdf?use_ai=${useAi}`,name=`IkerCare-hospitalizacion-${hosp}.pdf`;try{b.disabled=true;b.textContent='Preparando PDF…';const r=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/pdf'}});if(!r.ok){let msg='No fue posible descargar el PDF.';try{const d=await r.json();if(typeof d.detail==='string')msg=d.detail}catch(_){}throw new Error(msg)}if(!(r.headers.get('content-type')||'').includes('application/pdf'))throw new Error('El servidor no devolvió un PDF válido.');if(window.IkerCareNative?.downloadAuthenticatedFile){window.IkerCareNative.downloadAuthenticatedFile(new URL(url,location.origin).toString(),name,'application/pdf');toast('Descarga iniciada.')}else{const blob=await r.blob(),u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),3000);toast('PDF descargado correctamente.')}}catch(e){toast(e.message,true)}finally{b.disabled=false;b.textContent='Descargar PDF'}},true)}

  function init(){addStyle();addMedicationAiHelper();bindMedicationManager();replaceFoodForm();setupDocuments();setupHospitalReportOverride();overrideHospitalPdf();ensureChemoEventDialog();setTimeout(()=>{renderCareCards();enhanceChemoCards();enhanceDocumentCards()},500);$("#selectedDate")?.addEventListener('change',()=>setTimeout(renderCareCards,250));$("#patientSelect")?.addEventListener('change',()=>setTimeout(()=>{renderCareCards();enhanceChemoCards();enhanceDocumentCards()},600));new MutationObserver(()=>setTimeout(enhanceChemoCards,120)).observe($("#chemoList"),{childList:true});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();