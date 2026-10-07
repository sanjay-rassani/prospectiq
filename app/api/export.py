"""Export and login routes (Phase 10)."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import requires_auth
from app.config import get_settings
from app.db.session import get_session
from app.services.export import (
    export_companies_json,
    export_interactions_csv,
    export_opportunities_csv,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/export/companies.json")
def export_companies(session: SessionDep) -> Response:
    body = export_companies_json(session)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=companies.json"},
    )


@router.get("/export/opportunities.csv")
def export_opportunities(session: SessionDep) -> Response:
    body = export_opportunities_csv(session)
    return PlainTextResponse(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=opportunities.csv"},
    )


@router.get("/export/interactions.csv")
def export_interactions(session: SessionDep) -> Response:
    body = export_interactions_csv(session)
    return PlainTextResponse(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=interactions.csv"},
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    templates = get_templates(request)
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "title": "Login",
            "auth_required": requires_auth(settings),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    token: Annotated[str, Form()],
) -> Response:
    settings = get_settings()
    expected = getattr(request.app.state, "auth_secret", "") or settings.auth_token
    if not expected or not hmac.compare_digest(token.strip(), expected):
        return RedirectResponse(url="/login?error=Invalid token", status_code=303)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        "prospectiq_auth",
        expected,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


@router.get("/logout")
def logout() -> Response:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("prospectiq_auth")
    return response
