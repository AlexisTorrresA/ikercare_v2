from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

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

PRIMARY = (0.035, 0.30, 0.53)
PRIMARY_DARK = (0.025, 0.18, 0.34)
ACCENT = (0.05, 0.62, 0.58)
INK = (0.09, 0.13, 0.20)
MUTED = (0.38, 0.44, 0.52)
LIGHT = (0.95, 0.97, 0.985)
BORDER = (0.84, 0.88, 0.92)
WHITE = (1, 1, 1)
A4_W = 595
A4_H = 842
MARGIN = 42
HEADER_H = 112
FOOTER_Y = 814
LOGO_PATH = Path(__file__).resolve().parent / "static" / "icons" / "icon-192.png"


def _fmt_dt(value: datetime | None) -> str:
    if not value:
        return "Sin fecha"
    return value.strftime("%d/%m/%Y %H:%M")


def _wrap(text: str, width: int = 78) -> list[str]:
    safe = str(text or "").replace("•", "-").replace("·", "-")
    return textwrap.wrap(
        safe,
        width=width,
        break_long_words=False,
        replace_whitespace=False,
    ) or [""]


def _make_pdf(
    patient: Patient,
    sessions: list[CareChemoSession],
    events_by_chemo: dict[int, list[ChemoEvolutionEvent]],
) -> bytes:
    doc = fitz.open()
    page: fitz.Page | None = None
    y = 0.0
    page_no = 0

    def draw_header() -> None:
        nonlocal y
        assert page is not None
        page.draw_rect(fitz.Rect(0, 0, A4_W, HEADER_H), fill=PRIMARY_DARK, color=PRIMARY_DARK)
        page.draw_rect(fitz.Rect(0, HEADER_H - 8, A4_W, HEADER_H), fill=ACCENT, color=ACCENT)

        logo_rect = fitz.Rect(MARGIN, 27, MARGIN + 56, 83)
        if LOGO_PATH.exists():
            try:
                page.draw_circle((MARGIN + 28, 55), 29, fill=WHITE, color=WHITE)
                page.insert_image(logo_rect, filename=str(LOGO_PATH), keep_proportion=True)
            except Exception:
                page.draw_circle((MARGIN + 28, 55), 27, fill=WHITE, color=WHITE)
                page.insert_text((MARGIN + 13, 64), "IC", fontname="hebo", fontsize=18, color=PRIMARY_DARK)
        else:
            page.draw_circle((MARGIN + 28, 55), 27, fill=WHITE, color=WHITE)
            page.insert_text((MARGIN + 13, 64), "IC", fontname="hebo", fontsize=18, color=PRIMARY_DARK)

        page.insert_text((MARGIN + 74, 47), "IkerCare", fontname="hebo", fontsize=19, color=WHITE)
        page.insert_text(
            (MARGIN + 74, 69),
            "Informe de quimioterapia",
            fontname="helv",
            fontsize=11.5,
            color=(0.82, 0.90, 0.97),
        )
        page.insert_text(
            (A4_W - MARGIN - 122, 47),
            "REGISTRO CLÍNICO",
            fontname="hebo",
            fontsize=8.5,
            color=ACCENT,
        )
        y = HEADER_H + 22

    def draw_footer() -> None:
        assert page is not None
        page.draw_line(
            (MARGIN, FOOTER_Y - 12),
            (A4_W - MARGIN, FOOTER_Y - 12),
            color=BORDER,
            width=0.7,
        )
        page.insert_text(
            (MARGIN, FOOTER_Y),
            "IkerCare | Registro familiar de salud",
            fontname="helv",
            fontsize=7.5,
            color=MUTED,
        )
        page_label = f"Página {page_no}"
        label_width = fitz.get_text_length(page_label, fontname="helv", fontsize=7.5)
        page.insert_text(
            (A4_W - MARGIN - label_width, FOOTER_Y),
            page_label,
            fontname="helv",
            fontsize=7.5,
            color=MUTED,
        )

    def new_page() -> None:
        nonlocal page, y, page_no
        if page is not None:
            draw_footer()
        page = doc.new_page(width=A4_W, height=A4_H)
        page_no += 1
        draw_header()

    def ensure_space(height: float) -> None:
        if y + height > FOOTER_Y - 24:
            new_page()

    def write_lines(
        text: str,
        x: float,
        width_chars: int = 78,
        size: float = 9.5,
        color=INK,
        bold: bool = False,
        line_gap: float = 3,
        after: float = 0,
    ) -> None:
        nonlocal y
        assert page is not None
        lines = _wrap(text, width_chars)
        height = len(lines) * (size + line_gap) + after
        ensure_space(height)
        for line in lines:
            page.insert_text(
                (x, y),
                line,
                fontname="hebo" if bold else "helv",
                fontsize=size,
                color=color,
            )
            y += size + line_gap
        y += after

    def draw_pill(text: str, x: float, baseline: float, fill) -> float:
        assert page is not None
        padding = 7
        fontsize = 7.7
        width = fitz.get_text_length(text, fontname="helv", fontsize=fontsize) + padding * 2
        page.draw_rect(
            fitz.Rect(x, baseline - 11, x + width, baseline + 4),
            fill=fill,
            color=fill,
        )
        page.insert_text(
            (x + padding, baseline),
            text,
            fontname="helv",
            fontsize=fontsize,
            color=PRIMARY_DARK,
        )
        return width

    new_page()
    assert page is not None

    # Resumen superior del informe.
    ensure_space(96)
    page.draw_rect(
        fitz.Rect(MARGIN, y - 8, A4_W - MARGIN, y + 78),
        fill=LIGHT,
        color=BORDER,
        width=0.8,
    )
    page.insert_text((MARGIN + 16, y + 13), "PACIENTE", fontname="hebo", fontsize=7.8, color=ACCENT)
    patient_lines = _wrap(patient.name, 40)
    page.insert_text((MARGIN + 16, y + 34), patient_lines[0], fontname="hebo", fontsize=15, color=INK)
    page.insert_text(
        (MARGIN + 16, y + 55),
        f"{len(sessions)} quimioterapia(s) registrada(s)",
        fontname="helv",
        fontsize=9,
        color=MUTED,
    )

    right_x = A4_W - MARGIN - 190
    page.insert_text((right_x, y + 13), "GENERADO", fontname="hebo", fontsize=7.8, color=ACCENT)
    page.insert_text(
        (right_x, y + 34),
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        fontname="hebo",
        fontsize=10,
        color=INK,
    )
    page.insert_text(
        (right_x, y + 55),
        "Orden: más reciente a más antigua",
        fontname="helv",
        fontsize=8.5,
        color=MUTED,
    )
    y += 98

    write_lines(
        "Este informe consolida las quimioterapias registradas en IkerCare y su evolución posterior. "
        "No sustituye la ficha clínica oficial del centro tratante.",
        MARGIN,
        size=8.6,
        color=MUTED,
        after=12,
    )

    if not sessions:
        ensure_space(70)
        page.draw_rect(
            fitz.Rect(MARGIN, y - 5, A4_W - MARGIN, y + 50),
            fill=LIGHT,
            color=BORDER,
            width=0.8,
        )
        page.insert_text(
            (MARGIN + 16, y + 23),
            "No hay quimioterapias registradas.",
            fontname="helv",
            fontsize=10,
            color=MUTED,
        )
        y += 65
    else:
        for index, session in enumerate(sessions, start=1):
            events = events_by_chemo.get(session.id, [])
            name_lines = _wrap(session.name, 48)
            header_height = 82 + max(0, len(name_lines) - 1) * 15
            ensure_space(header_height + 26)
            top = y

            page.draw_rect(
                fitz.Rect(MARGIN, top - 5, A4_W - MARGIN, top + header_height),
                fill=WHITE,
                color=BORDER,
                width=0.8,
            )
            page.draw_rect(
                fitz.Rect(MARGIN, top - 5, MARGIN + 5, top + header_height),
                fill=ACCENT,
                color=ACCENT,
            )
            page.insert_text((MARGIN + 18, top + 16), f"{index:02d}", fontname="hebo", fontsize=9, color=ACCENT)

            name_y = top + 16
            for line in name_lines:
                page.insert_text((MARGIN + 48, name_y), line, fontname="hebo", fontsize=13, color=INK)
                name_y += 15

            date_y = name_y + 5
            page.insert_text(
                (MARGIN + 48, date_y),
                _fmt_dt(session.scheduled_at),
                fontname="helv",
                fontsize=9,
                color=MUTED,
            )

            pill_y = date_y + 26
            pill_x = MARGIN + 48
            pills = [
                ("Protocolo", session.protocol, (0.91, 0.95, 0.99)),
                ("Ciclo", session.cycle, (0.91, 0.97, 0.96)),
                ("Estado", session.status, (0.97, 0.94, 0.88)),
            ]
            for label, value, fill in pills:
                if not value:
                    continue
                pill_text = f"{label}: {value}"
                expected = fitz.get_text_length(pill_text, fontname="helv", fontsize=7.7) + 14
                if pill_x + expected > A4_W - MARGIN - 12:
                    break
                pill_x += draw_pill(pill_text, pill_x, pill_y, fill) + 7

            y = top + header_height + 16

            for label, value in (
                ("Objetivo", session.purpose),
                ("Notas", session.notes),
                ("Efectos registrados", session.adverse_effects),
            ):
                if value:
                    write_lines(
                        f"{label}: {value}",
                        MARGIN + 12,
                        width_chars=82,
                        size=9.2,
                        color=INK,
                        after=4,
                    )

            ensure_space(38)
            page.insert_text(
                (MARGIN + 12, y),
                "EVOLUCIÓN POSTERIOR",
                fontname="hebo",
                fontsize=8.4,
                color=PRIMARY,
            )
            y += 18

            if not events:
                write_lines(
                    "Sin eventos posteriores registrados.",
                    MARGIN + 24,
                    size=9,
                    color=MUTED,
                    after=12,
                )
            else:
                for event in events:
                    description_lines = _wrap(event.description or "", 74) if event.description else []
                    event_height = 35 + len(description_lines) * 12
                    ensure_space(event_height)
                    line_x = MARGIN + 22
                    page.draw_line(
                        (line_x, y - 4),
                        (line_x, y + event_height - 12),
                        color=BORDER,
                        width=1,
                    )
                    page.draw_circle((line_x, y + 5), 3.2, fill=ACCENT, color=ACCENT)
                    page.insert_text(
                        (line_x + 14, y + 8),
                        _fmt_dt(event.occurred_at),
                        fontname="hebo",
                        fontsize=8.4,
                        color=PRIMARY,
                    )
                    page.insert_text(
                        (line_x + 132, y + 8),
                        event.event_type,
                        fontname="hebo",
                        fontsize=9.2,
                        color=INK,
                    )
                    y += 22
                    if event.description:
                        write_lines(
                            event.description,
                            line_x + 14,
                            width_chars=72,
                            size=8.8,
                            color=MUTED,
                            after=6,
                        )
                    else:
                        y += 6
            y += 6

    draw_footer()
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
