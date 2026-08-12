from __future__ import annotations

import json
import logging
import os
import textwrap
from collections import defaultdict
from datetime import datetime, time
from statistics import mean

import fitz
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .document_processing import safe_filename
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
    EliminationLog,
    FoodLog,
    Hospitalization,
    Patient,
)
from .v2_router import _membership, now
from .v2_treatment_helpers import link_entity
from .v2_treatment_models import CareChemoFollowupEvent, CareFoodDetail, CareMedicationRevision

logger = logging.getLogger("ikercare.reports")
hospital_report_api = APIRouter(prefix="/api/v2", tags=["IkerCare hospitalization reports"])


def _avg(values):
    clean = [float(value) for value in values if value is not None]
    return round(mean(clean), 2) if clean else None


def _facts(db: Session, patient_id: int, hospitalization_id: int) -> dict:
    hospitalization = db.scalar(select(Hospitalization).where(Hospitalization.id == hospitalization_id, Hospitalization.patient_id == patient_id))
    if not hospitalization:
        raise HTTPException(status_code=404, detail="Hospitalización no encontrada.")
    start = hospitalization.admission_at
    end = hospitalization.discharge_at or now()
    patient = db.get(Patient, patient_id)

    vitals = db.scalars(select(CareVitalRecord).where(CareVitalRecord.patient_id == patient_id, CareVitalRecord.recorded_at.between(start, end)).order_by(CareVitalRecord.recorded_at)).all()
    crises = db.scalars(select(CareCrisisEvent).where(CareCrisisEvent.patient_id == patient_id, CareCrisisEvent.occurred_at.between(start, end)).order_by(CareCrisisEvent.occurred_at)).all()
    chemo = db.scalars(select(CareChemoSession).where(CareChemoSession.patient_id == patient_id, CareChemoSession.scheduled_at.between(start, end)).order_by(CareChemoSession.scheduled_at)).all()
    food = db.scalars(select(FoodLog).where(FoodLog.patient_id == patient_id, FoodLog.occurred_at.between(start, end)).order_by(FoodLog.occurred_at)).all()
    elimination = db.scalars(select(EliminationLog).where(EliminationLog.patient_id == patient_id, EliminationLog.occurred_at.between(start, end)).order_by(EliminationLog.occurred_at)).all()
    notes = db.scalars(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date >= start.date(), CareDailyNote.note_date <= end.date()).order_by(CareDailyNote.note_date)).all()
    history = db.scalars(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.patient_id == patient_id, ClinicalHistoryEvent.occurred_at.between(start, end)).order_by(ClinicalHistoryEvent.occurred_at)).all()
    documents = db.scalars(
        select(ClinicalDocument).where(
            ClinicalDocument.patient_id == patient_id,
            or_(
                ClinicalDocument.hospitalization_id == hospitalization_id,
                and_(ClinicalDocument.event_date.is_not(None), ClinicalDocument.event_date >= start.date(), ClinicalDocument.event_date <= end.date()),
            ),
        ).order_by(ClinicalDocument.event_date, ClinicalDocument.created_at)
    ).all()
    revisions = db.scalars(select(CareMedicationRevision).where(CareMedicationRevision.patient_id == patient_id, CareMedicationRevision.effective_at.between(start, end)).order_by(CareMedicationRevision.effective_at)).all()
    medication_logs = db.execute(
        select(CareMedicationLog, CareMedicationSchedule, CareMedication)
        .join(CareMedicationSchedule, CareMedicationSchedule.id == CareMedicationLog.schedule_id)
        .join(CareMedication, CareMedication.id == CareMedicationSchedule.medication_id)
        .where(CareMedication.patient_id == patient_id, CareMedicationLog.log_date >= start.date(), CareMedicationLog.log_date <= end.date())
        .order_by(CareMedicationLog.log_date, CareMedicationSchedule.time_of_day)
    ).all()
    chemo_ids = [item.id for item in chemo]
    chemo_events = db.scalars(select(CareChemoFollowupEvent).where(CareChemoFollowupEvent.chemo_session_id.in_(chemo_ids) if chemo_ids else False).order_by(CareChemoFollowupEvent.occurred_at)).all()
    food_details = {item.food_log_id: item for item in db.scalars(select(CareFoodDetail).where(CareFoodDetail.food_log_id.in_([row.id for row in food]) if food else False)).all()}

    for kind, rows, attr in [("vital", vitals, "recorded_at"), ("crisis", crises, "occurred_at"), ("chemo", chemo, "scheduled_at"), ("food", food, "occurred_at"), ("elimination", elimination, "occurred_at")]:
        for row in rows:
            link_entity(db, patient_id, kind, row.id, getattr(row, attr), hospitalization_id)

    days: dict[str, list[dict]] = defaultdict(list)

    def add(occurred_at: datetime, category: str, title: str, detail: str | None = None, **extra):
        days[occurred_at.date().isoformat()].append({"at": occurred_at.isoformat(timespec="minutes"), "category": category, "title": title, "detail": detail, **extra})

    for log, schedule, medication in medication_logs:
        occurred_at = log.actual_time or datetime.combine(log.log_date, schedule.time_of_day)
        revision = db.scalar(
            select(CareMedicationRevision)
            .where(CareMedicationRevision.medication_id == medication.id, CareMedicationRevision.effective_at <= occurred_at)
            .order_by(CareMedicationRevision.effective_at.desc(), CareMedicationRevision.id.desc())
            .limit(1)
        )
        dose = revision.dose if revision else medication.dose
        add(occurred_at, "medications", f"{medication.name}{(' ' + dose) if dose else ''}", f"{log.status} · horario {schedule.time_of_day.strftime('%H:%M')}")

    for revision in revisions:
        detail = f"{revision.event_type}: dosis {revision.dose or '—'}, vía {revision.route or '—'}, frecuencia {revision.frequency or '—'}, horarios {', '.join(revision.times_json or []) or '—'}, estado {revision.status}"
        if revision.status_reason:
            detail += f". Motivo: {revision.status_reason}"
        add(revision.effective_at, "treatment_changes", revision.name, detail)

    for item in chemo:
        add(item.scheduled_at, "chemotherapy", item.name, " · ".join(value for value in [item.protocol, item.cycle, item.status, item.notes] if value))
    for item in chemo_events:
        add(item.occurred_at, "chemo_events", item.event_type, item.description)
    for item in vitals:
        values = [
            f"T {item.temperature_c} °C" if item.temperature_c is not None else None,
            f"PA {item.systolic}/{item.diastolic}" if item.systolic and item.diastolic else None,
            f"FC {item.heart_rate}" if item.heart_rate else None,
            f"SatO2 {item.oxygen_saturation}%" if item.oxygen_saturation is not None else None,
            f"FR {item.respiratory_rate}" if item.respiratory_rate else None,
            f"Peso {item.weight_kg} kg" if item.weight_kg is not None else None,
            item.notes,
        ]
        add(item.recorded_at, "vitals", "Signos vitales", " · ".join(value for value in values if value))
    for item in crises:
        add(item.occurred_at, "events", item.event_type, item.description)
    for item in food:
        detail = food_details.get(item.id)
        quantity = " ".join(value for value in [str(item.amount) if item.amount is not None else None, item.unit] if value)
        add(item.occurred_at, "food", f"{item.meal_type or 'Otro'} · {item.item}", " · ".join(value for value in [quantity or None, detail.intake_level if detail else None, item.notes] if value))
    for item in elimination:
        title = {"dry": "Pañal seco", "wet": "Pipí", "soiled": "Deposición", "wet_and_soiled": "Pipí + deposición"}.get(item.diaper_status, item.diaper_status)
        add(item.occurred_at, "elimination", title, " · ".join(value for value in [item.urine_amount, item.urine_color, item.stool_description, item.notes] if value))
    for item in notes:
        add(datetime.combine(item.note_date, time(23, 59)), "notes", "Nota del día", item.text)
    for item in history:
        add(item.occurred_at, "history", item.title, item.description, hospital=item.hospital)
    for item in documents:
        occurred_at = datetime.combine(item.event_date, time.min) if item.event_date else item.created_at
        add(occurred_at, "exams", item.exam_name or item.filename, (item.extracted_text or "")[:1200], document_id=item.id)

    for day in days:
        days[day].sort(key=lambda row: row["at"])

    return {
        "patient": {"name": patient.name, "birth_date": patient.birth_date.isoformat() if patient.birth_date else None},
        "hospitalization": {
            "id": hospitalization.id,
            "hospital": hospitalization.hospital,
            "service": hospitalization.service,
            "admission_at": hospitalization.admission_at.isoformat(timespec="minutes"),
            "discharge_at": hospitalization.discharge_at.isoformat(timespec="minutes") if hospitalization.discharge_at else None,
            "reason": hospitalization.reason,
            "diagnosis": hospitalization.diagnosis,
            "summary": hospitalization.summary,
        },
        "days": dict(sorted(days.items())),
        "statistics": {
            "medication_logs": len(medication_logs),
            "medication_changes": len(revisions),
            "chemotherapy": len(chemo),
            "chemo_events": len(chemo_events),
            "vitals": len(vitals),
            "events": len(crises),
            "food": len(food),
            "elimination": len(elimination),
            "exams": len(documents),
            "temperature_avg": _avg([row.temperature_c for row in vitals]),
            "heart_rate_avg": _avg([row.heart_rate for row in vitals]),
            "oxygen_avg": _avg([row.oxygen_saturation for row in vitals]),
        },
    }


