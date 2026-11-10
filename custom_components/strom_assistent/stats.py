"""Zugriff auf die Recorder-Statistiken (HA-gebunden, async über den Recorder-Executor)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .logic.gaps import EnergyRow, PowerRow


def floor_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def ceil_hour(value: datetime) -> datetime:
    floored = floor_hour(value)
    return floored if floored == value else floored + timedelta(hours=1)


async def async_hourly(
    hass: HomeAssistant,
    statistic_ids: set[str],
    start: datetime,
    end: datetime | None,
    types: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Stündliche Statistik (Start/Ende als UTC)."""
    return await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        statistic_ids,
        "hour",
        None,
        types,
    )


async def async_metadata(hass: HomeAssistant, statistic_id: str) -> dict[str, Any] | None:
    """Recorder-Metadaten einer Statistik (oder ``None``)."""
    result = await get_instance(hass).async_add_executor_job(
        lambda: get_metadata(hass, statistic_ids={statistic_id})
    )
    entry = result.get(statistic_id)
    return dict(entry[1]) if entry else None


def _start(row: dict[str, Any]) -> datetime:
    return dt_util.utc_from_timestamp(row["start"])


def cumulative(rows: list[dict[str, Any]]) -> dict[datetime, float]:
    """Kumulativer Wert je Stunde (bevorzugt ``sum``, sonst ``state``)."""
    use = "sum" if any(r.get("sum") is not None for r in rows) else "state"
    return {_start(r): float(r[use]) for r in rows if r.get(use) is not None}


def energy_rows(rows: list[dict[str, Any]]) -> dict[datetime, EnergyRow]:
    return {_start(r): EnergyRow(r.get("state"), r.get("sum")) for r in rows}


def power_rows(rows: list[dict[str, Any]]) -> dict[datetime, PowerRow]:
    return {_start(r): PowerRow(r.get("mean"), r.get("min"), r.get("max")) for r in rows}
