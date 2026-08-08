const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const selectedDateInput = document.getElementById('selected-date');
let dashboardData = null;
let medicationsCatalog = [];

const statusLabels = {
  scheduled: 'Programada',
  in_progress: 'En curso',
  completed: 'Completada',
  postponed: 'Postergada',
  cancelled: 'Cancelada',
};

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

async function api(url, options = {}) {
  const config = { ...options };
  config.headers = { ...(options.headers || {}) };
  const method = (config.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    config.headers['X-CSRF-Token'] = csrfToken;
    if (config.body && !(config.body instanceof FormData)) {
      config.headers['Content-Type'] = 'application/json';
    }
  }

  const response = await fetch(url, config);
  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Sesión vencida');
  }
  if (!response.ok) {
    let message = `Error ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (_) {}
    throw new Error(message);
  }
  const contentType = response.headers.get('content-type') || '';
  return contentType.includes('application/json') ? response.json() : response;
}

function showToast(message, kind = 'success') {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.className = `toast visible ${kind}`;
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => {
    toast.className = 'toast';
  }, 3200);
}

function formatHumanDate(dateValue) {
  const parsed = new Date(`${dateValue}T12:00:00`);
  return new Intl.DateTimeFormat('es-CL', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(parsed);
}

function formatTime(dateTime) {
  if (!dateTime) return '—';
  return new Date(dateTime).toLocaleTimeString('es-CL', { hour: '2-digit', minute: '2-digit' });
}

function addDays(dateString, amount) {
  const date = new Date(`${dateString}T12:00:00`);
  date.setDate(date.getDate() + amount);
  return date.toISOString().slice(0, 10);
}

function currentLocalDate() {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  return new Date(now.getTime() - offset * 60_000).toISOString().slice(0, 10);
}

function defaultDateTime(dateString) {
  const now = new Date();
  const today = currentLocalDate();
  const hh = today === dateString ? String(now.getHours()).padStart(2, '0') : '09';
  const mm = today === dateString ? String(now.getMinutes()).padStart(2, '0') : '00';
  return `${dateString}T${hh}:${mm}`;
}

function setDefaultFormDates() {
  const value = defaultDateTime(selectedDateInput.value);
  ['chemo-date', 'vital-date', 'crisis-date'].forEach((id) => {
    const element = document.getElementById(id);
    if (element && !element.dataset.edited) element.value = value;
  });
}

function renderSummary(summary) {
  document.getElementById('summary-medications').textContent = `${summary.medications_taken}/${summary.medications_total}`;
  document.getElementById('summary-medications-detail').textContent = `${summary.medications_pending} pendientes · ${summary.medications_skipped} omitidos`;
  document.getElementById('summary-vitals').textContent = summary.vital_records;
  document.getElementById('summary-crises').textContent = summary.crisis_events;
  document.getElementById('summary-chemo').textContent = summary.chemo_sessions;
  document.getElementById('medication-progress').textContent = `${summary.medications_taken} de ${summary.medications_total} tomados`;
}

function renderMedications(items) {
  const container = document.getElementById('medication-list');
  const empty = document.getElementById('medication-empty');
  container.innerHTML = '';
  empty.classList.toggle('hidden', items.length > 0);

  for (const item of items) {
    const med = item.medication;
    const card = document.createElement('article');
    card.className = `medication-card status-${item.status}`;
    const actual = item.actual_time ? `<span class="actual-time">Registrado: ${escapeHtml(formatTime(item.actual_time))}</span>` : '';
    const statusText = item.status === 'taken' ? 'Tomado' : item.status === 'skipped' ? 'Omitido' : 'Pendiente';
    card.innerHTML = `
      <div class="time-badge">${escapeHtml(item.time)}</div>
      <label class="medication-check">
        <input type="checkbox" data-schedule-id="${item.schedule_id}" ${item.status === 'taken' ? 'checked' : ''}>
        <span class="checkmark">✓</span>
      </label>
      <div class="medication-main">
        <div class="medication-title-row">
          <div>
            <h3>${escapeHtml(med.name)}</h3>
            <div class="tag-row">
              <span class="tag">${escapeHtml(med.medication_type)}</span>
              ${med.dose ? `<span class="tag subtle">Dosis: ${escapeHtml(med.dose)}</span>` : ''}
              ${med.route ? `<span class="tag subtle">${escapeHtml(med.route)}</span>` : ''}
              ${med.frequency ? `<span class="tag subtle">${escapeHtml(med.frequency)}</span>` : ''}
            </div>
          </div>
          <span class="status-label">${statusText}</span>
        </div>
        ${med.purpose ? `<p><strong>Para qué sirve:</strong> ${escapeHtml(med.purpose)}</p>` : ''}
        ${med.instructions ? `<p class="instructions">${escapeHtml(med.instructions)}</p>` : ''}
        <div class="medication-footer">
          ${actual}
          <button class="button button-small button-ghost skip-medication" data-schedule-id="${item.schedule_id}" type="button">
            ${item.status === 'skipped' ? 'Volver a pendiente' : 'Marcar omitido'}
          </button>
        </div>
      </div>`;
    container.appendChild(card);
  }

  container.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.addEventListener('change', async (event) => {
      const scheduleId = Number(event.currentTarget.dataset.scheduleId);
      const status = event.currentTarget.checked ? 'taken' : 'pending';
      try {
        await api('/api/medication-logs/toggle', {
          method: 'POST',
          body: JSON.stringify({ schedule_id: scheduleId, log_date: selectedDateInput.value, status }),
        });
        showToast(status === 'taken' ? 'Medicamento marcado como tomado.' : 'Medicamento vuelto a pendiente.');
        await loadDashboard();
      } catch (error) {
        event.currentTarget.checked = !event.currentTarget.checked;
        showToast(error.message, 'error');
      }
    });
  });

  container.querySelectorAll('.skip-medication').forEach((button) => {
    button.addEventListener('click', async (event) => {
      const scheduleId = Number(event.currentTarget.dataset.scheduleId);
      const item = dashboardData.medications.find((row) => row.schedule_id === scheduleId);
      const status = item.status === 'skipped' ? 'pending' : 'skipped';
      try {
        await api('/api/medication-logs/toggle', {
          method: 'POST',
          body: JSON.stringify({ schedule_id: scheduleId, log_date: selectedDateInput.value, status }),
        });
        showToast(status === 'skipped' ? 'Medicamento marcado como omitido.' : 'Medicamento vuelto a pendiente.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });
}


function renderUnscheduledMedications(items) {
  const container = document.getElementById('unscheduled-medication-list');
  const empty = document.getElementById('unscheduled-medication-empty');
  const count = items.reduce((total, item) => total + item.administrations.length, 0);
  const countLabel = count === 1 ? '1 administración' : `${count} administraciones`;
  document.getElementById('unscheduled-count').textContent = countLabel;
  container.innerHTML = '';
  empty.classList.toggle('hidden', items.length > 0);

  for (const item of items) {
    const med = item.medication;
    const canRegister = med.active && med.times.length === 0;
    const card = document.createElement('article');
    card.className = 'record-card unscheduled-medication-card';
    const administrations = item.administrations.length
      ? `<div class="administration-list">
          ${item.administrations.map((administration) => `
            <div class="administration-row">
              <div>
                <strong>${escapeHtml(formatTime(administration.occurred_at))}</strong>
                ${administration.notes ? `<span>${escapeHtml(administration.notes)}</span>` : '<span class="muted">Sin comentario</span>'}
              </div>
              <button class="icon-button danger delete-medication-event" data-id="${administration.id}" type="button" title="Eliminar registro">×</button>
            </div>`).join('')}
        </div>`
      : '<p class="muted">Aún no se ha registrado una administración en este día.</p>';

    card.innerHTML = `
      <div class="record-card-header">
        <div><h4>${escapeHtml(med.name)}</h4><span class="record-time">Sin horario fijo</span></div>
      </div>
      <div class="tag-row">
        <span class="tag">${escapeHtml(med.medication_type)}</span>
        ${med.dose ? `<span class="tag subtle">Dosis: ${escapeHtml(med.dose)}</span>` : ''}
        ${med.route ? `<span class="tag subtle">${escapeHtml(med.route)}</span>` : ''}
        ${med.frequency ? `<span class="tag subtle">${escapeHtml(med.frequency)}</span>` : ''}
      </div>
      ${med.purpose ? `<p><strong>Para qué sirve:</strong> ${escapeHtml(med.purpose)}</p>` : ''}
      ${med.instructions ? `<p class="instructions">${escapeHtml(med.instructions)}</p>` : ''}
      ${canRegister ? `<div class="event-log-form" data-medication-id="${med.id}">
        <label>Hora<input class="event-log-time" type="time" value="${escapeHtml(defaultDateTime(selectedDateInput.value).slice(11, 16))}"></label>
        <label class="event-note-label">Comentario opcional<input class="event-log-note" type="text" placeholder="Motivo, síntomas o respuesta observada"></label>
        <button class="button button-primary button-small register-medication-event" data-id="${med.id}" type="button">Registrar administración</button>
      </div>` : '<p class="muted">Registro histórico: este medicamento ya no está disponible como administración sin horario fijo.</p>'}
      ${administrations}`;
    container.appendChild(card);
  }

  container.querySelectorAll('.register-medication-event').forEach((button) => {
    button.addEventListener('click', async (event) => {
      const medicationId = Number(event.currentTarget.dataset.id);
      const form = event.currentTarget.closest('.event-log-form');
      const timeValue = form.querySelector('.event-log-time').value;
      const notes = form.querySelector('.event-log-note').value.trim() || null;
      if (!timeValue) {
        showToast('Selecciona la hora de administración.', 'error');
        return;
      }
      try {
        await api(`/api/medications/${medicationId}/event-logs`, {
          method: 'POST',
          body: JSON.stringify({ occurred_at: `${selectedDateInput.value}T${timeValue}`, notes }),
        });
        showToast('Administración registrada.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });

  container.querySelectorAll('.delete-medication-event').forEach((button) => {
    button.addEventListener('click', async (event) => {
      if (!window.confirm('¿Eliminar este registro de administración?')) return;
      try {
        await api(`/api/medication-event-logs/${event.currentTarget.dataset.id}`, { method: 'DELETE' });
        showToast('Registro eliminado.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });
}

function renderChemo(items) {
  const container = document.getElementById('chemo-list');
  const empty = document.getElementById('chemo-empty');
  container.innerHTML = '';
  empty.classList.toggle('hidden', items.length > 0);

  for (const item of items) {
    const card = document.createElement('article');
    card.className = 'record-card';
    card.innerHTML = `
      <div class="record-card-header">
        <div><span class="record-time">${escapeHtml(formatTime(item.scheduled_at))}</span><h4>${escapeHtml(item.name)}</h4></div>
        <button class="icon-button danger delete-chemo" data-id="${item.id}" type="button" title="Eliminar">×</button>
      </div>
      <div class="tag-row">
        ${item.protocol ? `<span class="tag">${escapeHtml(item.protocol)}</span>` : ''}
        ${item.cycle ? `<span class="tag subtle">${escapeHtml(item.cycle)}</span>` : ''}
      </div>
      ${item.purpose ? `<p>${escapeHtml(item.purpose)}</p>` : ''}
      <label>Estado
        <select class="chemo-status-select" data-id="${item.id}">
          ${Object.entries(statusLabels).map(([value, label]) => `<option value="${value}" ${value === item.status ? 'selected' : ''}>${label}</option>`).join('')}
        </select>
      </label>
      <label>Notas<textarea class="chemo-update-notes" data-id="${item.id}" rows="2">${escapeHtml(item.notes || '')}</textarea></label>
      <label>Efectos adversos<textarea class="chemo-update-effects" data-id="${item.id}" rows="2">${escapeHtml(item.adverse_effects || '')}</textarea></label>
      <button class="button button-small button-secondary update-chemo" data-id="${item.id}" type="button">Actualizar</button>`;
    container.appendChild(card);
  }

  container.querySelectorAll('.update-chemo').forEach((button) => {
    button.addEventListener('click', async (event) => {
      const id = Number(event.currentTarget.dataset.id);
      const status = container.querySelector(`.chemo-status-select[data-id="${id}"]`).value;
      const notes = container.querySelector(`.chemo-update-notes[data-id="${id}"]`).value || null;
      const adverseEffects = container.querySelector(`.chemo-update-effects[data-id="${id}"]`).value || null;
      try {
        await api(`/api/chemo/${id}`, {
          method: 'PUT',
          body: JSON.stringify({ status, notes, adverse_effects: adverseEffects }),
        });
        showToast('Registro de quimioterapia actualizado.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });

  container.querySelectorAll('.delete-chemo').forEach((button) => {
    button.addEventListener('click', async (event) => {
      if (!window.confirm('¿Eliminar este registro de quimioterapia?')) return;
      try {
        await api(`/api/chemo/${event.currentTarget.dataset.id}`, { method: 'DELETE' });
        showToast('Registro eliminado.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });
}

function valueOrDash(value, suffix = '') {
  return value === null || value === undefined || value === '' ? '—' : `${value}${suffix}`;
}

function renderVitals(items) {
  const tbody = document.getElementById('vitals-table-body');
  const empty = document.getElementById('vitals-empty');
  tbody.innerHTML = '';
  empty.classList.toggle('hidden', items.length > 0);

  for (const item of items) {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td data-label="Hora"><strong>${escapeHtml(formatTime(item.recorded_at))}</strong>${item.notes ? `<span class="table-note">${escapeHtml(item.notes)}</span>` : ''}</td>
      <td data-label="Temperatura">${escapeHtml(valueOrDash(item.temperature_c, '°'))}</td>
      <td data-label="Presión">${item.systolic || item.diastolic ? `${escapeHtml(valueOrDash(item.systolic))}/${escapeHtml(valueOrDash(item.diastolic))}` : '—'}</td>
      <td data-label="Frecuencia cardíaca">${escapeHtml(valueOrDash(item.heart_rate))}</td>
      <td data-label="Saturación">${escapeHtml(valueOrDash(item.oxygen_saturation, '%'))}</td>
      <td data-label="Frecuencia respiratoria">${escapeHtml(valueOrDash(item.respiratory_rate))}</td>
      <td><button class="icon-button danger delete-vital" data-id="${item.id}" type="button" title="Eliminar">×</button></td>`;
    tbody.appendChild(row);
  }

  tbody.querySelectorAll('.delete-vital').forEach((button) => {
    button.addEventListener('click', async (event) => {
      if (!window.confirm('¿Eliminar este registro de signos vitales?')) return;
      try {
        await api(`/api/vitals/${event.currentTarget.dataset.id}`, { method: 'DELETE' });
        showToast('Registro eliminado.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });
}

function renderCrises(items) {
  const container = document.getElementById('crisis-list');
  const empty = document.getElementById('crisis-empty');
  container.innerHTML = '';
  empty.classList.toggle('hidden', items.length > 0);

  for (const item of items) {
    const card = document.createElement('article');
    card.className = 'record-card crisis-card';
    card.innerHTML = `
      <div class="record-card-header">
        <div><span class="record-time">${escapeHtml(formatTime(item.occurred_at))}</span><h4>${escapeHtml(item.event_type)}</h4></div>
        <button class="icon-button danger delete-crisis" data-id="${item.id}" type="button" title="Eliminar">×</button>
      </div>
      <div class="tag-row">
        ${item.duration_seconds !== null ? `<span class="tag">Duración: ${escapeHtml(item.duration_seconds)} s</span>` : ''}
        ${item.consciousness ? `<span class="tag subtle">${escapeHtml(item.consciousness)}</span>` : ''}
        <span class="tag ${item.team_notified ? 'success' : 'warning'}">${item.team_notified ? 'Equipo avisado' : 'Equipo no marcado como avisado'}</span>
      </div>
      <p>${escapeHtml(item.description)}</p>
      ${item.actions_taken ? `<p><strong>Acciones:</strong> ${escapeHtml(item.actions_taken)}</p>` : ''}
      ${item.notes ? `<p class="instructions">${escapeHtml(item.notes)}</p>` : ''}`;
    container.appendChild(card);
  }

  container.querySelectorAll('.delete-crisis').forEach((button) => {
    button.addEventListener('click', async (event) => {
      if (!window.confirm('¿Eliminar este evento?')) return;
      try {
        await api(`/api/crises/${event.currentTarget.dataset.id}`, { method: 'DELETE' });
        showToast('Evento eliminado.');
        await loadDashboard();
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });
}

function renderSettingsMedications(items) {
  const container = document.getElementById('settings-medication-list');
  container.innerHTML = '';
  for (const item of items) {
    const card = document.createElement('article');
    card.className = `record-card ${item.active ? '' : 'inactive-card'}`;
    card.innerHTML = `
      <div class="record-card-header">
        <div><h4>${escapeHtml(item.name)}</h4><span class="record-time">${item.active ? 'Activo' : 'Inactivo'}</span></div>
        <div class="button-row compact">
          <button class="button button-small button-secondary edit-medication" data-id="${item.id}" type="button">Editar</button>
          ${item.active ? `<button class="button button-small button-ghost deactivate-medication" data-id="${item.id}" type="button">Desactivar</button>` : ''}
        </div>
      </div>
      <div class="tag-row">
        <span class="tag">${escapeHtml(item.medication_type)}</span>
        ${item.frequency ? `<span class="tag subtle">${escapeHtml(item.frequency)}</span>` : ''}
        ${item.times.length ? item.times.map((time) => `<span class="tag subtle">${escapeHtml(time)}</span>`).join('') : '<span class="tag warning">Sin horario fijo</span>'}
      </div>
      ${item.purpose ? `<p>${escapeHtml(item.purpose)}</p>` : ''}
      ${item.dose ? `<p><strong>Dosis:</strong> ${escapeHtml(item.dose)}</p>` : ''}
      ${item.route ? `<p><strong>Vía:</strong> ${escapeHtml(item.route)}</p>` : ''}`;
    container.appendChild(card);
  }

  container.querySelectorAll('.edit-medication').forEach((button) => {
    button.addEventListener('click', () => editMedication(Number(button.dataset.id)));
  });
  container.querySelectorAll('.deactivate-medication').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!window.confirm('¿Desactivar este medicamento? Los registros anteriores se conservarán.')) return;
      try {
        await api(`/api/medications/${button.dataset.id}`, { method: 'DELETE' });
        showToast('Medicamento desactivado.');
        await Promise.all([loadMedicationsCatalog(), loadDashboard()]);
      } catch (error) {
        showToast(error.message, 'error');
      }
    });
  });
}

async function loadDashboard() {
  document.getElementById('human-date').textContent = formatHumanDate(selectedDateInput.value);
  setDefaultFormDates();
  try {
    dashboardData = await api(`/api/dashboard?date=${encodeURIComponent(selectedDateInput.value)}`);
    renderSummary(dashboardData.summary);
    renderMedications(dashboardData.medications);
    renderUnscheduledMedications(dashboardData.unscheduled_medications || []);
    renderChemo(dashboardData.chemo);
    renderVitals(dashboardData.vitals);
    renderCrises(dashboardData.crises);
    document.getElementById('daily-note').value = dashboardData.daily_note || '';
    document.getElementById('note-status').textContent = 'Sin cambios';
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function loadMedicationsCatalog() {
  try {
    medicationsCatalog = await api('/api/medications');
    renderSettingsMedications(medicationsCatalog);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function nullableNumber(id) {
  const value = document.getElementById(id).value;
  return value === '' ? null : Number(value);
}

function nullableText(id) {
  const value = document.getElementById(id).value.trim();
  return value || null;
}

function resetFormWithDate(formId, dateFieldId) {
  document.getElementById(formId).reset();
  const field = document.getElementById(dateFieldId);
  field.dataset.edited = '';
  field.value = defaultDateTime(selectedDateInput.value);
}

document.getElementById('chemo-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    scheduled_at: document.getElementById('chemo-date').value,
    name: document.getElementById('chemo-name').value.trim(),
    protocol: nullableText('chemo-protocol'),
    cycle: nullableText('chemo-cycle'),
    purpose: nullableText('chemo-purpose'),
    status: document.getElementById('chemo-status').value,
    notes: nullableText('chemo-notes'),
    adverse_effects: nullableText('chemo-effects'),
  };
  try {
    await api('/api/chemo', { method: 'POST', body: JSON.stringify(payload) });
    resetFormWithDate('chemo-form', 'chemo-date');
    showToast('Quimioterapia guardada.');
    await loadDashboard();
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.getElementById('vitals-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    recorded_at: document.getElementById('vital-date').value,
    temperature_c: nullableNumber('vital-temperature'),
    systolic: nullableNumber('vital-systolic'),
    diastolic: nullableNumber('vital-diastolic'),
    heart_rate: nullableNumber('vital-heart'),
    oxygen_saturation: nullableNumber('vital-oxygen'),
    respiratory_rate: nullableNumber('vital-respiratory'),
    weight_kg: nullableNumber('vital-weight'),
    notes: nullableText('vital-notes'),
  };
  const anyMeasurement = ['temperature_c', 'systolic', 'diastolic', 'heart_rate', 'oxygen_saturation', 'respiratory_rate', 'weight_kg']
    .some((key) => payload[key] !== null);
  if (!anyMeasurement) {
    showToast('Ingresa al menos un signo vital.', 'error');
    return;
  }
  try {
    await api('/api/vitals', { method: 'POST', body: JSON.stringify(payload) });
    resetFormWithDate('vitals-form', 'vital-date');
    showToast('Signos vitales guardados.');
    await loadDashboard();
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.getElementById('crisis-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    occurred_at: document.getElementById('crisis-date').value,
    event_type: document.getElementById('crisis-type').value.trim(),
    duration_seconds: nullableNumber('crisis-duration'),
    consciousness: nullableText('crisis-consciousness'),
    description: document.getElementById('crisis-description').value.trim(),
    actions_taken: nullableText('crisis-actions'),
    team_notified: document.getElementById('crisis-notified').checked,
    notes: nullableText('crisis-notes'),
  };
  try {
    await api('/api/crises', { method: 'POST', body: JSON.stringify(payload) });
    resetFormWithDate('crisis-form', 'crisis-date');
    showToast('Evento guardado. Recuerda mantener informado al equipo clínico.');
    await loadDashboard();
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.getElementById('daily-note').addEventListener('input', () => {
  document.getElementById('note-status').textContent = 'Cambios sin guardar';
});

document.getElementById('save-note').addEventListener('click', async () => {
  try {
    await api('/api/daily-note', {
      method: 'PUT',
      body: JSON.stringify({ note_date: selectedDateInput.value, text: document.getElementById('daily-note').value }),
    });
    document.getElementById('note-status').textContent = 'Guardado';
    showToast('Nota diaria guardada.');
  } catch (error) {
    showToast(error.message, 'error');
  }
});

function resetMedicationForm() {
  document.getElementById('medication-form').reset();
  document.getElementById('medication-id').value = '';
  document.getElementById('medication-active').checked = true;
  document.getElementById('medication-form-title').textContent = 'Agregar medicamento';
  document.getElementById('cancel-medication-edit').classList.add('hidden');
}

function editMedication(id) {
  const item = medicationsCatalog.find((med) => med.id === id);
  if (!item) return;
  document.getElementById('medication-id').value = item.id;
  document.getElementById('medication-name').value = item.name;
  document.getElementById('medication-type').value = item.medication_type;
  document.getElementById('medication-purpose').value = item.purpose || '';
  document.getElementById('medication-dose').value = item.dose || '';
  document.getElementById('medication-route').value = item.route || '';
  document.getElementById('medication-frequency').value = item.frequency || '';
  document.getElementById('medication-times').value = item.times.join(', ');
  document.getElementById('medication-instructions').value = item.instructions || '';
  document.getElementById('medication-active').checked = item.active;
  document.getElementById('medication-form-title').textContent = `Editar ${item.name}`;
  document.getElementById('cancel-medication-edit').classList.remove('hidden');
  document.getElementById('medication-form').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

document.getElementById('cancel-medication-edit').addEventListener('click', resetMedicationForm);

document.getElementById('medication-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = document.getElementById('medication-id').value;
  const times = document.getElementById('medication-times').value
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  const validTime = /^([01]\d|2[0-3]):[0-5]\d$/;
  if (times.some((value) => !validTime.test(value))) {
    showToast('Usa horas válidas en formato HH:MM, separadas por coma.', 'error');
    return;
  }
  const payload = {
    name: document.getElementById('medication-name').value.trim(),
    medication_type: document.getElementById('medication-type').value.trim(),
    purpose: nullableText('medication-purpose'),
    dose: nullableText('medication-dose'),
    route: nullableText('medication-route'),
    frequency: nullableText('medication-frequency'),
    instructions: nullableText('medication-instructions'),
    times,
    active: document.getElementById('medication-active').checked,
  };
  try {
    await api(id ? `/api/medications/${id}` : '/api/medications', {
      method: id ? 'PUT' : 'POST',
      body: JSON.stringify(payload),
    });
    resetMedicationForm();
    showToast(id ? 'Medicamento actualizado.' : 'Medicamento agregado.');
    await Promise.all([loadMedicationsCatalog(), loadDashboard()]);
  } catch (error) {
    showToast(error.message, 'error');
  }
});

function exportLast30Days() {
  const end = selectedDateInput.value;
  const start = addDays(end, -29);
  window.location.href = `/api/export/csv?start_date=${start}&end_date=${end}`;
}

document.getElementById('export-button').addEventListener('click', exportLast30Days);
document.getElementById('mobile-export-button')?.addEventListener('click', () => {
  closeMobileSheet();
  exportLast30Days();
});

selectedDateInput.addEventListener('change', () => {
  ['chemo-date', 'vital-date', 'crisis-date'].forEach((id) => {
    document.getElementById(id).dataset.edited = '';
  });
  loadDashboard();
});

document.getElementById('previous-day').addEventListener('click', () => {
  selectedDateInput.value = addDays(selectedDateInput.value, -1);
  selectedDateInput.dispatchEvent(new Event('change'));
});

document.getElementById('next-day').addEventListener('click', () => {
  selectedDateInput.value = addDays(selectedDateInput.value, 1);
  selectedDateInput.dispatchEvent(new Event('change'));
});

document.getElementById('today-button').addEventListener('click', () => {
  selectedDateInput.value = currentLocalDate();
  selectedDateInput.dispatchEvent(new Event('change'));
});

['chemo-date', 'vital-date', 'crisis-date'].forEach((id) => {
  document.getElementById(id).addEventListener('input', (event) => {
    event.currentTarget.dataset.edited = 'true';
  });
});

function activateTab(tabName, scrollToTop = true) {
  const panel = document.getElementById(`tab-${tabName}`);
  if (!panel) return;
  document.querySelectorAll('.tab-panel').forEach((item) => item.classList.remove('active'));
  document.querySelectorAll('[data-tab]').forEach((item) => item.classList.toggle('active', item.dataset.tab === tabName));
  document.querySelectorAll('.mobile-tab').forEach((item) => {
    const isMoreTab = !['medications', 'chemo', 'vitals', 'crises'].includes(tabName);
    item.classList.toggle('active', item.dataset.tab === tabName || (item.id === 'mobile-more-trigger' && isMoreTab));
  });
  panel.classList.add('active');
  localStorage.setItem('ikercare-active-tab', tabName);
  if (history.replaceState) history.replaceState(null, '', `#${tabName}`);
  if (scrollToTop) window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.querySelectorAll('[data-tab]').forEach((button) => {
  button.addEventListener('click', () => {
    closeMobileSheet();
    activateTab(button.dataset.tab);
  });
});

const mobileSheetLayer = document.getElementById('mobile-sheet-layer');
const mobileMoreTrigger = document.getElementById('mobile-more-trigger');

function openMobileSheet() {
  mobileSheetLayer?.classList.remove('hidden');
  mobileSheetLayer?.setAttribute('aria-hidden', 'false');
  mobileMoreTrigger?.setAttribute('aria-expanded', 'true');
  document.body.style.overflow = 'hidden';
}

function closeMobileSheet() {
  mobileSheetLayer?.classList.add('hidden');
  mobileSheetLayer?.setAttribute('aria-hidden', 'true');
  mobileMoreTrigger?.setAttribute('aria-expanded', 'false');
  document.body.style.overflow = '';
}

mobileMoreTrigger?.addEventListener('click', openMobileSheet);
document.getElementById('mobile-sheet-close')?.addEventListener('click', closeMobileSheet);
document.getElementById('mobile-sheet-backdrop')?.addEventListener('click', closeMobileSheet);
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMobileSheet(); });

const safetyBanner = document.getElementById('safety-banner');
if (sessionStorage.getItem('ikercare-safety-hidden') === 'true') safetyBanner?.classList.add('hidden');
document.getElementById('dismiss-safety-banner')?.addEventListener('click', () => {
  safetyBanner?.classList.add('hidden');
  sessionStorage.setItem('ikercare-safety-hidden', 'true');
});

const nativeSettingsButton = document.getElementById('native-server-settings');
if (window.IkerCareNative?.openServerSettings) {
  nativeSettingsButton?.classList.remove('hidden');
  nativeSettingsButton?.addEventListener('click', () => {
    closeMobileSheet();
    window.IkerCareNative.openServerSettings();
  });
}

window.addEventListener('offline', () => showToast('Sin conexión con el servidor. Revisa Wi-Fi o Tailscale.', 'error'));
window.addEventListener('online', () => showToast('Conexión recuperada.'));

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/service-worker.js').catch(() => {}));
}

const requestedTab = location.hash.slice(1) || localStorage.getItem('ikercare-active-tab') || 'medications';
activateTab(requestedTab, false);
setDefaultFormDates();
Promise.all([loadDashboard(), loadMedicationsCatalog()]);
