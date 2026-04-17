"""Timezone utilities for the learning app (self-contained).

Duplicated from the parent project's src.db to keep this package
independent (see ADR-023, Phase 2 architecture refactor 2026-04-17).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def now_jst() -> datetime:
    return datetime.now(tz=JST)


def today_jst() -> date:
    return now_jst().date()


def _require_aware(dt: datetime, param_name: str = "dt") -> datetime:
    if dt.tzinfo is None:
        raise ValueError(f"{param_name} must be timezone-aware")
    return dt
