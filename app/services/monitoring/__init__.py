"""Monitoring package: cadence, resurfacing, Today."""

__all__ = [
    "apply_next_refresh",
    "compute_next_refresh_at",
    "load_today",
    "maybe_resurface",
]


def __getattr__(name: str) -> object:
    if name in {"apply_next_refresh", "compute_next_refresh_at"}:
        from app.services.monitoring import cadence

        return getattr(cadence, name)
    if name == "maybe_resurface":
        from app.services.monitoring import resurface

        return resurface.maybe_resurface
    if name == "load_today":
        from app.services.monitoring import today

        return today.load_today
    raise AttributeError(name)
