from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_models import CareChemoSession
from .v2_router import _audit, _require_role

chemo_fix_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 chemo fixes"])

_ALLOWED_STATUSES = {"scheduled", "in_progress", "completed", "postponed", "cancelled"}


def _chemo(db: Session, patient_id: int, item_id: int) -> CareChemoSession:
    item = db.scalar(
        select(CareChemoSession).where(
            CareChemoSession.id == item_id,
            CareChemoSession.patient_id == patient_id,
        )
    )
    if not item:
        raise HTTPException(status_code=404, detail="Registro de quimioterapia no encontrado.")
    return item


@chemo_fix_api.get("/patients/{patient_id}/chemo/{item_id}")
def get_chemo(
    patient_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _chemo(db, patient_id, item_id)
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


@chemo_fix_api.put("/patients/{patient_id}/chemo/{item_id}")
def update_chemo(
    patient_id: int,
    item_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _chemo(db, patient_id, item_id)

    name = str(payload.get("name") or "").strip()
    scheduled_at = payload.get("scheduled_at")
    status_value = str(payload.get("status_value") or "scheduled")
    if not name:
        raise HTTPException(status_code=422, detail="El nombre de la quimioterapia es obligatorio.")
    if not scheduled_at:
        raise HTTPException(status_code=422, detail="La fecha y hora son obligatorias.")
    if status_value not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=422, detail="Estado de quimioterapia inválido.")

    try:
        parsed_date = datetime.fromisoformat(str(scheduled_at))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Fecha y hora inválidas.") from exc

    item.scheduled_at = parsed_date
    item.name = name[:180]
    item.protocol = (str(payload.get("protocol") or "").strip() or None)
    item.cycle = (str(payload.get("cycle") or "").strip() or None)
    item.purpose = (str(payload.get("purpose") or "").strip() or None)
    item.status = status_value
    item.notes = (str(payload.get("notes") or "").strip() or None)
    item.adverse_effects = (str(payload.get("adverse_effects") or "").strip() or None)

    _audit(db, user.id, patient_id, "chemo.updated", "chemo", item.id)
    db.commit()
    return {"ok": True}


@chemo_fix_api.delete("/patients/{patient_id}/chemo/{item_id}")
def delete_chemo(
    patient_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = _chemo(db, patient_id, item_id)
    db.delete(item)
    _audit(db, user.id, patient_id, "chemo.deleted", "chemo", item_id)
    db.commit()
    return {"ok": True}