def _local_narrative(facts: dict) -> str:
    hospitalization = facts["hospitalization"]
    text = f"{facts['patient']['name']} registra una hospitalización en {hospitalization['hospital']} desde {hospitalization['admission_at']}"
    text += f" hasta {hospitalization['discharge_at']}." if hospitalization.get("discharge_at") else ", sin alta registrada en IkerCare."
    if hospitalization.get("reason"):
        text += f" Motivo registrado: {hospitalization['reason']}."
    if hospitalization.get("diagnosis"):
        text += f" Diagnóstico registrado: {hospitalization['diagnosis']}."
    stats = facts["statistics"]
    text += f" Durante el periodo hay {stats['medication_logs']} registros de administración de medicamentos, {stats['medication_changes']} cambios de tratamiento, {stats['chemotherapy']} registros de quimioterapia, {stats['events']} eventos clínicos y {stats['exams']} exámenes/informes registrados."
    return text


def _narrative(facts: dict, use_ai: bool) -> tuple[str, bool, str | None]:
    if not use_ai:
        return _local_narrative(facts), False, None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _local_narrative(facts), False, "OpenAI no configurado; se usó resumen local."
    prompt = (
        "Redacta un resumen de evolución clínica familiar en español usando EXCLUSIVAMENTE el JSON entregado. "
        "No inventes información, no diagnostiques, no recomiendes tratamientos, no infieras dosis ni causalidad. "
        "Resume hospitalización, cambios de tratamiento, quimioterapia, eventos, signos vitales, alimentación y exámenes relevantes. "
        "Finaliza indicando que el texto se genera desde registros de IkerCare y debe contrastarse con la ficha clínica oficial. JSON:\n"
        + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini"), "input": prompt, "store": False},
            timeout=25.0,
        )
        response.raise_for_status()
        parts = []
        for output in response.json().get("output", []):
            for content in output.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
        result = "\n".join(parts).strip()
        if result:
            return result, True, None
    except Exception:
        logger.exception("AI hospitalization narrative failed")
    return _local_narrative(facts), False, "No fue posible usar IA; se generó un resumen local."


