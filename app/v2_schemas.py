
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,40}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NativeLoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=200)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    email: str = Field(min_length=5, max_length=254)
    display_name: str | None = Field(default=None, max_length=120)
    password: str = Field(min_length=12, max_length=200)
    accept_privacy: bool
    guardian_attestation: bool

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip()
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("Usa 3-40 caracteres: letras, números, punto, guion o guion bajo.")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("Correo inválido.")
        return value

    @model_validator(mode="after")
    def legal_acceptance(self):
        if not self.accept_privacy:
            raise ValueError("Debes aceptar la política de privacidad y términos.")
        if not self.guardian_attestation:
            raise ValueError("Debes declarar que tienes autorización para administrar los datos del paciente.")
        return self


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    birth_date: date | None = None
    sex_at_birth: str | None = Field(default=None, max_length=40)
    primary_hospital: str | None = Field(default=None, max_length=200)
    medical_record: str | None = Field(default=None, max_length=120)
    allergies: str | None = None
    diagnoses: str | None = None
    notes: str | None = None


class PatientUpdate(PatientCreate):
    pass


class MemberCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    role: Literal["owner", "editor", "viewer"] = "editor"


class CareMedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    generic_name: str | None = Field(default=None, max_length=160)
    medication_type: str = Field(default="Medicamento", max_length=120)
    purpose: str | None = Field(default=None, max_length=500)
    dose: str | None = Field(default=None, max_length=120)
    route: str | None = Field(default=None, max_length=80)
    frequency: str | None = Field(default=None, max_length=120)
    instructions: str | None = None
    times: list[str] = Field(default_factory=list)

    @field_validator("times")
    @classmethod
    def validate_times(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            datetime.strptime(value, "%H:%M")
            normalized.append(value)
        return sorted(set(normalized))


class CareMedicationUpdate(CareMedicationCreate):
    active: bool = True


class CareMedicationLogToggle(BaseModel):
    schedule_id: int
    log_date: date
    status: Literal["taken", "skipped", "pending"]
    notes: str | None = None


class CareMedicationEventCreate(BaseModel):
    medication_id: int
    occurred_at: datetime | None = None
    notes: str | None = None


class EliminationCreate(BaseModel):
    occurred_at: datetime
    diaper_status: Literal["dry", "wet", "soiled", "wet_and_soiled"]
    urine_amount: Literal["none", "small", "medium", "large"] | None = None
    urine_color: str | None = Field(default=None, max_length=60)
    stool_description: str | None = Field(default=None, max_length=200)
    notes: str | None = None


class FoodCreate(BaseModel):
    occurred_at: datetime
    meal_type: str | None = Field(default=None, max_length=60)
    item: str = Field(min_length=1, max_length=240)
    amount: float | None = Field(default=None, ge=0, le=100000)
    unit: str | None = Field(default=None, max_length=40)
    tolerated: bool | None = None
    vomiting: bool = False
    notes: str | None = None


class TeamMemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    specialty: str | None = Field(default=None, max_length=160)
    role: str | None = Field(default=None, max_length=120)
    hospital: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=254)
    notes: str | None = None
    is_primary: bool = False


class HospitalizationCreate(BaseModel):
    hospital: str = Field(min_length=1, max_length=220)
    service: str | None = Field(default=None, max_length=160)
    admission_at: datetime
    discharge_at: datetime | None = None
    reason: str | None = None
    diagnosis: str | None = None
    summary: str | None = None
    epicrisis_text: str | None = None

    @model_validator(mode="after")
    def dates_valid(self):
        if self.discharge_at and self.discharge_at < self.admission_at:
            raise ValueError("La fecha de alta no puede ser anterior al ingreso.")
        return self


class HistoryEventCreate(BaseModel):
    occurred_at: datetime
    category: Literal["hospitalization", "exam", "diagnosis", "procedure", "treatment", "consultation", "milestone", "other"]
    title: str = Field(min_length=1, max_length=220)
    description: str | None = None
    hospital: str | None = Field(default=None, max_length=220)
    clinician_name: str | None = Field(default=None, max_length=180)
    document_id: int | None = None


class ShareCreate(BaseModel):
    detail: Literal["simple", "complete"] = "simple"
    language: Literal["es", "en"] = "es"
    include_documents: bool = False
    start_date: date | None = None
    end_date: date | None = None
    hospitalization_id: int | None = None
    expires_hours: int = Field(default=24, ge=1, le=168)

    @model_validator(mode="after")
    def date_range(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("Rango de fechas inválido.")
        return self


class ConsentCreate(BaseModel):
    consent_type: Literal["privacy", "guardian", "ai_processing", "sharing"]
    granted: bool
    metadata: dict | None = None


class AccountDeleteRequest(BaseModel):
    password: str = Field(min_length=8, max_length=200)
    confirm: Literal["ELIMINAR"]


class PatientDeleteRequest(BaseModel):
    confirm_name: str
