from datetime import UTC, datetime, timedelta

import pytest

from custom_components.strom_assistent.logic.gaps import (
    EnergyRow,
    PowerRow,
    detect_energy_gaps,
    detect_power_gaps,
    plan_energy_repair,
    plan_power_repair,
)

T0 = datetime(2026, 11, 9, 18, tzinfo=UTC)


def h(i):
    return T0 + timedelta(hours=i)


# Referenz: 1 kWh/h. Ziel bleibt in den Stunden 3..5 stehen (Lücke), danach läuft es weiter.
REF = {h(i): 100.0 + i for i in range(12)}
TARGET_SUM = {h(i): 10.0 + (i if i < 3 else 2 if i < 6 else i - 3) for i in range(12)}


def test_no_gap_when_target_follows():
    target = {k: v - 90 for k, v in REF.items()}
    assert detect_energy_gaps(REF, target) == []


def test_detects_gap_and_missing_kwh():
    gaps = detect_energy_gaps(REF, TARGET_SUM)
    assert len(gaps) == 1
    assert gaps[0].start == h(3) and gaps[0].end == h(6)
    assert gaps[0].hours == 3
    assert gaps[0].missing_kwh == pytest.approx(3.0)


def test_missing_rows_count_as_gap():
    target = {k: v for k, v in TARGET_SUM.items() if k not in (h(3), h(4), h(5))}
    gaps = detect_energy_gaps(REF, target)
    assert [(g.start, g.end) for g in gaps] == [(h(3), h(6))]


def test_repair_fills_gap_and_shifts_later_rows():
    target = {k: EnergyRow(v, v) for k, v in TARGET_SUM.items()}
    gaps = detect_energy_gaps(REF, TARGET_SUM)
    plan = plan_energy_repair(REF, target, gaps)
    assert plan.added_kwh == pytest.approx(3.0)
    new = {r.start: r.new_sum for r in plan.rows}
    assert [new[h(i)] - new[h(i - 1)] for i in range(4, 12)] == pytest.approx([1.0] * 8)
    assert all(r.in_gap for r in plan.rows if h(3) <= r.start < h(6))
    assert not any(r.in_gap for r in plan.rows if r.start >= h(6))
    assert {r.start: r.state for r in plan.rows}[h(8)] == TARGET_SUM[h(8)]


def test_repair_rejects_implausible_reference():
    ref = {k: v + (500 if k >= h(4) else 0) for k, v in REF.items()}
    target = {k: EnergyRow(v, v) for k, v in TARGET_SUM.items()}
    gaps = detect_energy_gaps(ref, TARGET_SUM)
    with pytest.raises(ValueError):
        plan_energy_repair(ref, target, gaps, max_hour_kwh=30)


def test_repair_needs_anchor():
    target = {h(i): EnergyRow(1.0, 1.0) for i in range(3, 6)}
    gaps = detect_energy_gaps(REF, {h(2): 5.0})
    with pytest.raises(ValueError):
        plan_energy_repair(REF, target, gaps)


def test_no_gaps_no_plan():
    plan = plan_energy_repair(REF, {}, [])
    assert plan.rows == [] and plan.added_kwh == 0


def test_power_gap_bezug_and_einspeisung():
    ref = {h(i): PowerRow(500.0, 400.0, 600.0) for i in range(4)}
    ref[h(2)] = PowerRow(-800.0, -900.0, -700.0)
    target = {
        h(0): PowerRow(500.0),
        h(1): PowerRow(500.0),
        h(2): PowerRow(0.0),
        h(3): PowerRow(500.0),
    }
    assert detect_power_gaps(ref, target, "bezug") == []
    gaps = detect_power_gaps(ref, {}, "einspeisung")
    assert [(g.start, g.end) for g in gaps] == [(h(2), h(3))]
    rows = plan_power_repair(ref, {}, gaps, "einspeisung")
    assert rows[0].new.mean == 800.0 and rows[0].new.min == 700.0 and rows[0].new.max == 900.0
