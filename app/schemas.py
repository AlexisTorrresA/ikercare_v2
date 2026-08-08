from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MedicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    medication_type: str = Field(default="Medicamento", max_length=120)
    purpose: str | None = Field(default=None, max_length=300)
    dose: str | None = Field(default=None, max_length=120)
    route: str | None = Field(default=None, max_length=80)
    frequency: str | None = Field(default=None, max_length=120)
    instructions: str | None = None
    times: list[str] = Field(default_factory=list)

    @field_validator("times")
    @classmethod
    def validate_times(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                datetime.strptime(value, "%H:%M")
            except ValueError as exc:
                raise ValueError(f"Hora inválida: {value}") from exc
        return sorted(set(values))


class MedicationUpdate(MedicationCreate):
    active: bool = True


class MedicationLogToggle(BaseModel):
    schedule_id: int
    log_date: date
    status: Literal["taken", "skipped", "pending"]
    notes: str | None = None


class MedicationEventCreate(BaseModel):
    occurred_at: datetime | None = None
    notes: str | None = None


class ChemoCreate(BaseModel):
    scheduled_at: datetime
    name: str = Field(min_length=1, max_length=180)
    protocol: str | None = Field(default=None, max_length=180)
    cycle: str | None = Field(default=None, max_length=80)
    purpose: str | None = Field(default=None, max_length=300)
    status: Literal["scheduled", "in_progress", "completed", "postponed", "cancelled"] = "scheduled"
    notes: str | None = None
    adverse_effects: str | None = None


class ChemoStatusUpdate(BaseModel):
    status: Literal["scheduled", "in_progress", "completed", "postponed", "cancelled"]
    notes: str | None = None
    adverse_effects: str | None = None


class VitalCreate(BaseModel):
    recorded_at: datetime
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    systolic: int | None = Field(default=None, ge=20, le=300)
    diastolic: int | None = Field(default=None, ge=10, le=200)
    heart_rate: int | None = Field(default=None, ge=20, le=350)
    oxygen_saturation: int | None = Field(default=None, ge=0, le=100)
    respiratory_rate: int | None = Field(default=None, ge=0, le=150)
    weight_kg: float | None = Field(default=None, ge=0.5, le=300)
    notes: str | None = None


class CrisisCreate(BaseModel):
    occurred_at: datetime
    event_type: str = Field(min_length=1, max_length=140)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    consciousness: str | None = Field(default=None, max_length=120)
    description: str = Field(min_length=1)
    actions_taken: str | None = None
    team_notified: bool = False
    notes: str | None = None


class DailyNoteUpdate(BaseModel):
    note_date: date
    text: str = ""
