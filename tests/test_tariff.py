from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.strom_assistent.logic.tariff import (
    daily_costs,
    forecast,
    parse_tarife,
    tarif_at,
)

TZ = ZoneInfo("Europe/Berlin")
TARIFE = parse_tarife(
    [
        {
            "gueltig_ab": "2026-01-01",
            "grundpreis": 10,
            "arbeitspreis": 0.30,
            "einspeiseverguetung": 0.08,
        },
        {
            "gueltig_ab": "2026-06-01",
            "grundpreis": 12,
            "arbeitspreis": 0.40,
            "einspeiseverguetung": 0.10,
        },
    ]
)


def test_tarif_at_historical():
    assert tarif_at(TARIFE, date(2025, 12, 31)) is None
    assert tarif_at(TARIFE, date(2026, 5, 31)).arbeitspreis == 0.30
    assert tarif_at(TARIFE, date(2026, 6, 1)).arbeitspreis == 0.40


def test_costs_use_price_valid_on_that_day():
    may = datetime(2026, 5, 31, 10, tzinfo=UTC)
    june = datetime(2026, 6, 1, 10, tzinfo=UTC)
    days = [date(2026, 5, 31), date(2026, 6, 1)]
    res = daily_costs({may: 10, june: 10}, {june: 5}, TARIFE, TZ, days)
    assert res[days[0]].bezug_eur == pytest.approx(3.0)
    assert res[days[1]].bezug_eur == pytest.approx(4.0)
    assert res[days[1]].feed_eur == pytest.approx(0.5)
    assert res[days[0]].grund_eur == pytest.approx(10 / 31)
    assert res[days[1]].grund_eur == pytest.approx(12 / 30)


def test_days_without_tariff_are_missing_not_zero():
    assert daily_costs({}, {}, TARIFE, TZ, [date(2025, 1, 1)]) == {}


def test_dynamic_price_overrides():
    hour = datetime(2026, 7, 1, 10, tzinfo=UTC)
    res = daily_costs({hour: 2}, {}, TARIFE, TZ, [date(2026, 7, 1)], {hour: 0.10})
    assert res[date(2026, 7, 1)].bezug_eur == pytest.approx(0.2)


def test_local_day_boundary():
    # 23:00 UTC am 30.6. ist in Berlin (UTC+2) bereits der 1.7.
    hour = datetime(2026, 6, 30, 23, tzinfo=UTC)
    res = daily_costs({hour: 1}, {}, TARIFE, TZ, [date(2026, 6, 30), date(2026, 7, 1)])
    assert res[date(2026, 7, 1)].bezug_kwh == 1
    assert res[date(2026, 6, 30)].bezug_kwh == 0


def test_forecast():
    assert forecast(10, [], 5, 1, 2) is None
    assert forecast(10, [2.0, 4.0], 5, 1, 2) == pytest.approx(10 + 3 * 5 + 2)
