from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import _ai_narrative, _hospital_facts, _local_narrative, _pdf_bytes
from .v2_router import _membership

logger = logging.getLogger("ikercare.report_alias")
report_alias_api = APIRouter(prefix="/api/v2", tags=["IkerCare hospitalization report"])


@report_alias_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report")
def hospital_report(patient_id: int, hospitalization_id: int, use_ai: bool = True, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    _membership(db, user.id, patient_id)
    facts = _hospital_facts(db, patient_id, hospitalization_id)
    narrative, ai_used, message = _ai_narrative(facts) if use_ai else (_local_narrative(facts), False, None)
    return {"facts": facts, "statistics": facts["statistics"], "narrative": narrative, "ai_used": ai_used, "ai_message": message}


@report_alias_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report.pdf")
def hospital_report_pdf(patient_id: int, hospitalization_id: int, use_ai: bool = True, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    _membership(db, user.id, patient_id)
    try:
        facts = _hospital_facts(db, patient_id, hospitalization_id)
        narrative, ai_used, message = _ai_narrative(facts) if use_ai else (_local_narrative(facts), False, None)
        data = _pdf_bytes({"facts": facts, "narrative": narrative, "ai_used": ai_used, "ai_message": message})
        filename = f"IkerCare-hospitalizacion-{hospitalization_id}.pdf"
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Length": str(len(data)), "Cache-Control": "private, no-store"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hospitalization PDF failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No fue posible generar el PDF. Inténtalo nuevamente.") from exc
