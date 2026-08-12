from __future__ import annotations

import json
import logging
import os
import textwrap
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Optional

import fitz
import httpx
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import get_current_user, verify_csrf
from .crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from .db import Base, get_db
from .document_processing import extract_text, safe_filename, validate_upload
from .medical_catalog import search_medications
from .models import User
from .v2_models import (
    CareChemoSession, CareCrisisEvent, CareDailyNote, CareMedication,
    CareMedicationLog, CareMedicationSchedule, CareVitalRecord,
    ClinicalDocument, ClinicalHistoryEvent, EliminationLog, FoodLog,
    Hospitalization, Patient,
)
from .v2_router import _audit, _membership, _require_role, now

logger = logging.getLogger("ikercare.clinical_history")
clinical_history_api = APIRouter(prefix="/api/v2", tags=["IkerCare clinical history"])


class MedicationTreatmentHistory(Base):
    __tablename__ = "care_medication_treatment_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    dose: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    times_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_fields_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class MedicationState(Base):
    __tablename__ = "care_medication_state"
    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="active")
    unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChemoEvolutionEvent(Base):
    __tablename__ = "care_chemo_evolution_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    chemo_session_id: Mapped[int] = mapped_column(ForeignKey("care_chemo_sessions.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


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


class CareRecordMeta(Base):
    __tablename__ = "care_record_metadata"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "key", name="uq_care_record_metadata"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class MedicationCatalogCache(Base):
    __tablename__ = "care_medication_catalog_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_name: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(180))
    medication_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    usual_route: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    usual_unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


def _times(db: Session, medication_id: int) -> list[str]:
    rows = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id, CareMedicationSchedule.active.is_(True)).order_by(CareMedicationSchedule.time_of_day)).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


def _state(db: Session, med: CareMedication) -> MedicationState:
    row = db.get(MedicationState, med.id)
    if not row:
        row = MedicationState(medication_id=med.id, status="active" if med.active else "suspended", changed_at=med.updated_at or med.created_at or now())
        db.add(row); db.flush()
    return row


def _snapshot(db: Session, med: CareMedication, occurred_at: datetime, event_type: str, user_id: int | None, status: str | None = None, reason: str | None = None, changed: list[str] | None = None) -> MedicationTreatmentHistory:
    row = MedicationTreatmentHistory(
        medication_id=med.id, occurred_at=occurred_at, event_type=event_type,
        status=status or _state(db, med).status, dose=med.dose, route=med.route,
        frequency=med.frequency, times_json=json.dumps(_times(db, med.id), ensure_ascii=False),
        reason=reason, changed_fields_json=json.dumps(changed or [], ensure_ascii=False), created_by_user_id=user_id,
    )
    db.add(row); return row


def _ensure_initial_snapshot(db: Session, med: CareMedication, user_id: int | None) -> None:
    if not db.scalar(select(MedicationTreatmentHistory.id).where(MedicationTreatmentHistory.medication_id == med.id).limit(1)):
        _snapshot(db, med, med.created_at or now(), "initial", user_id, status=_state(db, med).status)


def _history_dict(row: MedicationTreatmentHistory) -> dict:
    try: times = json.loads(row.times_json or "[]")
    except Exception: times = []
    try: changed = json.loads(row.changed_fields_json or "[]")
    except Exception: changed = []
    return {"id": row.id, "occurred_at": row.occurred_at.isoformat(timespec="minutes"), "event_type": row.event_type, "status": row.status, "dose": row.dose, "route": row.route, "frequency": row.frequency, "times": times, "reason": row.reason, "changed_fields": changed}


@clinical_history_api.get("/patients/{patient_id}/medications/{medication_id}/treatment-history")
def medication_history(patient_id: int, medication_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med: raise HTTPException(404, "Medicamento no encontrado.")
    _ensure_initial_snapshot(db, med, user.id); state = _state(db, med); db.commit()
    rows = db.scalars(select(MedicationTreatmentHistory).where(MedicationTreatmentHistory.medication_id == med.id).order_by(MedicationTreatmentHistory.occurred_at, MedicationTreatmentHistory.id)).all()
    return {"status": state.status, "unit": state.unit, "reason": state.reason, "history": [_history_dict(x) for x in rows]}


@clinical_history_api.put("/patients/{patient_id}/medications/{medication_id}/history-update")
def medication_history_update(patient_id: int, medication_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(select(CareMedication).where(CareMedication.id == medication_id, CareMedication.patient_id == patient_id))
    if not med: raise HTTPException(404, "Medicamento no encontrado.")
    _ensure_initial_snapshot(db, med, user.id); state = _state(db, med)
    before = {"dose": med.dose, "route": med.route, "frequency": med.frequency, "times": _times(db, med.id), "status": state.status}
    for field in ("name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions"):
        if field in payload: setattr(med, field, payload.get(field))
    if "times" in payload:
        wanted = {datetime.strptime(v, "%H:%M").time() for v in (payload.get("times") or [])}
        existing = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all(); by_time={x.time_of_day:x for x in existing}
        enabled = state.status in {"active", "resumed"}
        for row in existing: row.active = enabled and row.time_of_day in wanted
        for value in wanted:
            if value not in by_time: db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=value, active=enabled))
        db.flush()
    if "unit" in payload: state.unit = payload.get("unit") or None
    occurred_at = datetime.fromisoformat(payload["effective_at"]) if payload.get("effective_at") else now()
    after = {"dose": med.dose, "route": med.route, "frequency": med.frequency, "times": _times(db, med.id), "status": state.status}
    changed=[k for k in ("dose","route","frequency","times") if before[k] != after[k]]
    if changed: _snapshot(db, med, occurred_at, "treatment_change", user.id, status=state.status, changed=changed)
    med.updated_at=occurred_at; _audit(db,user.id,patient_id,"medication.history_updated","medication",med.id,{"changed":changed}); db.commit()
    return {"ok":True,"changed_fields":changed}


