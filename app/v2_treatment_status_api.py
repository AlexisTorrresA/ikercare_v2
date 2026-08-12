from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .db import get_db
from .models import User
from .v2_clinical_history import MedicationState, MedicationTreatmentHistory, _ensure_initial_snapshot
from .v2_models import CareMedication, CareMedicationSchedule
from .v2_router import _audit, _require_role, now

status_api = APIRouter(prefix="/api/v2", tags=["IkerCare medication status"])


def _configured_times(db: Session, medication_id: int) -> list[str]:
    rows = db.scalars(
        select(CareMedicationSchedule)
        .where(CareMedicationSchedule.medication_id == medication_id)
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def _state(db: Session, med: CareMedication) -> MedicationState:
    row = db.get(MedicationState, med.id)
    if not row:
        row = MedicationState(
            medication_id=med.id,
            status="active" if med.active else "suspended",
            changed_at=med.updated_at or med.created_at or now(),
        )
        db.add(row)
        db.flush()
    return row


def _add_snapshot(db: Session, med: CareMedication, user_id: int, occurred_at: datetime, event_type: str, status: str, times: list[str], reason: str | None = None, changed: list[str] | None = None) -> MedicationTreatmentHistory:
    row = MedicationTreatmentHistory(
        medication_id=med.id,
        occurred_at=occurred_at,
        event_type=event_type,
        status=status,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        times_json=json.dumps(sorted(set(times)), ensure_ascii=False),
        reason=reason,
        changed_fields_json=json.dumps(changed or [], ensure_ascii=False),
        created_by_user_id=user_id,
    )
    db.add(row)
    return row


@status_api.put("/patients/{patient_id}/medications/{medication_id}/history-update-v2")
def history_update_v2(
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
    _ensure_initial_snapshot(db, med, user.id)
    state = _state(db, med)
    before_times = _configured_times(db, med.id)
    before = {"dose": med.dose, "route": med.route, "frequency": med.frequency, "times": before_times}

    for field in ("name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"):
        if field in payload:
            setattr(med, field, payload.get(field))

    wanted_times = sorted(set(payload.get("times") if isinstance(payload.get("times"), list) else before_times))
    wanted = {datetime.strptime(value, "%H:%M").time() for value in wanted_times}
    schedules = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all()
    by_time = {row.time_of_day: row for row in schedules}
    enabled = state.status in {"active", "resumed"}
    for row in schedules:
        row.active = enabled and row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=value, active=enabled))

    occurred_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    after = {"dose": med.dose, "route": med.route, "frequency": med.frequency, "times": wanted_times}
    changed = [field for field in before if before[field] != after[field]]
    if changed:
        _add_snapshot(db, med, user.id, occurred_at, "treatment_change", state.status, wanted_times, changed=changed)
    med.updated_at = occurred_at
    _audit(db, user.id, patient_id, "medication.history_updated", "medication", med.id, {"changed": changed})
    db.commit()
    return {"ok": True, "changed_fields": changed}


@status_api.post("/patients/{patient_id}/medications/{medication_id}/status-v2")
def status_change_v2(
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
    if status not in {"active", "suspended", "finished", "paused", "resumed"}:
        raise HTTPException(status_code=400, detail="Estado de medicamento inválido.")

    _ensure_initial_snapshot(db, med, user.id)
    state = _state(db, med)
    configured_times = _configured_times(db, med.id)
    if not configured_times:
        prior_rows = db.scalars(
            select(MedicationTreatmentHistory)
            .where(MedicationTreatmentHistory.medication_id == med.id)
            .order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc())
        ).all()
        for prior in prior_rows:
            try:
                candidate = json.loads(prior.times_json or "[]")
            except Exception:
                candidate = []
            if candidate:
                configured_times = candidate
                break

    occurred_at = datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now()
    reason = payload.get("reason") or None
    active = status in {"active", "resumed"}
    med.active = active
    wanted = {datetime.strptime(value, "%H:%M").time() for value in configured_times}
    schedules = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all()
    for schedule in schedules:
        schedule.active = active and schedule.time_of_day in wanted

    state.status = status
    state.reason = reason
    state.changed_at = occurred_at
    _add_snapshot(db, med, user.id, occurred_at, "status_change", status, configured_times, reason=reason)
    med.updated_at = occurred_at
    _audit(db, user.id, patient_id, f"medication.status.{status}", "medication", med.id, {"reason": reason})
    db.commit()
    return {"ok": True, "status": status, "active": active}
