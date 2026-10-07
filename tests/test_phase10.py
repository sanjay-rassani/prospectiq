"""Phase 10: export, sanitize, auth gate, secrets audit notes."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.auth import requires_auth, resolve_auth_secret
from app.config import Settings
from app.main import CorrelationFormatter
from app.models import Company, Opportunity
from app.services.export import export_companies_json, export_opportunities_csv
from app.services.sanitize import sanitize_for_display


def test_correlation_formatter_defaults_missing_id() -> None:
    formatter = CorrelationFormatter(
        "%(name)s [correlation_id=%(correlation_id)s] %(message)s"
    )
    record = logging.LogRecord(
        name="apscheduler.scheduler",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Scheduler has been shut down",
        args=(),
        exc_info=None,
    )
    assert "correlation_id=-" in formatter.format(record)


def test_sanitize_escapes_html() -> None:
    dirty = '<script>alert("x")</script>Hello & goodbye'
    clean = sanitize_for_display(dirty)
    assert "<script>" not in clean
    assert "Hello" in clean
    assert "&amp;" in clean
    assert "&quot;x&quot;" in clean


def test_requires_auth_only_off_loopback() -> None:
    assert requires_auth(Settings(host="127.0.0.1")) is False
    assert requires_auth(Settings(host="0.0.0.0")) is False
    assert requires_auth(Settings(host="192.168.1.10")) is True


def test_resolve_auth_secret_uses_env_token() -> None:
    secret = resolve_auth_secret(Settings(host="127.0.0.1", auth_token="fixed-token"))
    assert secret == "fixed-token"


def test_export_endpoints(client: object, session: Session) -> None:
    company = Company(name="Export Co", domain="export.example", status="researched")
    session.add(company)
    session.flush()
    session.add(
        Opportunity(
            company_id=company.id,
            title="Export Opp",
            solution_family="integrations_apis",
            problem_or_change="p",
            hypothesis="h",
            business_outcome="b",
            why_now="now",
            buyer_role="CTO",
            confidence="medium",
            status="active",
            unknowns=[],
        )
    )
    session.flush()
    assert "Export Co" in export_companies_json(session)
    assert "Export Opp" in export_opportunities_csv(session)
    r = client.get("/export/companies.json")  # type: ignore[attr-defined]
    assert r.status_code == 200
    assert b"Export Co" in r.content
    r2 = client.get("/export/opportunities.csv")  # type: ignore[attr-defined]
    assert r2.status_code == 200
    assert b"Export Opp" in r2.content
