from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_clinical_history import MedicationTreatmentHistory, _ensure_initial_snapshot, _history_dict, _snapshot, _state
from .v2_models import CareMedication, CareMedicationSchedule
from .v2_router import _audit, _membership, _require_role, now

medication_history_hotfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare medication history"])


@medication_history_hotfix_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def medication_treatment_history(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Mantiene el contrato del frontend: una lista cronológica de revisiones."""
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


@medication_history_hotfix_api.post("/patients/{patient_id}/medications/{medication_id}/status")
def change_medication_status(
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
    state = _state(db, med)
    occurred_at = datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now()
    reason = payload.get("reason") or None
    schedules = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all()

    if status in {"suspended", "finished", "paused"}:
        # La revisión de suspensión conserva los horarios que estaban vigentes justo antes
        # de desactivar el esquema. Así una reanudación posterior puede recuperarlos.
        _snapshot(db, med, occurred_at, "status_change", user.id, status=status, reason=reason)
        for schedule in schedules:
            schedule.active = False
        med.active = False
    else:
        # Busca la última configuración con horarios y los restaura sin inventar nuevos.
        prior_rows = db.scalars(
            select(MedicationTreatmentHistory)
            .where(MedicationTreatmentHistory.medication_id == med.id)
            .order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc())
        ).all()
        wanted = set()
        for prior in prior_rows:
            try:
                values = json.loads(prior.times_json or "[]")
            except Exception:
                values = []
            if values:
                wanted = {datetime.strptime(value, "%H:%M").time() for value in values}
                break
        for schedule in schedules:
            schedule.active = schedule.time_of_day in wanted if wanted else schedule.active
        med.active = True
        _snapshot(db, med, occurred_at, "status_change", user.id, status=status, reason=reason)

    state.status = status
    state.reason = reason
    state.changed_at = occurred_at
    med.updated_at = occurred_at
    _audit(db, user.id, patient_id, f"medication.status.{status}", "medication", med.id, {"reason": reason})
    db.commit()
    return {"ok": True, "status": status, "active": med.active}
