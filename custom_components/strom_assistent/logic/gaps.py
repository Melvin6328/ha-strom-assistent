"""Erkennung und Planung von Statistik-Lücken (reine Logik, ohne Home Assistant)."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

HOUR = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class Gap:
    """Zusammenhängender Zeitraum mit fehlender Statistik."""

    start: datetime
    end: datetime
    missing_kwh: float
    hours: int


@dataclass(frozen=True, slots=True)
class EnergyRow:
    """Eine stündliche Energie-Statistikzeile (Zählerstand am Stundenende)."""

    state: float | None
    sum: float | None


@dataclass(frozen=True, slots=True)
class PowerRow:
    """Eine stündliche Leistungs-Statistikzeile (W)."""

    mean: float | None
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True, slots=True)
class EnergyRepairRow:
    start: datetime
    state: float | None
    old_sum: float | None
    new_sum: float
    in_gap: bool


@dataclass(frozen=True, slots=True)
class EnergyRepairPlan:
    rows: list[EnergyRepairRow]
    added_kwh: float


@dataclass(frozen=True, slots=True)
class PowerRepairRow:
    start: datetime
    old_mean: float | None
    new: PowerRow


def _merge(bad: list[tuple[datetime, float]]) -> list[Gap]:
    """Aufeinanderfolgende Problemstunden zu Lücken zusammenfassen."""
    gaps: list[Gap] = []
    cur_start: datetime | None = None
    prev: datetime | None = None
    missing = 0.0
    count = 0
    for hour, miss in sorted(bad):
        if prev is not None and hour - prev == HOUR:
            missing += miss
            count += 1
        else:
            if cur_start is not None and prev is not None:
                gaps.append(Gap(cur_start, prev + HOUR, missing, count))
            cur_start, missing, count = hour, miss, 1
        prev = hour
    if cur_start is not None and prev is not None:
        gaps.append(Gap(cur_start, prev + HOUR, missing, count))
    return gaps


def _cum_at(keys: list[datetime], values: dict[datetime, float], hour: datetime) -> float | None:
    """Letzter bekannter kumulativer Wert bei oder vor ``hour``."""
    idx = bisect_right(keys, hour)
    return values[keys[idx - 1]] if idx else None


def _hourly_deltas(cum: dict[datetime, float]) -> dict[datetime, float]:
    return {h: v - cum[h - HOUR] for h, v in cum.items() if (h - HOUR) in cum}


def _target_deltas(
    ref_hours: list[datetime], target: dict[datetime, float]
) -> dict[datetime, float]:
    """Stundendelta des Ziels; fehlende Zeilen zählen als 0 (Wert wird fortgeschrieben)."""
    keys = sorted(target)
    out: dict[datetime, float] = {}
    for hour in ref_hours:
        now = _cum_at(keys, target, hour)
        before = _cum_at(keys, target, hour - HOUR)
        if now is not None and before is not None:
            out[hour] = now - before
    return out


def detect_energy_gaps(
    ref: dict[datetime, float],
    target: dict[datetime, float],
    *,
    ratio: float = 0.5,
    min_kwh: float = 0.01,
) -> list[Gap]:
    """Stunden finden, in denen der Referenzzähler lief, das Ziel aber (fast) nicht.

    ``ref`` und ``target`` sind kumulative Werte (``sum``) je Stundenstart.
    """
    ref_d = _hourly_deltas(ref)
    tgt_d = _target_deltas(sorted(ref_d), target)
    bad = [
        (h, d - tgt_d[h])
        for h, d in ref_d.items()
        if h in tgt_d and d >= min_kwh and tgt_d[h] < ratio * d
    ]
    return _merge(bad)


def _gap_hours(gaps: list[Gap]) -> set[datetime]:
    out: set[datetime] = set()
    for gap in gaps:
        hour = gap.start
        while hour < gap.end:
            out.add(hour)
            hour += HOUR
    return out


def plan_energy_repair(
    ref: dict[datetime, float],
    target: dict[datetime, EnergyRow],
    gaps: list[Gap],
    *,
    max_hour_kwh: float = 30.0,
) -> EnergyRepairPlan:
    """Neue ``sum``-Werte berechnen.

    Lückenstunden bekommen das Delta des Referenzzählers; alle späteren Zeilen
    werden um die nachgetragene Energie verschoben (``state`` bleibt unverändert).
    """
    if not gaps:
        return EnergyRepairPlan([], 0.0)
    ref_d = _hourly_deltas(ref)
    tgt_sum = {h: r.sum for h, r in target.items() if r.sum is not None}
    tgt_d = _target_deltas(sorted(ref_d), tgt_sum)
    gap_hours = _gap_hours(gaps)
    first = min(gap_hours)

    anchor_keys = sorted(h for h in tgt_sum if h < first)
    if not anchor_keys:
        raise ValueError("Keine Statistik vor der Lücke als Anker vorhanden")
    last_sum = tgt_sum[anchor_keys[-1]]
    last_state = target[anchor_keys[-1]].state

    hours = sorted({h for h in target if h >= first} | gap_hours)
    offset = 0.0
    rows: list[EnergyRepairRow] = []
    for hour in hours:
        in_gap = hour in gap_hours
        if in_gap:
            if hour not in ref_d or hour not in tgt_d:
                raise ValueError(f"Referenzdaten für {hour.isoformat()} unvollständig")
            if not 0 <= ref_d[hour] <= max_hour_kwh:
                raise ValueError(
                    f"Unplausibles Referenzdelta {ref_d[hour]:.3f} kWh bei {hour.isoformat()}"
                )
            offset += max(ref_d[hour] - tgt_d[hour], 0.0)
        row = target.get(hour)
        old_sum = row.sum if row and row.sum is not None else None
        base_sum = old_sum if old_sum is not None else last_sum
        state = row.state if row and row.state is not None else last_state
        rows.append(EnergyRepairRow(hour, state, old_sum, base_sum + offset, in_gap))
        last_sum = base_sum
        last_state = state
    return EnergyRepairPlan(rows, offset)


def _clip(value: float, richtung: str) -> float:
    return max(value, 0.0) if richtung == "bezug" else max(-value, 0.0)


def detect_power_gaps(
    ref: dict[datetime, PowerRow],
    target: dict[datetime, PowerRow],
    richtung: str,
    *,
    ratio: float = 0.5,
    min_w: float = 5.0,
) -> list[Gap]:
    """Stunden, in denen die Referenzleistung fließt, das Ziel aber fehlt oder ~0 ist."""
    bad: list[tuple[datetime, float]] = []
    for hour, row in ref.items():
        if row.mean is None:
            continue
        want = _clip(row.mean, richtung)
        got_row = target.get(hour)
        got = got_row.mean if got_row and got_row.mean is not None else 0.0
        if want >= min_w and got < ratio * want:
            bad.append((hour, (want - got) / 1000.0))
    return _merge(bad)


def plan_power_repair(
    ref: dict[datetime, PowerRow],
    target: dict[datetime, PowerRow],
    gaps: list[Gap],
    richtung: str,
) -> list[PowerRepairRow]:
    """Mittel/Min/Max der Lückenstunden aus der Referenz ableiten (Näherung)."""
    rows: list[PowerRepairRow] = []
    for hour in sorted(_gap_hours(gaps)):
        src = ref.get(hour)
        if src is None or src.mean is None:
            raise ValueError(f"Referenzdaten für {hour.isoformat()} fehlen")
        lo = _clip(src.min if src.min is not None else src.mean, richtung)
        hi = _clip(src.max if src.max is not None else src.mean, richtung)
        low, high = min(lo, hi), max(lo, hi)
        new = PowerRow(_clip(src.mean, richtung), low, high)
        old = target.get(hour)
        rows.append(PowerRepairRow(hour, old.mean if old else None, new))
    return rows
