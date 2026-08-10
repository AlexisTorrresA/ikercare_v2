from __future__ import annotations

import textwrap
from datetime import date

import fitz
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .requested_chemo import sync_requested_chemo_once
from .v2_extended_features import _pdf_bytes, _report_preview
from .v2_models import CareChemoSession
from .v2_router import _build_summary, _membership

hotfix_api = APIRouter(prefix="/api/v2", tags=["IkerCare V2 hotfix"])


@hotfix_api.get("/patients/{patient_id}/chemo/all")
def list_all_chemo_hotfix(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Ruta estática prioritaria para evitar que /chemo/all sea capturada por /chemo/{item_id}."""
    _membership(db, user.id, patient_id)
    sync_requested_chemo_once(db, user)
    rows = db.scalars(
        select(CareChemoSession)
        .where(CareChemoSession.patient_id == patient_id)
        .order_by(CareChemoSession.scheduled_at.asc(), CareChemoSession.id.asc())
    ).all()
    return [
        {
            "id": item.id,
            "scheduled_at": item.scheduled_at.isoformat(timespec="minutes"),
            "name": item.name,
            "protocol": item.protocol,
            "cycle": item.cycle,
            "purpose": item.purpose,
            "status": item.status,
            "status_value": item.status,
            "notes": item.notes,
            "adverse_effects": item.adverse_effects,
        }
        for item in rows
    ]


def _fallback_pdf(summary: dict) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    x = 48
    y = 52

    for raw_line in str(summary.get("plain_text") or "Informe IkerCare").splitlines():
        wrapped = textwrap.wrap(raw_line, width=88, break_long_words=False) or [""]
        for line in wrapped:
            if y > 790:
                page = doc.new_page(width=595, height=842)
                y = 52
            page.insert_text((x, y), line, fontsize=10.5, fontname="helv", color=(0.08, 0.12, 0.2))
            y += 15
        y += 3

    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


@hotfix_api.get("/patients/{patient_id}/reports/pdf")
def report_pdf_hotfix(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    scope: str = Query(default="all"),
    start_date: date | None = None,
    end_date: date | None = None,
    hospitalization_id: int | None = None,
    hospital: str | None = None,
    medication: str | None = None,
    use_ai: bool = False,
) -> Response:
    """Genera el PDF y usa el resumen estable como respaldo si falla el generador detallado."""
    _membership(db, user.id, patient_id)
    payload = {
        "scope": scope,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "hospitalization_id": hospitalization_id,
        "hospital": hospital,
        "medication": medication,
        "use_ai": use_ai,
    }
    try:
        report = _report_preview(db, patient_id, payload)
        pdf = _pdf_bytes(report)
    except Exception:
        summary = _build_summary(
            db,
            patient_id,
            start_date,
            end_date,
            hospitalization_id,
            "es",
            "complete",
        )
        pdf = _fallback_pdf(summary)

    filename = f"IkerCare-informe-{date.today().isoformat()}.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )
