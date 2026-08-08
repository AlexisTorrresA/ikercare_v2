from datetime import datetime
from os import getenv

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .auth import hash_password, verify_password
from .models import ChildProfile, Medication, MedicationSchedule, User


CLINICAL_MEDICATIONS = [
    {
        "name": "Levetiracetam",
        "medication_type": "Anticonvulsivo",
        "purpose": "Prevención y control de convulsiones.",
        "dose": "390 mg",
        "route": "Endovenosa (EV)",
        "frequency": "Cada 12 horas",
        "instructions": "Transcrito de la hoja hospitalaria. Confirmar dosis, vía y horario con la indicación vigente.",
        "times": ["01:00", "13:00"],
    },
    {
        "name": "Captopril",
        "medication_type": "Antihipertensivo · inhibidor ECA",
        "purpose": "Control de la presión arterial y apoyo cardiovascular.",
        "dose": "1,5 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 8 horas",
        "instructions": "Confirmar con enfermería qué hacer si vomita o si la presión está fuera del rango indicado.",
        "times": ["07:00", "15:00", "23:00"],
    },
    {
        "name": "Gabapentina",
        "medication_type": "Neuromodulador · anticonvulsivo",
        "purpose": "Manejo de dolor neuropático; su uso exacto depende de la indicación clínica.",
        "dose": "50 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 24 horas",
        "instructions": "Transcrito de la hoja hospitalaria. No suspender ni modificar sin indicación médica.",
        "times": ["21:00"],
    },
    {
        "name": "Clobazam",
        "medication_type": "Benzodiacepina anticonvulsiva",
        "purpose": "Apoyo en el control de convulsiones.",
        "dose": "7,5 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 24 horas",
        "instructions": "La fotografía no permite confirmar una hora fija. Registrar cada administración y definir el horario con enfermería.",
        "times": [],
    },
    {
        "name": "Lacosamida",
        "medication_type": "Anticonvulsivo",
        "purpose": "Control de convulsiones.",
        "dose": "6 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 12 horas",
        "instructions": "La fotografía no permite confirmar las horas exactas. Registrar cada administración y definirlas con enfermería.",
        "times": [],
    },
    {
        "name": "Amlodipino",
        "medication_type": "Antihipertensivo · bloqueador de canales de calcio",
        "purpose": "Control de la presión arterial.",
        "dose": "3 mg",
        "route": "Vía oral (VO)",
        "frequency": "Cada 24 horas",
        "instructions": "Registrar la presión si el equipo clínico lo solicita.",
        "times": ["17:00"],
    },
    {
        "name": "Piridoxina",
        "medication_type": "Vitamina B6 · premedicación",
        "purpose": "Premedicación indicada en la hoja antes de la vincristina (VCR).",
        "dose": "70 mg",
        "route": "Endovenosa (EV)",
        "frequency": "Previo a VCR",
        "instructions": "No es una dosis diaria fija. Registrar solo cuando sea administrada y confirmar el momento con oncología/enfermería.",
        "times": [],
    },
    {
        "name": "Ondansetrón",
        "medication_type": "Antiemético · antagonista 5-HT3",
        "purpose": "Prevención o tratamiento de náuseas y vómitos, especialmente asociados a quimioterapia.",
        "dose": "2 mg",
        "route": "Endovenosa (EV)",
        "frequency": "Cada 8 horas",
        "instructions": "La fotografía no permite confirmar las horas exactas. Registrar cada administración y definirlas con enfermería.",
        "times": [],
    },
    {
        "name": "Dexametasona",
        "medication_type": "Corticoide",
        "purpose": "Uso antiinflamatorio o como parte de la pauta oncológica, según la indicación médica.",
        "dose": "No legible en la fotografía",
        "route": "Confirmar con el equipo clínico",
        "frequency": "No legible en la fotografía",
        "instructions": "Completar dosis, vía y frecuencia usando la orden médica vigente antes de registrar una administración.",
        "times": [],
    },
    {
        "name": "PEG (polietilenglicol)",
        "medication_type": "Laxante osmótico",
        "purpose": "Ayuda a tratar el estreñimiento y ablandar las deposiciones.",
        "dose": "13 g",
        "route": "Vía oral (VO)",
        "frequency": "Según indicación / sin frecuencia visible",
        "instructions": "Registrar cuando sea administrado. Confirmar la formulación y frecuencia exactas con el equipo clínico.",
        "times": [],
    },
    {
        "name": "Paracetamol",
        "medication_type": "Analgésico y antipirético",
        "purpose": "Manejo de dolor o fiebre según indicación.",
        "dose": "200 mg",
        "route": "Endovenosa (EV)",
        "frequency": "SOS / según indicación",
        "instructions": "Registrar la hora, el motivo y la respuesta observada. No repetir fuera de la pauta hospitalaria.",
        "times": [],
    },
    {
        "name": "Lorazepam",
        "medication_type": "Benzodiacepina · medicamento de rescate",
        "purpose": "Puede utilizarse para control de crisis o sedación según indicación médica.",
        "dose": "1,5 mg",
        "route": "Endovenosa (EV)",
        "frequency": "SOS / rescate según indicación",
        "instructions": "Solo registrar cuando sea administrado por el equipo clínico. Anotar motivo, duración de la crisis y respuesta.",
        "times": [],
    },
]


