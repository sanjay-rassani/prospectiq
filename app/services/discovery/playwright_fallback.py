"""Optional Playwright fallback for domains that opt in (P9-7).

Playwright is an optional dependency. When not installed or not enabled for the domain,
callers keep using plain HTTP.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DomainFetchPolicy
from app.services.discovery.normalize import normalize_domain

logger = logging.getLogger(__name__)


def playwright_enabled_for_url(session: Session, url: str) -> bool:
    try:
        domain = normalize_domain(url)
    except ValueError:
        return False
    policy = session.scalar(
        select(DomainFetchPolicy).where(DomainFetchPolicy.domain == domain)
    )
    return bool(policy and policy.playwright_fallback)


def set_domain_policy(
    session: Session,
    domain: str,
    *,
    playwright_fallback: bool,
    notes: str | None = None,
    rate_limit_seconds: float | None = None,
) -> DomainFetchPolicy:
    domain = normalize_domain(domain)
    policy = session.scalar(
        select(DomainFetchPolicy).where(DomainFetchPolicy.domain == domain)
    )
    if policy is None:
        policy = DomainFetchPolicy(domain=domain)
        session.add(policy)
    policy.playwright_fallback = playwright_fallback
    policy.notes = notes
    policy.rate_limit_seconds = rate_limit_seconds
    session.flush()
    return policy


def fetch_with_playwright(url: str, timeout_ms: int = 30000) -> dict[str, Any]:
    """Return {ok, html, final_url, error}. Requires `playwright` to be installed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "html": None,
            "final_url": None,
            "error": (
                "playwright not installed; "
                "uv pip install playwright && playwright install chromium"
            ),
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            html = page.content()
            final = page.url
            status = response.status if response else None
            browser.close()
            return {
                "ok": True,
                "html": html,
                "final_url": final,
                "http_status": status,
                "error": None,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("playwright fetch failed for %s: %s", url, exc)
        return {"ok": False, "html": None, "final_url": None, "error": str(exc)}
