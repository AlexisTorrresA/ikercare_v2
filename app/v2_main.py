from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from .db import get_db
from .main import app, templates
from .models import User
from .requested_medications import sync_requested_medications
from .security_headers import SecurityHeadersMiddleware
from .v2_bootstrap import bootstrap_v2
from .v2_fix_router import router as v2_fix_router
from .v2_router import PRIVACY_VERSION, api as v2_api, public as v2_public

app.add_middleware(SecurityHeadersMiddleware)
app.include_router(v2_api)
app.include_router(v2_public)
app.include_router(v2_fix_router)

DbDep = Annotated[Session, Depends(get_db)]


@app.exception_handler(RequestValidationError)
async def friendly_registration_validation(request: Request, exc: RequestValidationError):
    if request.url.path != "/api/v2/auth/register":
        return await request_validation_exception_handler(request, exc)

    errors = exc.errors()
    message = "Revisa los datos ingresados."
    if errors:
        message = str(errors[0].get("msg") or message)
        if message.startswith("Value error, "):
            message = message[len("Value error, "):]
    return JSONResponse(status_code=422, content={"detail": message})


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
    sync_requested_medications(db, user)
    return templates.TemplateResponse(
        request=request,
        name="v2.html",
        context={
            "csrf_token": request.session.get("csrf_token", ""),
            "username": user.username,
            "privacy_version": PRIVACY_VERSION,
        },
    )
