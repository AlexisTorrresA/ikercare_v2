from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .medical_catalog import CATALOG, search_medications
from .models import User
from .v2_models import CareChemoSession, CareCrisisEvent, CareMedication, CareVitalRecord, EliminationLog, FoodLog
from .v2_router import _audit, _membership, _require_role, now
from .v2_treatment_helpers import (
    CHEMO_EVENT_TYPES,
    INTAKE_LEVELS,
    MEAL_TYPES,
    MED_STATUSES,
    link_entity,
    normalize,
    record_revision,
    serialize_med,
    set_med_schedules,
    validate_hospitalization,
)
from .v2_treatment_models import CareChemoFollowupEvent, CareFoodDetail, CareHospitalizationLink, CareMedicationRevision, MedicationCatalogCache

logger = logging.getLogger("ikercare.treatment")
treatment_api = APIRouter(prefix="/api/v2", tags=["IkerCare treatment history"])


@treatment_api.get("/medications/search")
def search_medications_extended(q: str = Query(min_length=2, max_length=80), db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> list[dict]:
    rows = search_medications(q, limit=10)
    seen = {normalize(row["name"]) for row in rows}
    query = normalize(q)
    cached = db.scalars(select(MedicationCatalogCache).where(MedicationCatalogCache.normalized_name.contains(query)).limit(10)).all()
    for row in cached:
        if row.normalized_name in seen:
            continue
        rows.append({"name": row.display_name, "generic_name": row.display_name, "type": row.medication_type or "Medicamento", "purpose": row.purpose, "route": row.route, "unit": row.unit, "source": row.source})
    return rows[:10]


@treatment_api.post("/medications/describe")
def describe_unknown_medication(payload: dict = Body(...), db: Session = Depends(get_db), _: User = Depends(get_current_user), __: None = Depends(verify_csrf)) -> dict:
    name = str(payload.get("name") or "").strip()
    if len(name) < 2 or len(name) > 160:
        raise HTTPException(status_code=400, detail="Ingresa un nombre de medicamento válido.")
    key = normalize(name)
    for item in CATALOG:
        if normalize(item["name"]) == key:
            return {"name": item["name"], "type": item["type"], "purpose": item["purpose"], "route": item.get("route"), "unit": item.get("unit"), "source": "curated_catalog"}
    cached = db.get(MedicationCatalogCache, key)
    if cached:
        return {"name": cached.display_name, "type": cached.medication_type, "purpose": cached.purpose, "route": cached.route, "unit": cached.unit, "source": cached.source}
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Este medicamento no está en el catálogo y la ayuda de IA no está configurada.")
    prompt = (
        "Devuelve SOLO JSON válido con claves medication_type, purpose, route, unit. "
        "Describe únicamente la categoría, uso general, vía habitual y unidad habitual del medicamento indicado. "
        "NO recomiendes dosis, frecuencia, duración, cambios de tratamiento ni conducta médica. "
        "Si no reconoces el medicamento con seguridad, usa null. Medicamento: " + name
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
        raw = re.sub(r"^```(?:json)?|```$", "", "\n".join(parts).strip(), flags=re.I | re.M).strip()
        parsed = json.loads(raw)
    except Exception:
        logger.exception("Medication description failed for %s", key)
        raise HTTPException(status_code=502, detail="No se pudo completar la información del medicamento en este momento.")
    cached = MedicationCatalogCache(
        normalized_name=key,
        display_name=name,
        medication_type=parsed.get("medication_type") or None,
        purpose=parsed.get("purpose") or None,
        route=parsed.get("route") or None,
        unit=parsed.get("unit") or None,
        source="openai",
    )
    db.merge(cached)
    db.commit()
    return {"name": name, "type": cached.medication_type, "purpose": cached.purpose, "route": cached.route, "unit": cached.unit, "source": "openai"}


@treatment_api.get("/patients/{patient_id}/medications")
def medications_with_history(patient_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    meds = db.scalars(select(CareMedication).where(CareMedication.patient_id == patient_id).order_by(CareMedication.active.desc(), CareMedication.name)).all()
    result = [serialize_med(db, med) for med in meds]
    db.commit()
    return result


@treatment_api.post("/patients/{patient_id}/medications", status_code=201)
def create_medication(patient_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre del medicamento es obligatorio.")
    times = [str(value).strip() for value in payload.get("times", []) if str(value).strip()]
    med = CareMedication(
        patient_id=patient_id,
        name=name[:160],
        generic_name=payload.get("generic_name"),
        medication_type=str(payload.get("medication_type") or "Medicamento")[:120],
        purpose=payload.get("purpose"),
        dose=payload.get("dose"),
        route=payload.get("route"),
        frequency=payload.get("frequency"),
        instructions=payload.get("instructions"),
        active=True,
        source=str(payload.get("source") or "manual")[:40],
        created_by_user_id=user.id,
    )
    db.add(med)
    db.flush()
    set_med_schedules(db, med, times)
    db.flush()
    effective_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    record_revision(db, med, user.id, status="active", reason=None, event_type="created", changed_fields=["created"], effective_at=effective_at, hospitalization_id=payload.get("hospitalization_id"), unit=payload.get("unit"))
    _audit(db, user.id, patient_id, "medication.created", "medication", med.id, {"history": True})
    db.commit()
    return serialize_med(db, med)


@treatment_api.put("/patients/{patient_id}/medications/{medication_id}")
def update_medication(patient_id: int, medication_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    previous = serialize_med(db, med)
    status = str(payload.get("status") or previous["status"]).lower()
    if status not in MED_STATUSES:
        raise HTTPException(status_code=400, detail="Estado de medicamento inválido.")
    for field in ["name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"]:
        if field in payload:
            value = payload.get(field)
            if field == "name" and not str(value or "").strip():
                raise HTTPException(status_code=400, detail="El nombre del medicamento es obligatorio.")
            setattr(med, field, str(value).strip() if field == "name" else value)
    times = payload.get("times", previous["times"])
    set_med_schedules(db, med, times)
    med.active = status in {"active", "resumed"}
    med.updated_at = now()
    db.flush()
    current = serialize_med(db, med)
    current["unit"] = payload.get("unit", previous.get("unit"))
    changed = [key for key in ["name", "medication_type", "purpose", "dose", "route", "frequency", "instructions", "times", "unit"] if current.get(key) != previous.get(key)]
    if status != previous["status"]:
        changed.append("status")
    if changed:
        event_type = {"suspended": "suspended", "finished": "finished", "paused": "paused", "resumed": "resumed"}.get(status, "changed")
        effective_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
        record_revision(db, med, user.id, status=status, reason=payload.get("status_reason"), event_type=event_type, changed_fields=changed, effective_at=effective_at, hospitalization_id=payload.get("hospitalization_id"), unit=payload.get("unit", previous.get("unit")))
    _audit(db, user.id, patient_id, "medication.updated", "medication", med.id, {"changed_fields": changed, "status": status})
    db.commit()
    return serialize_med(db, med)


@treatment_api.get("/patients/{patient_id}/medications/{medication_id}/history")
def medication_history(patient_id: int, medication_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    serialize_med(db, med)
    db.commit()
    rows = db.scalars(select(CareMedicationRevision).where(CareMedicationRevision.medication_id == medication_id).order_by(CareMedicationRevision.effective_at.asc(), CareMedicationRevision.id.asc())).all()
    return [{
        "id": row.id,
        "effective_at": row.effective_at.isoformat(timespec="minutes"),
        "event_type": row.event_type,
        "status": row.status,
        "status_reason": row.status_reason,
        "dose": row.dose,
        "route": row.route,
        "frequency": row.frequency,
        "times": row.times_json or [],
        "changed_fields": row.changed_fields_json or [],
        "hospitalization_id": row.hospitalization_id,
    } for row in rows]


def _food_payload(item: FoodLog, db: Session) -> dict:
    detail = db.get(CareFoodDetail, item.id)
    link = db.scalar(select(CareHospitalizationLink).where(CareHospitalizationLink.entity_type == "food", CareHospitalizationLink.entity_id == item.id))
    return {"id": item.id, "occurred_at": item.occurred_at.isoformat(timespec="minutes"), "meal_type": item.meal_type, "item": item.item, "amount": item.amount, "unit": item.unit, "tolerated": item.tolerated, "vomiting": item.vomiting, "notes": item.notes, "intake_level": detail.intake_level if detail else None, "hospitalization_id": link.hospitalization_id if link else None}


def _upsert_food(db: Session, user: User, patient_id: int, payload: dict, item: FoodLog | None = None) -> FoodLog:
    occurred_at = datetime.fromisoformat(str(payload.get("occurred_at")))
    meal_type = str(payload.get("meal_type") or "Otro")
    if meal_type not in MEAL_TYPES:
        meal_type = "Otro"
    name = str(payload.get("item") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Indica qué comió o bebió.")
    if item is None:
        item = FoodLog(patient_id=patient_id, occurred_at=occurred_at, meal_type=meal_type, item=name[:240], amount=payload.get("amount"), unit=payload.get("unit"), tolerated=payload.get("tolerated"), vomiting=bool(payload.get("vomiting", False)), notes=payload.get("notes"), created_by_user_id=user.id)
        db.add(item)
        db.flush()
    else:
        item.occurred_at, item.meal_type, item.item = occurred_at, meal_type, name[:240]
        item.amount, item.unit, item.tolerated, item.vomiting, item.notes = payload.get("amount"), payload.get("unit"), payload.get("tolerated"), bool(payload.get("vomiting", False)), payload.get("notes")
    detail = db.get(CareFoodDetail, item.id) or CareFoodDetail(food_log_id=item.id)
    detail.intake_level = payload.get("intake_level") if payload.get("intake_level") in INTAKE_LEVELS else None
    db.merge(detail)
    link_entity(db, patient_id, "food", item.id, occurred_at, payload.get("hospitalization_id"))
    return item


@treatment_api.post("/patients/{patient_id}/food", status_code=201)
def create_food(patient_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _upsert_food(db, user, patient_id, payload)
    _audit(db, user.id, patient_id, "food.created", "food", item.id)
    db.commit()
    return {"id": item.id}


@treatment_api.get("/patients/{patient_id}/food/{item_id}")
def get_food(patient_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    item = db.scalar(select(FoodLog).where(FoodLog.id == item_id, FoodLog.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    return _food_payload(item, db)


@treatment_api.put("/patients/{patient_id}/food/{item_id}")
def update_food(patient_id: int, item_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = db.scalar(select(FoodLog).where(FoodLog.id == item_id, FoodLog.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    _upsert_food(db, user, patient_id, payload, item)
    _audit(db, user.id, patient_id, "food.updated", "food", item.id)
    db.commit()
    return {"ok": True}


@treatment_api.get("/patients/{patient_id}/day-extras")
def day_extras(patient_id: int, selected_date: str = Query(alias="date"), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    from datetime import date, time
    target = date.fromisoformat(selected_date)
    start, end = datetime.combine(target, time.min), datetime.combine(target, time.max)
    foods = db.scalars(select(FoodLog).where(FoodLog.patient_id == patient_id, FoodLog.occurred_at.between(start, end))).all()
    return {"food": {str(item.id): {"intake_level": (db.get(CareFoodDetail, item.id).intake_level if db.get(CareFoodDetail, item.id) else None)} for item in foods}}


def _upsert_elimination(db: Session, user: User, patient_id: int, payload: dict, item: EliminationLog | None = None) -> EliminationLog:
    occurred_at = datetime.fromisoformat(str(payload.get("occurred_at")))
    status = str(payload.get("diaper_status") or "wet")
    if status not in {"dry", "wet", "soiled", "wet_and_soiled"}:
        raise HTTPException(status_code=400, detail="Tipo de pañal inválido.")
    if item is None:
        item = EliminationLog(patient_id=patient_id, occurred_at=occurred_at, diaper_status=status, urine_amount=payload.get("urine_amount"), urine_color=payload.get("urine_color"), stool_description=payload.get("stool_description"), notes=payload.get("notes"), created_by_user_id=user.id)
        db.add(item)
        db.flush()
    else:
        item.occurred_at, item.diaper_status = occurred_at, status
        item.urine_amount, item.urine_color, item.stool_description, item.notes = payload.get("urine_amount"), payload.get("urine_color"), payload.get("stool_description"), payload.get("notes")
    link_entity(db, patient_id, "elimination", item.id, occurred_at, payload.get("hospitalization_id"))
    return item


@treatment_api.post("/patients/{patient_id}/elimination", status_code=201)
def create_elimination(patient_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _upsert_elimination(db, user, patient_id, payload)
    _audit(db, user.id, patient_id, "elimination.created", "elimination", item.id)
    db.commit()
    return {"id": item.id}


@treatment_api.put("/patients/{patient_id}/elimination/{item_id}")
def update_elimination(patient_id: int, item_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = db.scalar(select(EliminationLog).where(EliminationLog.id == item_id, EliminationLog.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    _upsert_elimination(db, user, patient_id, payload, item)
    _audit(db, user.id, patient_id, "elimination.updated", "elimination", item.id)
    db.commit()
    return {"ok": True}


def _care_payload(model, patient_id: int, user_id: int, payload: dict, date_field: str):
    values = {key: value for key, value in payload.items() if key != "hospitalization_id"}
    values[date_field] = datetime.fromisoformat(str(values[date_field]))
    return model(patient_id=patient_id, created_by_user_id=user_id, **values)


@treatment_api.post("/patients/{patient_id}/vitals", status_code=201)
def create_vitals(patient_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _care_payload(CareVitalRecord, patient_id, user.id, payload, "recorded_at")
    db.add(item); db.flush(); link_entity(db, patient_id, "vital", item.id, item.recorded_at, payload.get("hospitalization_id")); _audit(db, user.id, patient_id, "vital.created", "vital", item.id); db.commit(); return {"id": item.id}


@treatment_api.post("/patients/{patient_id}/crises", status_code=201)
def create_crisis(patient_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _care_payload(CareCrisisEvent, patient_id, user.id, payload, "occurred_at")
    db.add(item); db.flush(); link_entity(db, patient_id, "crisis", item.id, item.occurred_at, payload.get("hospitalization_id")); _audit(db, user.id, patient_id, "crisis.created", "crisis", item.id); db.commit(); return {"id": item.id}


@treatment_api.post("/patients/{patient_id}/chemo", status_code=201)
def create_chemo(patient_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    scheduled_at = datetime.fromisoformat(str(payload.get("scheduled_at")))
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El medicamento/agente de quimioterapia es obligatorio.")
    item = CareChemoSession(patient_id=patient_id, scheduled_at=scheduled_at, name=name[:180], protocol=payload.get("protocol"), cycle=payload.get("cycle"), purpose=payload.get("purpose"), status=payload.get("status_value") or "scheduled", notes=payload.get("notes"), adverse_effects=payload.get("adverse_effects"), created_by_user_id=user.id)
    db.add(item); db.flush(); link_entity(db, patient_id, "chemo", item.id, item.scheduled_at, payload.get("hospitalization_id")); _audit(db, user.id, patient_id, "chemo.created", "chemo", item.id); db.commit(); return {"id": item.id}


@treatment_api.get("/patients/{patient_id}/chemo/{chemo_id}/events")
def chemo_events(patient_id: int, chemo_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    chemo = db.scalar(select(CareChemoSession).where(CareChemoSession.id == chemo_id, CareChemoSession.patient_id == patient_id))
    if not chemo:
        raise HTTPException(status_code=404, detail="Quimioterapia no encontrada.")
    rows = db.scalars(select(CareChemoFollowupEvent).where(CareChemoFollowupEvent.chemo_session_id == chemo_id).order_by(CareChemoFollowupEvent.occurred_at.asc())).all()
    return [{"id": row.id, "occurred_at": row.occurred_at.isoformat(timespec="minutes"), "event_type": row.event_type, "description": row.description, "hospitalization_id": row.hospitalization_id} for row in rows]


@treatment_api.post("/patients/{patient_id}/chemo/{chemo_id}/events", status_code=201)
def create_chemo_event(patient_id: int, chemo_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    chemo = db.scalar(select(CareChemoSession).where(CareChemoSession.id == chemo_id, CareChemoSession.patient_id == patient_id))
    if not chemo:
        raise HTTPException(status_code=404, detail="Quimioterapia no encontrada.")
    occurred_at = datetime.fromisoformat(str(payload.get("occurred_at") or now().isoformat()))
    event_type = str(payload.get("event_type") or "Otro")
    if event_type not in CHEMO_EVENT_TYPES:
        event_type = "Otro"
    hospitalization = validate_hospitalization(db, patient_id, payload.get("hospitalization_id"), occurred_at) or validate_hospitalization(db, patient_id, None, chemo.scheduled_at)
    item = CareChemoFollowupEvent(chemo_session_id=chemo_id, patient_id=patient_id, hospitalization_id=hospitalization.id if hospitalization else None, occurred_at=occurred_at, event_type=event_type, description=payload.get("description"), created_by_user_id=user.id)
    db.add(item); db.flush(); _audit(db, user.id, patient_id, "chemo_event.created", "chemo_event", item.id, {"chemo_id": chemo_id}); db.commit(); return {"id": item.id}


@treatment_api.delete("/patients/{patient_id}/chemo/{chemo_id}/events/{event_id}")
def delete_chemo_event(patient_id: int, chemo_id: int, event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = db.scalar(select(CareChemoFollowupEvent).where(CareChemoFollowupEvent.id == event_id, CareChemoFollowupEvent.chemo_session_id == chemo_id, CareChemoFollowupEvent.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Evento no encontrado.")
    db.delete(item); _audit(db, user.id, patient_id, "chemo_event.deleted", "chemo_event", event_id); db.commit(); return {"ok": True}
