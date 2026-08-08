
from __future__ import annotations

import base64
import io
import json
import os
import secrets
import threading
import time as time_module
from datetime import date, datetime, time, timedelta
from hashlib import sha256
from typing import Annotated

import qrcode
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .auth import authenticate, get_current_user, hash_password, start_session, verify_csrf, verify_password
from .crypto import decrypt_bytes, encrypt_bytes, sha256_hex
from .db import get_db
from .document_processing import extract_text, safe_filename, sanitize_profile_photo, validate_upload
from .medical_catalog import search_medications
from .models import User
from .v2_bootstrap import bootstrap_v2
from .v2_models import (
    AuditLog,
    CareChemoSession,
    CareCrisisEvent,
    CareDailyNote,
    CareMedication,
    CareMedicationEvent,
    CareMedicationLog,
    CareMedicationSchedule,
    CareTeamMember,
    CareVitalRecord,
    ClinicalDocument,
    ClinicalHistoryEvent,
    ConsentRecord,
    EliminationLog,
    FoodLog,
    Hospitalization,
    Patient,
    PatientMember,
    ShareLink,
    UserProfile,
)
from .v2_schemas import (
    AccountDeleteRequest,
    CareMedicationCreate,
    CareMedicationEventCreate,
    CareMedicationLogToggle,
    CareMedicationUpdate,
    ConsentCreate,
    EliminationCreate,
    FoodCreate,
    HistoryEventCreate,
    HospitalizationCreate,
    MemberCreate,
    NativeLoginRequest,
    PatientCreate,
    PatientDeleteRequest,
    PatientUpdate,
    RegisterRequest,
    ShareCreate,
    TeamMemberCreate,
)

api = APIRouter(prefix="/api/v2", tags=["IkerCare V2"])
public = APIRouter(tags=["IkerCare sharing"])

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(get_current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]

PRIVACY_VERSION = "2026-08-v2"
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 8
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCK = threading.Lock()


def now() -> datetime:
    return datetime.utcnow()


def _login_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return sha256(f"{host}:{username.lower()}".encode()).hexdigest()


def _check_login_throttle(request: Request, username: str) -> None:
    key = _login_key(request, username)
    current = time_module.time()
    with _LOGIN_LOCK:
        attempts = [value for value in _LOGIN_ATTEMPTS.get(key, []) if current - value < LOGIN_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[key] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos antes de reintentar.")


def _record_failed_login(request: Request, username: str) -> None:
    key = _login_key(request, username)
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.setdefault(key, []).append(time_module.time())


def _clear_login_attempts(request: Request, username: str) -> None:
    key = _login_key(request, username)
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(key, None)


def _password_is_reasonable(password: str) -> bool:
    return (
        len(password) >= 12
        and any(ch.isalpha() for ch in password)
        and any(ch.isdigit() for ch in password)
    )


def _membership(db: Session, user_id: int, patient_id: int) -> PatientMember:
    member = db.scalar(
        select(PatientMember).where(
            PatientMember.user_id == user_id,
            PatientMember.patient_id == patient_id,
        )
    )
    if not member:
        raise HTTPException(status_code=404, detail="Paciente no encontrado.")
    return member


def _require_role(db: Session, user_id: int, patient_id: int, allowed: set[str]) -> PatientMember:
    member = _membership(db, user_id, patient_id)
    if member.role not in allowed:
        raise HTTPException(status_code=403, detail="No tienes permisos para realizar esta acción.")
    return member


def _audit(
    db: Session,
    user_id: int | None,
    patient_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=user_id,
            patient_id=patient_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            metadata_json=metadata,
        )
    )


def _serialize_patient(patient: Patient, role: str | None = None) -> dict:
    return {
        "id": patient.id,
        "name": patient.name,
        "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
        "sex_at_birth": patient.sex_at_birth,
        "primary_hospital": patient.primary_hospital,
        "medical_record": patient.medical_record,
        "allergies": patient.allergies,
        "diagnoses": patient.diagnoses,
        "notes": patient.notes,
        "has_photo": bool(patient.photo_ciphertext),
        "role": role,
        "updated_at": patient.updated_at.isoformat(timespec="seconds"),
    }


def _serialize_medication(med: CareMedication, times: list[str] | None = None) -> dict:
    return {
        "id": med.id,
        "patient_id": med.patient_id,
        "name": med.name,
        "generic_name": med.generic_name,
        "medication_type": med.medication_type,
        "purpose": med.purpose,
        "dose": med.dose,
        "route": med.route,
        "frequency": med.frequency,
        "instructions": med.instructions,
        "active": med.active,
        "source": med.source,
        "times": times or [],
    }


@api.post("/auth/native-login")
def native_login(payload: NativeLoginRequest, request: Request, db: DbDep) -> dict:
    _check_login_throttle(request, payload.username)
    user = authenticate(db, payload.username.strip(), payload.password)
    if not user:
        _record_failed_login(request, payload.username)
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    _clear_login_attempts(request, payload.username)
    bootstrap_v2(db)
    start_session(request, user)
    profile = db.get(UserProfile, user.id)
    return {
        "ok": True,
        "username": user.username,
        "display_name": profile.display_name if profile else user.username,
        "privacy_accepted": bool(profile and profile.accepted_privacy_version == PRIVACY_VERSION),
    }


@api.post("/auth/register", status_code=201)
def register(payload: RegisterRequest, request: Request, db: DbDep) -> dict:
    if not _password_is_reasonable(payload.password):
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 12 caracteres, letras y números.")
    existing = db.scalar(
        select(User).where(func.lower(User.username) == payload.username.lower())
    )
    if existing:
        raise HTTPException(status_code=409, detail="Ese nombre de usuario ya existe.")
    email_exists = db.scalar(
        select(UserProfile).where(func.lower(UserProfile.email) == payload.email.lower())
    )
    if email_exists:
        raise HTTPException(status_code=409, detail="Ese correo ya está registrado.")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    profile = UserProfile(
        user_id=user.id,
        email=payload.email,
        display_name=payload.display_name or payload.username,
        accepted_privacy_version=PRIVACY_VERSION,
        accepted_terms_at=now(),
        guardian_attested_at=now(),
    )
    db.add(profile)
    db.add(
        ConsentRecord(
            user_id=user.id,
            consent_type="privacy",
            policy_version=PRIVACY_VERSION,
            granted=True,
            metadata_json={"guardian_attestation": True},
        )
    )
    _audit(db, user.id, None, "account.created", "user", user.id)
    db.commit()
    start_session(request, user)
    return {"ok": True, "user_id": user.id, "username": user.username}


@api.get("/auth/me")
def auth_me(db: DbDep, user: UserDep) -> dict:
    profile = db.get(UserProfile, user.id)
    memberships = db.scalars(
        select(PatientMember).where(PatientMember.user_id == user.id)
    ).all()
    return {
        "id": user.id,
        "username": user.username,
        "email": profile.email if profile else None,
        "display_name": profile.display_name if profile else user.username,
        "privacy_version": profile.accepted_privacy_version if profile else None,
        "privacy_current": bool(profile and profile.accepted_privacy_version == PRIVACY_VERSION),
        "patients": len(memberships),
    }


