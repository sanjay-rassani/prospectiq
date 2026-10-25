"""Settings, feeds, adapters, and feedback routes (Phase 9)."""

from __future__ import annotations

from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_session
from app.models import (
    AdapterKind,
    Company,
    DomainFetchPolicy,
    OperatorFeedback,
    SourceFeed,
)
from app.services.discovery.feedback import record_feedback
from app.services.discovery.playwright_fallback import set_domain_policy
from app.services.discovery.registry import list_adapters
from app.services.discovery.rss import add_feed, poll_feed
from app.services.leads.adapters import list_capabilities
from app.services.leads.filters import INDUSTRIES, SERVICES
from app.services.leads.locations import LOCATION_COUNTRIES, LOCATION_REGIONS, LOCATIONS
from app.services.scoring.profile import (
    DEFAULT_PROFILE_PATH,
    get_operator_profile,
    reload_operator_profile,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in value.replace("\n", ",").split(",") if p.strip()]


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        key = raw.strip()
        if not key:
            continue
        folded = key.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        out.append(key)
    return out


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, session: SessionDep) -> HTMLResponse:
    templates = get_templates(request)
    profile = get_operator_profile()
    settings = get_settings()
    feeds = session.scalars(select(SourceFeed).order_by(SourceFeed.name)).all()
    policies = session.scalars(select(DomainFetchPolicy).order_by(DomainFetchPolicy.domain)).all()
    feedback = session.scalars(
        select(OperatorFeedback).order_by(OperatorFeedback.created_at.desc()).limit(20)
    ).all()

    industry_keys = {k.casefold() for k, _ in INDUSTRIES}
    service_keys = {k.casefold() for k, _ in SERVICES}
    location_keys = {k.casefold() for k, _ in LOCATIONS}

    selected_industries = {i.casefold() for i in profile.target_industries}
    selected_excluded = {i.casefold() for i in profile.excluded_industries}
    selected_services = {s.casefold() for s in profile.preferred_solution_families}
    selected_regions = {r.casefold() for r in profile.target_regions}

    custom_industries_value = ", ".join(
        i for i in profile.target_industries if i.casefold() not in industry_keys
    )
    custom_excluded_industries_value = ", ".join(
        i for i in profile.excluded_industries if i.casefold() not in industry_keys
    )
    custom_services_value = ", ".join(
        s for s in profile.preferred_solution_families if s.casefold() not in service_keys
    )
    custom_regions_value = ", ".join(
        r for r in profile.target_regions if r.casefold() not in location_keys
    )

    return templates.TemplateResponse(
        request=request,
        name="settings/index.html",
        context={
            "title": "Settings",
            "profile": profile,
            "settings": settings,
            "adapters": list_adapters(),
            "source_capabilities": list_capabilities(settings),
            "feeds": feeds,
            "policies": policies,
            "feedback": feedback,
            "adapter_kinds": [k.value for k in AdapterKind],
            "industries": INDUSTRIES,
            "services": SERVICES,
            "location_regions": LOCATION_REGIONS,
            "location_countries": LOCATION_COUNTRIES,
            "selected_industries": selected_industries,
            "selected_excluded_industries": selected_excluded,
            "selected_services": selected_services,
            "selected_regions": selected_regions,
            "custom_industries_value": custom_industries_value,
            "custom_excluded_industries_value": custom_excluded_industries_value,
            "custom_services_value": custom_services_value,
            "custom_regions_value": custom_regions_value,
            "flash": request.query_params.get("flash"),
            "profile_path": str(DEFAULT_PROFILE_PATH),
        },
    )


