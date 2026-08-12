from __future__ import annotations

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_models import ClinicalDocument, ClinicalHistoryEvent, Hospitalization
from .v2_router import _membership


timeline_hotfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare timeline"])


@timeline_hotfix_api.get("/patients/{patient_id}/timeline")
def timeline_without_duplicates(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict]:
    _membership(db, user.id, patient_id)
    clauses = [
        ClinicalHistoryEvent.patient_id == patient_id,
        ClinicalHistoryEvent.document_id.is_(None),
        ClinicalHistoryEvent.category != "hospitalization",
    ]
    if start_date:
        clauses.append(ClinicalHistoryEvent.occurred_at >= datetime.combine(start_date, time.min))
    if end_date:
        clauses.append(ClinicalHistoryEvent.occurred_at <= datetime.combine(end_date, time.max))
    events = db.scalars(select(ClinicalHistoryEvent).where(*clauses).order_by(ClinicalHistoryEvent.occurred_at.desc()).limit(limit)).all()

    h_query = select(Hospitalization).where(Hospitalization.patient_id == patient_id)
    if start_date:
        h_query = h_query.where(Hospitalization.admission_at >= datetime.combine(start_date, time.min))
    if end_date:
        h_query = h_query.where(Hospitalization.admission_at <= datetime.combine(end_date, time.max))
    hospitalizations = db.scalars(h_query.order_by(Hospitalization.admission_at.desc()).limit(limit)).all()

    d_query = select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id)
    if start_date:
        d_query = d_query.where((ClinicalDocument.event_date.is_(None)) | (ClinicalDocument.event_date >= start_date))
    if end_date:
        d_query = d_query.where((ClinicalDocument.event_date.is_(None)) | (ClinicalDocument.event_date <= end_date))
    documents = db.scalars(d_query.order_by(ClinicalDocument.event_date.desc().nullslast(), ClinicalDocument.created_at.desc()).limit(limit)).all()

    output = [{
        "id": f"history-{row.id}", "occurred_at": row.occurred_at.isoformat(timespec="minutes"),
        "category": row.category, "title": row.title, "description": row.description,
        "hospital": row.hospital, "document_id": None,
    } for row in events]
    output += [{
        "id": f"hospitalization-{row.id}", "occurred_at": row.admission_at.isoformat(timespec="minutes"),
        "category": "hospitalization", "title": f"Hospitalización · {row.hospital}",
        "description": row.summary or row.reason or row.diagnosis, "hospital": row.hospital,
        "hospitalization_id": row.id,
    } for row in hospitalizations]
    output += [{
        "id": f"document-{row.id}",
        "occurred_at": (datetime.combine(row.event_date, time.min) if row.event_date else row.created_at).isoformat(timespec="minutes"),
        "category": "exam", "title": row.exam_name or row.filename,
        "description": row.extracted_text[:400] if row.extracted_text else None,
        "hospital": row.hospital, "document_id": row.id,
    } for row in documents]
    output.sort(key=lambda item: item["occurred_at"], reverse=True)
    return output[:limit]
