from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import MedicationTreatmentHistory, _ensure_initial_snapshot, _history_dict
from .v2_models import CareMedication
from .v2_router import _membership

history_compat_api = APIRouter(prefix="/api/v2", tags=["IkerCare treatment history compatibility"])


@history_compat_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def medication_treatment_history_list(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _membership(db, user.id, patient_id)
    medication = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    _ensure_initial_snapshot(db, medication, user.id)
    db.commit()
    rows = db.scalars(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == medication.id)
        .order_by(MedicationTreatmentHistory.occurred_at, MedicationTreatmentHistory.id)
    ).all()
    return [_history_dict(row) for row in rows]