@router.post("/settings/profile")
async def settings_save_profile(
    request: Request,
    positioning: Annotated[str, Form()] = "",
    band_high: Annotated[float, Form()] = 75,
    band_medium: Annotated[float, Form()] = 55,
    band_watch: Annotated[float, Form()] = 35,
    outreach_ready_min: Annotated[float, Form()] = 65,
    extraction_model: Annotated[str, Form()] = "",
    generation_model: Annotated[str, Form()] = "",
    refresh_high: Annotated[int, Form()] = 2,
    refresh_medium: Annotated[int, Form()] = 7,
    refresh_watch: Annotated[int, Form()] = 14,
    refresh_nurture: Annotated[int, Form()] = 30,
) -> RedirectResponse:
    """Persist operator profile YAML. Model names are documented; runtime uses .env."""
    form = await request.form()
    data: dict[str, Any] = {}
    if DEFAULT_PROFILE_PATH.exists():
        data = yaml.safe_load(DEFAULT_PROFILE_PATH.read_text()) or {}
    data["positioning"] = positioning.strip() or data.get("positioning", "")
    data["target_industries"] = _dedupe_keep_order(
        [str(v) for v in form.getlist("industry_choice")]
        + _split_csv(str(form.get("custom_industries") or ""))
    )
    data["target_regions"] = _dedupe_keep_order(
        [str(v) for v in form.getlist("region_choice")]
        + _split_csv(str(form.get("custom_regions") or ""))
    )
    data["excluded_industries"] = _dedupe_keep_order(
        [str(v) for v in form.getlist("exclude_industry_choice")]
        + _split_csv(str(form.get("custom_excluded_industries") or ""))
    )
    data["preferred_solution_families"] = _dedupe_keep_order(
        [str(v) for v in form.getlist("service_choice")]
        + _split_csv(str(form.get("custom_services") or ""))
    )
    data["thresholds"] = {
        "band_high": band_high,
        "band_medium": band_medium,
        "band_watch": band_watch,
        "outreach_ready_min": outreach_ready_min,
    }
    outreach = dict(data.get("outreach") or {})
    outreach["refresh_interval_days"] = {
        "high": refresh_high,
        "medium": refresh_medium,
        "watch": refresh_watch,
        "nurture": refresh_nurture,
        "reject": outreach.get("refresh_interval_days", {}).get("reject", 30),
    }
    data["outreach"] = outreach
    # Model selection is recorded for the operator; apply via .env / restart.
    data["models"] = {
        "extraction_model": extraction_model.strip() or get_settings().extraction_model,
        "generation_model": generation_model.strip() or get_settings().generation_model,
        "note": "Change EXTRACTION_MODEL / GENERATION_MODEL in .env and restart to apply.",
    }
    DEFAULT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PROFILE_PATH.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    reload_operator_profile()
    return RedirectResponse(url="/settings?flash=Profile saved", status_code=303)


@router.post("/settings/feeds")
def settings_add_feed(
    session: SessionDep,
    name: Annotated[str, Form()],
    url: Annotated[str, Form()],
    kind: Annotated[str, Form()] = AdapterKind.RSS.value,
) -> RedirectResponse:
    try:
        add_feed(session, name=name, url=url, kind=kind)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/settings?flash={exc}", status_code=303)
    return RedirectResponse(url="/settings?flash=Feed added", status_code=303)


@router.post("/settings/feeds/{feed_id}/toggle")
def settings_toggle_feed(session: SessionDep, feed_id: str) -> RedirectResponse:
    from uuid import UUID

    feed = session.get(SourceFeed, UUID(feed_id))
    if feed is None:
        return RedirectResponse(url="/settings?flash=Feed not found", status_code=303)
    feed.enabled = not feed.enabled
    session.flush()
    return RedirectResponse(
        url=f"/settings?flash=Feed {'enabled' if feed.enabled else 'disabled'}",
        status_code=303,
    )


@router.post("/settings/feeds/{feed_id}/delete")
def settings_delete_feed(session: SessionDep, feed_id: str) -> RedirectResponse:
    from uuid import UUID

    feed = session.get(SourceFeed, UUID(feed_id))
    if feed is None:
        return RedirectResponse(url="/settings?flash=Feed not found", status_code=303)
    session.delete(feed)
    session.flush()
    return RedirectResponse(url="/settings?flash=Feed removed", status_code=303)


@router.post("/settings/feeds/{feed_id}/poll")
def settings_poll_feed(session: SessionDep, feed_id: str) -> RedirectResponse:
    from uuid import UUID

    feed = session.get(SourceFeed, UUID(feed_id))
    if feed is None:
        return RedirectResponse(url="/settings?flash=Feed not found", status_code=303)
    try:
        stats = poll_feed(session, feed)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(url=f"/settings?flash=Poll failed: {exc}", status_code=303)
    return RedirectResponse(
        url=f"/settings?flash=Polled: {stats}",
        status_code=303,
    )


@router.post("/settings/domain-policy")
def settings_domain_policy(
    session: SessionDep,
    domain: Annotated[str, Form()],
    playwright_fallback: Annotated[str, Form()] = "off",
    notes: Annotated[str, Form()] = "",
) -> RedirectResponse:
    try:
        set_domain_policy(
            session,
            domain,
            playwright_fallback=playwright_fallback in {"on", "true", "1", "yes"},
            notes=notes or None,
        )
    except ValueError as exc:
        return RedirectResponse(url=f"/settings?flash={exc}", status_code=303)
    return RedirectResponse(url="/settings?flash=Domain policy saved", status_code=303)


@router.post("/companies/{company_id}/feedback")
def company_feedback(
    session: SessionDep,
    company_id: str,
    verdict: Annotated[str, Form()],
    reason: Annotated[str, Form()],
) -> RedirectResponse:
    from uuid import UUID

    company = session.get(Company, UUID(company_id))
    if company is None:
        return RedirectResponse(url="/companies?flash=Company not found", status_code=303)
    try:
        row = record_feedback(session, company, verdict=verdict, reason=reason)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/companies/{company_id}?flash={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/companies/{company_id}?flash=Feedback saved — {row.suggested_adjustment}",
        status_code=303,
    )
