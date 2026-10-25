"""Discover run history helpers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.leads.run_history import list_discovery_runs, record_discovery_run


def test_record_and_list_discovery_runs(session: Session) -> None:
    record_discovery_run(
        session,
        stats={"created": 3, "updated": 1, "filtered": 2, "seeded": 1, "errors": 0},
        summary="Done — 3 new",
        log_lines=["[INFO] Starting…", "[OK] Hacker News: 5", "[DONE] Done — 3 new"],
        ok=True,
    )
    record_discovery_run(
        session,
        stats={"errors": 1},
        summary="Stopped with errors.",
        log_lines=["[ERROR] boom"],
        ok=False,
        error="Poll failed: boom",
    )
    session.commit()

    rows = list_discovery_runs(session, limit=5)
    assert len(rows) >= 2
    assert rows[0]["ok"] is False
    assert "failed" in rows[0]["outcome"].casefold() or "boom" in rows[0]["outcome"].casefold()
    assert rows[1]["ok"] is True
    assert "+3 new" in rows[1]["outcome"]
    assert rows[1]["log_lines"]
    assert any("Hacker News" in line for line in rows[1]["log_lines"])


def test_zero_new_runs_replace_previous(session: Session) -> None:
    record_discovery_run(
        session,
        stats={"created": 2, "updated": 0, "filtered": 0, "seeded": 0, "errors": 0},
        summary="Done — 2 new",
        log_lines=["[DONE] 2"],
        ok=True,
    )
    record_discovery_run(
        session,
        stats={"created": 0, "updated": 0, "filtered": 5, "seeded": 0, "errors": 0},
        summary="Done — 0 new",
        log_lines=["[DONE] empty A"],
        ok=True,
    )
    record_discovery_run(
        session,
        stats={"created": 0, "updated": 1, "filtered": 3, "seeded": 0, "errors": 0},
        summary="Done — 0 new again",
        log_lines=["[DONE] empty B"],
        ok=True,
    )
    session.commit()

    rows = list_discovery_runs(session, limit=10)
    zero_new = [r for r in rows if r["ok"] and r["outcome"].startswith("+0 new")]
    productive = [r for r in rows if r["ok"] and "+2 new" in r["outcome"]]
    assert len(zero_new) == 1
    assert any("empty B" in line for line in zero_new[0]["log_lines"])
    assert len(productive) == 1
