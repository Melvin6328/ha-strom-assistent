"""Tarif- und Kostenrechnung (reine Logik, ohne Home Assistant)."""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from statistics import fmean
from typing import Any


@dataclass(frozen=True, slots=True)
class Tarif:
    gueltig_ab: date
    grundpreis: float  # EUR / Monat
    arbeitspreis: float  # EUR / kWh Bezug
    einspeiseverguetung: float  # EUR / kWh


@dataclass(slots=True)
class DayCost:
    bezug_kwh: float = 0.0
    feed_kwh: float = 0.0
    bezug_eur: float = 0.0
    feed_eur: float = 0.0
    grund_eur: float = 0.0


def parse_tarife(raw: Iterable[Mapping[str, Any]]) -> list[Tarif]:
    """Gespeicherte Tarifliste (Options) in sortierte ``Tarif``-Objekte wandeln."""
    out = [
        Tarif(
            date.fromisoformat(str(item["gueltig_ab"])),
            float(item["grundpreis"]),
            float(item["arbeitspreis"]),
            float(item["einspeiseverguetung"]),
        )
        for item in raw
    ]
    return sorted(out, key=lambda t: t.gueltig_ab)


def tarif_at(tarife: list[Tarif], day: date) -> Tarif | None:
    """Gültiger Tarif an einem Tag (neuester mit ``gueltig_ab <= day``)."""
    found: Tarif | None = None
    for tarif in tarife:
        if tarif.gueltig_ab <= day:
            found = tarif
    return found


def daily_costs(
    bezug_hours: Mapping[datetime, float],
    feed_hours: Mapping[datetime, float],
    tarife: list[Tarif],
    tz: tzinfo,
    days: Iterable[date],
    price_by_hour: Mapping[datetime, float] | None = None,
) -> dict[date, DayCost]:
    """Kosten je Tag aus stündlichen kWh-Deltas.

    Tage ohne gültigen Tarif fehlen im Ergebnis (nie still 0). Ein dynamischer Preis
    (``price_by_hour``) ersetzt den Arbeitspreis für die jeweilige Stunde.
    """
    result: dict[date, DayCost] = {}
    for day in days:
        tarif = tarif_at(tarife, day)
        if tarif is not None:
            result[day] = DayCost(
                grund_eur=tarif.grundpreis / calendar.monthrange(day.year, day.month)[1]
            )
    for hour, kwh in bezug_hours.items():
        day = hour.astimezone(tz).date()
        cost = result.get(day)
        if cost is None:
            continue
        tarif = tarif_at(tarife, day)
        price = (price_by_hour or {}).get(hour, tarif.arbeitspreis if tarif else 0.0)
        cost.bezug_kwh += kwh
        cost.bezug_eur += kwh * price
    for hour, kwh in feed_hours.items():
        day = hour.astimezone(tz).date()
        cost = result.get(day)
        tarif = tarif_at(tarife, day)
        if cost is None or tarif is None:
            continue
        cost.feed_kwh += kwh
        cost.feed_eur += kwh * tarif.einspeiseverguetung
    return result


def forecast(
    so_far: float,
    daily_variable: list[float],
    remaining_days: float,
    base_per_day: float,
    base_days: int,
) -> float | None:
    """Hochrechnung: bisher + Ø variable Tageskosten * Restzeit + Grundpreis der Resttage."""
    if not daily_variable:
        return None
    return so_far + fmean(daily_variable) * remaining_days + base_per_day * base_days