@hospital_report_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/full-report")
def full_report(patient_id: int, hospitalization_id: int, use_ai: bool = True, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    facts = _facts(db, patient_id, hospitalization_id)
    narrative, ai_used, message = _narrative(facts, use_ai)
    db.commit()
    return {"facts": facts, "narrative": narrative, "ai_used": ai_used, "message": message}


def _make_pdf(report: dict) -> bytes:
    facts = report["facts"]
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y, margin = 50, 45

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=595, height=842)
        y = 50

    def line(value: str = "", size: float = 10, bold: bool = False, gap: float = 4):
        nonlocal y
        safe = str(value or "").replace("•", "-")
        chunks = textwrap.wrap(safe, width=82 if size <= 10 else 68, break_long_words=False) or [""]
        if y + len(chunks) * (size + 4) + gap > 790:
            new_page()
        for chunk in chunks:
            page.insert_text((margin, y), chunk, fontsize=size, fontname="hebo" if bold else "helv", color=(0.08, 0.12, 0.2))
            y += size + 4
        y += gap

    hospitalization = facts["hospitalization"]
    line("IkerCare - Informe por hospitalización", 17, True, 8)
    line(f"Paciente: {facts['patient']['name']}", 12, True)
    line(f"Hospital: {hospitalization['hospital']}")
    line(f"Periodo: {hospitalization['admission_at']} - {hospitalization.get('discharge_at') or 'sin alta registrada'}")
    line("Registro familiar: no reemplaza la ficha clínica oficial.", 9, False, 10)
    line("Resumen de evolución", 13, True)
    line(report["narrative"], 10, False, 10)

    labels = {
        "medications": "Medicamentos",
        "treatment_changes": "Cambios de tratamiento",
        "chemotherapy": "Quimioterapia",
        "chemo_events": "Evolución post quimioterapia",
        "events": "Eventos clínicos",
        "vitals": "Signos vitales",
        "food": "Alimentación",
        "elimination": "Pañal / orina / deposiciones",
        "exams": "Exámenes",
        "history": "Hitos",
        "notes": "Observaciones",
    }
    order = list(labels)
    line("Historial día por día", 13, True)
    for day, items in facts["days"].items():
        line(day, 12, True, 5)
        groups = defaultdict(list)
        for item in items:
            groups[item["category"]].append(item)
        for category in order:
            if not groups.get(category):
                continue
            line(labels[category], 10.5, True, 2)
            for item in groups[category]:
                line(f"{item['at'][11:16]} - {item['title']}", 9.5, True, 1)
                if item.get("detail"):
                    line(item["detail"], 9, False, 2)

    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


@hospital_report_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/full-report.pdf")
def full_report_pdf(patient_id: int, hospitalization_id: int, use_ai: bool = True, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    _membership(db, user.id, patient_id)
    try:
        facts = _facts(db, patient_id, hospitalization_id)
        narrative, ai_used, message = _narrative(facts, use_ai)
        pdf = _make_pdf({"facts": facts, "narrative": narrative, "ai_used": ai_used, "message": message})
        db.commit()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Hospitalization PDF generation failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No se pudo generar el PDF. Inténtalo nuevamente.")
    filename = f"IkerCare-{safe_filename(facts['patient']['name'])}-hospitalizacion-{hospitalization_id}.pdf"
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(pdf)),
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })
