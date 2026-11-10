"""Einfache Geräteerkennung über Leistungssprünge (reine Logik)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Step:
    ts: float  # Zeitpunkt des Sprungs (Sekunden)
    delta_w: float
    before_w: float
    after_w: float


class StepDetector:
    """Meldet einen Sprung erst, wenn das neue Niveau ``hold_s`` Sekunden hält."""

    def __init__(self, threshold_w: float, hold_s: float) -> None:
        self.threshold = threshold_w
        self.hold = hold_s
        self.tolerance = threshold_w / 2
        self._ref: float | None = None
        self._cand: tuple[float, float] | None = None  # (Wert, Startzeit)

    def update(self, ts: float, value: float) -> Step | None:
        if self._ref is None:
            self._ref = value
            return None
        if self._cand is not None:
            cand_value, cand_ts = self._cand
            if abs(value - cand_value) <= self.tolerance:
                if ts - cand_ts >= self.hold:
                    step = Step(cand_ts, value - self._ref, self._ref, value)
                    self._ref = value
                    self._cand = None
                    return step
                return None
            self._cand = None  # Niveau nicht gehalten -> Spitze verwerfen
        if abs(value - self._ref) >= self.threshold:
            self._cand = (value, ts)
        else:
            self._ref = value
        return None
