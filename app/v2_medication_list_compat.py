from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import MedicationState
from .v2_models import CareMedication, CareMedicationSchedule
from .v2_router import _membership

medication_list_compat_api = APIRouter(prefix="/api/v2", tags=["IkerCare medication compatibility"])


@medication_list_compat_api.get("/patients/{patient_id}/medications")
def list_medications_with_configured_times(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Lista la configuración de medicamentos sin modificar la base de datos.

    Esta ruta se usa desde la pantalla "Administrar medicamentos" y puede ejecutarse
    varias veces desde el navegador. Mantenerla de solo lectura evita carreras al
    inicializar estados/historial y reduce drásticamente los viajes a PostgreSQL.
    """
    _membership(db, user.id, patient_id)
    medications = db.scalars(
        select(CareMedication)
        .where(CareMedication.patient_id == patient_id)
        .order_by(CareMedication.active.desc(), CareMedication.name)
    ).all()
    if not medications:
        return []

    medication_ids = [medication.id for medication in medications]

    states = {
        state.medication_id: state
        for state in db.scalars(
            select(MedicationState).where(MedicationState.medication_id.in_(medication_ids))
        ).all()
    }

    schedules_by_medication: dict[int, list[CareMedicationSchedule]] = defaultdict(list)
    schedules = db.scalars(
        select(CareMedicationSchedule)
        .where(CareMedicationSchedule.medication_id.in_(medication_ids))
        .order_by(CareMedicationSchedule.medication_id, CareMedicationSchedule.time_of_day)
    ).all()
    for schedule in schedules:
        schedules_by_medication[schedule.medication_id].append(schedule)

    result = []
    for medication in medications:
        state = states.get(medication.id)
        configured_schedules = schedules_by_medication.get(medication.id, [])
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
            "times": [row.time_of_day.strftime("%H:%M") for row in configured_schedules],
            "treatment_status": state.status if state else ("active" if medication.active else "suspended"),
            "status_reason": state.reason if state else None,
        })
    return result
