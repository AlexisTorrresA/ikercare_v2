from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_models import CareChemoSession
from .v2_router import _membership

hotfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 hotfix"])


@hotfix_api.get("/patients/{patient_id}/chemo/all")
def list_all_chemo_hotfix(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Ruta estática prioritaria para evitar que /chemo/all sea capturada por /chemo/{item_id}."""
    _membership(db, user.id, patient_id)
    rows = db.scalars(
        select(CareChemoSession)
        .where(CareChemoSession.patient_id == patient_id)
        .order_by(CareChemoSession.scheduled_at.asc(), CareChemoSession.id.asc())
    ).all()
    return [
        {
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
        for item in rows
    ]
