from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_models import (
    CareChemoSession,
    CareCrisisEvent,
    CareDailyNote,
    CareMedication,
    CareMedicationSchedule,
    CareVitalRecord,
    EliminationLog,
    FoodLog,
)
from .v2_router import _audit, _require_role, now
from .v2_schemas import EliminationCreate, FoodCreate

bugfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 fixes"])


def _owned_record(db: Session, model, patient_id: int, item_id: int, label: str):
    item = db.scalar(select(model).where(model.id == item_id, model.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail=f"{label} no encontrado.")
    return item


def _parse_datetime(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


@bugfix_api.delete("/patients/{patient_id}/medications/{medication_id}")
def delete_care_medication(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    """Quita un medicamento del esquema activo sin borrar su historial clínico."""
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    med.active = False
    med.updated_at = now()
    for schedule in db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all():
        schedule.active = False
    _audit(db, user.id, patient_id, "medication.deleted", "medication", med.id, {"name": med.name, "history_preserved": True})
    db.commit()
    return {"ok": True, "history_preserved": True}


@bugfix_api.get("/patients/{patient_id}/elimination/{item_id}")
def get_elimination_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, EliminationLog, patient_id, item_id, "Registro")
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "diaper_status": item.diaper_status, "urine_amount": item.urine_amount, "urine_color": item.urine_color, "stool_description": item.stool_description, "notes": item.notes}


@bugfix_api.put("/patients/{patient_id}/elimination/{item_id}")
def update_elimination_record(patient_id: int, item_id: int, payload: EliminationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, EliminationLog, patient_id, item_id, "Registro")
    for field, value in payload.model_dump().items(): setattr(item, field, value)
    _audit(db, user.id, patient_id, "elimination.updated", "elimination", item.id)
    db.commit()
    return {"ok": True}


@bugfix_api.get("/patients/{patient_id}/food/{item_id}")
def get_food_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, FoodLog, patient_id, item_id, "Registro")
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "meal_type": item.meal_type, "item": item.item, "amount": item.amount, "unit": item.unit, "tolerated": item.tolerated, "vomiting": item.vomiting, "notes": item.notes}


@bugfix_api.put("/patients/{patient_id}/food/{item_id}")
def update_food_record(patient_id: int, item_id: int, payload: FoodCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, FoodLog, patient_id, item_id, "Registro")
    for field, value in payload.model_dump().items(): setattr(item, field, value)
    _audit(db, user.id, patient_id, "food.updated", "food", item.id)
    db.commit()
    return {"ok": True}


@bugfix_api.get("/patients/{patient_id}/vitals/{item_id}")
def get_vital_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareVitalRecord, patient_id, item_id, "Registro")
    return {"id": item.id, "recorded_at": item.recorded_at.isoformat(timespec="minutes"), "temperature_c": item.temperature_c, "systolic": item.systolic, "diastolic": item.diastolic, "heart_rate": item.heart_rate, "oxygen_saturation": item.oxygen_saturation, "respiratory_rate": item.respiratory_rate, "weight_kg": item.weight_kg, "notes": item.notes}


@bugfix_api.put("/patients/{patient_id}/vitals/{item_id}")
def update_vital_record(patient_id: int, item_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareVitalRecord, patient_id, item_id, "Registro")
    allowed = {"recorded_at", "temperature_c", "systolic", "diastolic", "heart_rate", "oxygen_saturation", "respiratory_rate", "weight_kg", "notes"}
    for field in allowed:
        if field in payload:
            value = _parse_datetime(payload[field]) if field == "recorded_at" else payload[field]
            setattr(item, field, value)
    _audit(db, user.id, patient_id, "vital.updated", "vital", item.id)
    db.commit()
    return {"ok": True}


@bugfix_api.delete("/patients/{patient_id}/vitals/{item_id}")
def delete_vital_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareVitalRecord, patient_id, item_id, "Registro")
    db.delete(item)
    _audit(db, user.id, patient_id, "vital.deleted", "vital", item_id)
    db.commit()
    return {"ok": True}


@bugfix_api.get("/patients/{patient_id}/crises/{item_id}")
def get_crisis_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareCrisisEvent, patient_id, item_id, "Evento")
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "event_type": item.event_type, "duration_seconds": item.duration_seconds, "consciousness": item.consciousness, "description": item.description, "actions_taken": item.actions_taken, "team_notified": item.team_notified, "notes": item.notes}


@bugfix_api.put("/patients/{patient_id}/crises/{item_id}")
def update_crisis_record(patient_id: int, item_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareCrisisEvent, patient_id, item_id, "Evento")
    allowed = {"occurred_at", "event_type", "duration_seconds", "consciousness", "description", "actions_taken", "team_notified", "notes"}
    for field in allowed:
        if field in payload:
            value = _parse_datetime(payload[field]) if field == "occurred_at" else payload[field]
            setattr(item, field, value)
    _audit(db, user.id, patient_id, "crisis.updated", "crisis", item.id)
    db.commit()
    return {"ok": True}


@bugfix_api.delete("/patients/{patient_id}/crises/{item_id}")
def delete_crisis_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareCrisisEvent, patient_id, item_id, "Evento")
    db.delete(item)
    _audit(db, user.id, patient_id, "crisis.deleted", "crisis", item_id)
    db.commit()
    return {"ok": True}


@bugfix_api.get("/patients/{patient_id}/chemo/{item_id}")
def get_chemo_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareChemoSession, patient_id, item_id, "Registro de quimioterapia")
    return {
        "id": item.id,
        "scheduled_at": item.scheduled_at.isoformat(timespec="minutes"),
        "name": item.name,
        "protocol": item.protocol,
        "cycle": item.cycle,
        "purpose": item.purpose,
        "status_value": item.status,
        "notes": item.notes,
        "adverse_effects": item.adverse_effects,
    }


@bugfix_api.put("/patients/{patient_id}/chemo/{item_id}")
def update_chemo_record(patient_id: int, item_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareChemoSession, patient_id, item_id, "Registro de quimioterapia")
    if "scheduled_at" in payload:
        item.scheduled_at = _parse_datetime(payload["scheduled_at"])
    if "name" in payload:
        item.name = str(payload["name"])[:180]
    for field in ["protocol", "cycle", "purpose", "notes", "adverse_effects"]:
        if field in payload:
            setattr(item, field, payload[field])
    if "status_value" in payload:
        item.status = payload["status_value"]
    _audit(db, user.id, patient_id, "chemo.updated", "chemo", item.id)
    db.commit()
    return {"ok": True}


@bugfix_api.delete("/patients/{patient_id}/chemo/{item_id}")
def delete_chemo_record(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _owned_record(db, CareChemoSession, patient_id, item_id, "Registro de quimioterapia")
    db.delete(item)
    _audit(db, user.id, patient_id, "chemo.deleted", "chemo", item_id)
    db.commit()
    return {"ok": True}


@bugfix_api.delete("/patients/{patient_id}/daily-note")
def delete_daily_note(patient_id: int, note_date: date, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    note = db.scalar(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date == note_date))
    if note:
        db.delete(note)
        _audit(db, user.id, patient_id, "daily_note.deleted", "daily_note", note_date.isoformat())
        db.commit()
    return {"ok": True}
