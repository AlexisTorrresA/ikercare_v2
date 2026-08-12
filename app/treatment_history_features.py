from __future__ import annotations

import json
import logging
import os
import textwrap
from datetime import date, datetime, time
from statistics import mean
from typing import Optional

import fitz
import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, LargeBinary, String, Text, UniqueConstraint, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import get_current_user, verify_csrf
from .crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from .db import Base, get_db
from .document_processing import extract_text, safe_filename, validate_upload
from .medical_catalog import normalize, search_medications
from .models import User
from .v2_models import (
    CareChemoSession,
    CareCrisisEvent,
    CareDailyNote,
    CareMedication,
    CareMedicationLog,
    CareMedicationSchedule,
    CareVitalRecord,
    ClinicalDocument,
    ClinicalHistoryEvent,
    EliminationLog,
    FoodLog,
    Hospitalization,
    Patient,
)
from .v2_router import _audit, _membership, _require_role, now

logger = logging.getLogger("ikercare.treatment_history")
features_api = APIRouter(prefix="/api/v2", tags=["IkerCare treatment history"])


class MedicationRevision(Base):
    __tablename__ = "care_medication_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(40), default="changed")
    treatment_status: Mapped[str] = mapped_column(String(30), default="active")
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    medication_type: Mapped[str] = mapped_column(String(120), default="Medicamento")
    purpose: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    dose: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    times_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChemoEvolutionEvent(Base):
    __tablename__ = "care_chemo_evolution_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    chemo_session_id: Mapped[int] = mapped_column(ForeignKey("care_chemo_sessions.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClinicalDocumentAsset(Base):
    __tablename__ = "care_clinical_document_assets"
    __table_args__ = (UniqueConstraint("document_id", "position", name="uq_care_document_asset_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("care_clinical_documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(40), default="pending")
    extraction_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HospitalRecordLink(Base):
    __tablename__ = "care_hospital_record_links"
    __table_args__ = (UniqueConstraint("patient_id", "entity_type", "entity_id", name="uq_care_hospital_record_link"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str] = mapped_column(String(80), index=True)
    occurred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LearnedMedication(Base):
    __tablename__ = "care_learned_medications"
    __table_args__ = (UniqueConstraint("normalized_name", name="uq_care_learned_medication"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(180), index=True)
    name: Mapped[str] = mapped_column(String(180))
    medication_type: Mapped[str] = mapped_column(String(140), default="Medicamento")
    purpose: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    usual_route: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    usual_unit: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


STATUS_VALUES = {"active", "suspended", "finished", "paused", "resumed"}


def _med_times(db: Session, medication_id: int) -> list[str]:
    rows = db.scalars(
        select(CareMedicationSchedule)
        .where(CareMedicationSchedule.medication_id == medication_id, CareMedicationSchedule.active.is_(True))
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def _latest_revision(db: Session, medication_id: int) -> MedicationRevision | None:
    return db.scalar(
        select(MedicationRevision)
        .where(MedicationRevision.medication_id == medication_id)
        .order_by(MedicationRevision.effective_at.desc(), MedicationRevision.id.desc())
        .limit(1)
    )


def _ensure_initial_revision(db: Session, med: CareMedication, actor_user_id: int | None = None) -> MedicationRevision:
    existing = db.scalar(select(MedicationRevision).where(MedicationRevision.medication_id == med.id).order_by(MedicationRevision.effective_at.asc()).limit(1))
    if existing:
        return existing
    row = MedicationRevision(
        patient_id=med.patient_id,
        medication_id=med.id,
        effective_at=med.created_at or now(),
        event_type="created",
        treatment_status="active" if med.active else "suspended",
        name=med.name,
        medication_type=med.medication_type,
        purpose=med.purpose,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        instructions=med.instructions,
        times_json=_med_times(db, med.id),
        created_by_user_id=actor_user_id or med.created_by_user_id,
    )
    db.add(row)
    db.flush()
    return row


def _revision_json(row: MedicationRevision, effective_to: datetime | None = None) -> dict:
    return {
        "id": row.id,
        "effective_at": row.effective_at.isoformat(timespec="minutes"),
        "effective_to": effective_to.isoformat(timespec="minutes") if effective_to else None,
        "event_type": row.event_type,
        "treatment_status": row.treatment_status,
        "reason": row.reason,
        "name": row.name,
        "medication_type": row.medication_type,
        "purpose": row.purpose,
        "dose": row.dose,
        "route": row.route,
        "frequency": row.frequency,
        "instructions": row.instructions,
        "times": row.times_json or [],
    }


def _snapshot_at(db: Session, medication_id: int, moment: datetime) -> MedicationRevision | None:
    return db.scalar(
        select(MedicationRevision)
        .where(MedicationRevision.medication_id == medication_id, MedicationRevision.effective_at <= moment)
        .order_by(MedicationRevision.effective_at.desc(), MedicationRevision.id.desc())
        .limit(1)
    )


def _hospital_for_time(db: Session, patient_id: int, occurred_at: datetime | None) -> Hospitalization | None:
    if not occurred_at:
        return None
    return db.scalar(
        select(Hospitalization)
        .where(
            Hospitalization.patient_id == patient_id,
            Hospitalization.admission_at <= occurred_at,
            or_(Hospitalization.discharge_at.is_(None), Hospitalization.discharge_at >= occurred_at),
        )
        .order_by(Hospitalization.admission_at.desc())
        .limit(1)
    )


def _associate(db: Session, patient_id: int, entity_type: str, entity_id: int | str, occurred_at: datetime | None, hospitalization_id: int | None = None) -> None:
    hospital = db.scalar(select(Hospitalization).where(Hospitalization.id == hospitalization_id, Hospitalization.patient_id == patient_id)) if hospitalization_id else _hospital_for_time(db, patient_id, occurred_at)
    if not hospital:
        return
    row = db.scalar(
        select(HospitalRecordLink).where(
            HospitalRecordLink.patient_id == patient_id,
            HospitalRecordLink.entity_type == entity_type,
            HospitalRecordLink.entity_id == str(entity_id),
        )
    )
    if row:
        row.hospitalization_id = hospital.id
        row.occurred_at = occurred_at
    else:
        db.add(HospitalRecordLink(patient_id=patient_id, hospitalization_id=hospital.id, entity_type=entity_type, entity_id=str(entity_id), occurred_at=occurred_at))


@features_api.get("/patients/{patient_id}/medication-treatments")
def list_medication_treatments(patient_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    meds = db.scalars(select(CareMedication).where(CareMedication.patient_id == patient_id).order_by(CareMedication.name)).all()
    output = []
    changed = False
    for med in meds:
        if not _latest_revision(db, med.id):
            _ensure_initial_revision(db, med, user.id)
            changed = True
        latest = _latest_revision(db, med.id)
        output.append({
            "id": med.id,
            "name": med.name,
            "generic_name": med.generic_name,
            "medication_type": med.medication_type,
            "purpose": med.purpose,
            "dose": med.dose,
            "route": med.route,
            "frequency": med.frequency,
            "instructions": med.instructions,
            "times": _med_times(db, med.id),
            "active": med.active,
            "treatment_status": latest.treatment_status if latest else ("active" if med.active else "suspended"),
            "status_reason": latest.reason if latest else None,
        })
    if changed:
        db.commit()
    return output


@features_api.get("/patients/{patient_id}/medications/{medication_id}/history")
def medication_history(patient_id: int, medication_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    _ensure_initial_revision(db, med, user.id)
    db.commit()
    rows = db.scalars(select(MedicationRevision).where(MedicationRevision.medication_id == medication_id).order_by(MedicationRevision.effective_at.asc(), MedicationRevision.id.asc())).all()
    return [_revision_json(row, rows[index + 1].effective_at if index + 1 < len(rows) else None) for index, row in enumerate(rows)]


@features_api.post("/patients/{patient_id}/medications/enhanced", status_code=201)
def create_medication_with_history(
    patient_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Ingresa el nombre del medicamento.")
    times = sorted({str(value).strip() for value in payload.get("times", []) if str(value).strip()})
    for value in times:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Horario inválido: {value}.") from exc
    med = CareMedication(
        patient_id=patient_id,
        name=name[:160],
        generic_name=payload.get("generic_name") or None,
        medication_type=str(payload.get("medication_type") or "Medicamento")[:120],
        purpose=payload.get("purpose") or None,
        dose=payload.get("dose") or None,
        route=payload.get("route") or None,
        frequency=payload.get("frequency") or None,
        instructions=payload.get("instructions") or None,
        active=True,
        source=str(payload.get("source") or "manual")[:40],
        created_by_user_id=user.id,
    )
    db.add(med)
    db.flush()
    for value in times:
        db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=datetime.strptime(value, "%H:%M").time(), active=True))
    effective_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    revision = MedicationRevision(
        patient_id=patient_id,
        medication_id=med.id,
        effective_at=effective_at,
        event_type="created",
        treatment_status="active",
        reason=payload.get("reason") or None,
        name=med.name,
        medication_type=med.medication_type,
        purpose=med.purpose,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        instructions=med.instructions,
        times_json=times,
        created_by_user_id=user.id,
    )
    db.add(revision)
    db.flush()
    _associate(db, patient_id, "medication_revision", revision.id, effective_at, payload.get("hospitalization_id"))
    _audit(db, user.id, patient_id, "medication.created_with_history", "medication", med.id, {"name": med.name})
    db.commit()
    return {"id": med.id, "treatment_status": "active"}


@features_api.put("/patients/{patient_id}/medications/{medication_id}/treatment")
def update_medication_treatment(
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
    _ensure_initial_revision(db, med, user.id)
    latest = _latest_revision(db, med.id)
    status_value = str(payload.get("treatment_status") or (latest.treatment_status if latest else ("active" if med.active else "suspended"))).strip().lower()
    if status_value not in STATUS_VALUES:
        raise HTTPException(status_code=400, detail="Estado de tratamiento inválido.")
    old = {
        "name": med.name,
        "medication_type": med.medication_type,
        "purpose": med.purpose,
        "dose": med.dose,
        "route": med.route,
        "frequency": med.frequency,
        "instructions": med.instructions,
        "times": _med_times(db, med.id),
    }
    new_values = {
        "name": str(payload.get("name", med.name) or med.name).strip()[:160],
        "medication_type": str(payload.get("medication_type", med.medication_type) or "Medicamento").strip()[:120],
        "purpose": payload.get("purpose", med.purpose) or None,
        "dose": payload.get("dose", med.dose) or None,
        "route": payload.get("route", med.route) or None,
        "frequency": payload.get("frequency", med.frequency) or None,
        "instructions": payload.get("instructions", med.instructions) or None,
    }
    times = payload.get("times", old["times"])
    times = sorted({str(value).strip() for value in times if str(value).strip()})
    for value in times:
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Horario inválido: {value}.") from exc
    field_changed = any(old[key] != new_values[key] for key in new_values) or old["times"] != times
    status_changed = not latest or latest.treatment_status != status_value
    reason = str(payload.get("reason") or "").strip() or None
    if not field_changed and not status_changed and not reason:
        return {"ok": True, "changed": False, "treatment_status": status_value}

    med.name = new_values["name"]
    med.medication_type = new_values["medication_type"]
    med.purpose = new_values["purpose"]
    med.dose = new_values["dose"]
    med.route = new_values["route"]
    med.frequency = new_values["frequency"]
    med.instructions = new_values["instructions"]
    med.active = status_value in {"active", "resumed"}
    med.updated_at = now()

    existing = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all()
    wanted = {datetime.strptime(value, "%H:%M").time() for value in times}
    by_time = {row.time_of_day: row for row in existing}
    for row in existing:
        row.active = med.active and row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=value, active=med.active))

    effective_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    event_type = status_value if status_changed else "changed"
    revision = MedicationRevision(
        patient_id=patient_id,
        medication_id=med.id,
        effective_at=effective_at,
        event_type=event_type,
        treatment_status=status_value,
        reason=reason,
        name=med.name,
        medication_type=med.medication_type,
        purpose=med.purpose,
        dose=med.dose,
        route=med.route,
        frequency=med.frequency,
        instructions=med.instructions,
        times_json=times,
        created_by_user_id=user.id,
    )
    db.add(revision)
    db.flush()
    _associate(db, patient_id, "medication_revision", revision.id, effective_at, payload.get("hospitalization_id"))
    _audit(db, user.id, patient_id, "medication.treatment_changed", "medication", med.id, {"status": status_value, "fields_changed": field_changed})
    db.commit()
    return {"ok": True, "changed": True, "revision_id": revision.id, "treatment_status": status_value}


@features_api.get("/patients/{patient_id}/chemo/{chemo_id}/events")
def list_chemo_events(patient_id: int, chemo_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    chemo = db.scalar(select(CareChemoSession).where(CareChemoSession.id == chemo_id, CareChemoSession.patient_id == patient_id))
    if not chemo:
        raise HTTPException(status_code=404, detail="Quimioterapia no encontrada.")
    rows = db.scalars(select(ChemoEvolutionEvent).where(ChemoEvolutionEvent.chemo_session_id == chemo_id).order_by(ChemoEvolutionEvent.occurred_at.asc())).all()
    return [{"id": row.id, "occurred_at": row.occurred_at.isoformat(timespec="minutes"), "event_type": row.event_type, "description": row.description} for row in rows]


@features_api.post("/patients/{patient_id}/chemo/{chemo_id}/events", status_code=201)
def create_chemo_event(
    patient_id: int,
    chemo_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    chemo = db.scalar(select(CareChemoSession).where(CareChemoSession.id == chemo_id, CareChemoSession.patient_id == patient_id))
    if not chemo:
        raise HTTPException(status_code=404, detail="Quimioterapia no encontrada.")
    description = str(payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Describe brevemente el evento.")
    occurred_at = datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now()
    row = ChemoEvolutionEvent(
        patient_id=patient_id,
        chemo_session_id=chemo_id,
        occurred_at=occurred_at,
        event_type=str(payload.get("event_type") or "Otro").strip()[:100],
        description=description,
        created_by_user_id=user.id,
    )
    db.add(row)
    db.flush()
    _associate(db, patient_id, "chemo_event", row.id, occurred_at, payload.get("hospitalization_id"))
    _audit(db, user.id, patient_id, "chemo.evolution_created", "chemo_event", row.id, {"chemo_id": chemo_id})
    db.commit()
    return {"id": row.id}


@features_api.delete("/patients/{patient_id}/chemo/{chemo_id}/events/{event_id}")
def delete_chemo_event(patient_id: int, chemo_id: int, event_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    row = db.scalar(select(ChemoEvolutionEvent).where(ChemoEvolutionEvent.id == event_id, ChemoEvolutionEvent.chemo_session_id == chemo_id, ChemoEvolutionEvent.patient_id == patient_id))
    if not row:
        raise HTTPException(status_code=404, detail="Evento de quimioterapia no encontrado.")
    db.delete(row)
    db.commit()
    return {"ok": True}


def _extract_one(data: bytes, mime: str) -> tuple[str, str, str | None]:
    try:
        text_value, status_value, error_value = extract_text(data, mime)
        return text_value or "", status_value, error_value
    except Exception as exc:
        logger.exception("Document extraction failed for one image")
        return "", "failed", exc.__class__.__name__


@features_api.post("/patients/{patient_id}/documents/bundle", status_code=201)
async def upload_document_bundle(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
    files: list[UploadFile] = File(...),
    document_type: str = Form("exam"),
    exam_name: str | None = Form(None),
    hospital: str | None = Form(None),
    event_date: date | None = Form(None),
    hospitalization_id: int | None = Form(None),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    if not files or len(files) > 10:
        raise HTTPException(status_code=400, detail="Selecciona entre 1 y 10 imágenes o archivos.")
    if hospitalization_id:
        hospitalization = db.scalar(select(Hospitalization).where(Hospitalization.id == hospitalization_id, Hospitalization.patient_id == patient_id))
        if not hospitalization:
            raise HTTPException(status_code=400, detail="Hospitalización inválida.")

    prepared = []
    for position, upload in enumerate(files, start=1):
        data = await upload.read()
        mime = upload.content_type or "application/octet-stream"
        filename = safe_filename(upload.filename or f"archivo-{position}")
        try:
            validate_upload(filename, mime, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Archivo {position}: {exc}") from exc
        extracted, extraction_status, extraction_error = _extract_one(data, mime)
        prepared.append({"position": position, "filename": filename, "mime": mime, "data": data, "sha": sha256_hex(data), "text": extracted, "status": extraction_status, "error": extraction_error})

    first = prepared[0]
    merged = []
    extracted_count = 0
    for item in prepared:
        if item["text"]:
            extracted_count += 1
            merged.append(f"--- Imagen/archivo {item['position']}: {item['filename']} ---\n{item['text']}")
        else:
            merged.append(f"--- Imagen/archivo {item['position']}: {item['filename']} ---\n[Sin texto extraído]")
    aggregate_status = "text_extracted" if extracted_count == len(prepared) else ("partial" if extracted_count else "failed")
    errors = [f"{item['filename']}: {item['error']}" for item in prepared if item["error"]]
    document = ClinicalDocument(
        patient_id=patient_id,
        hospitalization_id=hospitalization_id,
        event_date=event_date,
        document_type=document_type[:80],
        exam_name=(exam_name or "")[:220] or None,
        hospital=(hospital or "")[:220] or None,
        filename=first["filename"],
        mime_type=first["mime"],
        size_bytes=sum(len(item["data"]) for item in prepared),
        sha256=first["sha"],
        encrypted_data=encrypt_bytes(first["data"], f"clinical-document:{patient_id}".encode()),
        extracted_text="\n\n".join(merged),
        extraction_status=aggregate_status,
        extraction_error="; ".join(errors) or None,
        uploaded_by_user_id=user.id,
    )
    db.add(document)
    db.flush()
    for item in prepared:
        db.add(ClinicalDocumentAsset(
            document_id=document.id,
            position=item["position"],
            filename=item["filename"],
            mime_type=item["mime"],
            size_bytes=len(item["data"]),
            sha256=item["sha"],
            encrypted_data=encrypt_bytes(item["data"], f"clinical-document-asset:{document.id}".encode()),
            extracted_text=item["text"] or None,
            extraction_status=item["status"],
            extraction_error=item["error"],
        ))
    occurred_at = datetime.combine(event_date, time.min) if event_date else now()
    history = ClinicalHistoryEvent(
        patient_id=patient_id,
        occurred_at=occurred_at,
        category="exam",
        title=exam_name or first["filename"],
        description=(document.extracted_text[:800] if document.extracted_text else None),
        hospital=hospital,
        document_id=document.id,
        created_by_user_id=user.id,
    )
    db.add(history)
    _associate(db, patient_id, "document", document.id, occurred_at, hospitalization_id)
    _audit(db, user.id, patient_id, "document.bundle_uploaded", "document", document.id, {"files": len(prepared), "status": aggregate_status})
    db.commit()
    return {"id": document.id, "files_processed": len(prepared), "files_with_text": extracted_count, "extraction_status": aggregate_status}


@features_api.get("/patients/{patient_id}/documents/{document_id}/details")
def document_details(patient_id: int, document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    document = db.scalar(select(ClinicalDocument).where(ClinicalDocument.id == document_id, ClinicalDocument.patient_id == patient_id))
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    assets = db.scalars(select(ClinicalDocumentAsset).where(ClinicalDocumentAsset.document_id == document_id).order_by(ClinicalDocumentAsset.position)).all()
    return {
        "id": document.id,
        "document_type": document.document_type,
        "exam_name": document.exam_name,
        "hospital": document.hospital,
        "event_date": document.event_date.isoformat() if document.event_date else None,
        "hospitalization_id": document.hospitalization_id,
        "extracted_text": document.extracted_text,
        "extraction_status": document.extraction_status,
        "assets": [{"id": item.id, "position": item.position, "filename": item.filename, "mime_type": item.mime_type, "extraction_status": item.extraction_status, "extracted_text": item.extracted_text} for item in assets],
    }


@features_api.put("/patients/{patient_id}/documents/{document_id}/metadata")
def update_document_metadata(
    patient_id: int,
    document_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(verify_csrf),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    document = db.scalar(select(ClinicalDocument).where(ClinicalDocument.id == document_id, ClinicalDocument.patient_id == patient_id))
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    if "document_type" in payload:
        document.document_type = str(payload.get("document_type") or "exam")[:80]
    if "exam_name" in payload:
        document.exam_name = str(payload.get("exam_name") or "").strip()[:220] or None
    if "hospital" in payload:
        document.hospital = str(payload.get("hospital") or "").strip()[:220] or None
    if "event_date" in payload:
        document.event_date = date.fromisoformat(payload["event_date"]) if payload.get("event_date") else None
    if "hospitalization_id" in payload:
        value = payload.get("hospitalization_id")
        if value:
            hospitalization = db.scalar(select(Hospitalization).where(Hospitalization.id == int(value), Hospitalization.patient_id == patient_id))
            if not hospitalization:
                raise HTTPException(status_code=400, detail="Hospitalización inválida.")
            document.hospitalization_id = hospitalization.id
        else:
            document.hospitalization_id = None
    occurred_at = datetime.combine(document.event_date, time.min) if document.event_date else None
    history_rows = db.scalars(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.patient_id == patient_id, ClinicalHistoryEvent.document_id == document.id)).all()
    for history in history_rows:
        history.title = document.exam_name or document.filename
        history.hospital = document.hospital
        history.description = document.extracted_text[:800] if document.extracted_text else None
        if occurred_at:
            history.occurred_at = occurred_at
    if document.hospitalization_id:
        _associate(db, patient_id, "document", document.id, occurred_at or document.created_at, document.hospitalization_id)
    _audit(db, user.id, patient_id, "document.metadata_updated", "document", document.id)
    db.commit()
    return {"ok": True, "id": document.id}


@features_api.get("/patients/{patient_id}/documents/{document_id}/assets/{asset_id}/download")
def download_document_asset(patient_id: int, document_id: int, asset_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    _membership(db, user.id, patient_id)
    document = db.scalar(select(ClinicalDocument).where(ClinicalDocument.id == document_id, ClinicalDocument.patient_id == patient_id))
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    asset = db.scalar(select(ClinicalDocumentAsset).where(ClinicalDocumentAsset.id == asset_id, ClinicalDocumentAsset.document_id == document_id))
    if not asset:
        raise HTTPException(status_code=404, detail="Archivo asociado no encontrado.")
    data = decrypt_bytes(asset.encrypted_data, f"clinical-document-asset:{document_id}".encode())
    return Response(data, media_type=asset.mime_type, headers={"Content-Disposition": f'inline; filename="{safe_filename(asset.filename)}"', "Cache-Control": "private, no-store"})


def _known_medication(db: Session, name: str) -> dict | None:
    normalized = normalize(name)
    learned = db.scalar(select(LearnedMedication).where(LearnedMedication.normalized_name == normalized))
    if learned:
        return {"name": learned.name, "type": learned.medication_type, "purpose": learned.purpose, "route": learned.usual_route, "unit": learned.usual_unit, "source": learned.source}
    for item in search_medications(name, limit=8):
        if normalize(item["name"]) == normalized or normalize(item.get("generic_name", "")) == normalized:
            return {"name": item["name"], "type": item["type"], "purpose": item["purpose"], "route": item.get("route"), "unit": item.get("unit"), "source": "curated_catalog"}
    return None


@features_api.post("/medications/enrich")
def enrich_medication(payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    name = str(payload.get("name") or "").strip()
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Escribe el nombre del medicamento.")
    known = _known_medication(db, name)
    if known:
        return known
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="El medicamento no está en el catálogo y la ayuda de IA no está configurada.")
    prompt = (
        "Devuelve SOLO JSON válido con las claves name, type, purpose, route, unit para el medicamento indicado. "
        "Indica categoría y uso general. NO recomiendes dosis, frecuencia, duración, tratamiento ni ajustes para una persona concreta. "
        "route y unit pueden ser null si no son inequívocas. Medicamento: " + name
    )
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini"), "input": prompt, "store": False},
            timeout=20.0,
        )
        response.raise_for_status()
        raw = response.json()
        chunks = []
        for item in raw.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        chunks.append(content["text"])
        text_value = "\n".join(chunks).strip()
        if text_value.startswith("```"):
            text_value = text_value.strip("`")
            if text_value.lower().startswith("json"):
                text_value = text_value[4:].strip()
        data = json.loads(text_value)
        result = {
            "name": str(data.get("name") or name)[:180],
            "type": str(data.get("type") or "Medicamento")[:140],
            "purpose": str(data.get("purpose") or "")[:600] or None,
            "route": str(data.get("route"))[:100] if data.get("route") else None,
            "unit": str(data.get("unit"))[:60] if data.get("unit") else None,
            "source": "ai",
        }
    except Exception as exc:
        logger.exception("Medication AI enrichment failed")
        raise HTTPException(status_code=502, detail="No se pudo completar la información del medicamento en este momento.") from exc
    if not db.scalar(select(LearnedMedication).where(LearnedMedication.normalized_name == normalize(result["name"]))):
        db.add(LearnedMedication(normalized_name=normalize(result["name"]), name=result["name"], medication_type=result["type"], purpose=result["purpose"], usual_route=result["route"], usual_unit=result["unit"], source="ai"))
        db.commit()
    return result


def _report_range(db: Session, patient_id: int, payload: dict) -> tuple[datetime, datetime, Hospitalization | None]:
    if payload.get("hospitalization_id"):
        hospitalization = db.scalar(select(Hospitalization).where(Hospitalization.id == int(payload["hospitalization_id"]), Hospitalization.patient_id == patient_id))
        if not hospitalization:
            raise HTTPException(status_code=404, detail="Hospitalización no encontrada.")
        return hospitalization.admission_at, hospitalization.discharge_at or datetime.now(), hospitalization
    start_date = date.fromisoformat(payload["start_date"]) if payload.get("start_date") else date(1970, 1, 1)
    end_date = date.fromisoformat(payload["end_date"]) if payload.get("end_date") else date.today()
    return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max), None


def _day(days: dict[str, dict], moment: datetime | date) -> dict:
    key = moment.isoformat() if isinstance(moment, date) and not isinstance(moment, datetime) else moment.date().isoformat()
    days.setdefault(key, {"date": key, "medications": [], "treatment_changes": [], "chemotherapy": [], "chemo_events": [], "events": [], "vitals": [], "food": [], "elimination": [], "exams": [], "notes": []})
    return days[key]


def _average(values) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return round(mean(clean), 2) if clean else None


def _build_report(db: Session, patient_id: int, payload: dict, actor_user_id: int | None = None) -> dict:
    patient = db.get(Patient, patient_id)
    start, end, hospitalization = _report_range(db, patient_id, payload)
    hospital_filter = str(payload.get("hospital") or "").strip().lower()
    medication_filter = str(payload.get("medication") or "").strip().lower()
    days: dict[str, dict] = {}

    medications = db.scalars(select(CareMedication).where(CareMedication.patient_id == patient_id)).all()
    for med in medications:
        _ensure_initial_revision(db, med, actor_user_id)
    db.flush()

    revisions = db.scalars(select(MedicationRevision).where(MedicationRevision.patient_id == patient_id, MedicationRevision.effective_at.between(start, end)).order_by(MedicationRevision.effective_at.asc())).all()
    for row in revisions:
        if medication_filter and medication_filter not in row.name.lower():
            continue
        _associate(db, patient_id, "medication_revision", row.id, row.effective_at)
        _day(days, row.effective_at)["treatment_changes"].append(_revision_json(row))

    logs = db.execute(
        select(CareMedicationLog, CareMedicationSchedule, CareMedication)
        .join(CareMedicationSchedule, CareMedicationSchedule.id == CareMedicationLog.schedule_id)
        .join(CareMedication, CareMedication.id == CareMedicationSchedule.medication_id)
        .where(CareMedication.patient_id == patient_id, CareMedicationLog.log_date >= start.date(), CareMedicationLog.log_date <= end.date())
        .order_by(CareMedicationLog.log_date.asc(), CareMedicationSchedule.time_of_day.asc())
    ).all()
    for log, schedule, med in logs:
        if medication_filter and medication_filter not in med.name.lower():
            continue
        moment = log.actual_time or datetime.combine(log.log_date, schedule.time_of_day)
        snapshot = _snapshot_at(db, med.id, moment)
        _associate(db, patient_id, "medication_log", log.id, moment)
        _day(days, moment)["medications"].append({
            "occurred_at": moment.isoformat(timespec="minutes"),
            "scheduled_time": schedule.time_of_day.strftime("%H:%M"),
            "name": med.name,
            "dose": snapshot.dose if snapshot else med.dose,
            "route": snapshot.route if snapshot else med.route,
            "frequency": snapshot.frequency if snapshot else med.frequency,
            "status": log.status,
            "notes": log.notes,
        })

    chemo = db.scalars(select(CareChemoSession).where(CareChemoSession.patient_id == patient_id, CareChemoSession.scheduled_at.between(start, end)).order_by(CareChemoSession.scheduled_at.asc())).all()
    for row in chemo:
        _associate(db, patient_id, "chemo", row.id, row.scheduled_at)
        _day(days, row.scheduled_at)["chemotherapy"].append({"id": row.id, "occurred_at": row.scheduled_at.isoformat(timespec="minutes"), "name": row.name, "protocol": row.protocol, "cycle": row.cycle, "status": row.status, "notes": row.notes, "adverse_effects": row.adverse_effects})
    chemo_ids = [row.id for row in chemo]
    chemo_events = db.scalars(select(ChemoEvolutionEvent).where(ChemoEvolutionEvent.chemo_session_id.in_(chemo_ids) if chemo_ids else False, ChemoEvolutionEvent.occurred_at.between(start, end)).order_by(ChemoEvolutionEvent.occurred_at.asc())).all()
    for row in chemo_events:
        _associate(db, patient_id, "chemo_event", row.id, row.occurred_at)
        _day(days, row.occurred_at)["chemo_events"].append({"occurred_at": row.occurred_at.isoformat(timespec="minutes"), "chemo_id": row.chemo_session_id, "event_type": row.event_type, "description": row.description})

    vitals = db.scalars(select(CareVitalRecord).where(CareVitalRecord.patient_id == patient_id, CareVitalRecord.recorded_at.between(start, end)).order_by(CareVitalRecord.recorded_at.asc())).all()
    for row in vitals:
        _associate(db, patient_id, "vital", row.id, row.recorded_at)
        _day(days, row.recorded_at)["vitals"].append({"occurred_at": row.recorded_at.isoformat(timespec="minutes"), "temperature_c": row.temperature_c, "systolic": row.systolic, "diastolic": row.diastolic, "heart_rate": row.heart_rate, "oxygen_saturation": row.oxygen_saturation, "respiratory_rate": row.respiratory_rate, "weight_kg": row.weight_kg, "notes": row.notes})

    crises = db.scalars(select(CareCrisisEvent).where(CareCrisisEvent.patient_id == patient_id, CareCrisisEvent.occurred_at.between(start, end)).order_by(CareCrisisEvent.occurred_at.asc())).all()
    for row in crises:
        _associate(db, patient_id, "crisis", row.id, row.occurred_at)
        _day(days, row.occurred_at)["events"].append({"occurred_at": row.occurred_at.isoformat(timespec="minutes"), "type": row.event_type, "description": row.description, "duration_seconds": row.duration_seconds, "notes": row.notes})

    food = db.scalars(select(FoodLog).where(FoodLog.patient_id == patient_id, FoodLog.occurred_at.between(start, end)).order_by(FoodLog.occurred_at.asc())).all()
    for row in food:
        _associate(db, patient_id, "food", row.id, row.occurred_at)
        _day(days, row.occurred_at)["food"].append({"occurred_at": row.occurred_at.isoformat(timespec="minutes"), "meal_type": row.meal_type, "item": row.item, "amount": row.amount, "unit": row.unit, "tolerated": row.tolerated, "vomiting": row.vomiting, "notes": row.notes})

    elimination = db.scalars(select(EliminationLog).where(EliminationLog.patient_id == patient_id, EliminationLog.occurred_at.between(start, end)).order_by(EliminationLog.occurred_at.asc())).all()
    for row in elimination:
        _associate(db, patient_id, "elimination", row.id, row.occurred_at)
        _day(days, row.occurred_at)["elimination"].append({"occurred_at": row.occurred_at.isoformat(timespec="minutes"), "diaper_status": row.diaper_status, "urine_amount": row.urine_amount, "urine_color": row.urine_color, "stool_description": row.stool_description, "notes": row.notes})

    documents = db.scalars(select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id).order_by(ClinicalDocument.event_date.asc().nulls_last(), ClinicalDocument.created_at.asc())).all()
    for row in documents:
        moment = datetime.combine(row.event_date, time.min) if row.event_date else row.created_at
        if not start <= moment <= end:
            continue
        if hospitalization and row.hospitalization_id not in (None, hospitalization.id):
            continue
        if hospital_filter and hospital_filter not in (row.hospital or "").lower():
            continue
        _associate(db, patient_id, "document", row.id, moment, row.hospitalization_id)
        assets = db.scalars(select(ClinicalDocumentAsset).where(ClinicalDocumentAsset.document_id == row.id).order_by(ClinicalDocumentAsset.position)).all()
        _day(days, moment)["exams"].append({"occurred_at": moment.isoformat(timespec="minutes"), "id": row.id, "name": row.exam_name or row.filename, "type": row.document_type, "hospital": row.hospital, "extracted_text": row.extracted_text, "files": len(assets) or 1})

    history = db.scalars(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.patient_id == patient_id, ClinicalHistoryEvent.occurred_at.between(start, end)).order_by(ClinicalHistoryEvent.occurred_at.asc())).all()
    for row in history:
        if row.document_id:
            continue
        if hospital_filter and hospital_filter not in (row.hospital or "").lower():
            continue
        _associate(db, patient_id, "history", row.id, row.occurred_at)
        _day(days, row.occurred_at)["events"].append({"occurred_at": row.occurred_at.isoformat(timespec="minutes"), "type": row.category, "description": row.title, "notes": row.description, "hospital": row.hospital})

    notes = db.scalars(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date >= start.date(), CareDailyNote.note_date <= end.date()).order_by(CareDailyNote.note_date.asc())).all()
    for row in notes:
        _day(days, row.note_date)["notes"].append({"text": row.text, "updated_at": row.updated_at.isoformat(timespec="minutes")})

    ordered_days = [days[key] for key in sorted(days)]
    statistics = {
        "days": len(ordered_days),
        "medication_administrations": sum(len(day["medications"]) for day in ordered_days),
        "treatment_changes": sum(len(day["treatment_changes"]) for day in ordered_days),
        "chemotherapy_sessions": len(chemo),
        "chemo_events": len(chemo_events),
        "vitals": len(vitals),
        "events": len(crises) + sum(1 for row in history if not row.document_id),
        "food": len(food),
        "elimination": len(elimination),
        "exams": sum(len(day["exams"]) for day in ordered_days),
        "temperature_avg": _average([row.temperature_c for row in vitals]),
        "heart_rate_avg": _average([row.heart_rate for row in vitals]),
        "oxygen_avg": _average([row.oxygen_saturation for row in vitals]),
    }
    facts = {
        "patient": {"name": patient.name, "birth_date": patient.birth_date.isoformat() if patient.birth_date else None, "diagnoses": patient.diagnoses, "allergies": patient.allergies},
        "period": {"start": start.isoformat(timespec="minutes"), "end": end.isoformat(timespec="minutes")},
        "hospitalization": ({"id": hospitalization.id, "hospital": hospitalization.hospital, "service": hospitalization.service, "admission_at": hospitalization.admission_at.isoformat(timespec="minutes"), "discharge_at": hospitalization.discharge_at.isoformat(timespec="minutes") if hospitalization.discharge_at else None, "reason": hospitalization.reason, "diagnosis": hospitalization.diagnosis, "summary": hospitalization.summary} if hospitalization else None),
        "days": ordered_days,
        "statistics": statistics,
    }
    db.commit()
    return facts


def _fallback_narrative(facts: dict) -> str:
    lines = [f"Resumen de evolución de {facts['patient']['name']} basado exclusivamente en los registros de IkerCare."]
    hospitalization = facts.get("hospitalization")
    if hospitalization:
        lines.append(f"Hospitalización en {hospitalization['hospital']} desde {hospitalization['admission_at']} hasta {hospitalization['discharge_at'] or 'sin alta registrada'}.")
    for day in facts["days"]:
        parts = []
        if day["medications"]: parts.append(f"{len(day['medications'])} administraciones de medicamentos")
        if day["treatment_changes"]: parts.append(f"{len(day['treatment_changes'])} cambios de tratamiento")
        if day["chemotherapy"]: parts.append(f"{len(day['chemotherapy'])} registros de quimioterapia")
        if day["chemo_events"]: parts.append(f"{len(day['chemo_events'])} eventos posteriores a quimioterapia")
        if day["events"]: parts.append(f"{len(day['events'])} eventos clínicos")
        if day["exams"]: parts.append(f"{len(day['exams'])} exámenes/informes")
        if parts:
            lines.append(f"{day['date']}: " + ", ".join(parts) + ".")
    return "\n".join(lines)


def _ai_narrative(facts: dict) -> tuple[str, bool, str | None]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fallback_narrative(facts), False, "OPENAI_API_KEY no configurada"
    prompt = (
        "Redacta en español un resumen cronológico de evolución clínica familiar usando EXCLUSIVAMENTE el JSON entregado. "
        "No inventes hechos, diagnósticos, tratamientos, causalidades, fechas, dosis ni recomendaciones. No interpretes valores clínicos. "
        "Menciona solo información presente y finaliza aclarando que la narración fue generada desde registros de IkerCare y no reemplaza la ficha clínica oficial.\n\n" + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    )
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": os.getenv("OPENAI_REPORT_MODEL", "gpt-5-mini"), "input": prompt, "store": False},
            timeout=18.0,
        )
        response.raise_for_status()
        raw = response.json()
        chunks = []
        for item in raw.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text" and content.get("text"):
                        chunks.append(content["text"])
        text_value = "\n".join(chunks).strip()
        return (text_value or _fallback_narrative(facts)), bool(text_value), None if text_value else "La IA no devolvió texto"
    except Exception as exc:
        logger.exception("Report AI narrative failed")
        return _fallback_narrative(facts), False, f"Redacción IA no disponible ({exc.__class__.__name__})"


@features_api.post("/patients/{patient_id}/reports/historical-preview")
def historical_report_preview(patient_id: int, payload: dict = Body(default={}), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    try:
        facts = _build_report(db, patient_id, payload, user.id)
        narrative, ai_used, ai_message = _ai_narrative(facts) if payload.get("use_ai") else (_fallback_narrative(facts), False, None)
        return {"facts": facts, "statistics": facts["statistics"], "narrative": narrative, "ai_used": ai_used, "ai_message": ai_message}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Historical report generation failed")
        raise HTTPException(status_code=500, detail="No se pudo generar el informe. Inténtalo nuevamente.") from exc


def _pdf_line(doc: fitz.Document, state: dict, text: str = "", size: float = 10.5, bold: bool = False, gap: float = 4) -> None:
    page = state["page"]
    y = state["y"]
    font = "hebo" if bold else "helv"
    safe = str(text or "").replace("•", "-")
    parts = textwrap.wrap(safe, width=82 if size <= 10.5 else 66, break_long_words=False) or [""]
    if y + len(parts) * (size + 4) + gap > 790:
        page = doc.new_page(width=595, height=842)
        y = 52
        state["page"] = page
    for part in parts:
        page.insert_text((48, y), part, fontsize=size, fontname=font, color=(0.08, 0.12, 0.2))
        y += size + 4
    state["y"] = y + gap


def _make_pdf(report: dict) -> bytes:
    facts = report["facts"]
    doc = fitz.open()
    state = {"page": doc.new_page(width=595, height=842), "y": 52}
    line = lambda text="", size=10.5, bold=False, gap=4: _pdf_line(doc, state, text, size, bold, gap)
    line("IkerCare - Informe histórico", 17, True, 8)
    line(f"Paciente: {facts['patient']['name']}", 12, True)
    if facts.get("hospitalization"):
        hospital = facts["hospitalization"]
        line(f"Hospitalización: {hospital['hospital']} · {hospital['admission_at']} a {hospital['discharge_at'] or 'sin alta registrada'}")
    else:
        line(f"Periodo: {facts['period']['start']} a {facts['period']['end']}")
    line("Registro familiar generado desde IkerCare. No reemplaza la ficha clínica oficial.", 9.5, False, 10)
    line("Resumen de evolución", 13, True)
    for paragraph in report["narrative"].splitlines():
        line(paragraph)
    line("Historial día por día", 13, True, 8)
    for day in facts["days"]:
        line(day["date"], 12.5, True, 6)
        sections = [
            ("Medicamentos", day["medications"], lambda x: f"{x['scheduled_time']} - {x['name']}{(' ' + x['dose']) if x.get('dose') else ''}{(' · ' + x['route']) if x.get('route') else ''} · {x['status']}"),
            ("Cambios de tratamiento", day["treatment_changes"], lambda x: f"{x['effective_at'][11:16]} - {x['name']} · {x['treatment_status']}{(' · dosis ' + x['dose']) if x.get('dose') else ''}{(' · ' + x['frequency']) if x.get('frequency') else ''}{(' · motivo: ' + x['reason']) if x.get('reason') else ''}"),
            ("Quimioterapia", day["chemotherapy"], lambda x: f"{x['occurred_at'][11:16]} - {x['name']}{(' · ' + x['cycle']) if x.get('cycle') else ''}{(' · ' + x['status']) if x.get('status') else ''}"),
            ("Eventos post quimioterapia", day["chemo_events"], lambda x: f"{x['occurred_at'][11:16]} - {x['event_type']}: {x['description']}"),
            ("Eventos clínicos", day["events"], lambda x: f"{x['occurred_at'][11:16]} - {x['type']}: {x['description']}{(' · ' + x['notes']) if x.get('notes') else ''}"),
            ("Signos vitales", day["vitals"], lambda x: f"{x['occurred_at'][11:16]} - Temp {x.get('temperature_c') if x.get('temperature_c') is not None else '-'} °C · PA {(str(x.get('systolic')) + '/' + str(x.get('diastolic'))) if x.get('systolic') and x.get('diastolic') else '-'} · FC {x.get('heart_rate') or '-'} · SatO2 {x.get('oxygen_saturation') or '-'}%"),
            ("Alimentación", day["food"], lambda x: f"{x['occurred_at'][11:16]} - {x.get('meal_type') or 'Otro'}: {x['item']}{(' · ' + str(x['amount']) + ' ' + (x.get('unit') or '')) if x.get('amount') is not None else ''}{(' · ' + x['notes']) if x.get('notes') else ''}"),
            ("Pañal / orina / deposiciones", day["elimination"], lambda x: f"{x['occurred_at'][11:16]} - {x['diaper_status']}{(' · orina ' + x['urine_amount']) if x.get('urine_amount') else ''}{(' · deposición ' + x['stool_description']) if x.get('stool_description') else ''}{(' · ' + x['notes']) if x.get('notes') else ''}"),
            ("Exámenes", day["exams"], lambda x: f"{x['name']}{(' · ' + x['hospital']) if x.get('hospital') else ''} · {x.get('files', 1)} archivo(s)"),
            ("Observaciones", day["notes"], lambda x: x['text']),
        ]
        for title, rows, formatter in sections:
            if not rows:
                continue
            line(title, 10.5, True, 2)
            for row in rows:
                line(formatter(row), 9.6, False, 2)
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


@features_api.get("/patients/{patient_id}/reports/historical-pdf")
def historical_report_pdf(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    start_date: date | None = None,
    end_date: date | None = None,
    hospitalization_id: int | None = None,
    hospital: str | None = None,
    medication: str | None = None,
    use_ai: bool = False,
) -> Response:
    _membership(db, user.id, patient_id)
    payload = {"start_date": start_date.isoformat() if start_date else None, "end_date": end_date.isoformat() if end_date else None, "hospitalization_id": hospitalization_id, "hospital": hospital, "medication": medication, "use_ai": use_ai}
    try:
        facts = _build_report(db, patient_id, payload, user.id)
        narrative, ai_used, ai_message = _ai_narrative(facts) if use_ai else (_fallback_narrative(facts), False, None)
        pdf = _make_pdf({"facts": facts, "statistics": facts["statistics"], "narrative": narrative, "ai_used": ai_used, "ai_message": ai_message})
        filename = f"IkerCare-informe-{date.today().isoformat()}.pdf"
        return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Length": str(len(pdf)), "Cache-Control": "private, no-store"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Historical PDF generation failed")
        raise HTTPException(status_code=500, detail="No se pudo generar el PDF. Inténtalo nuevamente.") from exc