@clinical_history_api.post("/patients/{patient_id}/medications/{medication_id}/status")
def medication_status(patient_id: int, medication_id: int, payload: dict = Body(...), db: Session = Depends(get_db), user: User = Depends(get_current_user), _: None = Depends(verify_csrf)) -> dict:
    _require_role(db,user.id,patient_id,{"owner","editor"})
    med=db.scalar(select(CareMedication).where(CareMedication.id==medication_id,CareMedication.patient_id==patient_id))
    if not med: raise HTTPException(404,"Medicamento no encontrado.")
    status=str(payload.get("status") or "").lower(); allowed={"active","suspended","finished","paused","resumed"}
    if status not in allowed: raise HTTPException(400,"Estado de medicamento inválido.")
    _ensure_initial_snapshot(db,med,user.id); state=_state(db,med); occurred_at=datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now(); reason=payload.get("reason") or None
    state.status=status; state.reason=reason; state.changed_at=occurred_at; med.active=status in {"active","resumed"}
    schedules=db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id==med.id)).all()
    if status not in {"active","resumed"}:
        for schedule in schedules: schedule.active=False
    elif not any(x.active for x in schedules):
        # Reanuda los horarios que existían en la última configuración histórica.
        prior=db.scalar(select(MedicationTreatmentHistory).where(MedicationTreatmentHistory.medication_id==med.id).order_by(MedicationTreatmentHistory.occurred_at.desc()).limit(1))
        try: wanted={datetime.strptime(v,"%H:%M").time() for v in json.loads(prior.times_json or "[]")} if prior else set()
        except Exception: wanted=set()
        for schedule in schedules: schedule.active=schedule.time_of_day in wanted
    _snapshot(db,med,occurred_at,"status_change",user.id,status=status,reason=reason); med.updated_at=occurred_at; _audit(db,user.id,patient_id,f"medication.status.{status}","medication",med.id); db.commit(); return {"ok":True,"status":status}


@clinical_history_api.get("/patients/{patient_id}/chemo/{chemo_id}/events")
def chemo_events(patient_id:int,chemo_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user))->list[dict]:
    _membership(db,user.id,patient_id); chemo=db.scalar(select(CareChemoSession).where(CareChemoSession.id==chemo_id,CareChemoSession.patient_id==patient_id))
    if not chemo: raise HTTPException(404,"Quimioterapia no encontrada.")
    rows=db.scalars(select(ChemoEvolutionEvent).where(ChemoEvolutionEvent.chemo_session_id==chemo_id).order_by(ChemoEvolutionEvent.occurred_at,ChemoEvolutionEvent.id)).all(); return [{"id":x.id,"occurred_at":x.occurred_at.isoformat(timespec="minutes"),"event_type":x.event_type,"description":x.description} for x in rows]


@clinical_history_api.post("/patients/{patient_id}/chemo/{chemo_id}/events",status_code=201)
def add_chemo_event(patient_id:int,chemo_id:int,payload:dict=Body(...),db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf))->dict:
    _require_role(db,user.id,patient_id,{"owner","editor"}); chemo=db.scalar(select(CareChemoSession).where(CareChemoSession.id==chemo_id,CareChemoSession.patient_id==patient_id))
    if not chemo: raise HTTPException(404,"Quimioterapia no encontrada.")
    at=datetime.fromisoformat(payload["occurred_at"]) if payload.get("occurred_at") else now(); row=ChemoEvolutionEvent(chemo_session_id=chemo_id,occurred_at=at,event_type=str(payload.get("event_type") or "Otro")[:100],description=payload.get("description") or None,created_by_user_id=user.id); db.add(row); db.flush(); _audit(db,user.id,patient_id,"chemo.evolution.created","chemo_event",row.id,{"chemo_id":chemo_id}); db.commit(); return {"id":row.id}


