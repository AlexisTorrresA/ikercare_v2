from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_medication_extras import _is_sos
from .v2_models import AuditLog, CareMedication, CareMedicationEvent
from .v2_router import _membership

sos_today_api = APIRouter(prefix="/api/v2", tags=["IkerCare SOS today"])


@sos_today_api.get("/patients/{patient_id}/medications-sos-day")
def medications_sos_for_day(
    patient_id: int,
    selected_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Lista medicamentos SOS activos y los usos SOS registrados para el día seleccionado."""
    member = _membership(db, user.id, patient_id)
    medications = db.scalars(
        select(CareMedication)
        .where(CareMedication.patient_id == patient_id, CareMedication.active.is_(True))
        .order_by(CareMedication.name)
    ).all()
    medications = [medication for medication in medications if _is_sos(db, medication)]
    if not medications:
        return {"can_edit": member.role in {"owner", "editor"}, "medications": []}

    audit_rows = db.scalars(
        select(AuditLog).where(
            AuditLog.patient_id == patient_id,
            AuditLog.action == "medication.sos_used",
            AuditLog.entity_type == "medication_event",
        )
    ).all()
    event_ids: list[int] = []
    for row in audit_rows:
        try:
            if row.entity_id is not None:
                event_ids.append(int(row.entity_id))
        except (TypeError, ValueError):
            continue

    uses_by_medication: dict[int, list[dict]] = {medication.id: [] for medication in medications}
    if event_ids:
        start = datetime.combine(selected_date, time.min)
        end = datetime.combine(selected_date, time.max)
        medication_ids = [medication.id for medication in medications]
        events = db.scalars(
            select(CareMedicationEvent)
            .where(
                CareMedicationEvent.id.in_(event_ids),
                CareMedicationEvent.medication_id.in_(medication_ids),
                CareMedicationEvent.occurred_at >= start,
                CareMedicationEvent.occurred_at <= end,
            )
            .order_by(CareMedicationEvent.occurred_at, CareMedicationEvent.id)
        ).all()
        for event in events:
            uses_by_medication.setdefault(event.medication_id, []).append(
                {
                    "id": event.id,
                    "occurred_at": event.occurred_at.isoformat(timespec="minutes"),
                    "notes": event.notes,
                }
            )

    return {
        "can_edit": member.role in {"owner", "editor"},
        "medications": [
            {
                "id": medication.id,
                "name": medication.name,
                "dose": medication.dose,
                "route": medication.route,
                "frequency": medication.frequency,
                "purpose": medication.purpose,
                "uses": uses_by_medication.get(medication.id, []),
            }
            for medication in medications
        ],
    }
