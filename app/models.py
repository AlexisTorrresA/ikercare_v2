from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChildProfile(Base):
    __tablename__ = "child_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), default="Iker")
    hospital: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    medical_record: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    medication_type: Mapped[str] = mapped_column(String(120), default="Medicamento")
    purpose: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    dose: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    route: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    frequency: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    schedules: Mapped[list[MedicationSchedule]] = relationship(
        back_populates="medication", cascade="all, delete-orphan"
    )
    event_logs: Mapped[list[MedicationEventLog]] = relationship(
        back_populates="medication", cascade="all, delete-orphan"
    )


class MedicationSchedule(Base):
    __tablename__ = "medication_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    time_of_day: Mapped[time] = mapped_column(Time)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    medication: Mapped[Medication] = relationship(back_populates="schedules")
    logs: Mapped[list[MedicationLog]] = relationship(back_populates="schedule", cascade="all, delete-orphan")


class MedicationLog(Base):
    __tablename__ = "medication_logs"
    __table_args__ = (UniqueConstraint("schedule_id", "log_date", name="uq_medication_schedule_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey("medication_schedules.id", ondelete="CASCADE"), index=True)
    log_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="taken")
    actual_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    schedule: Mapped[MedicationSchedule] = relationship(back_populates="logs")


class MedicationEventLog(Base):
    """Administraciones sin una hora fija: SOS, rescate o ligadas a un procedimiento."""

    __tablename__ = "medication_event_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("medications.id", ondelete="CASCADE"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    medication: Mapped[Medication] = relationship(back_populates="event_logs")


class ChemoSession(Base):
    __tablename__ = "chemo_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    name: Mapped[str] = mapped_column(String(180))
    protocol: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    cycle: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    adverse_effects: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VitalRecord(Base):
    __tablename__ = "vital_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    systolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    diastolic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    heart_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    oxygen_saturation: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    respiratory_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CrisisEvent(Base):
    __tablename__ = "crisis_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(140))
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    consciousness: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text)
    actions_taken: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class DailyNote(Base):
    __tablename__ = "daily_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    note_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
