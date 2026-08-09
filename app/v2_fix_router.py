from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_models import (
    AuditLog,
    CareMedication,
    CareMedicationEvent,
    CareMedicationLog,
    CareMedicationSchedule,
    PatientMember,
)

router = APIRouter(tags=["IkerCare V2 fixes"])

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(get_current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]


def _require_editor(db: Session, user_id: int, patient_id: int) -> None:
    member = db.scalar(
        select(PatientMember).where(
            PatientMember.user_id == user_id,
            PatientMember.patient_id == patient_id,
        )
    )
    if not member:
        raise HTTPException(status_code=404, detail="Paciente no encontrado.")
    if member.role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail="No tienes permisos para modificar medicamentos.")


@router.delete("/api/v2/patients/{patient_id}/medications/{medication_id}")
def delete_medication(
    patient_id: int,
    medication_id: int,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
) -> dict[str, bool]:
    """Elimina un medicamento del paciente y sus horarios/registros asociados."""
    _require_editor(db, user.id, patient_id)

    medication = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")

    schedule_ids = select(CareMedicationSchedule.id).where(
        CareMedicationSchedule.medication_id == medication_id
    )
    db.execute(delete(CareMedicationLog).where(CareMedicationLog.schedule_id.in_(schedule_ids)))
    db.execute(delete(CareMedicationEvent).where(CareMedicationEvent.medication_id == medication_id))
    db.execute(delete(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id))
    db.delete(medication)
    db.add(
        AuditLog(
            actor_user_id=user.id,
            patient_id=patient_id,
            action="medication.deleted",
            entity_type="medication",
            entity_id=str(medication_id),
            metadata_json={"name": medication.name},
        )
    )
    db.commit()
    return {"ok": True}
