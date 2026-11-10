"""Lastprofil-Baseline und Anomalie-Erkennung (robust: Median/MAD, ohne ML)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median

MAD_SCALE = 1.4826  # macht MAD vergleichbar mit der Standardabweichung


@dataclass(frozen=True, slots=True)
class Slot:
    median: float
    mad: float
    n: int


def mad(values: Sequence[float]) -> float:
    med = median(values)
    return median([abs(v - med) for v in values])


def percentile(values: Sequence[float], p: float) -> float:
    """Perzentil mit linearer Interpolation (p in 0..100)."""
    data = sorted(values)
    if not data:
        raise ValueError("leere Liste")
    pos = (len(data) - 1) * p / 100
    low = int(pos)
    high = min(low + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (pos - low)


def build_baseline(
    samples: Iterable[tuple[int, int, float]], min_samples: int = 4
) -> dict[tuple[int, int], Slot]:
    """Baseline je (Wochentag, Stunde) aus (weekday, hour, value)-Stichproben."""
    grouped: dict[tuple[int, int], list[float]] = {}
    for weekday, hour, value in samples:
        grouped.setdefault((weekday, hour), []).append(value)
    return {
        key: Slot(median(vals), mad(vals), len(vals))
        for key, vals in grouped.items()
        if len(vals) >= min_samples
    }


def deviation_pct(value: float, slot: Slot | None, min_base: float = 1.0) -> float | None:
    """Abweichung in % zum Median; ``None`` ohne Baseline oder bei ~0 Basis."""
    if slot is None or abs(slot.median) < min_base:
        return None
    return (value - slot.median) / abs(slot.median) * 100


def is_high(value: float, slot: Slot, k: float, floor: float) -> bool:
    """Wert liegt mehr als ``k`` robuste Streuungen (mind. ``floor``) über dem Median."""
    return value - slot.median > k * max(MAD_SCALE * slot.mad, floor)


def detect_anomaly(
    recent: Sequence[tuple[int, int, float]],
    baseline: dict[tuple[int, int], Slot],
    *,
    k: float,
    hours: int,
    floor: float,
) -> bool:
    """Anomalie, wenn die letzten ``hours`` Stunden alle deutlich über der Baseline liegen."""
    if hours < 1 or len(recent) < hours:
        return False
    for weekday, hour, value in recent[-hours:]:
        slot = baseline.get((weekday, hour))
        if slot is None or not is_high(value, slot, k, floor):
            return False
    return True


def night_baseload_anomaly(
    current: float, history: Sequence[float], *, k: float, floor: float, min_history: int = 5
) -> bool:
    """Nachtgrundlast erhöht gegenüber den bisherigen Nächten."""
    if len(history) < min_history:
        return False
    slot = Slot(median(history), mad(history), len(history))
    return is_high(current, slot, k, floor)
