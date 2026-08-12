from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .requested_medications import SOURCE_MARKER
from .v2_clinical_history import CareRecordMeta, MedicationTreatmentHistory
from .v2_models import CareMedication
from .v2_router import _audit, _require_role

medication_extra_api = APIRouter(prefix="/api/v2", tags=["IkerCare medication extras"])


def _medication(db: Session, patient_id: int, medication_id: int) -> CareMedication:
    med = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    return med


@medication_extra_api.delete("/patients/{patient_id}/medications/{medication_id}/permanent")
def permanently_delete_medication(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    """Elimina definitivamente medicamento, horarios, administraciones e historial asociado."""
    _require_role(db, user.id, patient_id, {"owner"})
    med = _medication(db, patient_id, medication_id)
    name = med.name

    if med.source == SOURCE_MARKER:
        key = " ".join(name.strip().casefold().split())[:80]
        tombstone = db.scalar(
            select(CareRecordMeta).where(
                CareRecordMeta.entity_type == "deleted_seed_medication",
                CareRecordMeta.entity_id == patient_id,
                CareRecordMeta.key == key,
            )
        )
        if not tombstone:
            db.add(CareRecordMeta(entity_type="deleted_seed_medication", entity_id=patient_id, key=key, value="1"))
        else:
            tombstone.value = "1"

    _audit(db, user.id, patient_id, "medication.permanently_deleted", "medication", medication_id, {"name": name})
    db.delete(med)
    db.commit()
    return {"ok": True, "deleted": True}


@medication_extra_api.delete("/patients/{patient_id}/medications/{medication_id}/treatment-history/{history_id}")
def delete_treatment_history_item(
    patient_id: int,
    medication_id: int,
    history_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    _medication(db, patient_id, medication_id)
    row = db.scalar(
        select(MedicationTreatmentHistory).where(
            MedicationTreatmentHistory.id == history_id,
            MedicationTreatmentHistory.medication_id == medication_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Registro de historial no encontrado.")
    if row.event_type == "initial":
        raise HTTPException(status_code=400, detail="El registro inicial se conserva mientras exista el medicamento.")
    _audit(db, user.id, patient_id, "medication.history_item_deleted", "medication_history", history_id, {"medication_id": medication_id})
    db.delete(row)
    db.commit()
    return {"ok": True}
