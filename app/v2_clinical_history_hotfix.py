from __future__ import annotations

import json
import logging
import os
from datetime import datetime, time
from typing import Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import get_current_user, verify_csrf
from .db import Base, get_db
from .models import User
from .v2_clinical_history import (
    ChemoEvolutionEvent,
    MedicationCatalogCache,
    MedicationState,
    MedicationTreatmentHistory,
    _ensure_initial_snapshot,
    _history_dict,
    _hospital_facts,
    _local_narrative,
    _pdf_bytes,
    _state,
)
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
)
from .v2_router import _audit, _membership, _require_role, now

logger = logging.getLogger("ikercare.clinical_history.hotfix")
history_hotfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare clinical history compatibility"])


class HospitalReportSnapshot(Base):
    __tablename__ = "care_hospital_report_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    facts_json: Mapped[str] = mapped_column(Text)
    narrative: Mapped[str] = mapped_column(Text)
    ai_used: Mapped[str] = mapped_column(String(10), default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class CareHospitalAssociation(Base):
    __tablename__ = "care_hospital_associations"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", name="uq_care_hospital_assoc"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(30), default="automatic")


def _configured_times(db: Session, medication_id: int) -> list[str]:
    latest = db.scalar(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == medication_id)
        .order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc())
    )
    if latest:
        try:
            values = json.loads(latest.times_json or "[]")
            if isinstance(values, list):
                return [str(value) for value in values]
        except Exception:
            pass
    rows = db.scalars(
        select(CareMedicationSchedule)
        .where(CareMedicationSchedule.medication_id == medication_id)
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def _set_schedules(db: Session, medication_id: int, values: list[str], enabled: bool) -> list[str]:
    normalized: list[str] = []
    parsed = []
    for value in values:
        parsed_value = datetime.strptime(str(value).strip(), "%H:%M").time()
        parsed.append(parsed_value)
        normalized.append(parsed_value.strftime("%H:%M"))
    wanted = set(parsed)
    existing = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id)).all()
    by_time = {row.time_of_day: row for row in existing}
    for row in existing:
        row.active = enabled and row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=medication_id, time_of_day=value, active=enabled))
    db.flush()
    return sorted(normalized)


def _add_history(
    db: Session,
    med: CareMedication,
    occurred_at: datetime,
    event_type: str,
    status: str,
    times: list[str],
    user_id: int,
    reason: str | None = None,
    changed_fields: list[str] | None = None,
) -> MedicationTreatmentHistory:
    row = MedicationTreatmentHistory(
        medication_id=med.id,
        occurred_at=occurred_at,
        event_type=event_type,
        status=status,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        times_json=json.dumps(times, ensure_ascii=False),
        reason=reason,
        changed_fields_json=json.dumps(changed_fields or [], ensure_ascii=False),
        created_by_user_id=user_id,
    )
    db.add(row)
    return row


@history_hotfix_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def treatment_history_compat(patient_id: int, medication_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    _ensure_initial_snapshot(db, med, user.id)
    db.commit()
    rows = db.scalars(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == med.id)
        .order_by(MedicationTreatmentHistory.occurred_at.asc(), MedicationTreatmentHistory.id.asc())
    ).all()
    return [_history_dict(row) for row in rows]


@history_hotfix_api.put("/patients/{patient_id}/medications/{medication_id}/history-update")
def update_treatment_history_safe(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    _ensure_initial_snapshot(db, med, user.id)
    state = _state(db, med)
    current = db.scalar(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == med.id)
        .order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc())
    )
    effective_at = datetime.fromisoformat(str(payload["effective_at"])) if payload.get("effective_at") else now()
    if current and effective_at < current.occurred_at:
        raise HTTPException(status_code=400, detail="La fecha del cambio no puede ser anterior al último cambio registrado.")

    old_times = _configured_times(db, med.id)
    before = {"dose": med.dose, "route": med.route, "frequency": med.frequency, "times": old_times}
    for field in ("name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"):
        if field in payload:
            setattr(med, field, payload.get(field))
    requested_times = [str(value) for value in payload.get("times", old_times)]
    enabled = state.status in {"active", "resumed"}
    final_times = _set_schedules(db, med.id, requested_times, enabled)
    after = {"dose": med.dose, "route": med.route, "frequency": med.frequency, "times": final_times}
    changed = [field for field in ("dose", "route", "frequency", "times") if before[field] != after[field]]
    if "unit" in payload:
        state.unit = str(payload.get("unit") or "").strip() or None
    if changed:
        _add_history(db, med, effective_at, "treatment_change", state.status, final_times, user.id, changed_fields=changed)
    med.updated_at = effective_at
    _audit(db, user.id, patient_id, "medication.history_updated", "medication", med.id, {"changed": changed})
    db.commit()
    return {"ok": True, "changed_fields": changed}


