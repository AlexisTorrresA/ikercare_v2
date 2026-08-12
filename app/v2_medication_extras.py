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


def _sos_meta(db: Session, medication_id: int) -> CareRecordMeta | None:
    return db.scalar(
        select(CareRecordMeta).where(
            CareRecordMeta.entity_type == "medication",
            CareRecordMeta.entity_id == medication_id,
            CareRecordMeta.key == "is_sos",
        )
    )


def _set_sos_meta(db: Session, medication_id: int, is_sos: bool) -> None:
    row = _sos_meta(db, medication_id)
    if row:
        row.value = "1" if is_sos else "0"
    else:
        db.add(
            CareRecordMeta(
                entity_type="medication",
                entity_id=medication_id,
                key="is_sos",
                value="1" if is_sos else "0",
            )
        )


def _is_sos(db: Session, med: CareMedication) -> bool:
    row = _sos_meta(db, med.id)
    if row:
        return row.value == "1"
    return "sos" in (med.frequency or "").casefold() or "rescate" in (med.frequency or "").casefold()


@medication_extra_api.post("/patients/{patient_id}/medications-with-options", status_code=201)
def create_medication_with_options(
    patient_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    """Crea un medicamento normal o SOS sin inventar dosis ni indicaciones."""
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Escribe el nombre del medicamento.")

    is_sos = bool(payload.get("is_sos"))
    times = [] if is_sos else [str(v).strip() for v in (payload.get("times") or []) if str(v).strip()]
    frequency = str(payload.get("frequency") or "").strip() or None
    if is_sos and not frequency:
        frequency = "SOS / según indicación"

    med = CareMedication(
        patient_id=patient_id,
        name=name[:160],
        generic_name=payload.get("generic_name") or None,
        medication_type=(str(payload.get("medication_type") or "Medicamento").strip() or "Medicamento")[:120],
        purpose=str(payload.get("purpose") or "").strip() or None,
        dose=str(payload.get("dose") or "").strip() or None,
        route=str(payload.get("route") or "").strip() or None,
        frequency=frequency,
        instructions=str(payload.get("instructions") or "").strip() or None,
        active=True,
        source="manual",
        created_by_user_id=user.id,
    )
    db.add(med)
    db.flush()

    for value in times:
        try:
            parsed = datetime.strptime(value, "%H:%M").time()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Horario inválido: {value}.") from exc
        db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=parsed, active=True))

    _set_sos_meta(db, med.id, is_sos)
    _audit(db, user.id, patient_id, "medication.created", "medication", med.id, {"name": med.name, "is_sos": is_sos})
    db.commit()
    return {"id": med.id, "name": med.name, "is_sos": is_sos, "times": times}


@medication_extra_api.get("/patients/{patient_id}/medications/{medication_id}/sos")
def get_medication_sos(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _membership(db, user.id, patient_id)
    med = _medication(db, patient_id, medication_id)
    return {"is_sos": _is_sos(db, med)}


@medication_extra_api.put("/patients/{patient_id}/medications/{medication_id}/sos")
def update_medication_sos(
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
    _set_sos_meta(db, medication_id, is_sos)

    if is_sos:
        for schedule in db.scalars(
            select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id)
        ).all():
            schedule.active = False
        if not med.frequency:
            med.frequency = "SOS / según indicación"

    med.updated_at = now()
    _audit(db, user.id, patient_id, "medication.sos_updated", "medication", medication_id, {"is_sos": is_sos})
    db.commit()
    return {"ok": True, "is_sos": is_sos}


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
    source = med.source

    if source == SOURCE_MARKER:
        key = " ".join(name.strip().casefold().split())[:80]
        tombstone = db.scalar(
            select(CareRecordMeta).where(
                CareRecordMeta.entity_type == "deleted_seed_medication",
                CareRecordMeta.entity_id == patient_id,
                CareRecordMeta.key == key,
            )
        )
        if tombstone:
            tombstone.value = "1"
        else:
            db.add(
                CareRecordMeta(
                    entity_type="deleted_seed_medication",
                    entity_id=patient_id,
                    key=key,
                    value="1",
                )
            )

    # Limpieza explícita para instalaciones donde la FK histórica no tenga cascade físico.
    schedule_ids = db.scalars(
        select(CareMedicationSchedule.id).where(CareMedicationSchedule.medication_id == medication_id)
    ).all()
    if schedule_ids:
        db.execute(delete(CareMedicationLog).where(CareMedicationLog.schedule_id.in_(schedule_ids)))
    db.execute(delete(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id))
    db.execute(delete(CareMedicationEvent).where(CareMedicationEvent.medication_id == medication_id))
    db.execute(delete(MedicationTreatmentHistory).where(MedicationTreatmentHistory.medication_id == medication_id))
    db.execute(delete(MedicationState).where(MedicationState.medication_id == medication_id))
    db.execute(
        delete(CareRecordMeta).where(
            CareRecordMeta.entity_type == "medication",
            CareRecordMeta.entity_id == medication_id,
        )
    )
    db.delete(med)
    _audit(db, user.id, patient_id, "medication.permanently_deleted", "medication", medication_id, {"name": name, "source": source})
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
