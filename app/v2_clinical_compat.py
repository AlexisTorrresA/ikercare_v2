from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import complete_report, complete_report_pdf, medication_history
from .v2_models import ClinicalDocument, ClinicalHistoryEvent, Hospitalization
from .v2_router import _membership

clinical_compat_api = APIRouter(prefix="/api/v2", tags=["IkerCare clinical compatibility"])


@clinical_compat_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def medication_history_for_ui(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Mantiene el contrato móvil como lista cronológica de cambios."""
    result = medication_history(patient_id=patient_id, medication_id=medication_id, db=db, user=user)
    return result.get("history", [])


@clinical_compat_api.get("/patients/{patient_id}/timeline")
def timeline_without_exam_duplicates(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict]:
    """Muestra cada examen una sola vez y conserva hospitalizaciones/hitos existentes."""
    _membership(db, user.id, patient_id)
    event_clauses = [
        ClinicalHistoryEvent.patient_id == patient_id,
        ClinicalHistoryEvent.document_id.is_(None),
        ClinicalHistoryEvent.category != "hospitalization",
    ]
    if start_date:
        event_clauses.append(ClinicalHistoryEvent.occurred_at >= datetime.combine(start_date, time.min))
    if end_date:
        event_clauses.append(ClinicalHistoryEvent.occurred_at <= datetime.combine(end_date, time.max))
    events = db.scalars(
        select(ClinicalHistoryEvent)
        .where(*event_clauses)
        .order_by(ClinicalHistoryEvent.occurred_at.desc())
        .limit(limit)
    ).all()

    hospital_query = select(Hospitalization).where(Hospitalization.patient_id == patient_id)
    if start_date:
        hospital_query = hospital_query.where(Hospitalization.admission_at >= datetime.combine(start_date, time.min))
    if end_date:
        hospital_query = hospital_query.where(Hospitalization.admission_at <= datetime.combine(end_date, time.max))
    hospitals = db.scalars(hospital_query.order_by(Hospitalization.admission_at.desc()).limit(limit)).all()

    document_query = select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id)
    documents = db.scalars(
        document_query.order_by(ClinicalDocument.event_date.desc().nullslast(), ClinicalDocument.created_at.desc()).limit(limit)
    ).all()

    output = [
        {
            "id": f"history-{row.id}",
            "occurred_at": row.occurred_at.isoformat(timespec="minutes"),
            "category": row.category,
            "title": row.title,
            "description": row.description,
            "hospital": row.hospital,
            "document_id": None,
        }
        for row in events
    ]
    output += [
        {
            "id": f"hospitalization-{row.id}",
            "occurred_at": row.admission_at.isoformat(timespec="minutes"),
            "category": "hospitalization",
            "title": f"Hospitalización · {row.hospital}",
            "description": row.summary or row.reason or row.diagnosis,
            "hospital": row.hospital,
            "hospitalization_id": row.id,
        }
        for row in hospitals
    ]
    for row in documents:
        occurred_at = datetime.combine(row.event_date, time.min) if row.event_date else row.created_at
        if start_date and occurred_at < datetime.combine(start_date, time.min):
            continue
        if end_date and occurred_at > datetime.combine(end_date, time.max):
            continue
        output.append({
            "id": f"document-{row.id}",
            "occurred_at": occurred_at.isoformat(timespec="minutes"),
            "category": "exam",
            "title": row.exam_name or row.filename,
            "description": row.extracted_text[:400] if row.extracted_text else None,
            "hospital": row.hospital,
            "document_id": row.id,
        })
    output.sort(key=lambda item: item["occurred_at"], reverse=True)
    return output[:limit]


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