def _is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    return normalized.startswith("confirmar") or normalized.startswith("dato inicial")


def _add_missing_schedules(medication: Medication, times: list[str]) -> None:
    existing_times = {schedule.time_of_day for schedule in medication.schedules}
    for time_value in times:
        parsed_time = datetime.strptime(time_value, "%H:%M").time()
        if parsed_time not in existing_times:
            medication.schedules.append(MedicationSchedule(time_of_day=parsed_time, active=True))


def _upsert_clinical_medications(db: Session) -> None:
    existing = db.scalars(select(Medication).options(selectinload(Medication.schedules))).all()
    by_name = {medication.name.strip().casefold(): medication for medication in existing}

    for item in CLINICAL_MEDICATIONS:
        key = item["name"].strip().casefold()
        medication = by_name.get(key)
        if medication is None:
            medication = Medication(
                name=item["name"],
                medication_type=item["medication_type"],
                purpose=item["purpose"],
                dose=item["dose"],
                route=item["route"],
                frequency=item["frequency"],
                instructions=item["instructions"],
            )
            _add_missing_schedules(medication, item["times"])
            db.add(medication)
            by_name[key] = medication
            continue

        # Actualiza únicamente campos vacíos o que todavía conservan los textos
        # de ejemplo. Así, un cambio manual del usuario nunca se sobrescribe al
        # reiniciar Docker.
        if _is_placeholder(medication.medication_type):
            medication.medication_type = item["medication_type"]
        if _is_placeholder(medication.purpose):
            medication.purpose = item["purpose"]
        if _is_placeholder(medication.dose):
            medication.dose = item["dose"]
        if _is_placeholder(medication.route) or medication.route == "Según indicación":
            medication.route = item["route"]
        if _is_placeholder(medication.frequency):
            medication.frequency = item["frequency"]
        if _is_placeholder(medication.instructions) or "Dato inicial de ejemplo" in (medication.instructions or ""):
            medication.instructions = item["instructions"]
        # No se vuelven a crear horarios en medicamentos ya existentes: una
        # edición manual (incluido dejarlos sin hora fija) debe prevalecer.


def seed_database(db: Session) -> None:
    username = getenv("ADMIN_USERNAME", "admin")
    password = getenv("ADMIN_PASSWORD", "cambiar-esta-clave")

    user = db.scalar(select(User).where(User.username == username))
    if not user:
        db.add(User(username=username, password_hash=hash_password(password)))
    elif not verify_password(password, user.password_hash):
        # El archivo .env es la fuente de verdad para la clave de la cuenta inicial.
        user.password_hash = hash_password(password)

    profile = db.scalar(select(ChildProfile).limit(1))
    if not profile:
        db.add(
            ChildProfile(
                name=getenv("CHILD_NAME", "Iker"),
                hospital=getenv("HOSPITAL_NAME") or None,
                notes="Verificar siempre horarios y dosis con la indicación vigente del equipo clínico.",
            )
        )

    seed_samples = getenv("SEED_SAMPLE_DATA", "true").lower() in {"1", "true", "yes", "si", "sí"}
    if seed_samples:
        _upsert_clinical_medications(db)

    db.commit()