@clinical_history_api.delete("/patients/{patient_id}/chemo/{chemo_id}/events/{event_id}")
def delete_chemo_event(patient_id:int,chemo_id:int,event_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf))->dict:
    _require_role(db,user.id,patient_id,{"owner","editor"}); row=db.scalar(select(ChemoEvolutionEvent).join(CareChemoSession,CareChemoSession.id==ChemoEvolutionEvent.chemo_session_id).where(ChemoEvolutionEvent.id==event_id,ChemoEvolutionEvent.chemo_session_id==chemo_id,CareChemoSession.patient_id==patient_id))
    if not row: raise HTTPException(404,"Evento no encontrado.")
    db.delete(row); db.commit(); return {"ok":True}


def _set_meta(db:Session,entity_type:str,entity_id:int,key:str,value:str|None):
    row=db.scalar(select(CareRecordMeta).where(CareRecordMeta.entity_type==entity_type,CareRecordMeta.entity_id==entity_id,CareRecordMeta.key==key))
    if row: row.value=value
    else: db.add(CareRecordMeta(entity_type=entity_type,entity_id=entity_id,key=key,value=value))

def _get_meta(db:Session,entity_type:str,entity_id:int,key:str)->str|None:
    row=db.scalar(select(CareRecordMeta).where(CareRecordMeta.entity_type==entity_type,CareRecordMeta.entity_id==entity_id,CareRecordMeta.key==key)); return row.value if row else None


@clinical_history_api.post("/patients/{patient_id}/food-enhanced",status_code=201)
def food_enhanced(patient_id:int,payload:dict=Body(...),db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf))->dict:
    _require_role(db,user.id,patient_id,{"owner","editor"}); item=FoodLog(patient_id=patient_id,occurred_at=datetime.fromisoformat(payload["occurred_at"]),meal_type=payload.get("meal_type") or None,item=str(payload.get("item") or "").strip()[:240],amount=float(payload["amount"]) if payload.get("amount") not in (None,"") else None,unit=payload.get("unit") or None,tolerated=payload.get("tolerated"),vomiting=bool(payload.get("vomiting")),notes=payload.get("notes") or None,created_by_user_id=user.id)
    if not item.item: raise HTTPException(400,"Indica qué alimento o bebida registraste.")
    db.add(item); db.flush(); _set_meta(db,"food",item.id,"portion",payload.get("portion") or None); _audit(db,user.id,patient_id,"food.created","food",item.id); db.commit(); return {"id":item.id}

@clinical_history_api.put("/patients/{patient_id}/food-enhanced/{item_id}")
def food_enhanced_update(patient_id:int,item_id:int,payload:dict=Body(...),db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf))->dict:
    _require_role(db,user.id,patient_id,{"owner","editor"}); item=db.scalar(select(FoodLog).where(FoodLog.id==item_id,FoodLog.patient_id==patient_id))
    if not item: raise HTTPException(404,"Registro no encontrado.")
    if payload.get("occurred_at"): item.occurred_at=datetime.fromisoformat(payload["occurred_at"])
    for f in ("meal_type","item","unit","notes"):
        if f in payload: setattr(item,f,payload.get(f) or None)
    if "amount" in payload: item.amount=float(payload["amount"]) if payload.get("amount") not in (None,"") else None
    if "tolerated" in payload:item.tolerated=payload.get("tolerated")
    if "vomiting" in payload:item.vomiting=bool(payload.get("vomiting"))
    _set_meta(db,"food",item.id,"portion",payload.get("portion") or None); _audit(db,user.id,patient_id,"food.updated","food",item.id); db.commit(); return {"ok":True}

@clinical_history_api.get("/patients/{patient_id}/food-metadata")
def food_metadata(patient_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user))->dict:
    _membership(db,user.id,patient_id); ids=db.scalars(select(FoodLog.id).where(FoodLog.patient_id==patient_id)).all(); result={}
    for i in ids:
        p=_get_meta(db,"food",i,"portion")
        if p: result[str(i)]={"portion":p}
    return result


