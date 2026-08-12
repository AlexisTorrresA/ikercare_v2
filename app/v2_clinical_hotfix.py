from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import DateTime, ForeignKey, JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import get_current_user, verify_csrf
from .db import Base, get_db
from .models import User
from .v2_clinical_history import (
    MedicationState,
    MedicationTreatmentHistory,
    _ai_narrative,
    _ensure_initial_snapshot,
    _history_dict,
    _hospital_facts,
    _pdf_bytes,
)
from .v2_models import (
    CareMedication,
    CareMedicationSchedule,
    ClinicalDocument,
    ClinicalHistoryEvent,
    Hospitalization,
)
from .v2_router import _audit, _membership, _require_role, now

logger = logging.getLogger("ikercare.clinical_hotfix")
clinical_hotfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare clinical hotfix"])


class HospitalReportSnapshot(Base):
    __tablename__ = "care_hospital_report_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    report_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


def _configured_times(db: Session, medication_id: int) -> list[str]:
    rows = db.scalars(
        select(CareMedicationSchedule)
        .where(CareMedicationSchedule.medication_id == medication_id)
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def _state(db: Session, medication: CareMedication) -> MedicationState:
    state = db.get(MedicationState, medication.id)
    if not state:
        state = MedicationState(
            medication_id=medication.id,
            status="active" if medication.active else "suspended",
            changed_at=medication.updated_at or medication.created_at or now(),
        )
        db.add(state)
        db.flush()
    return state


def _append_snapshot(
    db: Session,
    medication: CareMedication,
    user_id: int,
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
        times_json=json.dumps(sorted(set(times)), ensure_ascii=False),
        reason=reason,
        changed_fields_json=json.dumps(changed_fields or [], ensure_ascii=False),
        created_by_user_id=user_id,
    )
    db.add(row)
    return row


@clinical_hotfix_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def treatment_history_list(
    patient_id: int,
    medication_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Mantiene una respuesta simple para la UI móvil: lista cronológica de cambios."""
    _membership(db, user.id, patient_id)
    medication = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    _ensure_initial_snapshot(db, medication, user.id)
    db.commit()
    rows = db.scalars(
        select(MedicationTreatmentHistory)
        .where(MedicationTreatmentHistory.medication_id == medication_id)
        .order_by(MedicationTreatmentHistory.occurred_at, MedicationTreatmentHistory.id)
    ).all()
    return [_history_dict(row) for row in rows]


@clinical_hotfix_api.put("/patients/{patient_id}/medications/{medication_id}/history-update")
def treatment_update(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    medication = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")

    _ensure_initial_snapshot(db, medication, user.id)
    state = _state(db, medication)
    before_times = _configured_times(db, medication.id)
    before = {
        "dose": medication.dose,
        "route": medication.route,
        "frequency": medication.frequency,
        "times": before_times,
    }

    for field in ("name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"):
        if field in payload:
            setattr(medication, field, payload.get(field))

    wanted_times = payload.get("times") if isinstance(payload.get("times"), list) else before_times
    wanted_times = sorted({str(value).strip() for value in wanted_times if str(value).strip()})
    wanted = set()
    for value in wanted_times:
        try:
            wanted.add(datetime.strptime(value, "%H:%M").time())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Horario inválido: {value}.") from exc

    schedules = db.scalars(
        select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication.id)
    ).all()
    by_time = {row.time_of_day: row for row in schedules}
    enabled = state.status in {"active", "resumed"}
    for row in schedules:
        row.active = enabled and row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=medication.id, time_of_day=value, active=enabled))

    after = {
        "dose": medication.dose,
        "route": medication.route,
        "frequency": medication.frequency,
        "times": wanted_times,
    }
    changed = [field for field in before if before[field] != after[field]]
    occurred_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    if changed:
        _append_snapshot(db, medication, user.id, occurred_at, "treatment_change", state.status, wanted_times, changed_fields=changed)
    medication.updated_at = occurred_at
    _audit(db, user.id, patient_id, "medication.history_updated", "medication", medication.id, {"changed": changed})
    db.commit()
    return {"ok": True, "changed_fields": changed}


@clinical_hotfix_api.post("/patients/{patient_id}/medications/{medication_id}/status")
def treatment_status(
    patient_id: int,
    medication_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    medication = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"active", "suspended", "finished", "paused", "resumed"}:
        raise HTTPException(status_code=400, detail="Estado de medicamento inválido.")

    _ensure_initial_snapshot(db, medication, user.id)
    state = _state(db, medication)
    times = _configured_times(db, medication.id)
    if not times:
        previous = db.scalars(
            select(MedicationTreatmentHistory)
            .where(MedicationTreatmentHistory.medication_id == medication.id)
            .order_by(MedicationTreatmentHistory.occurred_at.desc(), MedicationTreatmentHistory.id.desc())
        ).all()
        for revision in previous:
            try:
                candidate = json.loads(revision.times_json or "[]")
            except Exception:
                candidate = []
            if candidate:
                times = candidate
                break

    occurred_at = datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now()
    reason = str(payload.get("reason") or "").strip() or None
    active = status in {"active", "resumed"}
    medication.active = active
    wanted = {datetime.strptime(value, "%H:%M").time() for value in times}
    schedules = db.scalars(
        select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication.id)
    ).all()
    for schedule in schedules:
        schedule.active = active and schedule.time_of_day in wanted
    state.status = status
    state.reason = reason
    state.changed_at = occurred_at
    _append_snapshot(db, medication, user.id, occurred_at, "status_change", status, times, reason=reason)
    medication.updated_at = occurred_at
    _audit(db, user.id, patient_id, f"medication.status.{status}", "medication", medication.id, {"reason": reason})
    db.commit()
    return {"ok": True, "status": status, "active": active}


@clinical_hotfix_api.put("/patients/{patient_id}/documents/{document_id}")
def update_document_without_duplicate(
    patient_id: int,
    document_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    document = db.scalar(
        select(ClinicalDocument).where(
            ClinicalDocument.id == document_id,
            ClinicalDocument.patient_id == patient_id,
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    if "exam_name" in payload:
        document.exam_name = str(payload.get("exam_name") or "").strip()[:220] or None
    if "document_type" in payload:
        document.document_type = str(payload.get("document_type") or "exam")[:80]
    if "hospital" in payload:
        document.hospital = str(payload.get("hospital") or "").strip()[:220] or None
    if "event_date" in payload:
        document.event_date = date.fromisoformat(payload["event_date"]) if payload.get("event_date") else None
    if "hospitalization_id" in payload:
        hospital_id = int(payload["hospitalization_id"]) if payload.get("hospitalization_id") else None
        if hospital_id and not db.scalar(
            select(Hospitalization.id).where(
                Hospitalization.id == hospital_id,
                Hospitalization.patient_id == patient_id,
            )
        ):
            raise HTTPException(status_code=400, detail="Hospitalización inválida.")
        document.hospitalization_id = hospital_id

    history_rows = db.scalars(
        select(ClinicalHistoryEvent)
        .where(
            ClinicalHistoryEvent.patient_id == patient_id,
            ClinicalHistoryEvent.document_id == document.id,
        )
        .order_by(ClinicalHistoryEvent.id)
    ).all()
    occurred_at = datetime.combine(document.event_date, time.min) if document.event_date else document.created_at
    if history_rows:
        primary = history_rows[0]
        primary.title = document.exam_name or document.filename
        primary.hospital = document.hospital
        primary.description = document.extracted_text[:800] if document.extracted_text else None
        primary.occurred_at = occurred_at
        for duplicate in history_rows[1:]:
            db.delete(duplicate)
    else:
        db.add(
            ClinicalHistoryEvent(
                patient_id=patient_id,
                occurred_at=occurred_at,
                category="exam",
                title=document.exam_name or document.filename,
                description=document.extracted_text[:800] if document.extracted_text else None,
                hospital=document.hospital,
                document_id=document.id,
                created_by_user_id=user.id,
            )
        )
    _audit(db, user.id, patient_id, "document.updated", "document", document.id)
    db.commit()
    return {"ok": True, "id": document.id}


@clinical_hotfix_api.get("/patients/{patient_id}/timeline")
def timeline_without_exam_duplicates(
    patient_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    _membership(db, user.id, patient_id)
    limit = min(max(limit, 1), 500)
    clauses = [ClinicalHistoryEvent.patient_id == patient_id, ClinicalHistoryEvent.document_id.is_(None)]
    if start_date:
        clauses.append(ClinicalHistoryEvent.occurred_at >= datetime.combine(start_date, time.min))
    if end_date:
        clauses.append(ClinicalHistoryEvent.occurred_at <= datetime.combine(end_date, time.max))
    events = db.scalars(
        select(ClinicalHistoryEvent).where(*clauses).order_by(ClinicalHistoryEvent.occurred_at.desc()).limit(limit)
    ).all()
    hospitals = db.scalars(
        select(Hospitalization).where(Hospitalization.patient_id == patient_id).order_by(Hospitalization.admission_at.desc()).limit(limit)
    ).all()
    documents = db.scalars(
        select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id).order_by(ClinicalDocument.event_date.desc().nullslast(), ClinicalDocument.created_at.desc()).limit(limit)
    ).all()

    output = [
        {"id": f"history-{row.id}", "occurred_at": row.occurred_at.isoformat(timespec="minutes"), "category": row.category, "title": row.title, "description": row.description, "hospital": row.hospital, "document_id": None}
        for row in events
    ]
    output += [
        {"id": f"hospitalization-{row.id}", "occurred_at": row.admission_at.isoformat(timespec="minutes"), "category": "hospitalization", "title": f"Hospitalización · {row.hospital}", "description": row.summary or row.reason or row.diagnosis, "hospital": row.hospital, "hospitalization_id": row.id}
        for row in hospitals
    ]
    for row in documents:
        occurred_at = datetime.combine(row.event_date, time.min) if row.event_date else row.created_at
        if start_date and occurred_at < datetime.combine(start_date, time.min):
            continue
        if end_date and occurred_at > datetime.combine(end_date, time.max):
            continue
        output.append({"id": f"document-{row.id}", "occurred_at": occurred_at.isoformat(timespec="minutes"), "category": "exam", "title": row.exam_name or row.filename, "description": row.extracted_text[:400] if row.extracted_text else None, "hospital": row.hospital, "document_id": row.id})
    output.sort(key=lambda item: item["occurred_at"], reverse=True)
    return output[:limit]


@clinical_hotfix_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report")
def hospitalization_report(
    patient_id: int,
    hospitalization_id: int,
    use_ai: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _membership(db, user.id, patient_id)
    try:
        facts = _hospital_facts(db, patient_id, hospitalization_id)
        narrative, ai_used, message = _ai_narrative(facts) if use_ai else (None, False, None)
        if narrative is None:
            from .v2_clinical_history import _local_narrative
            narrative = _local_narrative(facts)
        report = {"facts": facts, "statistics": facts["statistics"], "narrative": narrative, "ai_used": ai_used, "ai_message": message}
        snapshot_id = secrets.token_urlsafe(24)
        db.add(HospitalReportSnapshot(id=snapshot_id, patient_id=patient_id, hospitalization_id=hospitalization_id, user_id=user.id, report_json=report))
        cutoff = now() - timedelta(days=2)
        for old in db.scalars(select(HospitalReportSnapshot).where(HospitalReportSnapshot.created_at < cutoff)).all():
            db.delete(old)
        db.commit()
        return {**report, "report_id": snapshot_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hospital report failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No fue posible generar el informe. Inténtalo nuevamente.") from exc


@clinical_hotfix_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report.pdf")
def hospitalization_report_pdf(
    patient_id: int,
    hospitalization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _membership(db, user.id, patient_id)
    try:
        snapshot = db.scalar(
            select(HospitalReportSnapshot)
            .where(
                HospitalReportSnapshot.patient_id == patient_id,
                HospitalReportSnapshot.hospitalization_id == hospitalization_id,
                HospitalReportSnapshot.user_id == user.id,
                HospitalReportSnapshot.created_at >= now() - timedelta(minutes=30),
            )
            .order_by(HospitalReportSnapshot.created_at.desc())
            .limit(1)
        )
        if snapshot:
            report = snapshot.report_json
        else:
            from .v2_clinical_history import _local_narrative
            facts = _hospital_facts(db, patient_id, hospitalization_id)
            report = {"facts": facts, "statistics": facts["statistics"], "narrative": _local_narrative(facts), "ai_used": False, "ai_message": "PDF generado sin repetir la llamada de IA."}
        data = _pdf_bytes(report)
        filename = f"IkerCare-hospitalizacion-{hospitalization_id}.pdf"
        return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Length": str(len(data)), "Cache-Control": "private, no-store"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hospital PDF failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No fue posible descargar el PDF. Inténtalo nuevamente.") from exc
