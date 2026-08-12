from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import complete_report, complete_report_pdf, medication_history

clinical_compat_api = APIRouter(prefix="/api/v2", tags=["IkerCare clinical compatibility"])


@clinical_compat_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def medication_history_for_ui(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Mantiene el contrato de la interfaz: una lista cronológica de estados/cambios."""
    result = medication_history(patient_id=patient_id, medication_id=medication_id, db=db, user=user)
    return result.get("history", [])


def _add_vital_components(report: dict) -> dict:
    for day in report.get("facts", {}).get("days", []):
        for vital in day.get("vitals", []):
            pressure = vital.get("blood_pressure")
            if pressure and "/" in pressure:
                left, right = pressure.split("/", 1)
                try:
                    vital["systolic"] = int(left)
                    vital["diastolic"] = int(right)
                except ValueError:
                    pass
    return report


@clinical_compat_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report")
def hospital_report_ui(
    patient_id: int,
    hospitalization_id: int,
    use_ai: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return _add_vital_components(
        complete_report(
            patient_id=patient_id,
            hospitalization_id=hospitalization_id,
            use_ai=use_ai,
            db=db,
            user=user,
        )
    )


@clinical_compat_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report.pdf")
def hospital_report_pdf_ui(
    patient_id: int,
    hospitalization_id: int,
    use_ai: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    return complete_report_pdf(
        patient_id=patient_id,
        hospitalization_id=hospitalization_id,
        use_ai=use_ai,
        db=db,
        user=user,
    )
