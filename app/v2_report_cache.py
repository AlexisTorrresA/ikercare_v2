from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import DateTime, ForeignKey, JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import get_current_user
from .db import Base, get_db
from .models import User
from .v2_clinical_history import _ai_narrative, _hospital_facts, _local_narrative, _pdf_bytes
from .v2_router import _membership, now

logger = logging.getLogger("ikercare.report_cache")
report_cache_api = APIRouter(prefix="/api/v2", tags=["IkerCare report cache"])


class HospitalReportSnapshot(Base):
    __tablename__ = "care_hospital_report_snapshots_v2"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    report_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


@report_cache_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report")
def hospital_report(
    patient_id: int,
    hospitalization_id: int,
    use_ai: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    _membership(db, user.id, patient_id)
    try:
        facts = _hospital_facts(db, patient_id, hospitalization_id)
        narrative, ai_used, message = _ai_narrative(facts) if use_ai else (_local_narrative(facts), False, None)
        report = {
            "facts": facts,
            "statistics": facts["statistics"],
            "narrative": narrative,
            "ai_used": ai_used,
            "ai_message": message,
        }
        report_id = secrets.token_urlsafe(24)
        db.add(HospitalReportSnapshot(id=report_id, patient_id=patient_id, hospitalization_id=hospitalization_id, user_id=user.id, report_json=report))
        cutoff = now() - timedelta(days=2)
        for old in db.scalars(select(HospitalReportSnapshot).where(HospitalReportSnapshot.created_at < cutoff)).all():
            db.delete(old)
        db.commit()
        return {**report, "report_id": report_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hospital report failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No fue posible generar el informe. Inténtalo nuevamente.") from exc


@report_cache_api.get("/patients/{patient_id}/hospitalizations/{hospitalization_id}/hospital-report.pdf")
def hospital_report_pdf(
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
            facts = _hospital_facts(db, patient_id, hospitalization_id)
            report = {
                "facts": facts,
                "statistics": facts["statistics"],
                "narrative": _local_narrative(facts),
                "ai_used": False,
                "ai_message": "PDF generado localmente sin repetir una llamada de IA.",
            }
        data = _pdf_bytes(report)
        filename = f"IkerCare-hospitalizacion-{hospitalization_id}.pdf"
        return Response(
            content=data,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(len(data)),
                "Cache-Control": "private, no-store",
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Hospital PDF failed patient=%s hospitalization=%s", patient_id, hospitalization_id)
        raise HTTPException(status_code=500, detail="No fue posible descargar el PDF. Inténtalo nuevamente.") from exc