@clinical_history_api.post("/patients/{patient_id}/documents/group",status_code=201)
async def document_group(patient_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf),files:list[UploadFile]=File(...),document_type:str=Form("exam"),exam_name:str|None=Form(None),hospital:str|None=Form(None),event_date:date|None=Form(None),hospitalization_id:int|None=Form(None))->dict:
    _require_role(db,user.id,patient_id,{"owner","editor"})
    if not files or len(files)>10: raise HTTPException(400,"Selecciona entre 1 y 10 archivos para el mismo examen.")
    if hospitalization_id and not db.scalar(select(Hospitalization.id).where(Hospitalization.id==hospitalization_id,Hospitalization.patient_id==patient_id)): raise HTTPException(400,"Hospitalización inválida.")
    received=[]
    for position,file in enumerate(files):
        raw=await file.read()
        if not raw: continue
        received.append((position,file,raw))
    if not received: raise HTTPException(400,"No se recibieron archivos válidos.")
    # Valida por archivo, no aborta el grupo por un archivo defectuoso.
    valid=[]; failures=[]
    for position,file,raw in received:
        mime=file.content_type or "application/octet-stream"; filename=safe_filename(file.filename or f"archivo-{position+1}")
        try: validate_upload(filename,mime,raw); valid.append((position,file,raw,mime,filename))
        except Exception as exc: logger.warning("Invalid grouped document position=%s: %s",position,exc); failures.append(position+1)
    if not valid: raise HTTPException(400,"No fue posible procesar ninguno de los archivos seleccionados.")
    _,first_file,first_raw,first_mime,first_filename=valid[0]
    parent=ClinicalDocument(patient_id=patient_id,hospitalization_id=hospitalization_id,event_date=event_date,document_type=document_type[:80],exam_name=(exam_name or "")[:220] or None,hospital=(hospital or "")[:220] or None,filename=first_filename,mime_type=first_mime,size_bytes=sum(len(x[2]) for x in valid),sha256=sha256_hex(b"".join(x[2] for x in valid)),encrypted_data=encrypt_bytes(first_raw,f"clinical-document:{patient_id}".encode()),extracted_text=None,extraction_status="pending",extraction_error=None,uploaded_by_user_id=user.id); db.add(parent); db.flush()
    combined=[]; asset_failures=0
    for original_pos,file,raw,mime,filename in valid:
        try: extracted,status,error=extract_text(raw,mime)
        except Exception as exc: logger.exception("Grouped OCR failed document=%s position=%s",parent.id,original_pos); extracted,status,error="","failed",str(exc)
        if status in {"failed","extraction_failed"}: asset_failures+=1
        asset=ClinicalDocumentAsset(document_id=parent.id,position=original_pos,filename=filename,mime_type=mime,size_bytes=len(raw),sha256=sha256_hex(raw),encrypted_data=encrypt_bytes(raw,f"clinical-document-asset:{patient_id}:{parent.id}:{original_pos}".encode()),extracted_text=extracted or None,extraction_status=status,extraction_error=error); db.add(asset)
        if extracted: combined.append(f"--- Página/archivo {original_pos+1}: {filename} ---\n{extracted.strip()}")
    parent.extracted_text="\n\n".join(combined) or None; total_failures=len(failures)+asset_failures; parent.extraction_status="partial" if total_failures else ("text_extracted" if combined else "completed_no_text"); parent.extraction_error=f"{total_failures} archivo(s) no se procesaron completamente." if total_failures else None
    history=ClinicalHistoryEvent(patient_id=patient_id,occurred_at=datetime.combine(event_date,time.min) if event_date else now(),category="exam",title=exam_name or first_filename,description=(parent.extracted_text[:800] if parent.extracted_text else None),hospital=hospital,document_id=parent.id,created_by_user_id=user.id); db.add(history); _audit(db,user.id,patient_id,"document.group_uploaded","document",parent.id,{"assets":len(valid),"failures":total_failures}); db.commit(); return {"id":parent.id,"assets":len(valid),"failures":total_failures,"extraction_status":parent.extraction_status,"extracted_text":parent.extracted_text}

@clinical_history_api.get("/patients/{patient_id}/documents/{document_id}/assets")
def document_assets(patient_id:int,document_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user))->list[dict]:
    _membership(db,user.id,patient_id); doc=db.scalar(select(ClinicalDocument).where(ClinicalDocument.id==document_id,ClinicalDocument.patient_id==patient_id))
    if not doc: raise HTTPException(404,"Documento no encontrado.")
    rows=db.scalars(select(ClinicalDocumentAsset).where(ClinicalDocumentAsset.document_id==document_id).order_by(ClinicalDocumentAsset.position)).all(); return [{"id":x.id,"position":x.position,"filename":x.filename,"mime_type":x.mime_type,"extraction_status":x.extraction_status,"extracted_text":x.extracted_text} for x in rows]

@clinical_history_api.get("/patients/{patient_id}/documents/{document_id}/assets/{asset_id}/download")
def document_asset_download(patient_id:int,document_id:int,asset_id:int,db:Session=Depends(get_db),user:User=Depends(get_current_user))->Response:
    _membership(db,user.id,patient_id); row=db.scalar(select(ClinicalDocumentAsset).join(ClinicalDocument,ClinicalDocument.id==ClinicalDocumentAsset.document_id).where(ClinicalDocumentAsset.id==asset_id,ClinicalDocumentAsset.document_id==document_id,ClinicalDocument.patient_id==patient_id))
    if not row: raise HTTPException(404,"Archivo no encontrado.")
    raw=decrypt_bytes(row.encrypted_data,f"clinical-document-asset:{patient_id}:{document_id}:{row.position}".encode()); return Response(raw,media_type=row.mime_type,headers={"Content-Disposition":f'inline; filename="{safe_filename(row.filename)}"',"Cache-Control":"private, no-store"})

