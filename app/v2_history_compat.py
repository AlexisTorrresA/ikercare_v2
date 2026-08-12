from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_clinical_history import MedicationState, MedicationTreatmentHistory, _history_dict
from .v2_models import CareMedication, CareMedicationSchedule
from .v2_router import _audit, _membership, _require_role, now

history_compat_api = APIRouter(prefix="/api/v2", tags=["IkerCare treatment history compatibility"])


def _configured_times(db: Session, medication_id: int, active_only: bool = True) -> list[str]:
    query = select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id)
    if active_only:
        query = query.where(CareMedicationSchedule.active.is_(True))
    rows = db.scalars(query.order_by(CareMedicationSchedule.time_of_day)).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def _latest_history(db: Session, medication_id: int) -> MedicationTreatmentHistory | None:
    return db.scalar(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == medication_id)
        .order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc())
        .limit(1)
    )


def _history_times(row: MedicationTreatmentHistory | None) -> list[str]:
    if not row:
        return []
    try:
        return [str(value) for value in json.loads(row.times_json or "[]")]
    except Exception:
        return []


def _state(db: Session, medication: CareMedication) -> MedicationState:
    row = db.get(MedicationState, medication.id)
    if not row:
        row = MedicationState(
            medication_id=medication.id,
            status="active" if medication.active else "suspended",
            changed_at=medication.updated_at or medication.created_at or now(),
        )
        db.add(row)
        db.flush()
    return row


def _write_snapshot(
    db: Session,
    medication: CareMedication,
    user_id: int,
    *,
    occurred_at: datetime,
    event_type: str,
    status: str,
    times: list[str],
    reason: str | None = None,
    changed_fields: list[str] | None = None,
) -> MedicationTreatmentHistory:
    row = MedicationTreatmentHistory(
        medication_id=medication.id,
        occurred_at=occurred_at,
        event_type=event_type,
        status=status,
        dose=medication.dose,
        route=medication.route,
        frequency=medication.frequency,
        times_json=json.dumps(times, ensure_ascii=False),
        reason=reason,
        changed_fields_json=json.dumps(changed_fields or [], ensure_ascii=False),
        created_by_user_id=user_id,
    )
    db.add(row)
    return row


def _ensure_baseline(db: Session, medication: CareMedication, user_id: int) -> None:
    if db.scalar(select(MedicationTreatmentHistory.id).where(MedicationTreatmentHistory.medication_id == medication.id).limit(1)):
        return
    state = _state(db, medication)
    times = _configured_times(db, medication.id, active_only=True)
    if not times and not medication.active:
        # Para tratamientos antiguos ya suspendidos solo podemos conservar los
        # horarios que aún existen en la BD; no se inventa información previa.
        times = _configured_times(db, medication.id, active_only=False)
    _write_snapshot(
        db,
        medication,
        user_id,
        occurred_at=medication.created_at or now(),
        event_type="initial",
        status=state.status,
        times=times,
    )
    db.flush()


def _replace_schedule(db: Session, medication: CareMedication, wanted_times: list[str], enabled: bool) -> None:
    wanted = set()
    for value in wanted_times:
        try:
            wanted.add(datetime.strptime(value, "%H:%M").time())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Horario inválido: {value}") from exc
    rows = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication.id)).all()
    by_time = {row.time_of_day: row for row in rows}
    for row in rows:
        row.active = enabled and row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=medication.id, time_of_day=value, active=enabled))
    db.flush()


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
    _ensure_baseline(db, medication, user.id)
    db.commit()
    rows = db.scalars(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == medication.id)
        .order_by(MedicationTreatmentHistory.occurred_at, MedicationTreatmentHistory.id)
    ).all()
    return [_history_dict(row) for row in rows]


@history_compat_api.put("/patients/{patient_id}/medications/{medication_id}/history-update")
def medication_history_update(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    medication = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    _ensure_baseline(db, medication, user.id)
    state = _state(db, medication)
    latest = _latest_history(db, medication.id)
    current_times = _history_times(latest) if state.status not in {"active", "resumed"} else _configured_times(db, medication.id, True)
    before = {"dose": medication.dose, "route": medication.route, "frequency": medication.frequency, "times": current_times}

    for field in ("name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"):
        if field in payload:
            setattr(medication, field, payload.get(field))
    wanted_times = [str(value) for value in payload.get("times", current_times)]
    _replace_schedule(db, medication, wanted_times, state.status in {"active", "resumed"})
    if "unit" in payload:
        state.unit = payload.get("unit") or None
    after = {"dose": medication.dose, "route": medication.route, "frequency": medication.frequency, "times": wanted_times}
    changed = [key for key in ("dose", "route", "frequency", "times") if before[key] != after[key]]
    occurred_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    if changed:
        _write_snapshot(db, medication, user.id, occurred_at=occurred_at, event_type="treatment_change", status=state.status, times=wanted_times, changed_fields=changed)
    medication.updated_at = occurred_at
    _audit(db, user.id, patient_id, "medication.history_updated", "medication", medication.id, {"changed": changed})
    db.commit()
    return {"ok": True, "changed_fields": changed}


@history_compat_api.post("/patients/{patient_id}/medications/{medication_id}/status")
def medication_status(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    medication = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    status = str(payload.get("status") or "").lower()
    if status not in {"active", "suspended", "finished", "paused", "resumed"}:
        raise HTTPException(status_code=400, detail="Estado de medicamento inválido.")
    _ensure_baseline(db, medication, user.id)
    state = _state(db, medication)
    latest = _latest_history(db, medication.id)
    configured_times = _history_times(latest)
    if not configured_times:
        configured_times = _configured_times(db, medication.id, active_only=True)
    if not configured_times:
        configured_times = _configured_times(db, medication.id, active_only=False)

    active = status in {"active", "resumed"}
    _replace_schedule(db, medication, configured_times, active)
    occurred_at = datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now()
    reason = str(payload.get("reason") or "").strip() or None
    state.status = status
    state.reason = reason
    state.changed_at = occurred_at
    medication.active = active
    medication.updated_at = occurred_at
    _write_snapshot(db, medication, user.id, occurred_at=occurred_at, event_type="status_change", status=status, times=configured_times, reason=reason, changed_fields=["status"])
    _audit(db, user.id, patient_id, f"medication.status.{status}", "medication", medication.id, {"reason": reason})
    db.commit()
    return {"ok": True, "status": status}
