from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .db import get_db
from .main import app, templates
from .models import User
from .requested_medications import sync_requested_medications_once
from .security_headers import SecurityHeadersMiddleware
from .v2_bootstrap import bootstrap_v2
from .v2_bugfixes import bugfix_api
from .v2_router import PRIVACY_VERSION, api as v2_api, public as v2_public

app.add_middleware(SecurityHeadersMiddleware)
app.include_router(v2_api)
app.include_router(v2_public)
app.include_router(bugfix_api)

DbDep = Annotated[Session, Depends(get_db)]


@app.exception_handler(RequestValidationError)
async def friendly_registration_validation(request: Request, exc: RequestValidationError):
    if request.url.path == "/api/v2/auth/register":
        labels = {
            "username": "usuario",
            "email": "correo",
            "display_name": "nombre",
            "password": "contraseña",
            "accept_privacy": "aceptación de privacidad",
            "guardian_attestation": "declaración de autorización",
        }
        messages: list[str] = []
        for error in exc.errors():
            field = str(error.get("loc", [""])[-1])
            message = str(error.get("msg", "Datos inválidos."))
            if message.startswith("Value error, "):
                message = message.removeprefix("Value error, ")
            elif message == "Field required":
                message = f"Falta completar {labels.get(field, field)}."
            elif "at least" in message.lower() and field == "password":
                message = "La contraseña debe tener al menos 12 caracteres, letras y números."
            messages.append(message)
        detail = messages[0] if messages else "Revisa los datos ingresados e inténtalo nuevamente."
        return JSONResponse(status_code=422, content={"detail": detail})

    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": exc.errors()}))


@app.middleware("http")
async def prefer_v2_home(request: Request, call_next):
    if request.url.path == "/":
        return RedirectResponse(url="/v2", status_code=307)
    return await call_next(request)


@app.get("/v2", response_class=HTMLResponse, include_in_schema=False)
def v2_home(request: Request, db: DbDep):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    user = db.get(User, user_id)
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    bootstrap_v2(db)
    sync_requested_medications_once(db, user)
    return templates.TemplateResponse(
        request=request,
        name="v2.html",
        context={
            "csrf_token": request.session.get("csrf_token", ""),
            "username": user.username,
            "privacy_version": PRIVACY_VERSION,
        },
    )