@clinical_history_api.put("/patients/{patient_id}/documents/{document_id}")
def document_update(patient_id:int,document_id:int,payload:dict=Body(...),db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf))->dict:
    _require_role(db,user.id,patient_id,{"owner","editor"}); row=db.scalar(select(ClinicalDocument).where(ClinicalDocument.id==document_id,ClinicalDocument.patient_id==patient_id))
    if not row: raise HTTPException(404,"Documento no encontrado.")
    if "exam_name" in payload: row.exam_name=(payload.get("exam_name") or "")[:220] or None
    if "document_type" in payload: row.document_type=str(payload.get("document_type") or "exam")[:80]
    if "hospital" in payload: row.hospital=(payload.get("hospital") or "")[:220] or None
    if "event_date" in payload: row.event_date=date.fromisoformat(payload["event_date"]) if payload.get("event_date") else None
    if "hospitalization_id" in payload:
        hid=int(payload["hospitalization_id"]) if payload.get("hospitalization_id") else None
        if hid and not db.scalar(select(Hospitalization.id).where(Hospitalization.id==hid,Hospitalization.patient_id==patient_id)): raise HTTPException(400,"Hospitalización inválida.")
        row.hospitalization_id=hid
    history=db.scalar(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.document_id==row.id).order_by(ClinicalHistoryEvent.id).limit(1))
    if history:
        history.title=row.exam_name or row.filename; history.hospital=row.hospital; history.description=(row.extracted_text[:800] if row.extracted_text else None)
        if row.event_date: history.occurred_at=datetime.combine(row.event_date,time.min)
    _audit(db,user.id,patient_id,"document.updated","document",row.id); db.commit(); return {"ok":True,"id":row.id}


def _snapshot_at(rows:list[MedicationTreatmentHistory],at:datetime)->MedicationTreatmentHistory|None:
    chosen=None
    for row in rows:
        if row.occurred_at<=at: chosen=row
        else: break
    return chosen


