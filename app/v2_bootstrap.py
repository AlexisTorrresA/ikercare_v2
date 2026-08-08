
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    ChemoSession,
    ChildProfile,
    CrisisEvent,
    DailyNote,
    Medication,
    MedicationEventLog,
    MedicationLog,
    MedicationSchedule,
    User,
    VitalRecord,
)
from .v2_models import (
    CareChemoSession,
    CareCrisisEvent,
    CareDailyNote,
    CareMedication,
    CareMedicationEvent,
    CareMedicationLog,
    CareMedicationSchedule,
    CareVitalRecord,
    Patient,
    PatientMember,
    UserProfile,
)


def bootstrap_v2(db: Session) -> None:
    """Crea el espacio V2 y migra la información V1 una sola vez, sin borrar V1."""
    users = db.scalars(select(User).order_by(User.id)).all()
    for user in users:
        profile = db.get(UserProfile, user.id)
        if not profile:
            db.add(UserProfile(user_id=user.id, display_name=user.username))
    db.flush()

    if db.scalar(select(Patient.id).limit(1)) is not None:
        db.commit()
        return

    legacy_profile = db.scalar(select(ChildProfile).limit(1))
    legacy_admin = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
    owner = next((user for user in users if user.username.lower() == legacy_admin), users[0] if users else None)
    if not owner:
        db.commit()
        return

    patient = Patient(
        name=legacy_profile.name if legacy_profile else "Paciente",
        primary_hospital=legacy_profile.hospital if legacy_profile else None,
        medical_record=legacy_profile.medical_record if legacy_profile else None,
        notes=legacy_profile.notes if legacy_profile else None,
        created_by_user_id=owner.id,
    )
    db.add(patient)
    db.flush()

    # Privacidad crítica: la migración V1 pertenece únicamente a la cuenta
    # administradora legado. Nunca se concede acceso al paciente histórico a
    # usuarios que se registren posteriormente en la plataforma pública.
    db.add(PatientMember(patient_id=patient.id, user_id=owner.id, role="owner"))
    db.flush()

    medication_map: dict[int, CareMedication] = {}
    schedule_map: dict[int, CareMedicationSchedule] = {}

    medications = db.scalars(select(Medication).order_by(Medication.id)).all()
    for old in medications:
        new = CareMedication(
            patient_id=patient.id,
            name=old.name,
            medication_type=old.medication_type,
            purpose=old.purpose,
            dose=old.dose,
            route=old.route,
            frequency=old.frequency,
            instructions=old.instructions,
            active=old.active,
            source="migrated_v1",
            created_at=old.created_at,
            created_by_user_id=owner.id,
        )
        db.add(new)
        db.flush()
        medication_map[old.id] = new

    schedules = db.scalars(select(MedicationSchedule).order_by(MedicationSchedule.id)).all()
    for old in schedules:
        medication = medication_map.get(old.medication_id)
        if not medication:
            continue
        new = CareMedicationSchedule(
            medication_id=medication.id,
            time_of_day=old.time_of_day,
            active=old.active,
        )
        db.add(new)
        db.flush()
        schedule_map[old.id] = new

    for old in db.scalars(select(MedicationLog).order_by(MedicationLog.id)).all():
        schedule = schedule_map.get(old.schedule_id)
        if schedule:
            db.add(
                CareMedicationLog(
                    schedule_id=schedule.id,
                    log_date=old.log_date,
                    status=old.status,
                    actual_time=old.actual_time,
                    notes=old.notes,
                    updated_at=old.updated_at,
                    updated_by_user_id=owner.id,
                )
            )

    for old in db.scalars(select(MedicationEventLog).order_by(MedicationEventLog.id)).all():
        medication = medication_map.get(old.medication_id)
        if medication:
            db.add(
                CareMedicationEvent(
                    medication_id=medication.id,
                    occurred_at=old.occurred_at,
                    notes=old.notes,
                    created_at=old.created_at,
                    created_by_user_id=owner.id,
                )
            )

    for old in db.scalars(select(ChemoSession).order_by(ChemoSession.id)).all():
        db.add(
            CareChemoSession(
                patient_id=patient.id,
                scheduled_at=old.scheduled_at,
                name=old.name,
                protocol=old.protocol,
                cycle=old.cycle,
                purpose=old.purpose,
                status=old.status,
                notes=old.notes,
                adverse_effects=old.adverse_effects,
                created_at=old.created_at,
                created_by_user_id=owner.id,
            )
        )

    for old in db.scalars(select(VitalRecord).order_by(VitalRecord.id)).all():
        db.add(
            CareVitalRecord(
                patient_id=patient.id,
                recorded_at=old.recorded_at,
                temperature_c=old.temperature_c,
                systolic=old.systolic,
                diastolic=old.diastolic,
                heart_rate=old.heart_rate,
                oxygen_saturation=old.oxygen_saturation,
                respiratory_rate=old.respiratory_rate,
                weight_kg=old.weight_kg,
                notes=old.notes,
                created_by_user_id=owner.id,
            )
        )

    for old in db.scalars(select(CrisisEvent).order_by(CrisisEvent.id)).all():
        db.add(
            CareCrisisEvent(
                patient_id=patient.id,
                occurred_at=old.occurred_at,
                event_type=old.event_type,
                duration_seconds=old.duration_seconds,
                consciousness=old.consciousness,
                description=old.description,
                actions_taken=old.actions_taken,
                team_notified=old.team_notified,
                notes=old.notes,
                created_by_user_id=owner.id,
            )
        )

    for old in db.scalars(select(DailyNote).order_by(DailyNote.id)).all():
        db.add(
            CareDailyNote(
                patient_id=patient.id,
                note_date=old.note_date,
                text=old.text,
                updated_at=old.updated_at,
                updated_by_user_id=owner.id,
            )
        )

    db.commit()
