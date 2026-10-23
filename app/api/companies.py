"""Company list, seed, detail, and refresh routes."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from queue import Queue
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal, get_session
from app.models import Company, FeedEntry, SourceFeed, SourceSnapshot
from app.services.buyers.capture import add_manual_person
from app.services.discovery.delete_company import delete_company
from app.services.discovery.rss import add_feed, poll_all_feeds
from app.services.discovery.seed import refresh_company, seed_targets
from app.services.discovery.suggestions import (
    DISCOVER_PRESETS,
    EXCLUDE_GROUPS,
    KEYWORD_GROUPS,
    all_exclude_suggestions,
    all_keyword_suggestions,
    feed_suggestions_by_group,
    feed_suggestions_map,
    preset_choices,
)
from app.services.scoring.profile import (
    DEFAULT_PROFILE_PATH,
    get_operator_profile,
    reload_operator_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/companies", response_class=HTMLResponse)
def companies_list(request: Request, session: SessionDep) -> HTMLResponse:
    templates = get_templates(request)
    companies = session.scalars(
        select(Company).order_by(Company.updated_at.desc())
    ).all()
    snapshot_counts = dict(
        session.execute(
            select(SourceSnapshot.company_id, func.count())
            .group_by(SourceSnapshot.company_id)
        ).all()
    )
    return templates.TemplateResponse(
        request=request,
        name="companies/list.html",
        context={
            "title": "Companies",
            "companies": companies,
            "snapshot_counts": snapshot_counts,
            "flash": request.query_params.get("flash"),
        },
    )


@router.get("/companies/seed", response_class=HTMLResponse)
def seed_form(request: Request) -> HTMLResponse:
    templates = get_templates(request)
    return templates.TemplateResponse(
        request=request,
        name="companies/seed.html",
        context={"title": "Seed companies", "error": None, "blob": ""},
    )


@router.get("/companies/discover", response_class=HTMLResponse)
def discover_page(request: Request, session: SessionDep) -> HTMLResponse:
    """Auto-discovery via permitted feeds (not Google scrape / no platform logins)."""
    templates = get_templates(request)
    profile = get_operator_profile()
    feeds = session.scalars(select(SourceFeed).order_by(SourceFeed.name)).all()
    recent = session.execute(
        select(FeedEntry, Company, SourceFeed)
        .join(Company, FeedEntry.company_id == Company.id)
        .join(SourceFeed, FeedEntry.feed_id == SourceFeed.id)
        .where(FeedEntry.company_id.is_not(None))
        .order_by(FeedEntry.created_at.desc())
        .limit(25)
    ).all()
    catalog_kw = {k.casefold() for k in all_keyword_suggestions()}
    catalog_ex = {k.casefold() for k in all_exclude_suggestions()}
    selected_keywords = {k.casefold() for k in profile.discovery.keywords}
    selected_excludes = {k.casefold() for k in profile.discovery.exclude_keywords}
    custom_keywords_value = ", ".join(
        k for k in profile.discovery.keywords if k.casefold() not in catalog_kw
    )
    custom_excludes_value = ", ".join(
        k for k in profile.discovery.exclude_keywords if k.casefold() not in catalog_ex
    )
    return templates.TemplateResponse(
        request=request,
        name="companies/discover.html",
        context={
            "title": "Discover",
            "feeds": feeds,
            "recent": recent,
            "profile": profile,
            "discovery": profile.discovery,
            "keyword_groups": KEYWORD_GROUPS,
            "exclude_groups": EXCLUDE_GROUPS,
            "preset_choices": preset_choices(),
            "preset_data": {
                key: {
                    "keywords": [str(x).casefold() for x in (spec.get("keywords") or [])],
                    "exclude_keywords": [
                        str(x).casefold() for x in (spec.get("exclude_keywords") or [])
                    ],
                    "use_profile_industries_as_keywords": spec.get(
                        "use_profile_industries_as_keywords"
                    ),
                }
                for key, spec in DISCOVER_PRESETS.items()
                if key != "custom"
            },
            "selected_keywords": selected_keywords,
            "selected_excludes": selected_excludes,
            "custom_keywords_value": custom_keywords_value,
            "custom_excludes_value": custom_excludes_value,
            "feed_suggestion_groups": feed_suggestions_by_group(),
            "feed_suggestion_map": feed_suggestions_map(),
            "flash": request.query_params.get("flash"),
        },
    )


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in value.replace("\n", ",").split(",") if p.strip()]


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


@router.post("/companies/discover/prefs")
async def discover_save_prefs(request: Request) -> RedirectResponse:
    import yaml

    form = await request.form()
    focus_preset = str(form.get("focus_preset") or "custom")
    if focus_preset not in DISCOVER_PRESETS:
        focus_preset = "custom"

    custom_keywords = _split_csv(str(form.get("custom_keywords") or ""))
    custom_excludes = _split_csv(str(form.get("custom_excludes") or ""))
    keyword_choices = [str(v) for v in form.getlist("keyword_choice")]
    exclude_choices = [str(v) for v in form.getlist("exclude_choice")]
    keywords = _dedupe_keep_order(keyword_choices + custom_keywords)
    exclude_keywords = _dedupe_keep_order(exclude_choices + custom_excludes)

    try:
        max_entries = int(str(form.get("max_new_entries_per_feed") or "25"))
    except ValueError:
        max_entries = 25
    try:
        max_seeds = int(str(form.get("max_seeds_per_poll") or "15"))
    except ValueError:
        max_seeds = 15

    data: dict[str, Any] = {}
    if DEFAULT_PROFILE_PATH.exists():
        data = yaml.safe_load(DEFAULT_PROFILE_PATH.read_text()) or {}
    data["discovery"] = {
        "focus_preset": focus_preset,
        "keywords": keywords,
        "exclude_keywords": exclude_keywords,
        "use_profile_industries_as_keywords": bool(
            form.get("use_profile_industries_as_keywords")
        ),
        "skip_social_hosts": bool(form.get("skip_social_hosts")),
        "seed_new_links": bool(form.get("seed_new_links")),
        "only_unknown_domains": bool(form.get("only_unknown_domains")),
        "max_new_entries_per_feed": max(1, min(max_entries, 200)),
        "max_seeds_per_poll": max(0, min(max_seeds, 100)),
    }
    DEFAULT_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PROFILE_PATH.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    )
    reload_operator_profile()
    return RedirectResponse(
        url="/companies/discover?flash=Discover filters saved",
        status_code=303,
    )



@router.get("/companies/discover/poll/stream")
def discover_poll_stream() -> StreamingResponse:
    """SSE progress for Discover poll — page stays interactive (no long form POST)."""
    q: Queue[dict[str, Any] | None] = Queue()

    def worker() -> None:
        session = SessionLocal()
        try:
            reload_operator_profile()

            def on_progress(level: str, message: str) -> None:
                q.put({"level": level, "message": message})

            stats = poll_all_feeds(session, on_progress=on_progress)
            session.commit()
            summary = (
                f"Done — {stats['feeds']} feed(s), "
                f"{stats['new_entries']} new entr{'y' if stats['new_entries'] == 1 else 'ies'}, "
                f"{stats['seeded']} compan{'y' if stats['seeded'] == 1 else 'ies'} seeded"
            )
            if stats.get("filtered"):
                summary += f", {stats['filtered']} filtered"
            if stats["errors"]:
                summary += f", {stats['errors']} error(s)"
            q.put({"level": "done", "message": summary, "stats": stats})
        except Exception as exc:
            session.rollback()
            logger.exception("discover poll stream failed")
            q.put({"level": "error", "message": f"Poll failed: {exc}"})
            q.put(
                {
                    "level": "done",
                    "message": "Stopped with errors.",
                    "stats": {"feeds": 0, "new_entries": 0, "seeded": 0, "errors": 1},
                }
            )
        finally:
            session.close()
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def events() -> Iterator[str]:
        while True:
            item = q.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, default=str)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/companies/discover/feeds")
def discover_add_feed(
    session: SessionDep,
    name: Annotated[str, Form()],
    url: Annotated[str, Form()],
    kind: Annotated[str, Form()] = "rss",
) -> RedirectResponse:
    add_feed(session, name=name, url=url, kind=kind)
    return RedirectResponse(
        url="/companies/discover?flash=Feed added - poll to import new links",
        status_code=303,
    )


@router.post("/companies/seed", response_class=HTMLResponse, response_model=None)
def seed_submit(
    request: Request,
    session: SessionDep,
    blob: Annotated[str, Form()],
) -> HTMLResponse | RedirectResponse:
    templates = get_templates(request)
    try:
        outcomes = seed_targets(session, blob)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="companies/seed.html",
            context={"title": "Seed companies", "error": str(exc), "blob": blob},
            status_code=400,
        )

    if not outcomes:
        return templates.TemplateResponse(
            request=request,
            name="companies/seed.html",
            context={
                "title": "Seed companies",
                "error": "No valid domains found. Enter one domain or URL per line.",
                "blob": blob,
            },
            status_code=400,
        )

    if len(outcomes) == 1:
        return RedirectResponse(
            url=f"/companies/{outcomes[0].company.id}?flash={outcomes[0].message}",
            status_code=303,
        )

    stored = sum(1 for o in outcomes if o.snapshot)
    return RedirectResponse(
        url=f"/companies?flash=Seeded {len(outcomes)} companies; {stored} new snapshots",
        status_code=303,
    )


@router.get("/companies/{company_id}", response_class=HTMLResponse)
def company_detail(
    request: Request,
    session: SessionDep,
    company_id: UUID,
) -> HTMLResponse:
    templates = get_templates(request)
    company = session.scalar(
        select(Company)
        .where(Company.id == company_id)
        .options(
            selectinload(Company.snapshots),
            selectinload(Company.signals),
            selectinload(Company.opportunities),
            selectinload(Company.people),
            selectinload(Company.research_tasks),
        )
    )
    if company is None:
        return templates.TemplateResponse(
            request=request,
            name="companies/not_found.html",
            context={"title": "Not found"},
            status_code=404,
        )
    return templates.TemplateResponse(
        request=request,
        name="companies/detail.html",
        context={
            "title": company.name,
            "company": company,
            "flash": request.query_params.get("flash"),
        },
    )


@router.post("/companies/{company_id}/refresh")
def company_refresh(
    session: SessionDep,
    company_id: UUID,
) -> RedirectResponse:
    try:
        outcome = refresh_company(session, company_id)
    except LookupError:
        return RedirectResponse(url="/companies?flash=Company not found", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/companies/{company_id}?flash={exc}", status_code=303
        )
    return RedirectResponse(
        url=f"/companies/{company_id}?flash={outcome.message}",
        status_code=303,
    )


@router.post("/companies/{company_id}/delete")
def company_delete(
    session: SessionDep,
    company_id: UUID,
) -> RedirectResponse:
    try:
        message = delete_company(session, company_id)
    except LookupError:
        return RedirectResponse(url="/companies?flash=Company not found", status_code=303)
    return RedirectResponse(url=f"/companies?flash={message}", status_code=303)


@router.post("/companies/{company_id}/people")
def company_add_person(
    session: SessionDep,
    company_id: UUID,
    name: Annotated[str, Form()],
    role: Annotated[str, Form()],
    public_email: Annotated[str, Form()] = "",
    public_profile_url: Annotated[str, Form()] = "",
) -> RedirectResponse:
    company = session.get(Company, company_id)
    if company is None:
        return RedirectResponse(url="/companies?flash=Company not found", status_code=303)
    try:
        person = add_manual_person(
            session,
            company,
            name=name,
            role=role,
            public_email=public_email or None,
            public_profile_url=public_profile_url or None,
        )
    except ValueError as exc:
        return RedirectResponse(
            url=f"/companies/{company_id}?flash={exc}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/companies/{company_id}?flash=Added {person.name}",
        status_code=303,
    )
