from __future__ import annotations

import textwrap
from datetime import datetime

import fitz
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import get_current_user
from .db import get_db
from .models import User
from .v2_clinical_history import ChemoEvolutionEvent
from .v2_models import CareChemoSession, Patient
from .v2_router import _membership

chemo_report_api = APIRouter(prefix="/api/v2", tags=["IkerCare chemotherapy report"])


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "Sin fecha"
    return value.strftime("%d/%m/%Y %H:%M")


def _make_pdf(patient: Patient, sessions: list[CareChemoSession], events_by_chemo: dict[int, list[ChemoEvolutionEvent]]) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 48
    margin = 46

    def new_page() -> None:
        nonlocal page, y
        page = doc.new_page(width=595, height=842)
        y = 48

    def add(text: str = "", size: float = 10.5, bold: bool = False, gap: float = 4) -> None:
        nonlocal y
        font = "hebo" if bold else "helv"
        safe = str(text or "").replace("•", "-")
        width = 84 if size <= 10.5 else 66
        lines = textwrap.wrap(safe, width=width, break_long_words=False, replace_whitespace=False) or [""]
        needed = len(lines) * (size + 4) + gap
        if y + needed > 790:
            new_page()
        for line in lines:
            page.insert_text((margin, y), line, fontsize=size, fontname=font, color=(0.08, 0.12, 0.2))
            y += size + 4
        y += gap

    add("IkerCare - Informe de quimioterapia", 17, True, 8)
    add(f"Paciente: {patient.name}", 12, True)
    add("Orden: quimioterapia más reciente a más antigua.", 9.5)
    add("Este informe reúne los registros de quimioterapia y los eventos posteriores ingresados en IkerCare.", 9.5, False, 10)

    if not sessions:
        add("No hay quimioterapias registradas.", 11)
    else:
        for index, session in enumerate(sessions, start=1):
            add(f"{index}. {session.name}", 13, True, 2)
            add(f"Fecha/hora: {_fmt_dt(session.scheduled_at)}", 10)
            if session.protocol:
                add(f"Protocolo: {session.protocol}", 10)
            if session.cycle:
                add(f"Ciclo: {session.cycle}", 10)
            if session.status:
                add(f"Estado: {session.status}", 10)
            if session.purpose:
                add(f"Objetivo: {session.purpose}", 10)
            if session.notes:
                add(f"Notas: {session.notes}", 10)
            if session.adverse_effects:
                add(f"Efectos registrados: {session.adverse_effects}", 10)

            events = events_by_chemo.get(session.id, [])
            add("Evolución posterior", 11, True, 2)
            if not events:
                add("Sin eventos posteriores registrados.", 9.5)
            else:
                for event in events:
                    add(f"- {_fmt_dt(event.occurred_at)} · {event.event_type}", 9.8, True, 1)
                    if event.description:
                        add(event.description, 9.5, False, 2)
            add("", 4, False, 6)

    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


@chemo_report_api.get("/patients/{patient_id}/chemo-report.pdf")
def chemo_report_pdf(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    _membership(db, user.id, patient_id)
    patient = db.get(Patient, patient_id)
    sessions = db.scalars(
        select(CareChemoSession)
        .where(CareChemoSession.patient_id == patient_id)
        .order_by(CareChemoSession.scheduled_at.desc(), CareChemoSession.id.desc())
    ).all()
    events_by_chemo: dict[int, list[ChemoEvolutionEvent]] = {}
    if sessions:
        session_ids = [item.id for item in sessions]
        events = db.scalars(
            select(ChemoEvolutionEvent)
            .where(ChemoEvolutionEvent.chemo_session_id.in_(session_ids))
            .order_by(ChemoEvolutionEvent.occurred_at.asc(), ChemoEvolutionEvent.id.asc())
        ).all()
        for event in events:
            events_by_chemo.setdefault(event.chemo_session_id, []).append(event)

    pdf = _make_pdf(patient, sessions, events_by_chemo)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="IkerCare-quimioterapia.pdf"',
            "Content-Length": str(len(pdf)),
            "Cache-Control": "private, no-store",
        },
    )
