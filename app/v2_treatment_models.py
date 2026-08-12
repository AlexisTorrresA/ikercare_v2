from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class CareMedicationRevision(Base):
    __tablename__ = "care_medication_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int | None] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="SET NULL"), nullable=True, index=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(40), default="changed")
    status: Mapped[str] = mapped_column(String(30), default="active")
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    medication_type: Mapped[str] = mapped_column(String(120), default="Medicamento")
    purpose: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dose: Mapped[str | None] = mapped_column(String(120), nullable=True)
    route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(120), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    times_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    changed_fields_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareMedicationExtra(Base):
    __tablename__ = "care_medication_extras"

    medication_id: Mapped[int] = mapped_column(ForeignKey("care_medications.id", ondelete="CASCADE"), primary_key=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareFoodDetail(Base):
    __tablename__ = "care_food_details"

    food_log_id: Mapped[int] = mapped_column(ForeignKey("care_food_logs.id", ondelete="CASCADE"), primary_key=True)
    intake_level: Mapped[str | None] = mapped_column(String(40), nullable=True)


class CareChemoFollowupEvent(Base):
    __tablename__ = "care_chemo_followup_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    chemo_session_id: Mapped[int] = mapped_column(ForeignKey("care_chemo_sessions.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int | None] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="SET NULL"), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClinicalDocumentAsset(Base):
    __tablename__ = "care_clinical_document_assets"
    __table_args__ = (UniqueConstraint("document_id", "position", name="uq_document_asset_position"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("care_clinical_documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_status: Mapped[str] = mapped_column(String(40), default="pending")
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CareHospitalizationLink(Base):
    __tablename__ = "care_hospitalization_links"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", name="uq_hospitalization_entity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("care_patients.id", ondelete="CASCADE"), index=True)
    hospitalization_id: Mapped[int] = mapped_column(ForeignKey("care_hospitalizations.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class MedicationCatalogCache(Base):
    __tablename__ = "care_medication_catalog_cache"

    normalized_name: Mapped[str] = mapped_column(String(180), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(180))
    medication_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(500), nullable=True)
    route: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="ai")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
