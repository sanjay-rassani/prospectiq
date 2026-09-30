"""Phase 1 foundation checks."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_health_reports_database_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_today_page_renders(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Today" in response.text


def test_app_binds_to_loopback_by_default() -> None:
    """There is no authentication yet, so a non-loopback default would expose every
    prospect on the network (spec section 18, task P10-7)."""
    assert get_settings().host == "127.0.0.1"


def test_static_assets_are_vendored() -> None:
    """The UI must not depend on a CDN: no paid or third-party runtime services (FR-12)."""
    from app.main import BASE_DIR

    assert (BASE_DIR / "static" / "pico.min.css").exists()
    assert (BASE_DIR / "static" / "htmx.min.js").exists()