def _hospital_facts(db:Session,patient_id:int,hospitalization_id:int)->dict:
    hospital=db.scalar(select(Hospitalization).where(Hospitalization.id==hospitalization_id,Hospitalization.patient_id==patient_id)); patient=db.get(Patient,patient_id)
    if not hospital or not patient: raise HTTPException(404,"Hospitalización no encontrada.")
    start= hospital.admission_at; end=hospital.discharge_at or now(); start_date,end_date=start.date(),end.date()
    meds=db.scalars(select(CareMedication).where(CareMedication.patient_id==patient_id)).all()
    for med in meds:_ensure_initial_snapshot(db,med,None)
    db.flush()
    histories=db.scalars(select(MedicationTreatmentHistory).join(CareMedication,CareMedication.id==MedicationTreatmentHistory.medication_id).where(CareMedication.patient_id==patient_id,MedicationTreatmentHistory.occurred_at<=end).order_by(MedicationTreatmentHistory.medication_id,MedicationTreatmentHistory.occurred_at,MedicationTreatmentHistory.id)).all(); by_med=defaultdict(list)
    for row in histories:by_med[row.medication_id].append(row)
    logs=db.execute(select(CareMedicationLog,CareMedicationSchedule,CareMedication).join(CareMedicationSchedule,CareMedicationSchedule.id==CareMedicationLog.schedule_id).join(CareMedication,CareMedication.id==CareMedicationSchedule.medication_id).where(CareMedication.patient_id==patient_id,CareMedicationLog.log_date>=start_date,CareMedicationLog.log_date<=end_date).order_by(CareMedicationLog.log_date,CareMedicationSchedule.time_of_day)).all()
    chemo=db.scalars(select(CareChemoSession).where(CareChemoSession.patient_id==patient_id,CareChemoSession.scheduled_at.between(start,end)).order_by(CareChemoSession.scheduled_at)).all(); chemo_ids=[x.id for x in chemo]
    chemo_events=db.scalars(select(ChemoEvolutionEvent).where(ChemoEvolutionEvent.chemo_session_id.in_(chemo_ids) if chemo_ids else False,ChemoEvolutionEvent.occurred_at.between(start,end)).order_by(ChemoEvolutionEvent.occurred_at)).all()
    vitals=db.scalars(select(CareVitalRecord).where(CareVitalRecord.patient_id==patient_id,CareVitalRecord.recorded_at.between(start,end)).order_by(CareVitalRecord.recorded_at)).all(); crises=db.scalars(select(CareCrisisEvent).where(CareCrisisEvent.patient_id==patient_id,CareCrisisEvent.occurred_at.between(start,end)).order_by(CareCrisisEvent.occurred_at)).all(); food=db.scalars(select(FoodLog).where(FoodLog.patient_id==patient_id,FoodLog.occurred_at.between(start,end)).order_by(FoodLog.occurred_at)).all(); elim=db.scalars(select(EliminationLog).where(EliminationLog.patient_id==patient_id,EliminationLog.occurred_at.between(start,end)).order_by(EliminationLog.occurred_at)).all(); notes=db.scalars(select(CareDailyNote).where(CareDailyNote.patient_id==patient_id,CareDailyNote.note_date>=start_date,CareDailyNote.note_date<=end_date).order_by(CareDailyNote.note_date)).all(); history=db.scalars(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.patient_id==patient_id,ClinicalHistoryEvent.occurred_at.between(start,end)).order_by(ClinicalHistoryEvent.occurred_at)).all(); docs=db.scalars(select(ClinicalDocument).where(ClinicalDocument.patient_id==patient_id).order_by(ClinicalDocument.event_date,ClinicalDocument.created_at)).all(); docs=[d for d in docs if d.hospitalization_id==hospitalization_id or (d.event_date and start_date<=d.event_date<=end_date)]
    days={}; cursor=start_date
    while cursor<=end_date:
        days[cursor.isoformat()]={"date":cursor.isoformat(),"medications":[],"treatment_changes":[],"chemotherapy":[],"chemo_events":[],"events":[],"vitals":[],"food":[],"elimination":[],"documents":[],"notes":[]}; cursor+=timedelta(days=1)
    def bucket(d): return days.get(d.isoformat())
    for log,schedule,med in logs:
        at=log.actual_time or datetime.combine(log.log_date,schedule.time_of_day); snap=_snapshot_at(by_med[med.id],at); b=bucket(log.log_date)
        if b is not None:b["medications"].append({"time":schedule.time_of_day.strftime("%H:%M"),"name":med.name,"dose":snap.dose if snap else med.dose,"route":snap.route if snap else med.route,"frequency":snap.frequency if snap else med.frequency,"status":log.status})
    med_names={m.id:m.name for m in meds}
    for rows in by_med.values():
        for row in rows:
            if start<=row.occurred_at<=end and row.event_type!="initial":
                b=bucket(row.occurred_at.date())
                if b is not None:b["treatment_changes"].append({**_history_dict(row),"time":row.occurred_at.strftime("%H:%M"),"medication":med_names.get(row.medication_id,"Medicamento")})
    for x in chemo: bucket(x.scheduled_at.date())["chemotherapy"].append({"time":x.scheduled_at.strftime("%H:%M"),"name":x.name,"protocol":x.protocol,"cycle":x.cycle,"status":x.status,"notes":x.notes})
    chemo_map={x.id:x for x in chemo}
    for x in chemo_events: bucket(x.occurred_at.date())["chemo_events"].append({"time":x.occurred_at.strftime("%H:%M"),"chemo":chemo_map.get(x.chemo_session_id).name if chemo_map.get(x.chemo_session_id) else "Quimioterapia","type":x.event_type,"description":x.description})
    for x in vitals: bucket(x.recorded_at.date())["vitals"].append({"time":x.recorded_at.strftime("%H:%M"),"temperature_c":x.temperature_c,"blood_pressure":f"{x.systolic}/{x.diastolic}" if x.systolic and x.diastolic else None,"heart_rate":x.heart_rate,"oxygen_saturation":x.oxygen_saturation,"respiratory_rate":x.respiratory_rate,"weight_kg":x.weight_kg,"notes":x.notes})
    for x in crises: bucket(x.occurred_at.date())["events"].append({"time":x.occurred_at.strftime("%H:%M"),"type":x.event_type,"description":x.description,"actions":x.actions_taken})
    for x in food: bucket(x.occurred_at.date())["food"].append({"time":x.occurred_at.strftime("%H:%M"),"meal_type":x.meal_type,"item":x.item,"amount":x.amount,"unit":x.unit,"portion":_get_meta(db,"food",x.id,"portion"),"tolerated":x.tolerated,"vomiting":x.vomiting,"notes":x.notes})
    for x in elim: bucket(x.occurred_at.date())["elimination"].append({"time":x.occurred_at.strftime("%H:%M"),"diaper_status":x.diaper_status,"urine_amount":x.urine_amount,"urine_color":x.urine_color,"stool_description":x.stool_description,"notes":x.notes})
    for x in docs:
        d=x.event_date or x.created_at.date(); b=bucket(d)
        if b is not None:b["documents"].append({"id":x.id,"name":x.exam_name or x.filename,"type":x.document_type,"hospital":x.hospital,"extracted_text":(x.extracted_text or "")[:1800]})
    for x in notes: bucket(x.note_date)["notes"].append({"text":x.text})
    for x in history:
        if x.category not in {"exam","hospitalization"}: bucket(x.occurred_at.date())["events"].append({"time":x.occurred_at.strftime("%H:%M"),"type":x.title,"description":x.description,"hospital":x.hospital})
    facts={"patient":{"name":patient.name,"birth_date":patient.birth_date.isoformat() if patient.birth_date else None},"hospitalization":{"id":hospital.id,"hospital":hospital.hospital,"service":hospital.service,"admission_at":hospital.admission_at.isoformat(timespec="minutes"),"discharge_at":hospital.discharge_at.isoformat(timespec="minutes") if hospital.discharge_at else None,"reason":hospital.reason,"diagnosis":hospital.diagnosis,"summary":hospital.summary},"days":[days[k] for k in sorted(days)],"statistics":{"days":len(days),"medication_administrations":len(logs),"treatment_changes":sum(1 for x in histories if start<=x.occurred_at<=end and x.event_type!="initial"),"chemotherapy_sessions":len(chemo),"chemo_events":len(chemo_events),"vital_records":len(vitals),"clinical_events":len(crises)+len(history),"food_records":len(food),"elimination_records":len(elim),"documents":len(docs)}}; db.commit(); return facts


