
from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class UserProfile(Base):
    __tablename__ = "care_user_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True, index=True, nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    accepted_privacy_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    accepted_terms_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    guardian_attested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ai_processing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Patient(Base):
    __tablename__ = "care_patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    birth_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sex_at_birth: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    primary_hospital: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    medical_record: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    allergies: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnoses: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    photo_ciphertext: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    photo_mime: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    photo_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PatientMember(Base):
    __tablename__ = "care_patient_members"
    __table_args__ = (
        UniqueConstraint("patient_id", "user_id", name="uq_care_patient_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="editor")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareMedication(Base):
    __tablename__ = "care_medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    generic_name: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    medication_type: Mapped[str] = mapped_column(String(120), default="Medicamento")
    purpose: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    dose: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(40), default="manual")
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CareMedicationSchedule(Base):
    __tablename__ = "care_medication_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), index=True)
    time_of_day: Mapped[time] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CareMedicationLog(Base):
    __tablename__ = "care_medication_logs"
    __table_args__ = (
        UniqueConstraint("schedule_id", "log_date", name="uq_care_med_schedule_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("care_medication_schedules.id", ondelete="CASCADE"), index=True)
    log_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="taken")
    actual_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CareMedicationEvent(Base):
    __tablename__ = "care_medication_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareChemoSession(Base):
    __tablename__ = "care_chemo_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    name: Mapped[str] = mapped_column(String(180))
    protocol: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    cycle: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    adverse_effects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareVitalRecord(Base):
    __tablename__ = "care_vital_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    systolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    diastolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oxygen_saturation: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    respiratory_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class CareCrisisEvent(Base):
    __tablename__ = "care_crisis_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(140))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    consciousness: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    actions_taken: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class CareDailyNote(Base):
    __tablename__ = "care_daily_notes"
    __table_args__ = (
        UniqueConstraint("patient_id", "note_date", name="uq_care_daily_note"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    note_date: Mapped[date] = mapped_column(Date, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EliminationLog(Base):
    __tablename__ = "care_elimination_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    diaper_status: Mapped[str] = mapped_column(String(30), default="wet")
    urine_amount: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    urine_color: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    stool_description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class FoodLog(Base):
    __tablename__ = "care_food_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    meal_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    item: Mapped[str] = mapped_column(String(240))
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    tolerated: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    vomiting: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class CareTeamMember(Base):
    __tablename__ = "care_team_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    specialty: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    hospital: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Hospitalization(Base):
    __tablename__ = "care_hospitalizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospital: Mapped[str] = mapped_column(String(220))
    service: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    admission_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    discharge_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    epicrisis_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClinicalDocument(Base):
    __tablename__ = "care_clinical_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("care_hospitalizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(80), default="exam")
    exam_name: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    hospital: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(40), default="pending")
    extraction_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClinicalHistoryEvent(Base):
    __tablename__ = "care_history_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    category: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hospital: Mapped[Optional[str]] = mapped_column(String(220), nullable=True)
    clinician_name: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("care_clinical_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ShareLink(Base):
    __tablename__ = "care_share_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    detail: Mapped[str] = mapped_column(String(30), default="simple")
    language: Mapped[str] = mapped_column(String(10), default="es")
    include_documents: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hospitalization_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("care_hospitalizations.id", ondelete="SET NULL"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_access_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ConsentRecord(Base):
    __tablename__ = "care_consents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[Optional[int]] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=True)
    consent_type: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(40))
    granted: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "care_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[Optional[int]] = mapped_column(ForeignKey("care_patients.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
