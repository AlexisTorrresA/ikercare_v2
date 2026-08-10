from __future__ import annotations

import json
import os
import textwrap
from datetime import date, datetime, time
from statistics import mean

import fitz
import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_models import (
    CareChemoSession,
    CareCrisisEvent,
    CareDailyNote,
    CareMedication,
    CareMedicationLog,
    CareMedicationSchedule,
    CareVitalRecord,
    ClinicalDocument,
    ClinicalHistoryEvent,
    FoodLog,
    Hospitalization,
    Patient,
)
from .v2_router import _audit, _membership, _require_role

extended_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 extended"])


def _dt_start(value: date | None) -> datetime | None:
    return datetime.combine(value, time.min) if value else None


def _dt_end(value: date | None) -> datetime | None:
    return datetime.combine(value, time.max) if value else None


def _range_clauses(column, start_date: date | None, end_date: date | None):
    clauses = []
    if start_date:
        clauses.append(column >= _dt_start(start_date))
    if end_date:
        clauses.append(column <= _dt_end(end_date))
    return clauses


def _chemo_dict(item: CareChemoSession) -> dict:
    return {
        "id": item.id,
        "scheduled_at": item.scheduled_at.isoformat(timespec="minutes"),
        "name": item.name,
        "protocol": item.protocol,
        "cycle": item.cycle,
        "purpose": item.purpose,
        "status": item.status,
        "status_value": item.status,
        "notes": item.notes,
        "adverse_effects": item.adverse_effects,
    }


def _vital_dict(item: CareVitalRecord) -> dict:
    return {
        "id": item.id,
        "recorded_at": item.recorded_at.isoformat(timespec="minutes"),
        "temperature_c": item.temperature_c,
        "systolic": item.systolic,
        "diastolic": item.diastolic,
        "heart_rate": item.heart_rate,
        "oxygen_saturation": item.oxygen_saturation,
        "respiratory_rate": item.respiratory_rate,
        "weight_kg": item.weight_kg,
        "notes": item.notes,
    }


def _crisis_dict(item: CareCrisisEvent) -> dict:
    return {
        "id": item.id,
        "occurred_at": item.occurred_at.isoformat(timespec="minutes"),
        "event_type": item.event_type,
        "duration_seconds": item.duration_seconds,
        "consciousness": item.consciousness,
        "description": item.description,
        "actions_taken": item.actions_taken,
        "team_notified": item.team_notified,
        "notes": item.notes,
    }


