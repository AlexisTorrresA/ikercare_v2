from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User
from .v2_models import CareChemoSession, Patient, PatientMember

SOURCE_MARKER = "user_chemo_cycle1_2026_08"

# Datos transcritos únicamente desde las etiquetas y hoja aportadas por el usuario.
# Se evita completar información clínica que no sea claramente visible.
REQUESTED_CHEMO = [
    {
        "scheduled_at": datetime(2026, 8, 6, 9, 45),
        "name": "Vincristina",
        "protocol": "Oncológico",
        "cycle": "Ciclo 1",
        "purpose": None,
        "status": "completed",
        "notes": (
            "Dosis: 0,70 mg. Vía endovenosa (EV). Volumen total: 0,70 mL. "
            "Hospital Luis Calvo Mackenna · Central de Mezclas · Oncología · receta 14925. "
            "Fecha de admisión visible: 06-08-2026. Elaboración: 05-08-2026. "
            "Hora registrada en la hoja de administración: 09:45. "
            f"Origen: {SOURCE_MARKER}."
        ),
        "adverse_effects": "Sin complicaciones registradas en la anotación visible.",
    },
    {
        "scheduled_at": datetime(2026, 8, 6, 11, 20),
        "name": "Ciclofosfamida",
        "protocol": "Oncológico",
        "cycle": "Ciclo 1",
        "purpose": None,
        "status": "completed",
        "notes": (
            "Dosis: 780 mg. Vía endovenosa (EV). Preparación indicada en etiqueta: glucosa al 5%; "
            "61,00 mL de preparado y volumen total 100 mL. "
            "Hospital Luis Calvo Mackenna · Central de Mezclas · Oncología · receta 14925. "
            "Fecha de admisión visible: 06-08-2026. Elaboración: 05-08-2026. "
            "Administración registrada en la hoja desde 11:20 hasta 13:20. "
            f"Origen: {SOURCE_MARKER}."
        ),
        "adverse_effects": None,
    },
]


def sync_requested_chemo_once(db: Session, user: User) -> None:
    """Sincroniza los dos agentes confirmados del primer ciclo del paciente inicial del admin.

    Si ya se habían creado con una transcripción anterior, se corrigen en lugar de crear
    duplicados. Solo se modifican registros que contienen SOURCE_MARKER.
    """
    admin_username = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    if user.username.strip().lower() != admin_username:
        return

    child_name = os.getenv("CHILD_NAME", "Iker").strip().lower()
    owned = db.execute(
        select(Patient, PatientMember)
        .join(PatientMember, PatientMember.patient_id == Patient.id)
        .where(PatientMember.user_id == user.id, PatientMember.role == "owner")
        .order_by(Patient.id)
    ).all()
    if not owned:
        return

    patient = next(
        (patient for patient, _ in owned if patient.name.strip().lower() == child_name),
        owned[0][0],
    )

    changed = False
    for item in REQUESTED_CHEMO:
        existing = db.scalar(
            select(CareChemoSession).where(
                CareChemoSession.patient_id == patient.id,
                CareChemoSession.name == item["name"],
                CareChemoSession.notes.contains(SOURCE_MARKER),
            )
        )

        if existing:
            existing.scheduled_at = item["scheduled_at"]
            existing.protocol = item["protocol"]
            existing.cycle = item["cycle"]
            existing.purpose = item["purpose"]
            existing.status = item["status"]
            existing.notes = item["notes"]
            existing.adverse_effects = item["adverse_effects"]
            changed = True
            continue

        duplicate = db.scalar(
            select(CareChemoSession).where(
                CareChemoSession.patient_id == patient.id,
                CareChemoSession.name == item["name"],
                CareChemoSession.scheduled_at == item["scheduled_at"],
            )
        )
        if duplicate:
            continue

        db.add(
            CareChemoSession(
                patient_id=patient.id,
                scheduled_at=item["scheduled_at"],
                name=item["name"],
                protocol=item["protocol"],
                cycle=item["cycle"],
                purpose=item["purpose"],
                status=item["status"],
                notes=item["notes"],
                adverse_effects=item["adverse_effects"],
                created_by_user_id=user.id,
            )
        )
        changed = True

    if changed:
        db.commit()
