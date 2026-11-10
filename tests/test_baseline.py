import pytest

from custom_components.strom_assistent.logic.baseline import (
    Slot,
    build_baseline,
    detect_anomaly,
    deviation_pct,
    mad,
    night_baseload_anomaly,
    percentile,
)


def test_mad_and_percentile():
    assert mad([1, 2, 3, 4, 100]) == 1
    assert percentile([1, 2, 3, 4, 5], 0) == 1
    assert percentile([1, 2, 3, 4, 5], 50) == 3
    assert percentile([0, 10], 25) == 2.5
    with pytest.raises(ValueError):
        percentile([], 5)


def test_baseline_needs_min_samples():
    samples = [(0, 8, 100.0)] * 3 + [(1, 8, 200.0)] * 5
    base = build_baseline(samples)
    assert (0, 8) not in base
    assert base[(1, 8)].median == 200.0


def test_deviation():
    assert deviation_pct(150, Slot(100, 5, 8)) == 50
    assert deviation_pct(150, None) is None
    assert deviation_pct(150, Slot(0.0, 0, 8)) is None


def test_anomaly_requires_all_hours_high():
    base = {(0, h): Slot(200.0, 10.0, 8) for h in range(24)}
    high = [(0, 8, 900.0), (0, 9, 900.0), (0, 10, 900.0)]
    assert detect_anomaly(high, base, k=3, hours=3, floor=50)
    mixed = [(0, 8, 900.0), (0, 9, 210.0), (0, 10, 900.0)]
    assert not detect_anomaly(mixed, base, k=3, hours=3, floor=50)
    assert not detect_anomaly(high[:2], base, k=3, hours=3, floor=50)


def test_floor_prevents_tiny_mad_false_positive():
    base = {(0, 8): Slot(200.0, 0.0, 8)}
    assert not detect_anomaly([(0, 8, 260.0)], base, k=3, hours=1, floor=50)
    assert detect_anomaly([(0, 8, 400.0)], base, k=3, hours=1, floor=50)


def test_night_baseload():
    hist = [100, 105, 98, 102, 101, 99]
    assert night_baseload_anomaly(300, hist, k=3, floor=20)
    assert not night_baseload_anomaly(110, hist, k=3, floor=20)
    assert not night_baseload_anomaly(300, hist[:3], k=3, floor=20)