@extended_api.get("/patients/{patient_id}/chemo/all")
def list_all_chemo(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    _membership(db, user.id, patient_id)
    clauses = [CareChemoSession.patient_id == patient_id, *_range_clauses(CareChemoSession.scheduled_at, start_date, end_date)]
    rows = db.scalars(select(CareChemoSession).where(*clauses).order_by(CareChemoSession.scheduled_at.asc(), CareChemoSession.id.asc())).all()
    return [_chemo_dict(item) for item in rows]


@extended_api.get("/patients/{patient_id}/care-range")
def care_range(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    _membership(db, user.id, patient_id)
    vital_clauses = [CareVitalRecord.patient_id == patient_id, *_range_clauses(CareVitalRecord.recorded_at, start_date, end_date)]
    crisis_clauses = [CareCrisisEvent.patient_id == patient_id, *_range_clauses(CareCrisisEvent.occurred_at, start_date, end_date)]
    chemo_clauses = [CareChemoSession.patient_id == patient_id, *_range_clauses(CareChemoSession.scheduled_at, start_date, end_date)]
    vitals = db.scalars(select(CareVitalRecord).where(*vital_clauses).order_by(CareVitalRecord.recorded_at.desc())).all()
    crises = db.scalars(select(CareCrisisEvent).where(*crisis_clauses).order_by(CareCrisisEvent.occurred_at.desc())).all()
    chemo = db.scalars(select(CareChemoSession).where(*chemo_clauses).order_by(CareChemoSession.scheduled_at.asc())).all()
    return {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "vitals": [_vital_dict(item) for item in vitals],
        "crises": [_crisis_dict(item) for item in crises],
        "chemo": [_chemo_dict(item) for item in chemo],
    }


def _get_hospitalization(db: Session, patient_id: int, item_id: int) -> Hospitalization:
    item = db.scalar(select(Hospitalization).where(Hospitalization.id == item_id, Hospitalization.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Hospitalización no encontrada.")
    return item


@extended_api.get("/patients/{patient_id}/hospitalizations/{item_id}")
def get_hospitalization(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    item = _get_hospitalization(db, patient_id, item_id)
    return {
        "id": item.id,
        "hospital": item.hospital,
        "service": item.service,
        "admission_at": item.admission_at.isoformat(timespec="minutes"),
        "discharge_at": item.discharge_at.isoformat(timespec="minutes") if item.discharge_at else None,
        "reason": item.reason,
        "diagnosis": item.diagnosis,
        "summary": item.summary,
        "epicrisis_text": item.epicrisis_text,
    }


@extended_api.put("/patients/{patient_id}/hospitalizations/{item_id}")
def update_hospitalization(
    patient_id: int,
    item_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_hospitalization(db, patient_id, item_id)
    old_admission = item.admission_at
    old_hospital = item.hospital
    if payload.get("hospital") is not None:
        item.hospital = str(payload["hospital"]).strip()[:220]
    if "service" in payload:
        item.service = payload.get("service") or None
    if payload.get("admission_at"):
        item.admission_at = datetime.fromisoformat(str(payload["admission_at"]))
    if "discharge_at" in payload:
        item.discharge_at = datetime.fromisoformat(str(payload["discharge_at"])) if payload.get("discharge_at") else None
    for field in ("reason", "diagnosis", "summary", "epicrisis_text"):
        if field in payload:
            setattr(item, field, payload.get(field) or None)
    auto_events = db.scalars(
        select(ClinicalHistoryEvent).where(
            ClinicalHistoryEvent.patient_id == patient_id,
            ClinicalHistoryEvent.category == "hospitalization",
            ClinicalHistoryEvent.occurred_at == old_admission,
            ClinicalHistoryEvent.hospital == old_hospital,
        )
    ).all()
    for event in auto_events:
        event.occurred_at = item.admission_at
        event.hospital = item.hospital
        event.title = f"Hospitalización · {item.hospital}"
        event.description = item.reason or item.diagnosis
    _audit(db, user.id, patient_id, "hospitalization.updated", "hospitalization", item.id)
    db.commit()
    return {"ok": True}


@extended_api.delete("/patients/{patient_id}/hospitalizations/{item_id}")
def delete_hospitalization(
    patient_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_hospitalization(db, patient_id, item_id)
    auto_events = db.scalars(
        select(ClinicalHistoryEvent).where(
            ClinicalHistoryEvent.patient_id == patient_id,
            ClinicalHistoryEvent.category == "hospitalization",
            ClinicalHistoryEvent.occurred_at == item.admission_at,
            ClinicalHistoryEvent.hospital == item.hospital,
        )
    ).all()
    for event in auto_events:
        db.delete(event)
    for document in db.scalars(select(ClinicalDocument).where(ClinicalDocument.hospitalization_id == item.id)).all():
        document.hospitalization_id = None
    db.delete(item)
    _audit(db, user.id, patient_id, "hospitalization.deleted", "hospitalization", item_id)
    db.commit()
    return {"ok": True}


def _get_history(db: Session, patient_id: int, item_id: int) -> ClinicalHistoryEvent:
    item = db.scalar(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.id == item_id, ClinicalHistoryEvent.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Hito no encontrado.")
    return item


@extended_api.get("/patients/{patient_id}/history/{item_id}")
def get_history(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    item = _get_history(db, patient_id, item_id)
    return {
        "id": item.id,
        "occurred_at": item.occurred_at.isoformat(timespec="minutes"),
        "category": item.category,
        "title": item.title,
        "description": item.description,
        "hospital": item.hospital,
        "clinician_name": item.clinician_name,
        "document_id": item.document_id,
    }


@extended_api.put("/patients/{patient_id}/history/{item_id}")
def update_history(
    patient_id: int,
    item_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_history(db, patient_id, item_id)
    if payload.get("occurred_at"):
        item.occurred_at = datetime.fromisoformat(str(payload["occurred_at"]))
    for field in ("category", "title", "description", "hospital", "clinician_name"):
        if field in payload:
            setattr(item, field, payload.get(field) or ("other" if field == "category" else None))
    _audit(db, user.id, patient_id, "history.updated", "history", item.id)
    db.commit()
    return {"ok": True}


@extended_api.delete("/patients/{patient_id}/history/{item_id}")
def delete_history(
    patient_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_history(db, patient_id, item_id)
    db.delete(item)
    _audit(db, user.id, patient_id, "history.deleted", "history", item_id)
    db.commit()
    return {"ok": True}


def _avg(values):
    cleaned = [float(value) for value in values if value is not None]
    return round(mean(cleaned), 2) if cleaned else None


def _min(values):
    cleaned = [float(value) for value in values if value is not None]
    return min(cleaned) if cleaned else None


def _max(values):
    cleaned = [float(value) for value in values if value is not None]
    return max(cleaned) if cleaned else None


def _resolve_report_range(db: Session, patient_id: int, payload: dict) -> tuple[date | None, date | None, Hospitalization | None]:
    start_date = date.fromisoformat(payload["start_date"]) if payload.get("start_date") else None
    end_date = date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None
    hospitalization = None
    if payload.get("hospitalization_id"):
        hospitalization = _get_hospitalization(db, patient_id, int(payload["hospitalization_id"]))
        start_date = hospitalization.admission_at.date()
        end_date = hospitalization.discharge_at.date() if hospitalization.discharge_at else date.today()
    return start_date, end_date, hospitalization


def _report_data(db: Session, patient_id: int, payload: dict) -> dict:
    start_date, end_date, selected_hospitalization = _resolve_report_range(db, patient_id, payload)
    patient = db.get(Patient, patient_id)
    scope = str(payload.get("scope") or "all")
    hospital_filter = (payload.get("hospital") or "").strip().lower()
    medication_filter = (payload.get("medication") or "").strip().lower()

    hospitalizations = db.scalars(select(Hospitalization).where(Hospitalization.patient_id == patient_id).order_by(Hospitalization.admission_at.asc())).all()
    if start_date:
        hospitalizations = [item for item in hospitalizations if (item.discharge_at or item.admission_at) >= _dt_start(start_date)]
    if end_date:
        hospitalizations = [item for item in hospitalizations if item.admission_at <= _dt_end(end_date)]
    if hospital_filter:
        hospitalizations = [item for item in hospitalizations if hospital_filter in (item.hospital or "").lower()]
    if selected_hospitalization:
        hospitalizations = [selected_hospitalization]

    history_clauses = [ClinicalHistoryEvent.patient_id == patient_id, *_range_clauses(ClinicalHistoryEvent.occurred_at, start_date, end_date)]
    history = db.scalars(select(ClinicalHistoryEvent).where(*history_clauses).order_by(ClinicalHistoryEvent.occurred_at.asc())).all()
    if hospital_filter:
        history = [item for item in history if hospital_filter in (item.hospital or "").lower()]

    chemo_clauses = [CareChemoSession.patient_id == patient_id, *_range_clauses(CareChemoSession.scheduled_at, start_date, end_date)]
    chemo = db.scalars(select(CareChemoSession).where(*chemo_clauses).order_by(CareChemoSession.scheduled_at.asc())).all()

    vital_clauses = [CareVitalRecord.patient_id == patient_id, *_range_clauses(CareVitalRecord.recorded_at, start_date, end_date)]
    vitals = db.scalars(select(CareVitalRecord).where(*vital_clauses).order_by(CareVitalRecord.recorded_at.asc())).all()

    crisis_clauses = [CareCrisisEvent.patient_id == patient_id, *_range_clauses(CareCrisisEvent.occurred_at, start_date, end_date)]
    crises = db.scalars(select(CareCrisisEvent).where(*crisis_clauses).order_by(CareCrisisEvent.occurred_at.asc())).all()

    docs = db.scalars(select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id).order_by(ClinicalDocument.event_date.asc().nulls_last(), ClinicalDocument.created_at.asc())).all()
    if start_date:
        docs = [item for item in docs if item.event_date is None or item.event_date >= start_date]
    if end_date:
        docs = [item for item in docs if item.event_date is None or item.event_date <= end_date]
    if hospital_filter:
        docs = [item for item in docs if hospital_filter in (item.hospital or "").lower()]
    if selected_hospitalization:
        docs = [item for item in docs if item.hospitalization_id == selected_hospitalization.id]

    meds = db.scalars(select(CareMedication).where(CareMedication.patient_id == patient_id).order_by(CareMedication.name.asc())).all()
    if medication_filter:
        meds = [item for item in meds if medication_filter in item.name.lower()]

    log_query = (
        select(CareMedicationLog, CareMedicationSchedule, CareMedication)
        .join(CareMedicationSchedule, CareMedicationSchedule.id == CareMedicationLog.schedule_id)
        .join(CareMedication, CareMedication.id == CareMedicationSchedule.medication_id)
        .where(CareMedication.patient_id == patient_id)
        .order_by(CareMedicationLog.log_date.asc(), CareMedicationSchedule.time_of_day.asc())
    )
    logs = db.execute(log_query).all()
    if start_date:
        logs = [row for row in logs if row[0].log_date >= start_date]
    if end_date:
        logs = [row for row in logs if row[0].log_date <= end_date]
    if medication_filter:
        logs = [row for row in logs if medication_filter in row[2].name.lower()]

    if scope == "oncology":
        history = [item for item in history if any(term in (f"{item.category} {item.title} {item.description or ''}").lower() for term in ("onco", "quimio", "tumor", "cancer"))]
    elif scope == "medication" and medication_filter:
        history = [item for item in history if medication_filter in (f"{item.title} {item.description or ''}").lower()]
    elif scope == "hospitalization" and selected_hospitalization:
        start_dt = selected_hospitalization.admission_at
        end_dt = selected_hospitalization.discharge_at or datetime.now()
        history = [item for item in history if start_dt <= item.occurred_at <= end_dt]
        chemo = [item for item in chemo if start_dt <= item.scheduled_at <= end_dt]
        vitals = [item for item in vitals if start_dt <= item.recorded_at <= end_dt]
        crises = [item for item in crises if start_dt <= item.occurred_at <= end_dt]

    taken = sum(1 for log, _, _ in logs if log.status == "taken")
    skipped = sum(1 for log, _, _ in logs if log.status == "skipped")
    statistics = {
        "hospitalizations": len(hospitalizations),
        "chemotherapy_sessions": len(chemo),
        "crises_events": len(crises),
        "documents": len(docs),
        "medications_in_scope": len(meds),
        "medication_taken": taken,
        "medication_skipped": skipped,
        "vitals_count": len(vitals),
        "temperature": {"min": _min([v.temperature_c for v in vitals]), "avg": _avg([v.temperature_c for v in vitals]), "max": _max([v.temperature_c for v in vitals])},
        "heart_rate": {"min": _min([v.heart_rate for v in vitals]), "avg": _avg([v.heart_rate for v in vitals]), "max": _max([v.heart_rate for v in vitals])},
        "oxygen_saturation": {"min": _min([v.oxygen_saturation for v in vitals]), "avg": _avg([v.oxygen_saturation for v in vitals]), "max": _max([v.oxygen_saturation for v in vitals])},
        "systolic": {"min": _min([v.systolic for v in vitals]), "avg": _avg([v.systolic for v in vitals]), "max": _max([v.systolic for v in vitals])},
        "diastolic": {"min": _min([v.diastolic for v in vitals]), "avg": _avg([v.diastolic for v in vitals]), "max": _max([v.diastolic for v in vitals])},
    }

    facts = {
        "patient": {
            "name": patient.name,
            "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
            "primary_hospital": patient.primary_hospital,
            "diagnoses": patient.diagnoses,
            "allergies": patient.allergies,
        },
        "filters": {
            "scope": scope,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "hospital": payload.get("hospital") or None,
            "medication": payload.get("medication") or None,
            "hospitalization_id": selected_hospitalization.id if selected_hospitalization else None,
        },
        "hospitalizations": [
            {"id": h.id, "hospital": h.hospital, "service": h.service, "admission_at": h.admission_at.isoformat(timespec="minutes"), "discharge_at": h.discharge_at.isoformat(timespec="minutes") if h.discharge_at else None, "reason": h.reason, "diagnosis": h.diagnosis, "summary": h.summary}
            for h in hospitalizations
        ],
        "history": [
            {"occurred_at": h.occurred_at.isoformat(timespec="minutes"), "category": h.category, "title": h.title, "description": h.description, "hospital": h.hospital, "clinician_name": h.clinician_name}
            for h in history
        ],
        "chemotherapy": [_chemo_dict(item) for item in chemo],
        "vitals": [_vital_dict(item) for item in vitals],
        "crises": [_crisis_dict(item) for item in crises],
        "medications": [
            {"id": m.id, "name": m.name, "type": m.medication_type, "purpose": m.purpose, "dose": m.dose, "route": m.route, "frequency": m.frequency, "active": m.active}
            for m in meds
        ],
        "medication_logs": [
            {"date": log.log_date.isoformat(), "time": schedule.time_of_day.strftime("%H:%M"), "status": log.status, "actual_time": log.actual_time.isoformat(timespec="minutes") if log.actual_time else None, "medication": med.name}
            for log, schedule, med in logs
        ],
        "documents": [
            {"id": d.id, "event_date": d.event_date.isoformat() if d.event_date else None, "name": d.exam_name or d.filename, "type": d.document_type, "hospital": d.hospital, "extracted_text": (d.extracted_text or "")[:2500]}
            for d in docs
        ],
        "statistics": statistics,
    }
    return facts


def _deterministic_narrative(facts: dict) -> str:
    patient = facts["patient"]
    lines = [f"Resumen cronológico de {patient['name']}."]
    for item in facts["hospitalizations"]:
        end = item["discharge_at"] or "sin alta registrada"
        text = f"Hospitalización en {item['hospital']} desde {item['admission_at']} hasta {end}."
        if item.get("reason"):
            text += f" Motivo registrado: {item['reason']}."
        if item.get("diagnosis"):
            text += f" Diagnóstico registrado: {item['diagnosis']}."
        lines.append(text)
    for item in facts["chemotherapy"]:
        detail = " · ".join(value for value in [item.get("protocol"), item.get("cycle"), item.get("status")] if value)
        lines.append(f"Quimioterapia: {item['name']} el {item['scheduled_at']}{(' (' + detail + ')') if detail else ''}.")
    for item in facts["history"]:
        lines.append(f"{item['occurred_at']}: {item['title']}{(' en ' + item['hospital']) if item.get('hospital') else ''}.")
    if len(lines) == 1:
        lines.append("No hay eventos suficientes en el periodo seleccionado para construir una narrativa cronológica.")
    return "\n".join(lines)


def _ai_narrative(facts: dict) -> tuple[str, bool, str | None]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _deterministic_narrative(facts), False, "OPENAI_API_KEY no configurada"
    model = os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    prompt = (
        "Redacta en español una historia clínica familiar cronológica, clara y sobria usando EXCLUSIVAMENTE los hechos del JSON. "
        "No diagnostiques, no recomiendes tratamientos, no completes información faltante, no cambies dosis, fechas ni nombres. "
        "Si un dato no está en el JSON, omítelo. Describe hospitalizaciones, derivaciones si están registradas, tratamientos, quimioterapia, eventos relevantes y exámenes. "
        "Aclara al final que es una narración generada desde datos registrados en IkerCare y que debe contrastarse con la ficha clínica oficial.\n\n"
        + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "store": False},
            timeout=45.0,
        )
        response.raise_for_status()
        data = response.json()
        chunks: list[str] = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(content["text"])
        text = "\n".join(chunks).strip()
        if not text:
            return _deterministic_narrative(facts), False, "La API no devolvió texto"
        return text, True, None
    except Exception as exc:
        return _deterministic_narrative(facts), False, f"No se pudo generar narrativa IA: {exc.__class__.__name__}"


def _report_preview(db: Session, patient_id: int, payload: dict) -> dict:
    facts = _report_data(db, patient_id, payload)
    use_ai = bool(payload.get("use_ai"))
    if use_ai:
        narrative, ai_used, ai_message = _ai_narrative(facts)
    else:
        narrative, ai_used, ai_message = _deterministic_narrative(facts), False, None
    return {"facts": facts, "statistics": facts["statistics"], "narrative": narrative, "ai_used": ai_used, "ai_message": ai_message}


@extended_api.post("/patients/{patient_id}/reports/preview")
def report_preview(
    patient_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _membership(db, user.id, patient_id)
    return _report_preview(db, patient_id, payload)


def _pdf_bytes(report: dict) -> bytes:
    facts = report["facts"]
    patient = facts["patient"]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    margin = 48
    y = 52

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=595, height=842)
        y = 52

    def line(text: str = "", size: float = 10.5, bold: bool = False, gap: float = 5):
        nonlocal y
        font = "hebo" if bold else "helv"
        safe = str(text or "").replace("•", "-")
        width_chars = 86 if size <= 10.5 else 68
        parts = textwrap.wrap(safe, width=width_chars, break_long_words=False, replace_whitespace=False) or [""]
        needed = len(parts) * (size + 4) + gap
        if y + needed > 790:
            new_page()
        for part in parts:
            page.insert_text((margin, y), part, fontsize=size, fontname=font, color=(0.08, 0.12, 0.2))
            y += size + 4
        y += gap

    line("IkerCare - Informe familiar de salud", 17, True, 8)
    line(f"Paciente: {patient['name']}", 12, True)
    if patient.get("birth_date"):
        line(f"Fecha de nacimiento: {patient['birth_date']}")
    filters = facts["filters"]
    period = "Periodo: " + (filters.get("start_date") or "inicio") + " a " + (filters.get("end_date") or "actualidad")
    line(period)
    line("Este informe se genera desde datos registrados en IkerCare y no reemplaza la ficha clínica oficial.", 9.5, False, 10)

    line("Narrativa", 13, True)
    for paragraph in report["narrative"].splitlines():
        line(paragraph, 10.5)

    line("Resumen estadístico", 13, True)
    stats = report["statistics"]
    for key, label in [
        ("hospitalizations", "Hospitalizaciones"),
        ("chemotherapy_sessions", "Sesiones de quimioterapia"),
        ("crises_events", "Crisis/eventos"),
        ("documents", "Exámenes/documentos"),
        ("medication_taken", "Medicamentos marcados como tomados"),
        ("medication_skipped", "Medicamentos omitidos"),
        ("vitals_count", "Registros de signos vitales"),
    ]:
        line(f"{label}: {stats.get(key, 0)}", 10)
    for key, label in [("temperature", "Temperatura"), ("heart_rate", "Frecuencia cardíaca"), ("oxygen_saturation", "SatO2"), ("systolic", "Presión sistólica"), ("diastolic", "Presión diastólica")]:
        values = stats.get(key) or {}
        if values.get("avg") is not None:
            line(f"{label}: mín {values.get('min')} · promedio {values.get('avg')} · máx {values.get('max')}", 10)

    if facts["hospitalizations"]:
        line("Hospitalizaciones", 13, True)
        for item in facts["hospitalizations"]:
            line(f"{item['hospital']} · {item['admission_at']} - {item['discharge_at'] or 'sin alta registrada'}", 10.5, True, 2)
            if item.get("reason"): line(f"Motivo: {item['reason']}", 10)
            if item.get("diagnosis"): line(f"Diagnóstico: {item['diagnosis']}", 10)
            if item.get("summary"): line(f"Resumen: {item['summary']}", 10)

    if facts["chemotherapy"]:
        line("Quimioterapia", 13, True)
        for item in facts["chemotherapy"]:
            detail = " · ".join(v for v in [item.get("protocol"), item.get("cycle"), item.get("status")] if v)
            line(f"{item['scheduled_at']} · {item['name']}{(' · ' + detail) if detail else ''}", 10)

    if facts["medications"]:
        line("Medicamentos", 13, True)
        for item in facts["medications"]:
            details = " · ".join(v for v in [item.get("dose"), item.get("route"), item.get("frequency")] if v)
            line(f"{item['name']}{(' · ' + details) if details else ''}", 10)

    if facts["history"]:
        line("Hitos registrados", 13, True)
        for item in facts["history"]:
            line(f"{item['occurred_at']} · {item['title']}{(' · ' + item['hospital']) if item.get('hospital') else ''}", 10)
            if item.get("description"): line(item["description"], 9.5)

    if facts["documents"]:
        line("Exámenes e informes", 13, True)
        for item in facts["documents"]:
            line(f"{item.get('event_date') or 'Sin fecha'} · {item['name']}{(' · ' + item['hospital']) if item.get('hospital') else ''}", 10)

    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


@extended_api.get("/patients/{patient_id}/reports/pdf")
def report_pdf(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    scope: str = Query(default="all"),
    start_date: date | None = None,
    end_date: date | None = None,
    hospitalization_id: int | None = None,
    hospital: str | None = None,
    medication: str | None = None,
    use_ai: bool = False,
) -> Response:
    _membership(db, user.id, patient_id)
    payload = {
        "scope": scope,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "hospitalization_id": hospitalization_id,
        "hospital": hospital,
        "medication": medication,
        "use_ai": use_ai,
    }
    report = _report_preview(db, patient_id, payload)
    pdf = _pdf_bytes(report)
    filename = f"IkerCare-informe-{date.today().isoformat()}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})