@api.post("/legal/accept")
def accept_legal(payload: ConsentCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    profile = db.get(UserProfile, user.id)
    if not profile:
        profile = UserProfile(user_id=user.id, display_name=user.username)
        db.add(profile)
    if payload.consent_type == "privacy" and payload.granted:
        profile.accepted_privacy_version = PRIVACY_VERSION
        profile.accepted_terms_at = now()
    if payload.consent_type == "guardian" and payload.granted:
        profile.guardian_attested_at = now()
    if payload.consent_type == "ai_processing":
        profile.ai_processing_opt_in = payload.granted

    db.add(
        ConsentRecord(
            user_id=user.id,
            patient_id=None,
            consent_type=payload.consent_type,
            policy_version=PRIVACY_VERSION,
            granted=payload.granted,
            metadata_json=payload.metadata,
        )
    )
    _audit(db, user.id, None, "consent.updated", "consent", payload.consent_type, {"granted": payload.granted})
    db.commit()
    return {"ok": True, "privacy_version": PRIVACY_VERSION}


@api.get("/patients")
def list_patients(db: DbDep, user: UserDep) -> list[dict]:
    bootstrap_v2(db)
    rows = db.execute(
        select(Patient, PatientMember.role)
        .join(PatientMember, PatientMember.patient_id == Patient.id)
        .where(PatientMember.user_id == user.id)
        .order_by(Patient.name)
    ).all()
    return [_serialize_patient(patient, role) for patient, role in rows]


@api.post("/patients", status_code=201)
def create_patient(payload: PatientCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    profile = db.get(UserProfile, user.id)
    if not profile or profile.accepted_privacy_version != PRIVACY_VERSION or not profile.guardian_attested_at:
        raise HTTPException(status_code=428, detail="Debes aceptar la política vigente y declarar autorización para administrar los datos.")
    patient = Patient(**payload.model_dump(), created_by_user_id=user.id)
    db.add(patient)
    db.flush()
    db.add(PatientMember(patient_id=patient.id, user_id=user.id, role="owner"))
    _audit(db, user.id, patient.id, "patient.created", "patient", patient.id)
    db.commit()
    db.refresh(patient)
    return _serialize_patient(patient, "owner")


@api.get("/patients/{patient_id}")
def get_patient(patient_id: int, db: DbDep, user: UserDep) -> dict:
    member = _membership(db, user.id, patient_id)
    patient = db.get(Patient, patient_id)
    return _serialize_patient(patient, member.role)


@api.put("/patients/{patient_id}")
def update_patient(patient_id: int, payload: PatientUpdate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    member = _require_role(db, user.id, patient_id, {"owner", "editor"})
    patient = db.get(Patient, patient_id)
    for field, value in payload.model_dump().items():
        setattr(patient, field, value)
    patient.updated_at = now()
    _audit(db, user.id, patient.id, "patient.updated", "patient", patient.id)
    db.commit()
    return _serialize_patient(patient, member.role)


@api.post("/patients/{patient_id}/photo")
async def upload_patient_photo(
    patient_id: int,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
    file: UploadFile = File(...),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    data = await file.read()
    if len(data) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="La foto supera 3 MB.")
    try:
        clean, mime = sanitize_profile_photo(data, file.content_type or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    patient = db.get(Patient, patient_id)
    patient.photo_ciphertext = encrypt_bytes(clean, f"patient-photo:{patient_id}".encode())
    patient.photo_mime = mime
    patient.photo_sha256 = sha256_hex(clean)
    patient.updated_at = now()
    _audit(db, user.id, patient_id, "patient.photo_updated", "patient", patient_id)
    db.commit()
    return {"ok": True, "sha256": patient.photo_sha256}


@api.get("/patients/{patient_id}/photo")
def get_patient_photo(patient_id: int, db: DbDep, user: UserDep) -> Response:
    _membership(db, user.id, patient_id)
    patient = db.get(Patient, patient_id)
    if not patient or not patient.photo_ciphertext:
        raise HTTPException(status_code=404, detail="Foto no disponible.")
    data = decrypt_bytes(patient.photo_ciphertext, f"patient-photo:{patient_id}".encode())
    return Response(data, media_type=patient.photo_mime or "image/jpeg", headers={"Cache-Control": "private, max-age=300"})


@api.get("/patients/{patient_id}/members")
def list_members(patient_id: int, db: DbDep, user: UserDep) -> list[dict]:
    _membership(db, user.id, patient_id)
    rows = db.execute(
        select(PatientMember, User, UserProfile)
        .join(User, User.id == PatientMember.user_id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .where(PatientMember.patient_id == patient_id)
        .order_by(PatientMember.role, User.username)
    ).all()
    return [
        {
            "id": member.id,
            "user_id": target.id,
            "username": target.username,
            "display_name": profile.display_name if profile else target.username,
            "role": member.role,
        }
        for member, target, profile in rows
    ]


@api.post("/patients/{patient_id}/members", status_code=201)
def add_member(patient_id: int, payload: MemberCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner"})
    target = db.scalar(select(User).where(func.lower(User.username) == payload.username.lower()))
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")
    existing = db.scalar(
        select(PatientMember).where(
            PatientMember.patient_id == patient_id,
            PatientMember.user_id == target.id,
        )
    )
    if existing:
        existing.role = payload.role
        member = existing
    else:
        member = PatientMember(patient_id=patient_id, user_id=target.id, role=payload.role)
        db.add(member)
    _audit(db, user.id, patient_id, "member.upserted", "user", target.id, {"role": payload.role})
    db.commit()
    return {"ok": True, "user_id": target.id, "role": payload.role}


@api.delete("/patients/{patient_id}/members/{member_user_id}")
def remove_member(patient_id: int, member_user_id: int, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner"})
    if member_user_id == user.id:
        raise HTTPException(status_code=400, detail="No puedes quitarte a ti mismo desde esta opción.")
    member = db.scalar(
        select(PatientMember).where(
            PatientMember.patient_id == patient_id,
            PatientMember.user_id == member_user_id,
        )
    )
    if not member:
        raise HTTPException(status_code=404, detail="Miembro no encontrado.")
    db.delete(member)
    _audit(db, user.id, patient_id, "member.removed", "user", member_user_id)
    db.commit()
    return {"ok": True}


@api.get("/medications/search")
def medication_search(_: UserDep, q: str = Query(min_length=2, max_length=80)) -> list[dict]:
    return search_medications(q)


def _med_times(db: Session, medication_id: int) -> list[str]:
    rows = db.scalars(
        select(CareMedicationSchedule)
        .where(
            CareMedicationSchedule.medication_id == medication_id,
            CareMedicationSchedule.active.is_(True),
        )
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    return [row.time_of_day.strftime("%H:%M") for row in rows]


@api.get("/patients/{patient_id}/medications")
def list_care_medications(patient_id: int, db: DbDep, user: UserDep) -> list[dict]:
    _membership(db, user.id, patient_id)
    meds = db.scalars(
        select(CareMedication)
        .where(CareMedication.patient_id == patient_id)
        .order_by(CareMedication.active.desc(), CareMedication.name)
    ).all()
    return [_serialize_medication(med, _med_times(db, med.id)) for med in meds]


@api.post("/patients/{patient_id}/medications", status_code=201)
def create_care_medication(patient_id: int, payload: CareMedicationCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = CareMedication(
        patient_id=patient_id,
        name=payload.name.strip(),
        generic_name=payload.generic_name,
        medication_type=payload.medication_type,
        purpose=payload.purpose,
        dose=payload.dose,
        route=payload.route,
        frequency=payload.frequency,
        instructions=payload.instructions,
        source="manual",
        created_by_user_id=user.id,
    )
    db.add(med)
    db.flush()
    for value in payload.times:
        db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=datetime.strptime(value, "%H:%M").time()))
    _audit(db, user.id, patient_id, "medication.created", "medication", med.id, {"name": med.name})
    db.commit()
    return _serialize_medication(med, payload.times)


@api.put("/patients/{patient_id}/medications/{medication_id}")
def update_care_medication(
    patient_id: int,
    medication_id: int,
    payload: CareMedicationUpdate,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(
        select(CareMedication).where(
            CareMedication.id == medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    for field in ("name", "generic_name", "medication_type", "purpose", "dose", "route", "frequency", "instructions", "active"):
        setattr(med, field, getattr(payload, field))
    existing = db.scalars(select(CareMedicationSchedule).where(CareMedicationSchedule.medication_id == med.id)).all()
    wanted = {datetime.strptime(value, "%H:%M").time() for value in payload.times}
    by_time = {row.time_of_day: row for row in existing}
    for row in existing:
        row.active = row.time_of_day in wanted
    for value in wanted:
        if value not in by_time:
            db.add(CareMedicationSchedule(medication_id=med.id, time_of_day=value, active=True))
    med.updated_at = now()
    _audit(db, user.id, patient_id, "medication.updated", "medication", med.id)
    db.commit()
    return _serialize_medication(med, payload.times)


@api.post("/patients/{patient_id}/medication-logs/toggle")
def toggle_care_medication(
    patient_id: int,
    payload: CareMedicationLogToggle,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    row = db.execute(
        select(CareMedicationSchedule, CareMedication)
        .join(CareMedication, CareMedication.id == CareMedicationSchedule.medication_id)
        .where(
            CareMedicationSchedule.id == payload.schedule_id,
            CareMedication.patient_id == patient_id,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Horario no encontrado.")
    schedule, med = row
    log = db.scalar(
        select(CareMedicationLog).where(
            CareMedicationLog.schedule_id == schedule.id,
            CareMedicationLog.log_date == payload.log_date,
        )
    )
    if payload.status == "pending":
        if log:
            db.delete(log)
        _audit(db, user.id, patient_id, "medication_log.pending", "medication", med.id)
        db.commit()
        return {"status": "pending", "actual_time": None}

    if not log:
        log = CareMedicationLog(schedule_id=schedule.id, log_date=payload.log_date)
        db.add(log)
    log.status = payload.status
    log.notes = payload.notes
    log.actual_time = now() if payload.status == "taken" else None
    log.updated_by_user_id = user.id
    _audit(db, user.id, patient_id, f"medication_log.{payload.status}", "medication", med.id)
    db.commit()
    return {
        "status": log.status,
        "actual_time": log.actual_time.isoformat(timespec="minutes") if log.actual_time else None,
    }


@api.post("/patients/{patient_id}/medication-events", status_code=201)
def create_care_medication_event(
    patient_id: int,
    payload: CareMedicationEventCreate,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    med = db.scalar(
        select(CareMedication).where(
            CareMedication.id == payload.medication_id,
            CareMedication.patient_id == patient_id,
        )
    )
    if not med:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado.")
    item = CareMedicationEvent(
        medication_id=med.id,
        occurred_at=payload.occurred_at or now(),
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "medication_event.created", "medication_event", item.id, {"medication": med.name})
    db.commit()
    return {"id": item.id}


@api.post("/patients/{patient_id}/elimination", status_code=201)
def create_elimination(patient_id: int, payload: EliminationCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = EliminationLog(patient_id=patient_id, created_by_user_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "elimination.created", "elimination", item.id)
    db.commit()
    return {"id": item.id}


@api.delete("/patients/{patient_id}/elimination/{item_id}")
def delete_elimination(patient_id: int, item_id: int, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = db.scalar(select(EliminationLog).where(EliminationLog.id == item_id, EliminationLog.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    db.delete(item)
    _audit(db, user.id, patient_id, "elimination.deleted", "elimination", item_id)
    db.commit()
    return {"ok": True}


@api.post("/patients/{patient_id}/food", status_code=201)
def create_food(patient_id: int, payload: FoodCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = FoodLog(patient_id=patient_id, created_by_user_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "food.created", "food", item.id)
    db.commit()
    return {"id": item.id}


@api.delete("/patients/{patient_id}/food/{item_id}")
def delete_food(patient_id: int, item_id: int, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = db.scalar(select(FoodLog).where(FoodLog.id == item_id, FoodLog.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado.")
    db.delete(item)
    _audit(db, user.id, patient_id, "food.deleted", "food", item_id)
    db.commit()
    return {"ok": True}


@api.get("/patients/{patient_id}/team")
def list_team(patient_id: int, db: DbDep, user: UserDep) -> list[dict]:
    _membership(db, user.id, patient_id)
    rows = db.scalars(
        select(CareTeamMember).where(CareTeamMember.patient_id == patient_id).order_by(CareTeamMember.is_primary.desc(), CareTeamMember.name)
    ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "specialty": row.specialty,
            "role": row.role,
            "hospital": row.hospital,
            "phone": row.phone,
            "email": row.email,
            "notes": row.notes,
            "is_primary": row.is_primary,
        }
        for row in rows
    ]


@api.post("/patients/{patient_id}/team", status_code=201)
def create_team_member(patient_id: int, payload: TeamMemberCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    if payload.is_primary:
        for item in db.scalars(select(CareTeamMember).where(CareTeamMember.patient_id == patient_id)).all():
            item.is_primary = False
    item = CareTeamMember(patient_id=patient_id, created_by_user_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "care_team.created", "care_team", item.id)
    db.commit()
    return {"id": item.id}


@api.delete("/patients/{patient_id}/team/{item_id}")
def delete_team_member(patient_id: int, item_id: int, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = db.scalar(select(CareTeamMember).where(CareTeamMember.id == item_id, CareTeamMember.patient_id == patient_id))
    if not item:
        raise HTTPException(status_code=404, detail="Profesional no encontrado.")
    db.delete(item)
    _audit(db, user.id, patient_id, "care_team.deleted", "care_team", item_id)
    db.commit()
    return {"ok": True}


@api.get("/patients/{patient_id}/hospitalizations")
def list_hospitalizations(patient_id: int, db: DbDep, user: UserDep) -> list[dict]:
    _membership(db, user.id, patient_id)
    rows = db.scalars(
        select(Hospitalization).where(Hospitalization.patient_id == patient_id).order_by(Hospitalization.admission_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "hospital": row.hospital,
            "service": row.service,
            "admission_at": row.admission_at.isoformat(timespec="minutes"),
            "discharge_at": row.discharge_at.isoformat(timespec="minutes") if row.discharge_at else None,
            "reason": row.reason,
            "diagnosis": row.diagnosis,
            "summary": row.summary,
            "epicrisis_text": row.epicrisis_text,
        }
        for row in rows
    ]


@api.post("/patients/{patient_id}/hospitalizations", status_code=201)
def create_hospitalization(patient_id: int, payload: HospitalizationCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = Hospitalization(patient_id=patient_id, created_by_user_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    db.add(
        ClinicalHistoryEvent(
            patient_id=patient_id,
            occurred_at=item.admission_at,
            category="hospitalization",
            title=f"Hospitalización · {item.hospital}",
            description=item.reason or item.diagnosis,
            hospital=item.hospital,
            created_by_user_id=user.id,
        )
    )
    _audit(db, user.id, patient_id, "hospitalization.created", "hospitalization", item.id)
    db.commit()
    return {"id": item.id}


@api.post("/patients/{patient_id}/history", status_code=201)
def create_history_event(patient_id: int, payload: HistoryEventCreate, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    if payload.document_id:
        document = db.scalar(
            select(ClinicalDocument).where(
                ClinicalDocument.id == payload.document_id,
                ClinicalDocument.patient_id == patient_id,
            )
        )
        if not document:
            raise HTTPException(status_code=400, detail="Documento asociado inválido.")
    item = ClinicalHistoryEvent(patient_id=patient_id, created_by_user_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "history.created", "history", item.id)
    db.commit()
    return {"id": item.id}


@api.get("/patients/{patient_id}/timeline")
def timeline(
    patient_id: int,
    db: DbDep,
    user: UserDep,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict]:
    _membership(db, user.id, patient_id)
    clauses = [ClinicalHistoryEvent.patient_id == patient_id]
    if start_date:
        clauses.append(ClinicalHistoryEvent.occurred_at >= datetime.combine(start_date, time.min))
    if end_date:
        clauses.append(ClinicalHistoryEvent.occurred_at <= datetime.combine(end_date, time.max))
    events = db.scalars(
        select(ClinicalHistoryEvent).where(*clauses).order_by(ClinicalHistoryEvent.occurred_at.desc()).limit(limit)
    ).all()

    hospitalizations = db.scalars(
        select(Hospitalization).where(Hospitalization.patient_id == patient_id).order_by(Hospitalization.admission_at.desc()).limit(limit)
    ).all()
    documents = db.scalars(
        select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id).order_by(ClinicalDocument.event_date.desc().nullslast(), ClinicalDocument.created_at.desc()).limit(limit)
    ).all()

    output = [
        {
            "id": f"history-{row.id}",
            "occurred_at": row.occurred_at.isoformat(timespec="minutes"),
            "category": row.category,
            "title": row.title,
            "description": row.description,
            "hospital": row.hospital,
            "document_id": row.document_id,
        }
        for row in events
    ]
    for row in hospitalizations:
        output.append(
            {
                "id": f"hospitalization-{row.id}",
                "occurred_at": row.admission_at.isoformat(timespec="minutes"),
                "category": "hospitalization",
                "title": f"Hospitalización · {row.hospital}",
                "description": row.summary or row.reason or row.diagnosis,
                "hospital": row.hospital,
                "hospitalization_id": row.id,
            }
        )
    for row in documents:
        event_dt = datetime.combine(row.event_date, time.min) if row.event_date else row.created_at
        output.append(
            {
                "id": f"document-{row.id}",
                "occurred_at": event_dt.isoformat(timespec="minutes"),
                "category": "exam",
                "title": row.exam_name or row.filename,
                "description": row.extracted_text[:400] if row.extracted_text else None,
                "hospital": row.hospital,
                "document_id": row.id,
            }
        )
    output.sort(key=lambda item: item["occurred_at"], reverse=True)
    return output[:limit]


@api.post("/patients/{patient_id}/documents", status_code=201)
async def upload_document(
    patient_id: int,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
    file: UploadFile = File(...),
    document_type: str = Form("exam"),
    exam_name: str | None = Form(None),
    hospital: str | None = Form(None),
    event_date: date | None = Form(None),
    hospitalization_id: int | None = Form(None),
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    data = await file.read()
    mime = file.content_type or "application/octet-stream"
    filename = safe_filename(file.filename or "documento")
    try:
        validate_upload(filename, mime, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if hospitalization_id:
        hospitalization = db.scalar(
            select(Hospitalization).where(
                Hospitalization.id == hospitalization_id,
                Hospitalization.patient_id == patient_id,
            )
        )
        if not hospitalization:
            raise HTTPException(status_code=400, detail="Hospitalización inválida.")

    extracted, extraction_status, extraction_error = extract_text(data, mime)
    document = ClinicalDocument(
        patient_id=patient_id,
        hospitalization_id=hospitalization_id,
        event_date=event_date,
        document_type=document_type[:80],
        exam_name=(exam_name or "")[:220] or None,
        hospital=(hospital or "")[:220] or None,
        filename=filename,
        mime_type=mime,
        size_bytes=len(data),
        sha256=sha256_hex(data),
        encrypted_data=encrypt_bytes(data, f"clinical-document:{patient_id}".encode()),
        extracted_text=extracted or None,
        extraction_status=extraction_status,
        extraction_error=extraction_error,
        uploaded_by_user_id=user.id,
    )
    db.add(document)
    db.flush()
    db.add(
        ClinicalHistoryEvent(
            patient_id=patient_id,
            occurred_at=datetime.combine(event_date, time.min) if event_date else now(),
            category="exam",
            title=exam_name or filename,
            description=(extracted[:800] if extracted else None),
            hospital=hospital,
            document_id=document.id,
            created_by_user_id=user.id,
        )
    )
    _audit(
        db,
        user.id,
        patient_id,
        "document.uploaded",
        "document",
        document.id,
        {"mime": mime, "size": len(data), "sha256": document.sha256, "extraction_status": extraction_status},
    )
    db.commit()
    return {
        "id": document.id,
        "filename": document.filename,
        "extraction_status": document.extraction_status,
        "extracted_text": document.extracted_text,
    }


@api.get("/patients/{patient_id}/documents")
def list_documents(patient_id: int, db: DbDep, user: UserDep) -> list[dict]:
    _membership(db, user.id, patient_id)
    rows = db.scalars(
        select(ClinicalDocument).where(ClinicalDocument.patient_id == patient_id).order_by(ClinicalDocument.created_at.desc())
    ).all()
    return [
        {
            "id": row.id,
            "event_date": row.event_date.isoformat() if row.event_date else None,
            "document_type": row.document_type,
            "exam_name": row.exam_name,
            "hospital": row.hospital,
            "filename": row.filename,
            "mime_type": row.mime_type,
            "size_bytes": row.size_bytes,
            "sha256": row.sha256,
            "extraction_status": row.extraction_status,
            "extracted_text": row.extracted_text,
            "hospitalization_id": row.hospitalization_id,
            "created_at": row.created_at.isoformat(timespec="minutes"),
        }
        for row in rows
    ]


@api.get("/patients/{patient_id}/documents/{document_id}/download")
def download_document(patient_id: int, document_id: int, db: DbDep, user: UserDep) -> Response:
    _membership(db, user.id, patient_id)
    row = db.scalar(
        select(ClinicalDocument).where(
            ClinicalDocument.id == document_id,
            ClinicalDocument.patient_id == patient_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    data = decrypt_bytes(row.encrypted_data, f"clinical-document:{patient_id}".encode())
    _audit(db, user.id, patient_id, "document.downloaded", "document", row.id)
    db.commit()
    return Response(
        data,
        media_type=row.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename(row.filename)}"',
            "Cache-Control": "private, no-store",
        },
    )


@api.delete("/patients/{patient_id}/documents/{document_id}")
def delete_document(patient_id: int, document_id: int, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    row = db.scalar(
        select(ClinicalDocument).where(
            ClinicalDocument.id == document_id,
            ClinicalDocument.patient_id == patient_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    history = db.scalars(select(ClinicalHistoryEvent).where(ClinicalHistoryEvent.document_id == row.id)).all()
    for item in history:
        item.document_id = None
    db.delete(row)
    _audit(db, user.id, patient_id, "document.deleted", "document", document_id)
    db.commit()
    return {"ok": True}


def _range_from_params(
    db: Session,
    patient_id: int,
    start_date: date | None,
    end_date: date | None,
    hospitalization_id: int | None,
) -> tuple[date | None, date | None]:
    if hospitalization_id:
        hospitalization = db.scalar(
            select(Hospitalization).where(
                Hospitalization.id == hospitalization_id,
                Hospitalization.patient_id == patient_id,
            )
        )
        if not hospitalization:
            raise HTTPException(status_code=404, detail="Hospitalización no encontrada.")
        start_date = hospitalization.admission_at.date()
        end_date = hospitalization.discharge_at.date() if hospitalization.discharge_at else date.today()
    return start_date, end_date


def _date_filter(column, start_date: date | None, end_date: date | None):
    clauses = []
    if start_date:
        clauses.append(column >= datetime.combine(start_date, time.min))
    if end_date:
        clauses.append(column <= datetime.combine(end_date, time.max))
    return clauses


def _build_summary(
    db: Session,
    patient_id: int,
    start_date: date | None,
    end_date: date | None,
    hospitalization_id: int | None,
    language: str,
    detail: str,
) -> dict:
    start_date, end_date = _range_from_params(db, patient_id, start_date, end_date, hospitalization_id)
    patient = db.get(Patient, patient_id)

    meds = db.scalars(
        select(CareMedication).where(CareMedication.patient_id == patient_id, CareMedication.active.is_(True)).order_by(CareMedication.name)
    ).all()
    team = db.scalars(
        select(CareTeamMember).where(CareTeamMember.patient_id == patient_id).order_by(CareTeamMember.is_primary.desc(), CareTeamMember.name)
    ).all()

    h_clauses = [Hospitalization.patient_id == patient_id]
    if start_date:
        h_clauses.append(Hospitalization.admission_at >= datetime.combine(start_date, time.min))
    if end_date:
        h_clauses.append(Hospitalization.admission_at <= datetime.combine(end_date, time.max))
    hospitalizations = db.scalars(select(Hospitalization).where(*h_clauses).order_by(Hospitalization.admission_at.desc())).all()

    d_clauses = [ClinicalDocument.patient_id == patient_id]
    if start_date:
        d_clauses.append(or_(ClinicalDocument.event_date.is_(None), ClinicalDocument.event_date >= start_date))
    if end_date:
        d_clauses.append(or_(ClinicalDocument.event_date.is_(None), ClinicalDocument.event_date <= end_date))
    documents = db.scalars(select(ClinicalDocument).where(*d_clauses).order_by(ClinicalDocument.created_at.desc())).all()

    c_clauses = [CareCrisisEvent.patient_id == patient_id, *_date_filter(CareCrisisEvent.occurred_at, start_date, end_date)]
    crises = db.scalars(select(CareCrisisEvent).where(*c_clauses).order_by(CareCrisisEvent.occurred_at.desc())).all()

    chemo_clauses = [CareChemoSession.patient_id == patient_id, *_date_filter(CareChemoSession.scheduled_at, start_date, end_date)]
    chemo = db.scalars(select(CareChemoSession).where(*chemo_clauses).order_by(CareChemoSession.scheduled_at.desc())).all()

    v_clauses = [CareVitalRecord.patient_id == patient_id, *_date_filter(CareVitalRecord.recorded_at, start_date, end_date)]
    vitals = db.scalars(select(CareVitalRecord).where(*v_clauses).order_by(CareVitalRecord.recorded_at.desc()).limit(30)).all()

    food_clauses = [FoodLog.patient_id == patient_id, *_date_filter(FoodLog.occurred_at, start_date, end_date)]
    elimination_clauses = [EliminationLog.patient_id == patient_id, *_date_filter(EliminationLog.occurred_at, start_date, end_date)]
    food_count = db.scalar(select(func.count(FoodLog.id)).where(*food_clauses)) or 0
    elimination_count = db.scalar(select(func.count(EliminationLog.id)).where(*elimination_clauses)) or 0

    labels = {
        "es": {
            "title": "Resumen personal de salud",
            "meds": "Medicamentos activos",
            "team": "Equipo tratante registrado",
            "hospitalizations": "Hospitalizaciones",
            "documents": "Exámenes e informes",
            "crises": "Eventos o crisis",
            "chemo": "Quimioterapia",
            "vitals": "Últimos signos vitales",
            "period": "Periodo",
            "warning": "Este resumen es un registro familiar y no reemplaza la ficha clínica oficial ni la evaluación médica.",
        },
        "en": {
            "title": "Personal health summary",
            "meds": "Active medications",
            "team": "Recorded care team",
            "hospitalizations": "Hospitalizations",
            "documents": "Tests and clinical reports",
            "crises": "Events or crises",
            "chemo": "Chemotherapy",
            "vitals": "Latest vital signs",
            "period": "Period",
            "warning": "This summary is a family-maintained health record and does not replace the official medical record or professional medical assessment.",
        },
    }[language]

    result = {
        "title": labels["title"],
        "warning": labels["warning"],
        "language": language,
        "detail": detail,
        "period": {"start": start_date.isoformat() if start_date else None, "end": end_date.isoformat() if end_date else None},
        "patient": {
            "name": patient.name,
            "birth_date": patient.birth_date.isoformat() if patient.birth_date else None,
            "primary_hospital": patient.primary_hospital,
            "medical_record": patient.medical_record,
            "allergies": patient.allergies,
            "diagnoses": patient.diagnoses,
        },
        "medications": [
            {
                "name": med.name,
                "dose": med.dose,
                "route": med.route,
                "frequency": med.frequency,
                "purpose": med.purpose,
            }
            for med in meds
        ],
        "care_team": [
            {"name": item.name, "specialty": item.specialty, "hospital": item.hospital, "is_primary": item.is_primary}
            for item in team
        ],
        "hospitalizations": [
            {
                "hospital": item.hospital,
                "service": item.service,
                "admission_at": item.admission_at.isoformat(timespec="minutes"),
                "discharge_at": item.discharge_at.isoformat(timespec="minutes") if item.discharge_at else None,
                "reason": item.reason,
                "diagnosis": item.diagnosis,
                "summary": item.summary if detail == "complete" else None,
            }
            for item in hospitalizations
        ],
        "documents": [
            {
                "id": item.id,
                "event_date": item.event_date.isoformat() if item.event_date else None,
                "exam_name": item.exam_name or item.filename,
                "hospital": item.hospital,
                "mime_type": item.mime_type,
                "extracted_text": (item.extracted_text[:4000] if detail == "complete" and item.extracted_text else None),
            }
            for item in documents
        ],
        "crises": [
            {
                "occurred_at": item.occurred_at.isoformat(timespec="minutes"),
                "type": item.event_type,
                "duration_seconds": item.duration_seconds,
                "description": item.description if detail == "complete" else None,
            }
            for item in crises
        ],
        "chemotherapy": [
            {
                "scheduled_at": item.scheduled_at.isoformat(timespec="minutes"),
                "name": item.name,
                "protocol": item.protocol,
                "cycle": item.cycle,
                "status": item.status,
                "notes": item.notes if detail == "complete" else None,
            }
            for item in chemo
        ],
        "vitals": [
            {
                "recorded_at": item.recorded_at.isoformat(timespec="minutes"),
                "temperature_c": item.temperature_c,
                "blood_pressure": f"{item.systolic}/{item.diastolic}" if item.systolic and item.diastolic else None,
                "heart_rate": item.heart_rate,
                "oxygen_saturation": item.oxygen_saturation,
                "respiratory_rate": item.respiratory_rate,
                "weight_kg": item.weight_kg,
            }
            for item in vitals[:10 if detail == "simple" else 30]
        ],
        "care_counts": {"food_records": food_count, "elimination_records": elimination_count},
    }

    lines = [labels["title"], labels["warning"], ""]
    lines.append(f"{patient.name}")
    if patient.birth_date:
        lines.append(("Fecha de nacimiento: " if language == "es" else "Date of birth: ") + patient.birth_date.isoformat())
    if patient.diagnoses:
        lines.append(("Diagnósticos registrados: " if language == "es" else "Recorded diagnoses: ") + patient.diagnoses)
    if patient.allergies:
        lines.append(("Alergias: " if language == "es" else "Allergies: ") + patient.allergies)
    if start_date or end_date:
        lines.append(f"{labels['period']}: {start_date or '…'} — {end_date or '…'}")
    lines.append("")
    lines.append(labels["meds"] + ":")
    for med in meds:
        parts = [med.name, med.dose, med.route, med.frequency]
        lines.append("- " + " · ".join(part for part in parts if part))
    lines.append("")
    lines.append(labels["hospitalizations"] + ":")
    for item in hospitalizations:
        lines.append(f"- {item.hospital}: {item.admission_at.date()} — {(item.discharge_at.date() if item.discharge_at else 'actual')}")
        if item.diagnosis:
            lines.append(f"  {item.diagnosis}")
    lines.append("")
    lines.append(labels["documents"] + f": {len(documents)}")
    lines.append(labels["crises"] + f": {len(crises)}")
    lines.append(labels["chemo"] + f": {len(chemo)}")
    result["plain_text"] = "\n".join(lines)
    return result


@api.get("/patients/{patient_id}/summary")
def patient_summary(
    patient_id: int,
    db: DbDep,
    user: UserDep,
    language: str = Query(default="es", pattern="^(es|en)$"),
    detail: str = Query(default="simple", pattern="^(simple|complete)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    hospitalization_id: int | None = None,
) -> dict:
    _membership(db, user.id, patient_id)
    return _build_summary(db, patient_id, start_date, end_date, hospitalization_id, language, detail)


@api.post("/patients/{patient_id}/shares", status_code=201)
def create_share(patient_id: int, payload: ShareCreate, request: Request, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    token = secrets.token_urlsafe(32)
    token_hash = sha256(token.encode()).hexdigest()
    expires_at = now() + timedelta(hours=payload.expires_hours)
    row = ShareLink(
        patient_id=patient_id,
        token_hash=token_hash,
        created_by_user_id=user.id,
        detail=payload.detail,
        language=payload.language,
        include_documents=payload.include_documents,
        start_date=payload.start_date,
        end_date=payload.end_date,
        hospitalization_id=payload.hospitalization_id,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    _audit(db, user.id, patient_id, "share.created", "share", row.id, {"expires_at": expires_at.isoformat(), "detail": row.detail})
    db.commit()

    base_url = os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/")).rstrip("/")
    share_url = f"{base_url}/share/{row.id}#{token}"
    qr_image = qrcode.make(share_url)
    qr_buffer = io.BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_data_uri = "data:image/png;base64," + base64.b64encode(qr_buffer.getvalue()).decode("ascii")
    return {
        "id": row.id,
        "url": share_url,
        "qr_data_uri": qr_data_uri,
        "expires_at": expires_at.isoformat(timespec="minutes"),
        "detail": row.detail,
        "language": row.language,
        "include_documents": row.include_documents,
    }


@api.get("/patients/{patient_id}/shares")
def list_shares(patient_id: int, db: DbDep, user: UserDep) -> list[dict]:
    _membership(db, user.id, patient_id)
    rows = db.scalars(
        select(ShareLink).where(ShareLink.patient_id == patient_id).order_by(ShareLink.created_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": row.id,
            "detail": row.detail,
            "language": row.language,
            "include_documents": row.include_documents,
            "expires_at": row.expires_at.isoformat(timespec="minutes"),
            "revoked": bool(row.revoked_at),
            "access_count": row.access_count,
            "last_access_at": row.last_access_at.isoformat(timespec="minutes") if row.last_access_at else None,
        }
        for row in rows
    ]


@api.delete("/patients/{patient_id}/shares/{share_id}")
def revoke_share(patient_id: int, share_id: int, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    row = db.scalar(select(ShareLink).where(ShareLink.id == share_id, ShareLink.patient_id == patient_id))
    if not row:
        raise HTTPException(status_code=404, detail="Enlace no encontrado.")
    row.revoked_at = now()
    _audit(db, user.id, patient_id, "share.revoked", "share", row.id)
    db.commit()
    return {"ok": True}


@api.get("/shares/{share_id}/qr")
def share_qr(share_id: int, db: DbDep, user: UserDep, request: Request) -> Response:
    row = db.get(ShareLink, share_id)
    if not row:
        raise HTTPException(status_code=404, detail="Enlace no encontrado.")
    _membership(db, user.id, row.patient_id)
    raise HTTPException(
        status_code=410,
        detail="Por seguridad, el QR se genera solo en el momento de crear el enlace porque el servidor no almacena el token en texto plano.",
    )


def _share_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(os.getenv("SECRET_KEY", "change-me"), salt="ikercare-share-session-v2")


def _resolve_share_token(db: Session, share_id: int, token: str) -> ShareLink:
    token_hash = sha256(token.encode()).hexdigest()
    row = db.scalar(select(ShareLink).where(ShareLink.id == share_id, ShareLink.token_hash == token_hash))
    if not row or row.revoked_at or row.expires_at <= now():
        raise HTTPException(status_code=404, detail="Enlace inválido, vencido o revocado.")
    return row


def _share_from_cookie(request: Request, db: Session, share_id: int) -> ShareLink:
    signed = request.cookies.get("ikercare_share")
    if not signed:
        raise HTTPException(status_code=401, detail="Debes abrir nuevamente el QR/enlace compartido.")
    try:
        payload = _share_serializer().loads(signed, max_age=7 * 24 * 3600)
    except (BadSignature, SignatureExpired) as exc:
        raise HTTPException(status_code=401, detail="La autorización temporal venció.") from exc
    if int(payload.get("share_id", -1)) != share_id:
        raise HTTPException(status_code=403, detail="Autorización de compartición inválida.")
    row = db.get(ShareLink, share_id)
    if not row or row.revoked_at or row.expires_at <= now() or payload.get("token_hash") != row.token_hash:
        raise HTTPException(status_code=404, detail="Enlace inválido, vencido o revocado.")
    return row


@public.get("/share/{share_id}", response_class=HTMLResponse)
def public_share_page(share_id: int) -> HTMLResponse:
    # El secreto viaja en el fragmento # del URL. Los fragmentos no se envían
    # en la petición HTTP, por lo que el token no termina en access logs del proxy.
    body = f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer"><title>Resumen compartido IkerCare</title>
<style>body{{font-family:system-ui,sans-serif;max-width:880px;margin:auto;padding:24px;line-height:1.5;color:#162033}}.card{{border:1px solid #dce3ef;border-radius:16px;padding:18px;margin:14px 0}}.warning{{background:#fff7e6;border-left:4px solid #e6a400;padding:12px}}pre{{white-space:pre-wrap;font:inherit}}.hidden{{display:none}}</style></head><body>
<h1 id="title">Resumen compartido de salud</h1><div id="status" class="warning">Verificando enlace temporal…</div><div id="content" class="card hidden"><pre id="summary"></pre><div id="documents"></div></div>
<script>
(async()=>{{
  const token=location.hash.slice(1); const status=document.getElementById('status');
  if(!token){{status.textContent='Falta la clave temporal del enlace. Solicita un nuevo QR al cuidador.';return;}}
  try{{
    const r=await fetch('/share/{share_id}/open',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{token}}),credentials:'same-origin'}});
    const d=await r.json(); if(!r.ok) throw new Error(d.detail||'No se pudo abrir el enlace');
    history.replaceState(null,'',location.pathname);
    document.documentElement.lang=d.language; document.getElementById('title').textContent=d.language==='en'?'Shared health summary':'Resumen compartido de salud';
    status.textContent=d.warning; document.getElementById('summary').textContent=d.plain_text;
    const box=document.getElementById('documents'); if(d.documents&&d.documents.length){{const h=document.createElement('h2');h.textContent=d.language==='en'?'Documents':'Documentos';box.appendChild(h);const ul=document.createElement('ul');d.documents.forEach(x=>{{const li=document.createElement('li');const a=document.createElement('a');a.href=x.url;a.textContent=x.exam_name;a.rel='noreferrer';li.appendChild(a);ul.appendChild(li);}});box.appendChild(ul);}}
    document.getElementById('content').classList.remove('hidden');
  }}catch(e){{status.textContent=e.message||'Enlace inválido o vencido.';}}
}})();
</script><p><small>Enlace temporal de solo lectura. IkerCare no reemplaza la ficha clínica oficial.</small></p></body></html>'''
    return HTMLResponse(body, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer"})


@public.post("/share/{share_id}/open")
def public_share_open(
    share_id: int,
    request: Request,
    db: DbDep,
    token: Annotated[str, Body(embed=True, min_length=20, max_length=200)],
) -> JSONResponse:
    row = _resolve_share_token(db, share_id, token)
    row.access_count += 1
    row.last_access_at = now()
    db.commit()
    summary = _build_summary(db, row.patient_id, row.start_date, row.end_date, row.hospitalization_id, row.language, row.detail)
    docs = []
    if row.include_documents:
        docs = [{"id": doc["id"], "exam_name": doc["exam_name"], "url": f"/share/{share_id}/documents/{doc['id']}"} for doc in summary["documents"]]
    response = JSONResponse({
        "language": row.language,
        "warning": summary["warning"],
        "plain_text": summary["plain_text"],
        "documents": docs,
        "expires_at": row.expires_at.isoformat(timespec="minutes"),
    })
    signed = _share_serializer().dumps({"share_id": row.id, "token_hash": row.token_hash})
    max_age = max(1, int((row.expires_at - now()).total_seconds()))
    response.set_cookie(
        "ikercare_share", signed, max_age=max_age, httponly=True,
        secure=(request.url.scheme == "https" or os.getenv("COOKIE_SECURE", "false").lower() == "true"),
        samesite="lax", path=f"/share/{share_id}",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@public.get("/share/{share_id}/documents/{document_id}")
def public_shared_document(share_id: int, document_id: int, request: Request, db: DbDep) -> Response:
    row = _share_from_cookie(request, db, share_id)
    if not row.include_documents:
        raise HTTPException(status_code=403, detail="Este enlace no incluye documentos.")
    document = db.scalar(select(ClinicalDocument).where(ClinicalDocument.id == document_id, ClinicalDocument.patient_id == row.patient_id))
    if not document:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    data = decrypt_bytes(document.encrypted_data, f"clinical-document:{row.patient_id}".encode())
    return Response(data, media_type=document.mime_type, headers={"Content-Disposition": f'inline; filename="{safe_filename(document.filename)}"', "Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive", "Referrer-Policy": "no-referrer"})


def _html_escape(value: str | None) -> str:
    import html
    return html.escape(value or "")


@api.get("/patients/{patient_id}/changes")
def changes(
    patient_id: int,
    db: DbDep,
    user: UserDep,
    since: datetime | None = None,
) -> dict:
    _membership(db, user.id, patient_id)
    query = select(AuditLog).where(AuditLog.patient_id == patient_id)
    if since:
        query = query.where(AuditLog.created_at > since)
    rows = db.scalars(query.order_by(AuditLog.created_at.desc()).limit(100)).all()
    return {
        "server_time": now().isoformat(timespec="seconds"),
        "changed": bool(rows),
        "changes": [
            {
                "id": row.id,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "created_at": row.created_at.isoformat(timespec="seconds"),
            }
            for row in rows
        ],
    }


@api.get("/patients/{patient_id}/notification-schedule")
def notification_schedule(patient_id: int, db: DbDep, user: UserDep) -> dict:
    _membership(db, user.id, patient_id)
    rows = db.execute(
        select(CareMedication, CareMedicationSchedule)
        .join(CareMedicationSchedule, CareMedicationSchedule.medication_id == CareMedication.id)
        .where(
            CareMedication.patient_id == patient_id,
            CareMedication.active.is_(True),
            CareMedicationSchedule.active.is_(True),
        )
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    patient = db.get(Patient, patient_id)
    return {
        "patient_id": patient_id,
        "patient_name": patient.name,
        "timezone": os.getenv("APP_TIMEZONE", "America/Santiago"),
        "items": [
            {
                "schedule_id": schedule.id,
                "medication_id": med.id,
                "name": med.name,
                "dose": med.dose,
                "route": med.route,
                "time": schedule.time_of_day.strftime("%H:%M"),
            }
            for med, schedule in rows
        ],
    }


@api.get("/patients/{patient_id}/day")
def day_dashboard(patient_id: int, db: DbDep, user: UserDep, selected_date: date = Query(alias="date")) -> dict:
    _membership(db, user.id, patient_id)
    start = datetime.combine(selected_date, time.min)
    end = datetime.combine(selected_date, time.max)

    schedules = db.execute(
        select(CareMedication, CareMedicationSchedule)
        .join(CareMedicationSchedule, CareMedicationSchedule.medication_id == CareMedication.id)
        .where(
            CareMedication.patient_id == patient_id,
            CareMedication.active.is_(True),
            CareMedicationSchedule.active.is_(True),
        )
        .order_by(CareMedicationSchedule.time_of_day)
    ).all()
    schedule_ids = [schedule.id for _, schedule in schedules]
    logs = db.scalars(
        select(CareMedicationLog).where(
            CareMedicationLog.schedule_id.in_(schedule_ids) if schedule_ids else False,
            CareMedicationLog.log_date == selected_date,
        )
    ).all()
    logs_by_schedule = {row.schedule_id: row for row in logs}

    elimination = db.scalars(
        select(EliminationLog).where(EliminationLog.patient_id == patient_id, EliminationLog.occurred_at.between(start, end)).order_by(EliminationLog.occurred_at.desc())
    ).all()
    food = db.scalars(
        select(FoodLog).where(FoodLog.patient_id == patient_id, FoodLog.occurred_at.between(start, end)).order_by(FoodLog.occurred_at.desc())
    ).all()
    vitals = db.scalars(
        select(CareVitalRecord).where(CareVitalRecord.patient_id == patient_id, CareVitalRecord.recorded_at.between(start, end)).order_by(CareVitalRecord.recorded_at.desc())
    ).all()
    crises = db.scalars(
        select(CareCrisisEvent).where(CareCrisisEvent.patient_id == patient_id, CareCrisisEvent.occurred_at.between(start, end)).order_by(CareCrisisEvent.occurred_at.desc())
    ).all()
    chemo = db.scalars(
        select(CareChemoSession).where(CareChemoSession.patient_id == patient_id, CareChemoSession.scheduled_at.between(start, end)).order_by(CareChemoSession.scheduled_at)
    ).all()
    note = db.scalar(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date == selected_date))

    return {
        "date": selected_date.isoformat(),
        "medications": [
            {
                "schedule_id": schedule.id,
                "time": schedule.time_of_day.strftime("%H:%M"),
                "medication": _serialize_medication(med, [schedule.time_of_day.strftime("%H:%M")]),
                "status": logs_by_schedule[schedule.id].status if schedule.id in logs_by_schedule else "pending",
                "actual_time": logs_by_schedule[schedule.id].actual_time.isoformat(timespec="minutes") if schedule.id in logs_by_schedule and logs_by_schedule[schedule.id].actual_time else None,
                "notes": logs_by_schedule[schedule.id].notes if schedule.id in logs_by_schedule else None,
            }
            for med, schedule in schedules
        ],
        "elimination": [
            {
                "id": row.id,
                "occurred_at": row.occurred_at.isoformat(timespec="minutes"),
                "diaper_status": row.diaper_status,
                "urine_amount": row.urine_amount,
                "urine_color": row.urine_color,
                "stool_description": row.stool_description,
                "notes": row.notes,
            }
            for row in elimination
        ],
        "food": [
            {
                "id": row.id,
                "occurred_at": row.occurred_at.isoformat(timespec="minutes"),
                "meal_type": row.meal_type,
                "item": row.item,
                "amount": row.amount,
                "unit": row.unit,
                "tolerated": row.tolerated,
                "vomiting": row.vomiting,
                "notes": row.notes,
            }
            for row in food
        ],
        "vitals": [
            {
                "id": row.id,
                "recorded_at": row.recorded_at.isoformat(timespec="minutes"),
                "temperature_c": row.temperature_c,
                "systolic": row.systolic,
                "diastolic": row.diastolic,
                "heart_rate": row.heart_rate,
                "oxygen_saturation": row.oxygen_saturation,
                "respiratory_rate": row.respiratory_rate,
                "weight_kg": row.weight_kg,
                "notes": row.notes,
            }
            for row in vitals
        ],
        "crises": [
            {
                "id": row.id,
                "occurred_at": row.occurred_at.isoformat(timespec="minutes"),
                "event_type": row.event_type,
                "duration_seconds": row.duration_seconds,
                "description": row.description,
                "actions_taken": row.actions_taken,
                "team_notified": row.team_notified,
                "notes": row.notes,
            }
            for row in crises
        ],
        "chemo": [
            {
                "id": row.id,
                "scheduled_at": row.scheduled_at.isoformat(timespec="minutes"),
                "name": row.name,
                "protocol": row.protocol,
                "cycle": row.cycle,
                "status": row.status,
                "notes": row.notes,
            }
            for row in chemo
        ],
        "daily_note": note.text if note else "",
    }


@api.post("/patients/{patient_id}/vitals", status_code=201)
def create_v2_vital(
    patient_id: int,
    recorded_at: datetime,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
    temperature_c: float | None = None,
    systolic: int | None = None,
    diastolic: int | None = None,
    heart_rate: int | None = None,
    oxygen_saturation: int | None = None,
    respiratory_rate: int | None = None,
    weight_kg: float | None = None,
    notes: str | None = None,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = CareVitalRecord(
        patient_id=patient_id,
        recorded_at=recorded_at,
        temperature_c=temperature_c,
        systolic=systolic,
        diastolic=diastolic,
        heart_rate=heart_rate,
        oxygen_saturation=oxygen_saturation,
        respiratory_rate=respiratory_rate,
        weight_kg=weight_kg,
        notes=notes,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "vital.created", "vital", item.id)
    db.commit()
    return {"id": item.id}


@api.post("/patients/{patient_id}/crises", status_code=201)
def create_v2_crisis(
    patient_id: int,
    occurred_at: datetime,
    event_type: str,
    description: str,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
    duration_seconds: int | None = None,
    consciousness: str | None = None,
    actions_taken: str | None = None,
    team_notified: bool = False,
    notes: str | None = None,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = CareCrisisEvent(
        patient_id=patient_id,
        occurred_at=occurred_at,
        event_type=event_type[:140],
        duration_seconds=duration_seconds,
        consciousness=consciousness,
        description=description,
        actions_taken=actions_taken,
        team_notified=team_notified,
        notes=notes,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "crisis.created", "crisis", item.id)
    db.commit()
    return {"id": item.id}


@api.post("/patients/{patient_id}/chemo", status_code=201)
def create_v2_chemo(
    patient_id: int,
    scheduled_at: datetime,
    name: str,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
    protocol: str | None = None,
    cycle: str | None = None,
    purpose: str | None = None,
    status_value: str = "scheduled",
    notes: str | None = None,
    adverse_effects: str | None = None,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    item = CareChemoSession(
        patient_id=patient_id,
        scheduled_at=scheduled_at,
        name=name[:180],
        protocol=protocol,
        cycle=cycle,
        purpose=purpose,
        status=status_value[:30],
        notes=notes,
        adverse_effects=adverse_effects,
        created_by_user_id=user.id,
    )
    db.add(item)
    db.flush()
    _audit(db, user.id, patient_id, "chemo.created", "chemo", item.id)
    db.commit()
    return {"id": item.id}


@api.put("/patients/{patient_id}/daily-note")
def save_v2_note(
    patient_id: int,
    note_date: date,
    text: str,
    db: DbDep,
    user: UserDep,
    _: CsrfDep,
) -> dict:
    _require_role(db, user.id, patient_id, {"owner", "editor"})
    note = db.scalar(select(CareDailyNote).where(CareDailyNote.patient_id == patient_id, CareDailyNote.note_date == note_date))
    if not note:
        note = CareDailyNote(patient_id=patient_id, note_date=note_date, text=text, updated_by_user_id=user.id)
        db.add(note)
    else:
        note.text = text
        note.updated_by_user_id = user.id
        note.updated_at = now()
    _audit(db, user.id, patient_id, "daily_note.updated", "daily_note", note_date.isoformat())
    db.commit()
    return {"ok": True}


@api.delete("/patients/{patient_id}")
def delete_patient(patient_id: int, payload: PatientDeleteRequest, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    _require_role(db, user.id, patient_id, {"owner"})
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente no encontrado.")
    if payload.confirm_name.strip().lower() != patient.name.strip().lower():
        raise HTTPException(status_code=400, detail="El nombre de confirmación no coincide.")
    db.delete(patient)
    db.commit()
    return {"ok": True}


def _delete_user_account(db: Session, user: User) -> None:
    """Elimina la cuenta y los pacientes de los que es el único propietario.

    Si un paciente conserva otro propietario autorizado, se elimina solamente la
    membresía/datos de cuenta de este usuario para no borrar información de terceros.
    """
    owned = db.scalars(
        select(PatientMember).where(PatientMember.user_id == user.id, PatientMember.role == "owner")
    ).all()
    for membership in owned:
        other_owners = db.scalar(
            select(func.count(PatientMember.id)).where(
                PatientMember.patient_id == membership.patient_id,
                PatientMember.role == "owner",
                PatientMember.user_id != user.id,
            )
        ) or 0
        if other_owners == 0:
            patient = db.get(Patient, membership.patient_id)
            if patient:
                db.delete(patient)
    _audit(db, user.id, None, "account.deletion_requested", "user", user.id)
    db.flush()
    db.delete(user)
    db.commit()


@api.post("/account/delete")
def delete_account(payload: AccountDeleteRequest, request: Request, db: DbDep, user: UserDep, _: CsrfDep) -> dict:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Contraseña incorrecta.")

    _delete_user_account(db, user)
    request.session.clear()
    return {"ok": True}


@public.get("/privacy", response_class=HTMLResponse)
def privacy_page() -> HTMLResponse:
    entity = _html_escape(os.getenv("LEGAL_ENTITY_NAME", "Responsable por configurar antes del lanzamiento público"))
    contact = _html_escape(os.getenv("PRIVACY_CONTACT_EMAIL", "Contacto de privacidad por configurar"))
    return HTMLResponse(
        f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="index,follow"><title>Privacidad IkerCare</title>
<style>body{{font-family:system-ui;max-width:900px;margin:auto;padding:24px;line-height:1.58;color:#172033}}h2{{margin-top:28px}}.warn{{background:#fff6df;border-left:4px solid #d79000;padding:12px}}</style></head>
<body><h1>Política de privacidad de IkerCare — borrador V2</h1>
<div class="warn"><strong>Estado:</strong> texto técnico en revisión jurídica. No distribuir públicamente en Google Play hasta completar la identidad/contacto del responsable y revisar esta política con el comportamiento final de la aplicación.</div>
<p><strong>Responsable:</strong> {entity}<br><strong>Contacto de privacidad:</strong> {contact}<br><strong>Versión:</strong> {PRIVACY_VERSION}</p>
<h2>Finalidad y alcance</h2><p>IkerCare es un organizador personal y familiar de información de salud. Permite registrar cuidados, medicamentos, signos, alimentación, eliminación, eventos, equipo tratante, hospitalizaciones y documentos, y compartir resúmenes cuando un usuario autorizado lo solicita. No reemplaza la ficha clínica oficial, la atención profesional, una indicación médica, una alarma clínica ni un dispositivo médico.</p>
<h2>Datos tratados</h2><p>Según las funciones utilizadas, pueden tratarse datos de cuenta/contacto, datos identificatorios del paciente, fotografía, antecedentes y documentos de salud, medicamentos, signos, crisis, alimentación/eliminación, profesionales tratantes, hospitalizaciones, relaciones de cuidadores autorizados, auditoría y datos técnicos estrictamente necesarios para seguridad y operación.</p>
<h2>Niños, niñas y adolescentes</h2><p>Quien incorpore o administre información de un menor debe declarar que cuenta con autorización, representación o calidad suficiente. La app aplica controles de acceso por paciente y busca usar lenguaje comprensible. Los mecanismos definitivos de acreditación/consentimiento serán revisados jurídicamente antes del lanzamiento público.</p>
<h2>Archivos y OCR</h2><p>Los documentos e imágenes cargados se cifran antes de persistirse. La extracción de texto/OCR de V2 se realiza en el servidor de IkerCare y no se envía automáticamente a un proveedor externo de IA. El catálogo de medicamentos es local y no autocompleta dosis.</p>
<h2>Compartición</h2><p>Los enlaces/QR se generan solo por una acción de un usuario autorizado, son de solo lectura, temporales y revocables. El QR contiene un enlace con token aleatorio, no la historia clínica directamente. Compartir un enlace no sustituye los mecanismos formales de interoperabilidad o autorización de un prestador de salud.</p>
<h2>Seguridad</h2><p>Se aplican HTTPS, control de acceso por paciente, sesiones seguras, CSRF, auditoría, cifrado de archivos y enlaces temporales. Ningún sistema puede garantizar riesgo cero; mantenemos un programa de mejora y respuesta a vulnerabilidades.</p>
<h2>Conservación, derechos y eliminación</h2><p>Los plazos concretos de conservación y backups deben completarse antes de producción pública. Los usuarios disponen de eliminación dentro de la app y de un recurso web para solicitarla. El tratamiento de solicitudes puede requerir verificación de identidad y respetar obligaciones legales de conservación aplicables.</p>
<h2>Proveedores y transferencias</h2><p>Antes del lanzamiento se publicará la lista/categorías reales de encargados y subencargados (hosting, base de datos, almacenamiento, correo, analítica o IA si se habilita), sus finalidades y las condiciones aplicables a transferencias internacionales.</p>
<p><a href="/account/delete">Solicitar eliminación de cuenta</a></p></body></html>""",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@public.get("/account/delete", response_class=HTMLResponse)
def delete_account_page() -> HTMLResponse:
    return HTMLResponse(
        """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Eliminar cuenta IkerCare</title>
<style>body{font-family:system-ui;max-width:620px;margin:auto;padding:24px;line-height:1.55;color:#172033}input{display:block;width:100%;padding:12px;margin:7px 0 14px;box-sizing:border-box}button{padding:12px 16px;background:#9d2230;color:white;border:0;border-radius:10px}.warn{background:#fff1f2;padding:12px;border-radius:10px}</style></head>
<body><h1>Eliminar cuenta IkerCare</h1><p>Este recurso permite solicitar y ejecutar la eliminación fuera de la APK. Para impedir borrados no autorizados debes autenticarte.</p>
<div class="warn">Si eres el único propietario de un paciente, sus datos asociados se eliminarán junto con tu cuenta. Si existe otro propietario autorizado, el paciente se conserva y se elimina tu acceso. La retención que sea legalmente obligatoria debe indicarse en la política definitiva.</div>
<form method="post" action="/account/delete" autocomplete="off"><label>Usuario<input name="username" required autocomplete="username"></label><label>Contraseña<input type="password" name="password" required autocomplete="current-password"></label><label>Escribe <strong>ELIMINAR</strong><input name="confirmation" required></label><button type="submit">Eliminar definitivamente</button></form>
<p><a href="/privacy">Política de privacidad</a></p></body></html>""",
        headers={"Cache-Control": "no-store"},
    )


@public.post("/account/delete", response_class=HTMLResponse)
def delete_account_public(
    request: Request,
    db: DbDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    confirmation: Annotated[str, Form()],
) -> HTMLResponse:
    _check_login_throttle(request, username)
    if confirmation.strip().upper() != "ELIMINAR":
        raise HTTPException(status_code=400, detail="Confirmación inválida.")
    user = authenticate(db, username.strip(), password)
    if not user:
        _record_failed_login(request, username)
        raise HTTPException(status_code=401, detail="No se pudo verificar la cuenta.")
    _clear_login_attempts(request, username)
    _delete_user_account(db, user)
    request.session.clear()
    return HTMLResponse(
        """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cuenta eliminada</title></head><body style="font-family:system-ui;max-width:620px;margin:auto;padding:24px"><h1>Solicitud completada</h1><p>La cuenta fue eliminada de IkerCare. Consulta la política de privacidad para conocer eventuales retenciones legalmente obligatorias o temporales de backups, una vez definidas para producción.</p></body></html>""",
        headers={"Cache-Control": "no-store"},
    )


@public.get("/.well-known/security.txt")
def security_txt() -> Response:
    contact = os.getenv("SECURITY_CONTACT_EMAIL", "").strip()
    lines = []
    if contact:
        lines.append(f"Contact: mailto:{contact}")
    else:
        lines.append("Contact: configure SECURITY_CONTACT_EMAIL before public launch")
    lines.extend(["Preferred-Languages: es, en", "Policy: /privacy"])
    return Response("\n".join(lines) + "\n", media_type="text/plain", headers={"Cache-Control": "max-age=3600"})
