from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .v2_models import CareMedication, CareMedicationSchedule, Hospitalization
from .v2_treatment_models import CareHospitalizationLink, CareMedicationExtra, CareMedicationRevision

MED_STATUSES = {"active", "suspended", "finished", "paused", "resumed"}
MEAL_TYPES = ["Desayuno", "Colación", "Almuerzo", "Once/Merienda", "Cena", "Alimentación nocturna", "Lactancia/Leche", "Líquidos", "Otro"]
INTAKE_LEVELS = ["Todo", "Más de la mitad", "La mitad", "Menos de la mitad", "Muy poco", "Nada"]
CHEMO_EVENT_TYPES = ["Náuseas", "Vómitos", "Fiebre", "Dolor", "Somnolencia", "Irritabilidad", "Falta de apetito", "Diarrea", "Estreñimiento", "Convulsión", "Cambios de presión", "Cambios de saturación", "Otro"]


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def hospitalization_at(db: Session, patient_id: int, occurred_at: datetime) -> Hospitalization | None:
    return db.scalar(
        select(Hospitalization)
        .where(
            Hospitalization.patient_id == patient_id,
            Hospitalization.admission_at <= occurred_at,
            or_(Hospitalization.discharge_at.is_(None), Hospitalization.discharge_at >= occurred_at),
        )
        .order_by(Hospitalization.admission_at.desc())
        .limit(1)
    )


def validate_hospitalization(db: Session, patient_id: int, hospitalization_id: int | None, occurred_at: datetime | None = None) -> Hospitalization | None:
    if hospitalization_id:
        item = db.scalar(select(Hospitalization).where(Hospitalization.id == hospitalization_id, Hospitalization.patient_id == patient_id))
        if not item:
            raise HTTPException(status_code=400, detail="Hospitalización inválida.")
        return item
    return hospitalization_at(db, patient_id, occurred_at) if occurred_at else None


def link_entity(db: Session, patient_id: int, entity_type: str, entity_id: int, occurred_at: datetime, hospitalization_id: int | None = None) -> int | None:
    hospitalization = validate_hospitalization(db, patient_id, hospitalization_id, occurred_at)
    existing = db.scalar(select(CareHospitalizationLink).where(CareHospitalizationLink.entity_type == entity_type, CareHospitalizationLink.entity_id == entity_id))
    if not hospitalization:
        if existing:
            db.delete(existing)
        return None
    if existing:
        existing.patient_id = patient_id
        existing.hospitalization_id = hospitalization.id
    else:
        db.add(CareHospitalizationLink(patient_id=patient_id, hospitalization_id=hospitalization.id, entity_type=entity_type, entity_id=entity_id))
    return hospitalization.id


def med_times(db: Session, medication_id: int) -> list[str]:
    rows = db.scalars(
        select(CareMedicationSchedule)
        .where(CareMedicationSchedule.medication_id == medication_id, CareMedicationSchedule.active.is_(True))
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def latest_revision(db: Session, medication_id: int) -> CareMedicationRevision | None:
    return db.scalar(
        select(CareMedicationRevision)
        .where(CareMedicationRevision.medication_id == medication_id)
        .order_by(CareMedicationRevision.effective_at.desc(), CareMedicationRevision.id.desc())
        .limit(1)
    )


def ensure_med_baseline(db: Session, med: CareMedication, user_id: int | None = None) -> CareMedicationRevision:
    latest = latest_revision(db, med.id)
    if latest:
        return latest
    effective_at = med.created_at or datetime.utcnow()
    hospitalization = hospitalization_at(db, med.patient_id, effective_at)
    revision = CareMedicationRevision(
        medication_id=med.id,
        patient_id=med.patient_id,
        hospitalization_id=hospitalization.id if hospitalization else None,
        effective_at=effective_at,
        event_type="baseline",
        status="active" if med.active else "suspended",
        name=med.name,
        medication_type=med.medication_type,
        purpose=med.purpose,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        instructions=med.instructions,
        times_json=med_times(db, med.id),
        changed_fields_json=["baseline"],
        created_by_user_id=user_id or med.created_by_user_id,
    )
    db.add(revision)
    db.flush()
    return revision


def med_extra(db: Session, medication_id: int) -> CareMedicationExtra | None:
    return db.get(CareMedicationExtra, medication_id)


def serialize_med(db: Session, med: CareMedication) -> dict:
    latest = ensure_med_baseline(db, med)
    extra = med_extra(db, med.id)
    return {
        "id": med.id,
        "patient_id": med.patient_id,
        "name": med.name,
        "generic_name": med.generic_name,
        "medication_type": med.medication_type,
        "purpose": med.purpose,
        "dose": med.dose,
        "route": med.route,
        "frequency": med.frequency,
        "instructions": med.instructions,
        "active": med.active,
        "source": med.source,
        "times": med_times(db, med.id),
        "status": latest.status,
        "status_reason": latest.status_reason,
        "status_at": latest.effective_at.isoformat(timespec="minutes"),
        "unit": extra.unit if extra else None,
    }


def set_med_schedules(db: Session, med: CareMedication, times: list[str]) -> None:
    parsed = set()
    for value in times:
        try:
            parsed.add(datetime.strptime(value, "%H:%M").time())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Horario inválido: {value}") from exc
    existing = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all()
    by_time = {row.time_of_day: row for row in existing}
    for row in existing:
        row.active = row.time_of_day in parsed
    for value in parsed:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=value, active=True))


def record_revision(db: Session, med: CareMedication, user_id: int, *, status: str, reason: str | None, event_type: str, changed_fields: list[str], effective_at: datetime, hospitalization_id: int | None, unit: str | None) -> CareMedicationRevision:
    hospitalization = validate_hospitalization(db, med.patient_id, hospitalization_id, effective_at)
    revision = CareMedicationRevision(
        medication_id=med.id,
        patient_id=med.patient_id,
        hospitalization_id=hospitalization.id if hospitalization else None,
        effective_at=effective_at,
        event_type=event_type,
        status=status,
        status_reason=reason or None,
        name=med.name,
        medication_type=med.medication_type,
        purpose=med.purpose,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        instructions=med.instructions,
        times_json=med_times(db, med.id),
        changed_fields_json=changed_fields,
        created_by_user_id=user_id,
    )
    db.add(revision)
    if unit is not None:
        extra = db.get(CareMedicationExtra, med.id)
        if not extra:
            extra = CareMedicationExtra(medication_id=med.id)
            db.add(extra)
        extra.unit = unit or None
        extra.updated_at = datetime.utcnow()
    return revision