def _local_narrative(facts:dict)->str:
    h=facts["hospitalization"]; s=facts["statistics"]; lines=[f"{facts['patient']['name']} estuvo hospitalizado en {h['hospital']} desde {h['admission_at']} hasta {h['discharge_at'] or 'la fecha actual del registro'}." ]
    if h.get("reason"):lines.append(f"Motivo registrado: {h['reason']}.")
    if h.get("diagnosis"):lines.append(f"Diagnóstico registrado: {h['diagnosis']}.")
    lines.append(f"Durante esta estadía se registraron {s['medication_administrations']} administraciones de medicamentos, {s['treatment_changes']} cambios de tratamiento, {s['chemotherapy_sessions']} quimioterapias, {s['vital_records']} controles de signos vitales, {s['food_records']} registros de alimentación, {s['elimination_records']} registros de eliminación y {s['documents']} exámenes o informes."); return "\n".join(lines)

def _ai_narrative(facts:dict)->tuple[str,bool,str|None]:
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key:return _local_narrative(facts),False,"OpenAI no está configurado; se usó resumen local."
    prompt="Redacta en español un resumen de evolución cronológico y sobrio usando EXCLUSIVAMENTE los hechos del JSON. No inventes, no diagnostiques, no recomiendes tratamientos y no cambies dosis, fechas, hospitales ni nombres. Resume hospitalización, cambios de medicamentos, quimioterapia, eventos, signos vitales, alimentación y exámenes relevantes. Si falta un dato, omítelo. Termina indicando que es una narración basada en registros de IkerCare y debe contrastarse con la ficha clínica oficial. JSON:\n"+json.dumps(facts,ensure_ascii=False)
    try:
        r=httpx.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json={"model":os.getenv("OPENAI_REPORT_MODEL","gpt-5-mini"),"input":prompt,"store":False},timeout=40.0); r.raise_for_status(); chunks=[]
        for item in r.json().get("output",[]):
            for c in item.get("content",[]):
                if c.get("type")=="output_text" and c.get("text"):chunks.append(c["text"])
        text="\n".join(chunks).strip(); return (text or _local_narrative(facts)),bool(text),None if text else "La IA no devolvió texto; se usó resumen local."
    except Exception:logger.exception("Hospital report AI failed"); return _local_narrative(facts),False,"No fue posible usar IA; se usó resumen local."

@clinical_history_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/complete-report")
def complete_report(patient_id:int,hospitalization_id:int,use_ai:bool=True,db:Session=Depends(get_db),user:User=Depends(get_current_user))->dict:
    _membership(db,user.id,patient_id); facts=_hospital_facts(db,patient_id,hospitalization_id); narrative,ai_used,msg=_ai_narrative(facts) if use_ai else (_local_narrative(facts),False,None); return {"facts":facts,"statistics":facts["statistics"],"narrative":narrative,"ai_used":ai_used,"ai_message":msg}


def _pdf_bytes(report:dict)->bytes:
    doc=fitz.open(); page=doc.new_page(width=595,height=842); y=50; margin=46
    def np():
        nonlocal page,y; page=doc.new_page(width=595,height=842); y=50
    def w(text="",size=10,bold=False,gap=4):
        nonlocal y; lines=textwrap.wrap(str(text or "").replace("•","-"),width=82 if size<=10 else 66,break_long_words=False) or [""]
        if y+len(lines)*(size+4)+gap>790:np()
        for line in lines:page.insert_text((margin,y),line,fontsize=size,fontname="hebo" if bold else "helv",color=(0.08,0.12,0.2)); y+=size+4
        y+=gap
    f=report["facts"]; h=f["hospitalization"]; w("IkerCare - Informe completo de hospitalización",16,True,8); w(f"Paciente: {f['patient']['name']}",12,True); w(f"Hospital: {h['hospital']}"); w(f"Ingreso: {h['admission_at']} · Alta: {h['discharge_at'] or 'sin alta registrada'}",10,False,10); w("Resumen de evolución",13,True)
    for p in report["narrative"].splitlines():w(p,10)
    w("Historial día por día",13,True,8); labels=[("medications","Medicamentos"),("treatment_changes","Cambios de tratamiento"),("chemotherapy","Quimioterapia"),("chemo_events","Evolución post quimioterapia"),("events","Eventos clínicos"),("vitals","Signos vitales"),("food","Alimentación"),("elimination","Pañal / orina / deposiciones"),("documents","Exámenes"),("notes","Observaciones")]
    for day in f["days"]:
        if not any(day.get(k) for k,_ in labels):continue
        w(day["date"],12,True,5)
        for key,title in labels:
            items=day.get(key) or []
            if not items:continue
            w(title,10.5,True,2)
            for item in items:
                if key=="medications":text=f"{item.get('time','')} - {item.get('name','')} {item.get('dose') or ''} {item.get('route') or ''} ({item.get('status','')})"
                elif key=="treatment_changes":text=f"{item.get('time','')} - {item.get('medication','')}: {item.get('status','')} · {item.get('dose') or ''} · {item.get('frequency') or ''} · {item.get('route') or ''}"+(f" · Motivo: {item.get('reason')}" if item.get('reason') else "")
                elif key=="vitals":text=f"{item.get('time','')} - T {item.get('temperature_c') if item.get('temperature_c') is not None else '-'} · PA {item.get('blood_pressure') or '-'} · FC {item.get('heart_rate') or '-'} · SatO2 {item.get('oxygen_saturation') if item.get('oxygen_saturation') is not None else '-'}"
                elif key=="food":text=f"{item.get('time','')} - {item.get('meal_type') or 'Alimentación'}: {item.get('item','')} {item.get('amount') or ''} {item.get('unit') or ''} {item.get('portion') or ''}. {item.get('notes') or ''}"
                elif key=="elimination":text=f"{item.get('time','')} - {item.get('diaper_status','')} · orina {item.get('urine_amount') or '-'} {item.get('urine_color') or ''} · deposición {item.get('stool_description') or '-'}. {item.get('notes') or ''}"
                elif key=="documents":text=f"- {item.get('name','')} ({item.get('type','')}) {item.get('hospital') or ''}"
                elif key=="notes":text=item.get("text") or ""
                else:text=f"{item.get('time','')} - {item.get('name') or item.get('chemo') or item.get('type') or ''}: {item.get('description') or item.get('notes') or ''}"
                w(text,9.5)
    data=doc.tobytes(garbage=3,deflate=True); doc.close(); return data

