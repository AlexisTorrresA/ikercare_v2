from __future__ import annotations

import csv
import io
import os
import zipfile
from contextlib import asynccontextmanager
from datetime import date, datetime, time
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from .auth import authenticate, get_current_user, start_session, verify_csrf
from .db import Base, apply_lightweight_migrations, engine, get_db
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
from .schemas import (
    ChemoCreate,
    ChemoStatusUpdate,
    CrisisCreate,
    DailyNoteUpdate,
    MedicationCreate,
    MedicationEventCreate,
    MedicationLogToggle,
    MedicationUpdate,
    VitalCreate,
)
from .seed import seed_database

BASE_DIR = Path(__file__).resolve().parent
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "America/Santiago"))


def now_local_naive() -> datetime:
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def day_bounds(target: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min)
    end = datetime.combine(target, time.max)
    return start, end


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    apply_lightweight_migrations()
    with Session(engine) as db:
        seed_database(db)
    yield


app = FastAPI(
    title="IkerCare",
    description="Registro familiar de medicamentos, quimioterapia, signos vitales y eventos clínicos.",
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "cambiar-secret-key-en-produccion"),
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

DbDep = Annotated[Session, Depends(get_db)]
UserDep = Annotated[User, Depends(get_current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(
        BASE_DIR / "static" / "service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})


@app.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: DbDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user = authenticate(db, username.strip(), password)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Usuario o contraseña incorrectos."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    start_session(request, user)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: DbDep, _: UserDep) -> HTMLResponse:
    profile = db.scalar(select(ChildProfile).limit(1))
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "csrf_token": request.session["csrf_token"],
            "child_name": profile.name if profile else "Paciente",
            "today": now_local_naive().date().isoformat(),
        },
    )


def serialize_medication(medication: Medication) -> dict:
    return {
        "id": medication.id,
        "name": medication.name,
        "medication_type": medication.medication_type,
        "purpose": medication.purpose,
        "dose": medication.dose,
        "route": medication.route,
        "frequency": medication.frequency,
        "instructions": medication.instructions,
        "active": medication.active,
        "times": [schedule.time_of_day.strftime("%H:%M") for schedule in sorted(medication.schedules, key=lambda s: s.time_of_day) if schedule.active],
    }


@app.get("/api/dashboard")
def dashboard(
    db: DbDep,
    _: UserDep,
    selected_date: date = Query(alias="date"),
) -> dict:
    active_schedules = db.scalars(
        select(MedicationSchedule)
        .join(Medication)
        .options(selectinload(MedicationSchedule.medication))
        .where(Medication.active.is_(True), MedicationSchedule.active.is_(True))
    ).all()

    # Los horarios actualmente activos forman la agenda. Además, recuperamos
    # cualquier horario histórico con un registro en la fecha seleccionada para
    # que editar o desactivar un medicamento nunca oculte una toma anterior.
    logs = db.scalars(
        select(MedicationLog)
        .options(selectinload(MedicationLog.schedule).selectinload(MedicationSchedule.medication))
        .where(MedicationLog.log_date == selected_date)
    ).all()
    logs_by_schedule: dict[int, MedicationLog] = {log.schedule_id: log for log in logs}
    schedules_by_id = {schedule.id: schedule for schedule in active_schedules}
    for log in logs:
        schedules_by_id.setdefault(log.schedule_id, log.schedule)
    schedules = sorted(
        schedules_by_id.values(),
        key=lambda schedule: (schedule.time_of_day, schedule.medication.name.lower()),
    )

    medication_items = []
    for schedule in schedules:
        log = logs_by_schedule.get(schedule.id)
        medication_items.append(
            {
                "schedule_id": schedule.id,
                "time": schedule.time_of_day.strftime("%H:%M"),
                "status": log.status if log else "pending",
                "actual_time": log.actual_time.isoformat(timespec="minutes") if log and log.actual_time else None,
                "log_notes": log.notes if log else None,
                "medication": serialize_medication(schedule.medication),
            }
        )

    start, end = day_bounds(selected_date)

    active_medications = db.scalars(
        select(Medication)
        .options(selectinload(Medication.schedules))
        .where(Medication.active.is_(True))
        .order_by(Medication.name)
    ).all()
    unscheduled_by_id = {
        medication.id: medication
        for medication in active_medications
        if not any(schedule.active for schedule in medication.schedules)
    }
    event_logs = db.scalars(
        select(MedicationEventLog)
        .options(selectinload(MedicationEventLog.medication).selectinload(Medication.schedules))
        .where(MedicationEventLog.occurred_at.between(start, end))
        .order_by(MedicationEventLog.occurred_at.desc())
    ).all()
    event_logs_by_medication: dict[int, list[MedicationEventLog]] = {}
    for event_log in event_logs:
        event_logs_by_medication.setdefault(event_log.medication_id, []).append(event_log)
        # Conserva visible el historial aunque después el medicamento se haya
        # desactivado o se le haya agregado un horario fijo.
        unscheduled_by_id.setdefault(event_log.medication_id, event_log.medication)
    unscheduled_medications = sorted(unscheduled_by_id.values(), key=lambda medication: medication.name.lower())

    chemo = db.scalars(
        select(ChemoSession).where(ChemoSession.scheduled_at.between(start, end)).order_by(ChemoSession.scheduled_at)
    ).all()
    vitals = db.scalars(
        select(VitalRecord).where(VitalRecord.recorded_at.between(start, end)).order_by(VitalRecord.recorded_at.desc())
    ).all()
    crises = db.scalars(
        select(CrisisEvent).where(CrisisEvent.occurred_at.between(start, end)).order_by(CrisisEvent.occurred_at.desc())
    ).all()
    note = db.scalar(select(DailyNote).where(DailyNote.note_date == selected_date))
    profile = db.scalar(select(ChildProfile).limit(1))

    taken = sum(item["status"] == "taken" for item in medication_items)
    skipped = sum(item["status"] == "skipped" for item in medication_items)
    total = len(medication_items)

    return {
        "date": selected_date.isoformat(),
        "profile": {
            "name": profile.name if profile else "Paciente",
            "hospital": profile.hospital if profile else None,
        },
        "summary": {
            "medications_total": total,
            "medications_taken": taken,
            "medications_skipped": skipped,
            "medications_pending": total - taken - skipped,
            "unscheduled_administrations": len(event_logs),
            "vital_records": len(vitals),
            "crisis_events": len(crises),
            "chemo_sessions": len(chemo),
        },
        "medications": medication_items,
        "unscheduled_medications": [
            {
                "medication": serialize_medication(medication),
                "administrations": [
                    {
                        "id": event_log.id,
                        "occurred_at": event_log.occurred_at.isoformat(timespec="minutes"),
                        "notes": event_log.notes,
                    }
                    for event_log in event_logs_by_medication.get(medication.id, [])
                ],
            }
            for medication in unscheduled_medications
        ],
        "chemo": [
            {
                "id": item.id,
                "scheduled_at": item.scheduled_at.isoformat(timespec="minutes"),
                "name": item.name,
                "protocol": item.protocol,
                "cycle": item.cycle,
                "purpose": item.purpose,
                "status": item.status,
                "notes": item.notes,
                "adverse_effects": item.adverse_effects,
            }
            for item in chemo
        ],
        "vitals": [
            {
                "id": item.id,
                "recorded_at": item.recorded_at.isoformat(timespec="minutes"),
                "temperature_c": item.temperature_c,
                "systolic": item.systolic,
                "diastolic": item.diastolic,
                "heart_rate": item.heart_rate,
                "oxygen_saturation": item.oxygen_saturation,
                "respiratory_rate": item.respiratory_rate,
                "weight_kg": item.weight_kg,
                "notes": item.notes,
            }
            for item in vitals
        ],
        "crises": [
            {
                "id": item.id,
                "occurred_at": item.occurred_at.isoformat(timespec="minutes"),
                "event_type": item.event_type,
                "duration_seconds": item.duration_seconds,
                "consciousness": item.consciousness,
                "description": item.description,
                "actions_taken": item.actions_taken,
                "team_notified": item.team_notified,
                "notes": item.notes,
            }
            for item in crises
        ],
        "daily_note": note.text if note else "",
    }


@app.post("/api/medication-logs/toggle")
def toggle_medication_log(payload: MedicationLogToggle, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    schedule = db.get(MedicationSchedule, payload.schedule_id)
    if not schedule or not schedule.active:
        raise HTTPException(status_code=404, detail="Horario no encontrado")

    log = db.scalar(
        select(MedicationLog).where(
            MedicationLog.schedule_id == payload.schedule_id,
            MedicationLog.log_date == payload.log_date,
        )
    )
    if payload.status == "pending":
        if log:
            db.delete(log)
            db.commit()
        return {"status": "pending", "actual_time": None}

    if not log:
        log = MedicationLog(schedule_id=payload.schedule_id, log_date=payload.log_date)
        db.add(log)
    log.status = payload.status
    log.notes = payload.notes
    log.actual_time = now_local_naive() if payload.status == "taken" else None
    db.commit()
    db.refresh(log)
    return {
        "status": log.status,
        "actual_time": log.actual_time.isoformat(timespec="minutes") if log.actual_time else None,
    }


@app.post("/api/medications/{medication_id}/event-logs", status_code=201)
def create_medication_event_log(
    medication_id: int,
    payload: MedicationEventCreate,
    db: DbDep,
    _: UserDep,
    __: CsrfDep,
) -> dict:
    medication = db.get(Medication, medication_id)
    if not medication or not medication.active:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado o inactivo")

    event_log = MedicationEventLog(
        medication_id=medication_id,
        occurred_at=payload.occurred_at or now_local_naive(),
        notes=payload.notes,
    )
    db.add(event_log)
    db.commit()
    db.refresh(event_log)
    return {
        "id": event_log.id,
        "occurred_at": event_log.occurred_at.isoformat(timespec="minutes"),
        "notes": event_log.notes,
    }


@app.delete("/api/medication-event-logs/{event_log_id}")
def delete_medication_event_log(event_log_id: int, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    event_log = db.get(MedicationEventLog, event_log_id)
    if not event_log:
        raise HTTPException(status_code=404, detail="Administración no encontrada")
    db.delete(event_log)
    db.commit()
    return {"ok": True}


@app.get("/api/medications")
def list_medications(db: DbDep, _: UserDep) -> list[dict]:
    medications = db.scalars(
        select(Medication).options(selectinload(Medication.schedules)).order_by(Medication.active.desc(), Medication.name)
    ).all()
    return [serialize_medication(medication) for medication in medications]


@app.post("/api/medications", status_code=201)
def create_medication(payload: MedicationCreate, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    medication = Medication(
        name=payload.name.strip(),
        medication_type=payload.medication_type.strip() or "Medicamento",
        purpose=payload.purpose,
        dose=payload.dose,
        route=payload.route,
        frequency=payload.frequency,
        instructions=payload.instructions,
    )
    for time_value in payload.times:
        medication.schedules.append(MedicationSchedule(time_of_day=datetime.strptime(time_value, "%H:%M").time()))
    db.add(medication)
    db.commit()
    db.refresh(medication)
    return serialize_medication(medication)


@app.put("/api/medications/{medication_id}")
def update_medication(
    medication_id: int,
    payload: MedicationUpdate,
    db: DbDep,
    _: UserDep,
    __: CsrfDep,
) -> dict:
    medication = db.scalar(
        select(Medication).options(selectinload(Medication.schedules)).where(Medication.id == medication_id)
    )
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado")

    medication.name = payload.name.strip()
    medication.medication_type = payload.medication_type.strip() or "Medicamento"
    medication.purpose = payload.purpose
    medication.dose = payload.dose
    medication.route = payload.route
    medication.frequency = payload.frequency
    medication.instructions = payload.instructions
    medication.active = payload.active

    requested_times = {datetime.strptime(value, "%H:%M").time() for value in payload.times}
    schedules_by_time: dict[time, list[MedicationSchedule]] = {}
    for schedule in medication.schedules:
        schedules_by_time.setdefault(schedule.time_of_day, []).append(schedule)

    # Se reutilizan horarios existentes para conservar sus registros históricos.
    # Los horarios retirados se desactivan en lugar de eliminarse.
    for scheduled_time, schedules_at_time in schedules_by_time.items():
        schedules_at_time[0].active = scheduled_time in requested_times
        for duplicate in schedules_at_time[1:]:
            duplicate.active = False

    for scheduled_time in requested_times:
        if scheduled_time not in schedules_by_time:
            medication.schedules.append(MedicationSchedule(time_of_day=scheduled_time, active=True))

    db.commit()
    db.refresh(medication)
    return serialize_medication(medication)


@app.delete("/api/medications/{medication_id}")
def deactivate_medication(medication_id: int, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    medication = db.get(Medication, medication_id)
    if not medication:
        raise HTTPException(status_code=404, detail="Medicamento no encontrado")
    medication.active = False
    db.commit()
    return {"ok": True}


@app.post("/api/chemo", status_code=201)
def create_chemo(payload: ChemoCreate, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    item = ChemoSession(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id}


@app.put("/api/chemo/{chemo_id}")
def update_chemo_status(
    chemo_id: int,
    payload: ChemoStatusUpdate,
    db: DbDep,
    _: UserDep,
    __: CsrfDep,
) -> dict:
    item = db.get(ChemoSession, chemo_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro de quimioterapia no encontrado")
    item.status = payload.status
    item.notes = payload.notes
    item.adverse_effects = payload.adverse_effects
    db.commit()
    return {"ok": True}


@app.delete("/api/chemo/{chemo_id}")
def delete_chemo(chemo_id: int, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    item = db.get(ChemoSession, chemo_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.post("/api/vitals", status_code=201)
def create_vital(payload: VitalCreate, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    item = VitalRecord(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id}


@app.delete("/api/vitals/{vital_id}")
def delete_vital(vital_id: int, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    item = db.get(VitalRecord, vital_id)
    if not item:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.post("/api/crises", status_code=201)
def create_crisis(payload: CrisisCreate, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    item = CrisisEvent(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"id": item.id}


@app.delete("/api/crises/{crisis_id}")
def delete_crisis(crisis_id: int, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    item = db.get(CrisisEvent, crisis_id)
    if not item:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.put("/api/daily-note")
def save_daily_note(payload: DailyNoteUpdate, db: DbDep, _: UserDep, __: CsrfDep) -> dict:
    note = db.scalar(select(DailyNote).where(DailyNote.note_date == payload.note_date))
    if not note:
        note = DailyNote(note_date=payload.note_date, text=payload.text)
        db.add(note)
    else:
        note.text = payload.text
    db.commit()
    return {"ok": True}


def write_csv(rows: list[dict]) -> str:
    output = io.StringIO()
    if not rows:
        output.write("sin_registros\n")
        return output.getvalue()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


@app.get("/api/export/csv")
def export_csv(
    db: DbDep,
    _: UserDep,
    start_date: date,
    end_date: date,
):
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="El rango de fechas no es válido")
    if (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="El rango máximo es de 366 días")

    start, _ = day_bounds(start_date)
    _, end = day_bounds(end_date)

    medication_logs = db.scalars(
        select(MedicationLog)
        .options(selectinload(MedicationLog.schedule).selectinload(MedicationSchedule.medication))
        .where(MedicationLog.log_date.between(start_date, end_date))
        .order_by(MedicationLog.log_date, MedicationLog.schedule_id)
    ).all()
    medication_event_logs = db.scalars(
        select(MedicationEventLog)
        .options(selectinload(MedicationEventLog.medication))
        .where(MedicationEventLog.occurred_at.between(start, end))
        .order_by(MedicationEventLog.occurred_at)
    ).all()
    vitals = db.scalars(select(VitalRecord).where(VitalRecord.recorded_at.between(start, end)).order_by(VitalRecord.recorded_at)).all()
    crises = db.scalars(select(CrisisEvent).where(CrisisEvent.occurred_at.between(start, end)).order_by(CrisisEvent.occurred_at)).all()
    chemo = db.scalars(select(ChemoSession).where(ChemoSession.scheduled_at.between(start, end)).order_by(ChemoSession.scheduled_at)).all()

    files = {
        "medicamentos.csv": write_csv(
            [
                {
                    "fecha": log.log_date.isoformat(),
                    "hora_programada": log.schedule.time_of_day.strftime("%H:%M"),
                    "medicamento": log.schedule.medication.name,
                    "dosis": log.schedule.medication.dose or "",
                    "via": log.schedule.medication.route or "",
                    "frecuencia": log.schedule.medication.frequency or "",
                    "estado": log.status,
                    "hora_real": log.actual_time.isoformat(timespec="minutes") if log.actual_time else "",
                    "comentarios": log.notes or "",
                }
                for log in medication_logs
            ]
        ),
        "medicamentos_sos_sin_horario.csv": write_csv(
            [
                {
                    "fecha_hora": log.occurred_at.isoformat(timespec="minutes"),
                    "medicamento": log.medication.name,
                    "dosis": log.medication.dose or "",
                    "via": log.medication.route or "",
                    "frecuencia": log.medication.frequency or "",
                    "comentarios": log.notes or "",
                }
                for log in medication_event_logs
            ]
        ),
        "signos_vitales.csv": write_csv(
            [
                {
                    "fecha_hora": item.recorded_at.isoformat(timespec="minutes"),
                    "temperatura_c": item.temperature_c,
                    "presion_sistolica": item.systolic,
                    "presion_diastolica": item.diastolic,
                    "frecuencia_cardiaca": item.heart_rate,
                    "saturacion_oxigeno": item.oxygen_saturation,
                    "frecuencia_respiratoria": item.respiratory_rate,
                    "peso_kg": item.weight_kg,
                    "comentarios": item.notes or "",
                }
                for item in vitals
            ]
        ),
        "crisis_eventos.csv": write_csv(
            [
                {
                    "fecha_hora": item.occurred_at.isoformat(timespec="minutes"),
                    "tipo": item.event_type,
                    "duracion_segundos": item.duration_seconds,
                    "conciencia": item.consciousness or "",
                    "descripcion": item.description,
                    "acciones": item.actions_taken or "",
                    "equipo_avisado": "sí" if item.team_notified else "no",
                    "comentarios": item.notes or "",
                }
                for item in crises
            ]
        ),
        "quimioterapia.csv": write_csv(
            [
                {
                    "fecha_hora": item.scheduled_at.isoformat(timespec="minutes"),
                    "nombre": item.name,
                    "protocolo": item.protocol or "",
                    "ciclo": item.cycle or "",
                    "objetivo": item.purpose or "",
                    "estado": item.status,
                    "notas": item.notes or "",
                    "efectos_adversos": item.adverse_effects or "",
                }
                for item in chemo
            ]
        ),
    }

    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in files.items():
            archive.writestr(filename, content.encode("utf-8-sig"))
    memory.seek(0)
    filename = f"iker-care_{start_date.isoformat()}_{end_date.isoformat()}.zip"
    return StreamingResponse(
        memory,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
