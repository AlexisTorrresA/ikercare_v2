from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User
from .v2_models import CareMedication, CareMedicationSchedule, Patient, PatientMember

# Transcripción de los medicamentos visibles en las capturas entregadas por el usuario.
# No se inventan dosis u horarios que no sean legibles en las imágenes.
REQUESTED_MEDICATIONS = [
    {
        "name": "Amlodipino",
        "medication_type": "Antihipertensivo · bloqueador de canales de calcio",
        "purpose": "Control de la presión arterial.",
        "dose": "3 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 24 horas",
        "times": ["15:00"],
    },
    {
        "name": "Captopril",
        "medication_type": "Antihipertensivo · inhibidor ECA",
        "purpose": "Control de la presión arterial y apoyo cardiovascular.",
        "dose": "1,5 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 8 horas",
        "times": ["07:00", "15:00", "23:00"],
    },
    {
        "name": "Clobazam",
        "medication_type": "Benzodiacepina anticonvulsiva",
        "purpose": "Apoyo en el control de convulsiones.",
        "dose": "7,5 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 24 horas",
        "times": ["23:00"],
    },
    {
        "name": "Dexametasona",
        "medication_type": "Corticoide / antiinflamatorio",
        "purpose": "Reduce inflamación y edema. En neurología/oncológica puede utilizarse para disminuir inflamación alrededor de lesiones del sistema nervioso.",
        "dose": "2 mg",
        "route": "Endovenosa (EV)",
        "frequency": "Cada 8 horas",
        "times": ["07:00", "15:00", "23:00"],
    },
    {
        "name": "Filgrastim",
        "medication_type": "Factor estimulante de colonias / estimulante de glóbulos blancos",
        "purpose": "Estimula la médula ósea para producir más neutrófilos, un tipo de glóbulo blanco que ayuda a combatir infecciones. Se usa frecuentemente cuando la quimioterapia disminuye los neutrófilos.",
        "dose": None,
        "route": "Subcutánea (SC)",
        "frequency": "Cada 24 horas",
        "times": ["12:00"],
    },
    {
        "name": "Gabapentina",
        "medication_type": "Neuromodulador · anticonvulsivo",
        "purpose": "Manejo de dolor neuropático; su uso exacto depende de la indicación clínica.",
        "dose": "50 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 24 horas",
        "times": ["21:00"],
    },
    {
        "name": "Lacosamida",
        "medication_type": "Anticonvulsivo",
        "purpose": "Control de convulsiones.",
        "dose": "12 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 12 horas",
        "times": ["07:00", "19:00"],
    },
    {
        "name": "Levetiracetam",
        "medication_type": "Anticonvulsivo",
        "purpose": "Prevención y control de convulsiones.",
        "dose": "390 mg",
        "route": "Endovenosa (EV)",
        "frequency": "Cada 12 horas",
        "times": ["08:00", "20:00"],
    },
    {
        "name": "Lorazepam",
        "medication_type": "Benzodiacepina · medicamento de rescate",
        "purpose": "Puede utilizarse para control de crisis o sedación según indicación médica.",
        "dose": "1,5 mg",
        "route": "Endovenosa (EV)",
        "frequency": "SOS / rescate según indicación",
        "times": [],
    },
    {
        "name": "Omeprazol",
        "medication_type": "Inhibidor de bomba de protones",
        "purpose": "Disminuye la producción de ácido gástrico.",
        "dose": None,
        "route": None,
        "frequency": None,
        "times": None,
    },
]


def _replace_schedules(db: Session, medication_id: int, times: list[str]) -> None:
    rows = db.scalars(
        select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == medication_id)
    ).all()
    wanted = {datetime.strptime(value, "%H:%M").time() for value in times}
    by_time = {row.time_of_day: row for row in rows}
    for row in rows:
        row.active = row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=medication_id, time_of_day=value, active=True))


def sync_requested_medications(db: Session, user: User) -> None:
    """Aplica solo a la cuenta administradora inicial y a su paciente configurado."""
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

    patient = next((patient for patient, _ in owned if patient.name.strip().lower() == child_name), owned[0][0])
    existing = db.scalars(
        select(CareMedication).where(CareMedication.patient_id == patient.id)
    ).all()
    by_name = {item.name.strip().casefold(): item for item in existing}

    changed = False
    for source in REQUESTED_MEDICATIONS:
        key = source["name"].strip().casefold()
        medication = by_name.get(key)
        if medication is None:
            medication = CareMedication(
                patient_id=patient.id,
                name=source["name"],
                medication_type=source["medication_type"],
                purpose=source["purpose"],
                dose=source["dose"],
                route=source["route"],
                frequency=source["frequency"],
                source="user_images_2026_08",
                created_by_user_id=user.id,
            )
            db.add(medication)
            db.flush()
            by_name[key] = medication
            changed = True
        else:
            medication.medication_type = source["medication_type"]
            medication.purpose = source["purpose"]
            if source["dose"] is not None:
                medication.dose = source["dose"]
            if source["route"] is not None:
                medication.route = source["route"]
            if source["frequency"] is not None:
                medication.frequency = source["frequency"]
            medication.active = True
            changed = True

        if source["times"] is not None:
            _replace_schedules(db, medication.id, source["times"])

    if changed:
        db.commit()