@history_hotfix_api.post("/patients/{patient_id}/medications/{medication_id}/status")
def change_medication_status_safe(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    status = str(payload.get("status") or "").strip().lower()
    allowed = {"active", "suspended", "finished", "paused", "resumed"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Estado de medicamento inválido.")
    _ensure_initial_snapshot(db, med, user.id)
    previous_times = _configured_times(db, med.id)
    occurred_at = datetime.fromisoformat(str(payload["occurred_at"])) if payload.get("occurred_at") else now()
    latest = db.scalar(select(MedicationTreatmentHistory).where(MedicationTreatmentHistory.medication_id == med.id).order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc()))
    if latest and occurred_at < latest.occurred_at:
        raise HTTPException(status_code=400, detail="La fecha del estado no puede ser anterior al último cambio registrado.")
    reason = str(payload.get("reason") or "").strip() or None
    state = _state(db, med)
    state.status = status
    state.reason = reason
    state.changed_at = occurred_at
    med.active = status in {"active", "resumed"}
    _set_schedules(db, med.id, previous_times, med.active)
    event_type = {"suspended": "suspension", "finished": "finished", "paused": "pause", "resumed": "resumption", "active": "status_change"}[status]
    _add_history(db, med, occurred_at, event_type, status, previous_times, user.id, reason=reason)
    med.updated_at = occurred_at
    _audit(db, user.id, patient_id, f"medication.status.{status}", "medication", med.id, {"reason": reason})
    db.commit()
    return {"ok": True, "status": status}


@history_hotfix_api.put("/patients/{patient_id}/chemo/{chemo_id}/events/{event_id}")
def update_chemo_evolution_event(
    patient_id: int,
    chemo_id: int,
    event_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    row = db.scalar(
        select(ChemoEvolutionEvent)
        .join(CareChemoSession, CareChemoSession.id == ChemoEvolutionEvent.chemo_session_id)
        .where(
            ChemoEvolutionEvent.id == event_id,
            ChemoEvolutionEvent.chemo_session_id == chemo_id,
            CareChemoSession.patient_id == patient_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    if payload.get("occurred_at"):
        row.occurred_at = datetime.fromisoformat(str(payload["occurred_at"]))
    if "event_type" in payload:
        row.event_type = str(payload.get("event_type") or "Otro")[:100]
    if "description" in payload:
        row.description = str(payload.get("description") or "").strip() or None
    _audit(db, user.id, patient_id, "chemo.evolution.updated", "chemo_event", row.id)
    db.commit()
    return {"ok": True}


def _ai_hospital_summary(facts: dict) -> tuple[str, bool, str | None]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _local_narrative(facts), False, "OpenAI no está configurado; se usó resumen local."
    model = os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    prompt = (
        "Redacta en español un resumen de evolución cronológico, claro y sobrio usando EXCLUSIVAMENTE los hechos del JSON. "
        "No inventes información, no diagnostiques, no recomiendes tratamientos, no cambies dosis, fechas, horarios, hospitales ni nombres. "
        "Resume los cambios de medicamentos, suspensiones/reanudaciones, quimioterapia y sus eventos, exámenes, signos vitales, eventos clínicos, alimentación y eliminación cuando estén registrados. "
        "Si un dato no existe, omítelo. Termina indicando que el texto se basa en registros de IkerCare y debe contrastarse con la ficha clínica oficial.\nJSON:\n"
        + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt, "store": False},
            timeout=30.0,
        )
        response.raise_for_status()
        chunks: list[str] = []
        for item in response.json().get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(content["text"])
        text_value = "\n".join(chunks).strip()
        if text_value:
            return text_value, True, None
    except Exception:
        logger.exception("Hospitalization narrative generation failed")
    return _local_narrative(facts), False, "No fue posible usar IA; se usó resumen local."


def _associate(db: Session, patient_id: int, hospitalization_id: int, entity_type: str, entity_id: int) -> None:
    existing = db.scalar(select(CareHospitalAssociation.id).where(CareHospitalAssociation.entity_type == entity_type, CareHospitalAssociation.entity_id == entity_id).limit(1))
    if not existing:
        db.add(CareHospitalAssociation(patient_id=patient_id, hospitalization_id=hospitalization_id, entity_type=entity_type, entity_id=entity_id, source="automatic"))


def _associate_hospital_records(db: Session, patient_id: int, hospitalization_id: int) -> None:
    stay = db.scalar(select(Hospitalization).where(Hospitalization.id == hospitalization_id, Hospitalization.patient_id == patient_id))
    if not stay:
        return
    start, end = stay.admission_at, stay.discharge_at or now()
    start_date, end_date = start.date(), end.date()
    dated_models = [
        ("vital", CareVitalRecord, CareVitalRecord.recorded_at),
        ("crisis", CareCrisisEvent, CareCrisisEvent.occurred_at),
        ("chemo", CareChemoSession, CareChemoSession.scheduled_at),
        ("food", FoodLog, FoodLog.occurred_at),
        ("elimination", EliminationLog, EliminationLog.occurred_at),
        ("history", ClinicalHistoryEvent, ClinicalHistoryEvent.occurred_at),
    ]
    for entity_type, model, column in dated_models:
        rows = db.scalars(select(model).where(model.patient_id == patient_id, column >= start, column <= end)).all()
        for row in rows:
            _associate(db, patient_id, hospitalization_id, entity_type, row.id)
    docs = db.scalars(select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id)).all()
    for row in docs:
        if row.hospitalization_id == hospitalization_id or (row.event_date and start_date <= row.event_date <= end_date):
            _associate(db, patient_id, hospitalization_id, "document", row.id)
            if row.hospitalization_id is None:
                row.hospitalization_id = hospitalization_id
    notes = db.scalars(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date >= start_date, CareDailyNote.note_date <= end_date)).all()
    for row in notes:
        _associate(db, patient_id, hospitalization_id, "daily_note", row.id)
    med_ids = db.scalars(select(CareMedication.id).where(CareMedication.patient_id == patient_id)).all()
    if med_ids:
        schedules = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id.in_(med_ids))).all()
        schedule_ids = [row.id for row in schedules]
        if schedule_ids:
            logs = db.scalars(select(CareMedicationLog).where(CareMedicationLog.schedule_id.in_(schedule_ids), CareMedicationLog.log_date >= start_date, CareMedicationLog.log_date <= end_date)).all()
            for row in logs:
                _associate(db, patient_id, hospitalization_id, "medication_log", row.id)
        history_rows = db.scalars(select(MedicationTreatmentHistory).where(MedicationTreatmentHistory.medication_id.in_(med_ids), MedicationTreatmentHistory.occurred_at >= start, MedicationTreatmentHistory.occurred_at <= end)).all()
        for row in history_rows:
            _associate(db, patient_id, hospitalization_id, "medication_history", row.id)
    chemo_ids = db.scalars(select(CareChemoSession.id).where(CareChemoSession.patient_id == patient_id, CareChemoSession.scheduled_at >= start, CareChemoSession.scheduled_at <= end)).all()
    if chemo_ids:
        evolution = db.scalars(select(ChemoEvolutionEvent).where(ChemoEvolutionEvent.chemo_session_id.in_(chemo_ids), ChemoEvolutionEvent.occurred_at >= start, ChemoEvolutionEvent.occurred_at <= end)).all()
        for row in evolution:
            _associate(db, patient_id, hospitalization_id, "chemo_event", row.id)


