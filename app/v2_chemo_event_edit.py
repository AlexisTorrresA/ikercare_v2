from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_clinical_history import ChemoEvolutionEvent
from .v2_models import CareChemoSession
from .v2_router import _audit, _require_role

chemo_event_edit_api = APIRouter(prefix="/api/v2", tags=["IkerCare chemo event edit"])


@chemo_event_edit_api.put("/patients/{patient_id}/chemo/{chemo_id}/events/{event_id}")
def update_chemo_event(
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
        row.description = payload.get("description") or None

    _audit(
        db,
        user.id,
        patient_id,
        "chemo.evolution.updated",
        "chemo_event",
        row.id,
        {"chemo_id": chemo_id},
    )
    db.commit()
    return {"ok": True}