@clinical_history_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/complete-report.pdf")
def complete_report_pdf(patient_id:int,hospitalization_id:int,use_ai:bool=True,db:Session=Depends(get_db),user:User=Depends(get_current_user))->Response:
    _membership(db,user.id,patient_id)
    try:
        facts=_hospital_facts(db,patient_id,hospitalization_id); narrative,ai_used,msg=_ai_narrative(facts) if use_ai else (_local_narrative(facts),False,None); data=_pdf_bytes({"facts":facts,"narrative":narrative,"ai_used":ai_used,"ai_message":msg}); return Response(data,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="IkerCare-hospitalizacion-{hospitalization_id}.pdf"',"Content-Length":str(len(data)),"Cache-Control":"private, no-store"})
    except HTTPException:raise
    except Exception as exc:logger.exception("Hospital PDF failed patient=%s hospitalization=%s",patient_id,hospitalization_id); raise HTTPException(500,"No fue posible generar el PDF. Inténtalo nuevamente en unos segundos.") from exc


def _norm(v:str)->str:return " ".join((v or "").strip().lower().split())

@clinical_history_api.post("/medications/ai-enrich")
def medication_enrich(payload:dict=Body(...),db:Session=Depends(get_db),user:User=Depends(get_current_user),_:None=Depends(verify_csrf))->dict:
    name=str(payload.get("name") or "").strip()
    if len(name)<2:raise HTTPException(400,"Escribe el nombre del medicamento.")
    curated=search_medications(name,3); exact=next((x for x in curated if _norm(x["name"])==_norm(name)),None)
    if exact:return {"name":exact["name"],"medication_type":exact.get("type"),"purpose":exact.get("purpose"),"usual_route":exact.get("route"),"usual_unit":exact.get("unit"),"source":"catalog"}
    normalized=_norm(name); cached=db.scalar(select(MedicationCatalogCache).where(MedicationCatalogCache.normalized_name==normalized))
    if cached:return {"name":cached.display_name,"medication_type":cached.medication_type,"purpose":cached.purpose,"usual_route":cached.usual_route,"usual_unit":cached.usual_unit,"source":cached.source}
    key=os.getenv("OPENAI_API_KEY","").strip()
    if not key:raise HTTPException(503,"Este medicamento no está en el catálogo y la ayuda de IA no está configurada.")
    prompt=f"Devuelve SOLO JSON válido con las claves medication_type, purpose, usual_route, usual_unit para el medicamento {name!r}. Describe categoría y uso general. NO incluyas dosis, frecuencia, recomendaciones, diagnósticos ni instrucciones de tratamiento. Si no lo reconoces con suficiente confianza usa valores null."
    try:
        r=httpx.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json={"model":os.getenv("OPENAI_REPORT_MODEL","gpt-5-mini"),"input":prompt,"store":False},timeout=30.0); r.raise_for_status(); text=""
        for item in r.json().get("output",[]):
            for c in item.get("content",[]):
                if c.get("type")=="output_text":text+=c.get("text","")
        a,b=text.find("{"),text.rfind("}"); data=json.loads(text[a:b+1]); row=MedicationCatalogCache(normalized_name=normalized,display_name=name,medication_type=data.get("medication_type"),purpose=data.get("purpose"),usual_route=data.get("usual_route"),usual_unit=data.get("usual_unit"),source="openai"); db.add(row); db.commit(); return {"name":name,"medication_type":row.medication_type,"purpose":row.purpose,"usual_route":row.usual_route,"usual_unit":row.usual_unit,"source":"openai"}
    except Exception as exc:logger.exception("Medication AI enrich failed"); raise HTTPException(502,"No se pudo completar la información del medicamento en este momento.") from exc
