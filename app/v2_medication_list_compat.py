from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import MedicationState, _ensure_initial_snapshot
from .v2_models import CareMedication, CareMedicationSchedule
from .v2_router import _membership

medication_list_compat_api = APIRouter(prefix="/api/v2", tags=["IkerCare medication compatibility"])


@medication_list_compat_api.get("/patients/{patient_id}/medications")
def list_medications_with_configured_times(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _membership(db, user.id, patient_id)
    medications = db.scalars(
        select(CareMedication)
        .where(CareMedication.patient_id == patient_id)
        .order_by(CareMedication.active.desc(), CareMedication.name)
    ).all()
    result = []
    changed = False
    for medication in medications:
        if not db.get(MedicationState, medication.id):
            _ensure_initial_snapshot(db, medication, user.id)
            changed = True
        state = db.get(MedicationState, medication.id)
        schedules = db.scalars(
            select(CareMedicationSchedule)
            .where(CareMedicationSchedule.medication_id == medication.id)
            .order_by(CareMedicationSchedule.time_of_day)
        ).all()
        result.append({
            "id": medication.id,
            "patient_id": medication.patient_id,
            "name": medication.name,
            "generic_name": medication.generic_name,
            "medication_type": medication.medication_type,
            "purpose": medication.purpose,
            "dose": medication.dose,
            "route": medication.route,
            "frequency": medication.frequency,
            "instructions": medication.instructions,
            "active": medication.active,
            "source": medication.source,
            "times": [row.time_of_day.strftime("%H:%M") for row in schedules],
            "treatment_status": state.status if state else ("active" if medication.active else "suspended"),
            "status_reason": state.reason if state else None,
        })
    if changed:
        db.commit()
    return result
