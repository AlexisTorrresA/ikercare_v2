
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .db import get_db
from .main import app, templates
from .models import User
from .security_headers import SecurityHeadersMiddleware
from .v2_bootstrap import bootstrap_v2
from .v2_router import PRIVACY_VERSION, api as v2_api, public as v2_public

app.add_middleware(SecurityHeadersMiddleware)
app.include_router(v2_api)
app.include_router(v2_public)

DbDep = Annotated[Session, Depends(get_db)]


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
    return templates.TemplateResponse(
        request=request,
        name="v2.html",
        context={
            "csrf_token": request.session.get("csrf_token", ""),
            "username": user.username,
            "privacy_version": PRIVACY_VERSION,
        },
    )
