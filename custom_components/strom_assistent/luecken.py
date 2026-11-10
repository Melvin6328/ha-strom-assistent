"""Statistik-Lücken prüfen und reparieren (Funktion C)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder.models import StatisticData
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BEZUG_ENERGIE,
    CONF_EINSPEISE_ENERGIE,
    CONF_LEISTUNG,
    CONF_ZIEL_BEZUG_ENERGIE,
    CONF_ZIEL_BEZUG_LEISTUNG,
    CONF_ZIEL_EINSPEISE_ENERGIE,
    CONF_ZIEL_EINSPEISE_LEISTUNG,
    RICHTUNG_BEZUG,
    RICHTUNG_EINSPEISUNG,
)
from .logic.gaps import (
    Gap,
    detect_energy_gaps,
    detect_power_gaps,
    plan_energy_repair,
    plan_power_repair,
)
from .stats import (
    async_hourly,
    async_metadata,
    ceil_hour,
    cumulative,
    energy_rows,
    floor_hour,
    power_rows,
)

_LOGGER = logging.getLogger(__name__)

# Konfigurierte Ziel-Statistiken: Config-Key -> (Art, Richtung)
ZIELE: dict[str, tuple[str, str]] = {
    CONF_ZIEL_BEZUG_ENERGIE: ("energie", RICHTUNG_BEZUG),
    CONF_ZIEL_EINSPEISE_ENERGIE: ("energie", RICHTUNG_EINSPEISUNG),
    CONF_ZIEL_BEZUG_LEISTUNG: ("leistung", RICHTUNG_BEZUG),
    CONF_ZIEL_EINSPEISE_LEISTUNG: ("leistung", RICHTUNG_EINSPEISUNG),
}


@dataclass(slots=True)
class CheckResult:
    entity_id: str
    reference: str
    art: str
    richtung: str
    gaps: list[Gap]
    plan_rows: list[dict[str, Any]]
    added_kwh: float
    shifted_rows: int
    rows_to_write: list[StatisticData]
    metadata: dict[str, Any]

    @property
    def missing_kwh(self) -> float:
        return sum(g.missing_kwh for g in self.gaps)


def configured_targets(entry: ConfigEntry) -> list[tuple[str, str]]:
    """(entity_id, richtung) aller konfigurierten Ziel-Statistiken."""
    return [
        (entry.data[key], richtung)
        for key, (_art, richtung) in ZIELE.items()
        if entry.data.get(key)
    ]


def reference_for(entry: ConfigEntry, art: str, richtung: str) -> str | None:
    if art == "leistung":
        return entry.data.get(CONF_LEISTUNG)
    key = CONF_BEZUG_ENERGIE if richtung == RICHTUNG_BEZUG else CONF_EINSPEISE_ENERGIE
    return entry.data.get(key)


def default_richtung(entry: ConfigEntry, entity_id: str) -> str:
    for key, (_art, richtung) in ZIELE.items():
        if entry.data.get(key) == entity_id:
            return richtung
    return RICHTUNG_BEZUG


def _iso(value: datetime) -> str:
    return dt_util.as_local(value).isoformat()


async def async_check(
    hass: HomeAssistant,
    entry: ConfigEntry,
    entity_id: str,
    start: datetime,
    end: datetime,
    richtung: str,
    *,
    max_hour_kwh: float = 30.0,
) -> CheckResult:
    """Lücken im Zeitraum finden und die nötige Korrektur berechnen (schreibt nichts)."""
    meta = await async_metadata(hass, entity_id)
    if meta is None:
        raise ServiceValidationError(f"Keine Langzeitstatistik für {entity_id} gefunden")
    art = "energie" if meta.get("has_sum") else "leistung"
    reference = reference_for(entry, art, richtung)
    if not reference:
        raise ServiceValidationError(f"Keine Referenz-Entität für {art}/{richtung} konfiguriert")

    start = floor_hour(dt_util.as_utc(start))
    end = ceil_hour(dt_util.as_utc(end))
    fetch_start = start - timedelta(hours=1)
    # Für die Verschiebung nachfolgender Zeilen wird bis jetzt geladen.
    fetch_end = max(end, floor_hour(dt_util.utcnow()))
    types = {"state", "sum"} if art == "energie" else {"mean", "min", "max"}
    data = await async_hourly(hass, {entity_id, reference}, fetch_start, fetch_end, types)
    ref_rows = data.get(reference, [])
    tgt_rows = data.get(entity_id, [])

    gaps: list[Gap]
    plan_rows: list[dict[str, Any]] = []
    to_write: list[StatisticData] = []
    added = 0.0
    shifted = 0
    try:
        if art == "energie":
            ref = cumulative(ref_rows)
            tgt_all = energy_rows(tgt_rows)
            tgt_sum = {h: r.sum for h, r in tgt_all.items() if r.sum is not None}
            window = lambda d: {h: v for h, v in d.items() if h <= end}  # noqa: E731
            gaps = detect_energy_gaps(window(ref), window(tgt_sum))
            plan = plan_energy_repair(ref, tgt_all, gaps, max_hour_kwh=max_hour_kwh)
            added = plan.added_kwh
            for row in plan.rows:
                if row.in_gap:
                    plan_rows.append(
                        {
                            "start": _iso(row.start),
                            "sum_alt": row.old_sum,
                            "sum_neu": round(row.new_sum, 4),
                        }
                    )
                else:
                    shifted += 1
                to_write.append(StatisticData(start=row.start, state=row.state, sum=row.new_sum))
        else:
            ref_p = power_rows(ref_rows)
            tgt_p = power_rows(tgt_rows)
            window_p = lambda d: {h: v for h, v in d.items() if h <= end}  # noqa: E731
            gaps = detect_power_gaps(window_p(ref_p), window_p(tgt_p), richtung)
            for prow in plan_power_repair(ref_p, tgt_p, gaps, richtung):
                plan_rows.append(
                    {
                        "start": _iso(prow.start),
                        "mean_alt": prow.old_mean,
                        "mean_neu": round(prow.new.mean or 0.0, 2),
                    }
                )
                to_write.append(
                    StatisticData(
                        start=prow.start,
                        mean=prow.new.mean,
                        min=prow.new.min,
                        max=prow.new.max,
                    )
                )
            added = sum(g.missing_kwh for g in gaps)
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    return CheckResult(
        entity_id, reference, art, richtung, gaps, plan_rows, added, shifted, to_write, meta
    )


def gaps_as_dicts(gaps: list[Gap]) -> list[dict[str, Any]]:
    return [
        {
            "start": _iso(g.start),
            "ende": _iso(g.end),
            "stunden": g.hours,
            "fehlende_kwh": round(g.missing_kwh, 3),
        }
        for g in gaps
    ]


def write_repair(hass: HomeAssistant, result: CheckResult, *, max_kwh: float) -> None:
    """Berechnete Korrektur in die Statistik schreiben (nur nach Prüfung)."""
    if not result.gaps or not result.rows_to_write:
        return
    if result.added_kwh > max_kwh:
        raise ServiceValidationError(
            f"Nachzutragende Energie {result.added_kwh:.2f} kWh überschreitet max_kwh={max_kwh}"
        )
    _LOGGER.warning(
        "Repariere Statistik %s (%s): %d Lücke(n), %.3f kWh, %d Zeilen",
        result.entity_id,
        result.art,
        len(result.gaps),
        result.added_kwh,
        len(result.rows_to_write),
    )
    # Quelle "recorder" ist für Entitäten mit eigener entity_id korrekt.
    async_import_statistics(hass, result.metadata, result.rows_to_write)  # type: ignore[arg-type]