@history_hotfix_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report")
def hospitalization_report(
    patient_id: int,
    hospitalization_id: int,
    use_ai: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _membership(db, user.id, patient_id)
    facts = _hospital_facts(db, patient_id, hospitalization_id)
    _associate_hospital_records(db, patient_id, hospitalization_id)
    narrative, ai_used, ai_message = _ai_hospital_summary(facts) if use_ai else (_local_narrative(facts), False, None)
    snapshot = HospitalReportSnapshot(
        patient_id=patient_id,
        hospitalization_id=hospitalization_id,
        user_id=user.id,
        facts_json=json.dumps(facts, ensure_ascii=False),
        narrative=narrative,
        ai_used="true" if ai_used else "false",
    )
    db.add(snapshot)
    db.commit()
    return {"facts": facts, "statistics": facts["statistics"], "narrative": narrative, "ai_used": ai_used, "ai_message": ai_message}


@history_hotfix_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report.pdf")
def hospitalization_report_pdf(
    patient_id: int,
    hospitalization_id: int,
    use_ai: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _membership(db, user.id, patient_id)
    try:
        snapshot = db.scalar(
            select(HospitalReportSnapshot)
            .where(
                HospitalReportSnapshot.patient_id == patient_id,
                HospitalReportSnapshot.hospitalization_id == hospitalization_id,
                HospitalReportSnapshot.user_id == user.id,
            )
            .order_by(HospitalReportSnapshot.created_at.desc(), HospitalReportSnapshot.id.desc())
        )
        if snapshot:
            facts = json.loads(snapshot.facts_json)
            narrative = snapshot.narrative
        else:
            facts = _hospital_facts(db, patient_id, hospitalization_id)
            narrative = _local_narrative(facts)
        # El endpoint PDF nunca espera una segunda llamada a OpenAI: evita timeouts en Render.
        pdf = _pdf_bytes({"facts": facts, "narrative": narrative})
        filename = f"IkerCare-hospitalizacion-{hospitalization_id}.pdf"
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(pdf)),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hospitalization PDF failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No fue posible generar el PDF. Inténtalo nuevamente.") from exc


@history_hotfix_api.post("/medications/ai-enrich")
def medication_ai_enrich_safe(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 180:
        raise HTTPException(status_code=400, detail="Escribe un nombre de medicamento válido.")
    normalized = " ".join(name.lower().split())
    cached = db.scalar(select(MedicationCatalogCache).where(MedicationCatalogCache.normalized_name == normalized))
    if cached:
        return {"name": cached.display_name, "medication_type": cached.medication_type, "purpose": cached.purpose, "usual_route": cached.usual_route, "usual_unit": cached.usual_unit, "source": cached.source}
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="La ayuda de IA para medicamentos no está configurada.")
    schema = {
        "type": "object",
        "properties": {
            "recognized": {"type": "boolean"},
            "medication_type": {"type": ["string", "null"]},
            "purpose": {"type": ["string", "null"]},
            "usual_route": {"type": ["string", "null"]},
            "usual_unit": {"type": ["string", "null"]},
        },
        "required": ["recognized", "medication_type", "purpose", "usual_route", "usual_unit"],
        "additionalProperties": False,
    }
    prompt = (
        f"Medicamento escrito por el usuario: {name}. Devuelve únicamente información descriptiva general para ayudar a completar un registro familiar: categoría farmacológica, uso general, vía habitual solo si es inequívoca y unidad habitual solo si es inequívoca. "
        "No recomiendes ni calcules dosis, frecuencia, horarios ni cambios de tratamiento. Si no lo reconoces con suficiente confianza, recognized=false."
    )
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.getenv("OPENAI_MEDICATION_MODEL", os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini")),
                "input": prompt,
                "store": False,
                "text": {"format": {"type": "json_schema", "name": "medication_catalog", "schema": schema, "strict": True}},
            },
            timeout=25.0,
        )
        response.raise_for_status()
        chunks: list[str] = []
        for item in response.json().get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(content["text"])
        parsed = json.loads("".join(chunks))
        if not parsed.get("recognized"):
            raise HTTPException(status_code=404, detail="No pude identificar ese medicamento con suficiente seguridad.")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Medication enrichment failed name=%s", name)
        raise HTTPException(status_code=502, detail="No fue posible completar la información del medicamento en este momento.") from exc
    row = MedicationCatalogCache(
        normalized_name=normalized,
        display_name=name,
        medication_type=parsed.get("medication_type"),
        purpose=parsed.get("purpose"),
        usual_route=parsed.get("usual_route"),
        usual_unit=parsed.get("usual_unit"),
        source="ai",
    )
    db.add(row)
    db.commit()
    return {"name": row.display_name, "medication_type": row.medication_type, "purpose": row.purpose, "usual_route": row.usual_route, "usual_unit": row.usual_unit, "source": "ai"}
