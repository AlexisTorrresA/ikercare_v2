from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .requested_medications import SOURCE_MARKER
from .v2_clinical_history import CareRecordMeta, MedicationState, MedicationTreatmentHistory
from .v2_models import CareMedication, CareMedicationEvent, CareMedicationLog, CareMedicationSchedule
from .v2_router import _audit, _membership, _require_role, now

medication_controls_api = APIRouter(prefix="/api/v2", tags=["IkerCare medication controls"])


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


def _sos_meta(db: Session, medication_id: int) -> CareRecordMeta | None:
    return db.scalar(
        select(CareRecordMeta).where(
            CareRecordMeta.entity_type == "medication",
            CareRecordMeta.entity_id == medication_id,
            CareRecordMeta.key == "is_sos",
        )
    )


@medication_controls_api.get("/patients/{patient_id}/medications/{medication_id}/sos")
def get_medication_sos(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _membership(db, user.id, patient_id)
    _medication(db, patient_id, medication_id)
    row = _sos_meta(db, medication_id)
    return {"is_sos": bool(row and row.value == "1")}


@medication_controls_api.put("/patients/{patient_id}/medications/{medication_id}/sos")
def set_medication_sos(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = _medication(db, patient_id, medication_id)
    is_sos = bool(payload.get("is_sos"))
    row = _sos_meta(db, medication_id)
    if not row:
        row = CareRecordMeta(entity_type="medication", entity_id=medication_id, key="is_sos", value="1" if is_sos else "0")
        db.add(row)
    else:
        row.value = "1" if is_sos else "0"

    if is_sos:
        # Un medicamento SOS no tiene recordatorios horarios automáticos.
        for schedule in db.scalars(
            select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id)
        ).all():
            schedule.active = False
        if not med.frequency or med.frequency.strip().lower() in {"cada 24 horas", "diario"}:
            med.frequency = "SOS / según indicación"
    med.updated_at = now()
    _audit(db, user.id, patient_id, "medication.sos_updated", "medication", medication_id, {"is_sos": is_sos})
    db.commit()
    return {"ok": True, "is_sos": is_sos}


@medication_controls_api.post("/patients/{patient_id}/medications/{medication_id}/sos-use", status_code=201)
def register_sos_use(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = _medication(db, patient_id, medication_id)
    row = _sos_meta(db, medication_id)
    if not row or row.value != "1":
        raise HTTPException(status_code=400, detail="Este medicamento no está marcado como SOS.")
    occurred_at = datetime.fromisoformat(str(payload["occurred_at"])) if payload.get("occurred_at") else now()
    event = CareMedicationEvent(
        medication_id=medication_id,
        occurred_at=occurred_at,
        notes=(str(payload.get("notes") or "").strip() or "Administración SOS registrada"),
        created_by_user_id=user.id,
    )
    db.add(event)
    db.flush()
    _audit(db, user.id, patient_id, "medication.sos_used", "medication_event", event.id, {"medication": med.name})
    db.commit()
    return {"id": event.id, "occurred_at": occurred_at.isoformat(timespec="minutes")}


@medication_controls_api.delete("/patients/{patient_id}/medications/{medication_id}/treatment-history/{history_id}")
def delete_treatment_history_entry(
    patient_id: int,
    medication_id: int,
    history_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = _medication(db, patient_id, medication_id)
    entry = db.scalar(
        select(MedicationTreatmentHistory).where(
            MedicationTreatmentHistory.id == history_id,
            MedicationTreatmentHistory.medication_id == medication_id,
        )
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Registro histórico no encontrado.")
    db.delete(entry)
    _audit(db, user.id, patient_id, "medication.history_entry_deleted", "medication_history", history_id, {"medication": med.name})
    db.commit()
    return {"ok": True}


@medication_controls_api.delete("/patients/{patient_id}/medications/{medication_id}/permanent")
def permanently_delete_medication(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = _medication(db, patient_id, medication_id)
    name = med.name
    source = med.source

    # Si provenía de la sincronización inicial, deja una marca para que no vuelva a crearse.
    if source == SOURCE_MARKER:
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

    # Limpieza explícita para mantener compatibilidad también en instalaciones sin cascadas activas.
    schedule_ids = db.scalars(select(CareMedicationSchedule.id).where(CareMedicationSchedule.medication_id == medication_id)).all()
    if schedule_ids:
        db.execute(delete(CareMedicationLog).where(CareMedicationLog.schedule_id.in_(schedule_ids)))
    db.execute(delete(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id))
    db.execute(delete(CareMedicationEvent).where(CareMedicationEvent.medication_id == medication_id))
    db.execute(delete(MedicationTreatmentHistory).where(MedicationTreatmentHistory.medication_id == medication_id))
    db.execute(delete(MedicationState).where(MedicationState.medication_id == medication_id))
    db.execute(delete(CareRecordMeta).where(CareRecordMeta.entity_type == "medication", CareRecordMeta.entity_id == medication_id))
    db.delete(med)
    _audit(db, user.id, patient_id, "medication.permanently_deleted", "medication", medication_id, {"name": name, "source": source})
    db.commit()
    return {"ok": True}
