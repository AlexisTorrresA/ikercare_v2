from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_models import CareMedication, CareMedicationSchedule
from .v2_router import _audit, _require_role, now

bugfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 fixes"])


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
    med = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")

    med.active = False
    med.updated_at = now()
    schedules = db.scalars(
        select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)
    ).all()
    for schedule in schedules:
        schedule.active = False

    _audit(
        db,
        user.id,
        patient_id,
        "medication.deleted",
        "medication",
        med.id,
        {"name": med.name, "history_preserved": True},
    )
    db.commit()
    return {"ok": True, "history_preserved": True}
