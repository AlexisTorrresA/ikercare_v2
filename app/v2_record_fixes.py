from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_models import CareCrisisEvent, CareDailyNote, CareVitalRecord, EliminationLog, FoodLog
from .v2_router import _audit, _require_role
from .v2_schemas import EliminationCreate, FoodCreate

record_fix_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 record fixes"])


def _get_record(db: Session, model, patient_id: int, item_id: int):
    item = db.scalar(select(model).where(model.id == item_id, model.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    return item


@record_fix_api.get("/patients/{patient_id}/elimination/{item_id}")
def get_elimination(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor", "viewer"})
    item = _get_record(db, EliminationLog, patient_id, item_id)
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "diaper_status": item.diaper_status, "urine_amount": item.urine_amount, "urine_color": item.urine_color, "stool_description": item.stool_description, "notes": item.notes}


@record_fix_api.put("/patients/{patient_id}/elimination/{item_id}")
def update_elimination(patient_id: int, item_id: int, payload: EliminationCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_record(db, EliminationLog, patient_id, item_id)
    for field, value in payload.model_dump().items(): setattr(item, field, value)
    _audit(db, user.id, patient_id, "elimination.updated", "elimination", item.id)
    db.commit()
    return {"ok": True}


@record_fix_api.get("/patients/{patient_id}/food/{item_id}")
def get_food(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor", "viewer"})
    item = _get_record(db, FoodLog, patient_id, item_id)
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "meal_type": item.meal_type, "item": item.item, "amount": item.amount, "unit": item.unit, "tolerated": item.tolerated, "vomiting": item.vomiting, "notes": item.notes}


@record_fix_api.put("/patients/{patient_id}/food/{item_id}")
def update_food(patient_id: int, item_id: int, payload: FoodCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_record(db, FoodLog, patient_id, item_id)
    for field, value in payload.model_dump().items(): setattr(item, field, value)
    _audit(db, user.id, patient_id, "food.updated", "food", item.id)
    db.commit()
    return {"ok": True}


@record_fix_api.get("/patients/{patient_id}/vitals/{item_id}")
def get_vital(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor", "viewer"})
    item = _get_record(db, CareVitalRecord, patient_id, item_id)
    return {"id": item.id, "recorded_at": item.recorded_at.isoformat(timespec="minutes"), "temperature_c": item.temperature_c, "systolic": item.systolic, "diastolic": item.diastolic, "heart_rate": item.heart_rate, "oxygen_saturation": item.oxygen_saturation, "respiratory_rate": item.respiratory_rate, "weight_kg": item.weight_kg, "notes": item.notes}


@record_fix_api.put("/patients/{patient_id}/vitals/{item_id}")
def update_vital(patient_id: int, item_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_record(db, CareVitalRecord, patient_id, item_id)
    allowed = {"recorded_at", "temperature_c", "systolic", "diastolic", "heart_rate", "oxygen_saturation", "respiratory_rate", "weight_kg", "notes"}
    for field in allowed:
        if field in payload:
            value = payload[field]
            if field == "recorded_at" and isinstance(value, str):
                from datetime import datetime
                value = datetime.fromisoformat(value)
            setattr(item, field, value)
    _audit(db, user.id, patient_id, "vital.updated", "vital", item.id)
    db.commit()
    return {"ok": True}


@record_fix_api.delete("/patients/{patient_id}/vitals/{item_id}")
def delete_vital(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_record(db, CareVitalRecord, patient_id, item_id)
    db.delete(item)
    _audit(db, user.id, patient_id, "vital.deleted", "vital", item_id)
    db.commit()
    return {"ok": True}


@record_fix_api.get("/patients/{patient_id}/crises/{item_id}")
def get_crisis(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor", "viewer"})
    item = _get_record(db, CareCrisisEvent, patient_id, item_id)
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "event_type": item.event_type, "duration_seconds": item.duration_seconds, "consciousness": item.consciousness, "description": item.description, "actions_taken": item.actions_taken, "team_notified": item.team_notified, "notes": item.notes}


@record_fix_api.put("/patients/{patient_id}/crises/{item_id}")
def update_crisis(patient_id: int, item_id: int, payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_record(db, CareCrisisEvent, patient_id, item_id)
    allowed = {"occurred_at", "event_type", "duration_seconds", "consciousness", "description", "actions_taken", "team_notified", "notes"}
    for field in allowed:
        if field in payload:
            value = payload[field]
            if field == "occurred_at" and isinstance(value, str):
                from datetime import datetime
                value = datetime.fromisoformat(value)
            setattr(item, field, value)
    _audit(db, user.id, patient_id, "crisis.updated", "crisis", item.id)
    db.commit()
    return {"ok": True}


@record_fix_api.delete("/patients/{patient_id}/crises/{item_id}")
def delete_crisis(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _get_record(db, CareCrisisEvent, patient_id, item_id)
    db.delete(item)
    _audit(db, user.id, patient_id, "crisis.deleted", "crisis", item_id)
    db.commit()
    return {"ok": True}


@record_fix_api.delete("/patients/{patient_id}/daily-note")
def delete_daily_note(patient_id: int, note_date: date, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    note = db.scalar(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date == note_date))
    if note:
        db.delete(note)
        _audit(db, user.id, patient_id, "daily_note.deleted", "daily_note", note_date.isoformat())
        db.commit()
    return {"ok": True}
