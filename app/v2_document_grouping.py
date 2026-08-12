from __future__ import annotations

import logging
from datetime import date, datetime, time

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user, verify_csrf
from .crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from .db import get_db
from .document_processing import extract_text, safe_filename, validate_upload
from .models import User
from .v2_models import ClinicalDocument, ClinicalHistoryEvent
from .v2_router import _audit, _membership, _require_role, now
from .v2_treatment_helpers import link_entity, validate_hospitalization
from .v2_treatment_models import ClinicalDocumentAsset

logger = logging.getLogger("ikercare.documents")
document_group_api = APIRouter(prefix="/api/v2", tags=["IkerCare grouped documents"])


def _combined_status(statuses: list[str]) -> str:
    normalized = ["failed" if status == "extraction_failed" else status for status in statuses]
    successes = sum(status in {"text_extracted", "ocr_completed"} for status in normalized)
    failures = sum(status == "failed" for status in normalized)
    if successes and failures:
        return "partial"
    if successes:
        return "text_extracted"
    if failures == len(normalized):
        return "failed"
    return "partial"


@document_group_api.post("/patients/{patient_id}/documents/grouped", status_code=201)
async def upload_grouped_document(
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
        raise HTTPException(status_code=400, detail="Selecciona entre 1 y 10 archivos.")
    if hospitalization_id:
        validate_hospitalization(db, patient_id, hospitalization_id)

    pages = []
    for position, file in enumerate(files, 1):
        data = await file.read()
        mime = file.content_type or "application/octet-stream"
        filename = safe_filename(file.filename or f"pagina-{position}")
        try:
            validate_upload(filename, mime, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"{filename}: {exc}") from exc
        try:
            extracted, extraction_status, extraction_error = extract_text(data, mime)
        except Exception as exc:
            logger.exception("Extraction failed for page %s", position)
            extracted, extraction_status, extraction_error = "", "failed", str(exc)
        pages.append({
            "position": position,
            "data": data,
            "mime": mime,
            "filename": filename,
            "text": extracted or "",
            "status": extraction_status,
            "error": extraction_error,
        })

    first = pages[0]
    combined_text = "\n\n".join(
        f"--- Página {page['position']}: {page['filename']} ---\n{page['text']}"
        for page in pages if page["text"]
    )
    document = ClinicalDocument(
        patient_id=patient_id,
        hospitalization_id=hospitalization_id,
        event_date=event_date,
        document_type=document_type[:80],
        exam_name=(exam_name or "")[:220] or None,
        hospital=(hospital or "")[:220] or None,
        filename=first["filename"],
        mime_type=first["mime"],
        size_bytes=len(first["data"]),
        sha256=sha256_hex(first["data"]),
        encrypted_data=encrypt_bytes(first["data"], f"clinical-document:{patient_id}".encode()),
        extracted_text=combined_text or None,
        extraction_status=_combined_status([page["status"] for page in pages]),
        extraction_error="; ".join(f"Página {page['position']}: {page['error']}" for page in pages if page["error"]) or None,
        uploaded_by_user_id=user.id,
    )
    db.add(document)
    db.flush()

    for page in pages[1:]:
        db.add(ClinicalDocumentAsset(
            document_id=document.id,
            position=page["position"],
            filename=page["filename"],
            mime_type=page["mime"],
            size_bytes=len(page["data"]),
            sha256=sha256_hex(page["data"]),
            encrypted_data=encrypt_bytes(page["data"], f"clinical-document-asset:{patient_id}:{document.id}:{page['position']}".encode()),
            extracted_text=page["text"] or None,
            extraction_status=page["status"],
            extraction_error=page["error"],
        ))

    occurred_at = datetime.combine(event_date, time.min) if event_date else now()
    db.add(ClinicalHistoryEvent(
        patient_id=patient_id,
        occurred_at=occurred_at,
        category="exam",
        title=exam_name or first["filename"],
        description=combined_text[:800] if combined_text else None,
        hospital=hospital,
        document_id=document.id,
        created_by_user_id=user.id,
    ))
    link_entity(db, patient_id, "document", document.id, occurred_at, hospitalization_id)
    _audit(db, user.id, patient_id, "document.grouped_uploaded", "document", document.id, {"files": len(pages), "extraction_status": document.extraction_status})
    db.commit()
    return {"id": document.id, "files": len(pages), "extraction_status": document.extraction_status, "extracted_text": document.extracted_text}


@document_group_api.get("/patients/{patient_id}/documents/{document_id}/assets")
def list_assets(patient_id: int, document_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    _membership(db, user.id, patient_id)
    document = db.scalar(select(ClinicalDocument).where(ClinicalDocument.id == document_id, ClinicalDocument.patient_id == patient_id))
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    assets = db.scalars(select(ClinicalDocumentAsset).where(ClinicalDocumentAsset.document_id == document_id).order_by(ClinicalDocumentAsset.position)).all()
    result = [{"position": 1, "filename": document.filename, "mime_type": document.mime_type, "size_bytes": document.size_bytes, "url": f"/api/v2/patients/{patient_id}/documents/{document_id}/assets/1"}]
    result.extend({"position": asset.position, "filename": asset.filename, "mime_type": asset.mime_type, "size_bytes": asset.size_bytes, "url": f"/api/v2/patients/{patient_id}/documents/{document_id}/assets/{asset.position}"} for asset in assets)
    return result


@document_group_api.get("/patients/{patient_id}/documents/{document_id}/assets/{position}")
def download_asset(patient_id: int, document_id: int, position: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    _membership(db, user.id, patient_id)
    document = db.scalar(select(ClinicalDocument).where(ClinicalDocument.id == document_id, ClinicalDocument.patient_id == patient_id))
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    if position == 1:
        data = decrypt_bytes(document.encrypted_data, f"clinical-document:{patient_id}".encode())
        mime, filename = document.mime_type, document.filename
    else:
        asset = db.scalar(select(ClinicalDocumentAsset).where(ClinicalDocumentAsset.document_id == document_id, ClinicalDocumentAsset.position == position))
        if not asset:
            raise HTTPException(status_code=404, detail="Imagen/página no encontrada.")
        data = decrypt_bytes(asset.encrypted_data, f"clinical-document-asset:{patient_id}:{document_id}:{position}".encode())
        mime, filename = asset.mime_type, asset.filename
    return Response(data, media_type=mime, headers={"Content-Disposition": f'inline; filename="{safe_filename(filename)}"', "Cache-Control": "private, no-store"})


@document_group_api.put("/patients/{patient_id}/documents/{document_id}")
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
        hid = int(payload["hospitalization_id"]) if payload.get("hospitalization_id") else None
        if hid:
            validate_hospitalization(db, patient_id, hid)
        document.hospitalization_id = hid
    occurred_at = datetime.combine(document.event_date, time.min) if document.event_date else document.created_at
    history_rows = db.scalars(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.document_id == document.id)).all()
    if not history_rows:
        history_rows = [ClinicalHistoryEvent(patient_id=patient_id, occurred_at=occurred_at, category="exam", title=document.exam_name or document.filename, document_id=document.id, created_by_user_id=user.id)]
        db.add(history_rows[0])
    for history in history_rows:
        history.occurred_at = occurred_at
        history.title = document.exam_name or document.filename
        history.description = document.extracted_text[:800] if document.extracted_text else None
        history.hospital = document.hospital
    link_entity(db, patient_id, "document", document.id, occurred_at, document.hospitalization_id)
    _audit(db, user.id, patient_id, "document.updated", "document", document.id)
    db.commit()
    return {"ok": True, "id": document.id}
