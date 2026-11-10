"""Koordinatoren für Strom-Assistent (Tarif, Lastprofil, Lücken)."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BEZUG_ENERGIE,
    CONF_EINSPEISE_ENERGIE,
    CONF_LEISTUNG,
    DEFAULT_GERAETE_DAUER_S,
    DEFAULT_GERAETE_SCHWELLE_W,
    DEFAULT_K,
    DEFAULT_LUECKE_TAGE,
    DEFAULT_MIN_ABWEICHUNG_W,
    DEFAULT_STUNDEN,
    DOMAIN,
    EVENT_ANOMALIE,
    EVENT_GERAET,
    ISSUE_LUECKE,
    ISSUE_QUELLE,
    OPT_GERAETE_AKTIV,
    OPT_GERAETE_DAUER_S,
    OPT_GERAETE_SCHWELLE_W,
    OPT_K,
    OPT_LUECKE_TAGE,
    OPT_MIN_ABWEICHUNG_W,
    OPT_PREIS_ENTITAET,
    OPT_STUNDEN,
    OPT_TARIFE,
)
from .logic.baseline import (
    build_baseline,
    detect_anomaly,
    deviation_pct,
    night_baseload_anomaly,
    percentile,
)
from .logic.steps import StepDetector
from .logic.tariff import daily_costs, forecast, parse_tarife, tarif_at
from .luecken import async_check, configured_targets, gaps_as_dicts
from .stats import async_hourly, cumulative, floor_hour

_LOGGER = logging.getLogger(__name__)

type StromConfigEntry = ConfigEntry["Coordinators"]


def _float_state(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id or (state := hass.states.get(entity_id)) is None:
        return None
    if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        return float(state.state)
    except ValueError:
        return None


class _Base(DataUpdateCoordinator[dict[str, Any]]):
    """Gemeinsame Logik: Quellen prüfen und Repair-Issues pflegen."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        interval: timedelta,
    ) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=name, update_interval=interval)
        self._missing_count: dict[str, int] = {}

    def check_sources(self, entity_ids: list[str]) -> list[str]:
        """Nicht verfügbare Quellen melden. Issue erst ab der 2. Prüfung in Folge (Startup)."""
        missing: list[str] = []
        for entity_id in entity_ids:
            issue_id = f"{ISSUE_QUELLE}_{entity_id}"
            if _float_state(self.hass, entity_id) is None:
                missing.append(entity_id)
                self._missing_count[entity_id] = self._missing_count.get(entity_id, 0) + 1
                if self._missing_count[entity_id] >= 2:
                    ir.async_create_issue(
                        self.hass,
                        DOMAIN,
                        issue_id,
                        is_fixable=False,
                        severity=ir.IssueSeverity.ERROR,
                        translation_key=ISSUE_QUELLE,
                        translation_placeholders={"entity_id": entity_id},
                    )
            else:
                self._missing_count.pop(entity_id, None)
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        return missing


class TarifCoordinator(_Base):
    """Funktion A: Kosten, Erlöse, Hochrechnung."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "Tarif", timedelta(minutes=10))

    async def _async_update_data(self) -> dict[str, Any]:
        entry = self.config_entry
        bezug_id = entry.data[CONF_BEZUG_ENERGIE]
        feed_id = entry.data[CONF_EINSPEISE_ENERGIE]
        price_id = entry.options.get(OPT_PREIS_ENTITAET)
        watched = [bezug_id, feed_id] + ([price_id] if price_id else [])
        if self.check_sources(watched):
            return {}  # Sensoren -> unavailable, nie 0

        tarife = parse_tarife(entry.options.get(OPT_TARIFE, []))
        if not tarife:
            return {}
        tz = dt_util.DEFAULT_TIME_ZONE
        now = dt_util.now()
        today = now.date()
        year_start = dt_util.as_utc(datetime(today.year, 1, 1, tzinfo=tz)) - timedelta(hours=1)

        ids = {bezug_id, feed_id}
        data = await async_hourly(self.hass, ids, year_start, None, {"state", "sum"})
        price_by_hour: dict[datetime, float] = {}
        if price_id:
            pdata = await async_hourly(self.hass, {price_id}, year_start, None, {"mean"})
            price_by_hour = {
                dt_util.utc_from_timestamp(r["start"]): float(r["mean"])
                for r in pdata.get(price_id, [])
                if r.get("mean") is not None
            }

        cur_hour = floor_hour(dt_util.utcnow())
        bezug_h = self._hour_deltas(data.get(bezug_id, []), bezug_id, cur_hour)
        feed_h = self._hour_deltas(data.get(feed_id, []), feed_id, cur_hour)
        live_price = _float_state(self.hass, price_id) if price_id else None
        if live_price is not None:
            price_by_hour[cur_hour] = live_price

        days = [
            date(today.year, 1, 1) + timedelta(days=i)
            for i in range((today - date(today.year, 1, 1)).days + 1)
        ]
        costs = daily_costs(bezug_h, feed_h, tarife, tz, days, price_by_hour or None)
        if today not in costs:
            return {}

        def total(sel: list[date], attr: str) -> float:
            return sum(getattr(costs[d], attr) for d in sel if d in costs)

        month = [d for d in days if d.month == today.month]
        kosten = lambda sel: total(sel, "bezug_eur") + total(sel, "grund_eur")  # noqa: E731
        erloes_monat = total(month, "feed_eur")
        netto_monat = kosten(month) - erloes_monat
        netto_jahr = kosten(days) - total(days, "feed_eur")

        full_days = [d for d in days if d < today and d in costs][-14:]
        daily_var = [costs[d].bezug_eur - costs[d].feed_eur for d in full_days]
        tarif_today = tarif_at(tarife, today)
        base_day = costs[today].grund_eur
        month_end = _next_month_start(today, tz)
        year_end = datetime(today.year + 1, 1, 1, tzinfo=tz)

        def prognose(so_far: float, end: datetime) -> float | None:
            remaining = max((end - now).total_seconds() / 86400, 0.0)
            base_days = max((end.date() - today).days - 1, 0)
            value = forecast(so_far, daily_var, remaining, base_day, base_days)
            return None if value is None else round(value, 2)

        result: dict[str, Any] = {
            "kosten_heute": costs[today].bezug_eur + costs[today].grund_eur,
            "kosten_monat": kosten(month),
            "kosten_jahr": kosten(days),
            "erloes_monat": erloes_monat,
            "netto_kosten_monat": netto_monat,
            "prognose_monat": prognose(netto_monat, month_end),
            "prognose_jahr": prognose(netto_jahr, year_end),
            "preis_bezug": live_price
            if live_price is not None
            else (tarif_today.arbeitspreis if tarif_today else None),
            "preis_einspeisung": tarif_today.einspeiseverguetung if tarif_today else None,
        }
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in result.items()}

    def _hour_deltas(
        self, rows: list[dict[str, Any]], entity_id: str, cur_hour: datetime
    ) -> dict[datetime, float]:
        """Stündliche kWh-Deltas aus ``sum`` plus laufende (noch nicht kompilierte) Stunde."""
        cum = cumulative(rows)
        deltas = {
            h: v - cum[h - timedelta(hours=1)]
            for h, v in cum.items()
            if (h - timedelta(hours=1)) in cum
        }
        prev = [
            r
            for r in rows
            if dt_util.utc_from_timestamp(r["start"]) < cur_hour and r.get("state") is not None
        ]
        live = _float_state(self.hass, entity_id)
        if prev and live is not None and cur_hour not in deltas:
            deltas[cur_hour] = max(live - float(prev[-1]["state"]), 0.0)
        return deltas


def _next_month_start(today: date, tz: Any) -> datetime:
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return datetime(year, month, 1, tzinfo=tz)


class LastprofilCoordinator(_Base):
    """Funktion B: Baseline, Grundlast, Anomalie."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "Lastprofil", timedelta(minutes=15))
        self._anomaly_prev = False

    async def _async_update_data(self) -> dict[str, Any]:
        entry = self.config_entry
        power_id = entry.data[CONF_LEISTUNG]
        if self.check_sources([power_id]):
            return {}
        k = float(entry.options.get(OPT_K, DEFAULT_K))
        hours = int(entry.options.get(OPT_STUNDEN, DEFAULT_STUNDEN))
        floor = float(entry.options.get(OPT_MIN_ABWEICHUNG_W, DEFAULT_MIN_ABWEICHUNG_W))

        tz = dt_util.DEFAULT_TIME_ZONE
        now = dt_util.utcnow()
        cur_hour = floor_hour(now)
        data = await async_hourly(
            self.hass, {power_id}, cur_hour - timedelta(days=56), cur_hour, {"mean", "min"}
        )
        rows = [
            (dt_util.utc_from_timestamp(r["start"]).astimezone(tz), r)
            for r in data.get(power_id, [])
            if r.get("mean") is not None
        ]
        if len(rows) < 24:
            return {"grundlast": None, "abweichung": None, "anomalie": False}

        split = cur_hour.astimezone(tz) - timedelta(hours=hours)
        samples = [(t.weekday(), t.hour, float(r["mean"])) for t, r in rows if t < split]
        baseline = build_baseline(samples)
        recent = [(t.weekday(), t.hour, float(r["mean"])) for t, r in rows if t >= split]
        cons_anom = detect_anomaly(recent, baseline, k=k, hours=hours, floor=floor)

        deviation = None
        if recent:
            wd, hr, val = recent[-1]
            deviation = deviation_pct(val, baseline.get((wd, hr)))

        base_now, night_anom = self._night(rows, tz, k, floor)
        anomaly = cons_anom or night_anom
        reasons = [
            r
            for r, on in (
                ("verbrauch_ueber_baseline", cons_anom),
                ("nachtgrundlast_erhoeht", night_anom),
            )
            if on
        ]
        if anomaly and not self._anomaly_prev:
            self.hass.bus.async_fire(
                EVENT_ANOMALIE,
                {
                    "entity_id": power_id,
                    "gruende": reasons,
                    "abweichung_prozent": deviation,
                    "grundlast_w": base_now,
                },
            )
        self._anomaly_prev = anomaly
        return {
            "grundlast": None if base_now is None else round(base_now, 1),
            "abweichung": None if deviation is None else round(deviation, 1),
            "anomalie": anomaly,
            "gruende": reasons,
        }

    @staticmethod
    def _night(
        rows: list[tuple[datetime, dict[str, Any]]], tz: Any, k: float, floor: float
    ) -> tuple[float | None, bool]:
        """Grundlast der letzten Nacht (00-06 Uhr, 5-%-Perzentil der Stunden-Minima) + Vergleich."""
        per_night: dict[date, list[float]] = {}
        for t, r in rows:
            if t.hour < 6 and r.get("min") is not None:
                per_night.setdefault(t.date(), []).append(float(r["min"]))
        nights = {d: percentile(v, 5) for d, v in per_night.items() if len(v) >= 4}
        if not nights:
            return None, False
        last = max(nights)
        history = [v for d, v in nights.items() if d != last]
        return nights[last], night_baseload_anomaly(nights[last], history, k=k, floor=floor)


class GeraeteDetektor:
    """Zweite Stufe: Geräteerkennung über Leistungssprünge (Event, kein Sensor)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entity_id = entry.data[CONF_LEISTUNG]
        self.detector = StepDetector(
            float(entry.options.get(OPT_GERAETE_SCHWELLE_W, DEFAULT_GERAETE_SCHWELLE_W)),
            float(entry.options.get(OPT_GERAETE_DAUER_S, DEFAULT_GERAETE_DAUER_S)),
        )

    @callback
    def async_start(self) -> Any:
        return async_track_state_change_event(self.hass, [self.entity_id], self._changed)

    @callback
    def _changed(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None:
            return
        try:
            value = float(new.state)
        except ValueError:
            return
        step = self.detector.update(new.last_updated.timestamp(), value)
        if step is not None:
            self.hass.bus.async_fire(
                EVENT_GERAET,
                {
                    "entity_id": self.entity_id,
                    "delta_w": round(step.delta_w, 1),
                    "richtung": "an" if step.delta_w > 0 else "aus",
                    "leistung_vorher_w": round(step.before_w, 1),
                    "leistung_nachher_w": round(step.after_w, 1),
                    "zeitpunkt": dt_util.utc_from_timestamp(step.ts).isoformat(),
                },
            )


class LueckenCoordinator(_Base):
    """Funktion C: regelmäßige Lückenprüfung mit Repair-Issues."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, "Lücken", timedelta(hours=1))

    async def _async_update_data(self) -> dict[str, Any]:
        entry = self.config_entry
        days = int(entry.options.get(OPT_LUECKE_TAGE, DEFAULT_LUECKE_TAGE))
        end = floor_hour(dt_util.utcnow())
        start = end - timedelta(days=days)
        total = 0
        found: dict[str, list[dict[str, Any]]] = {}
        for entity_id, richtung in configured_targets(entry):
            issue_id = f"{ISSUE_LUECKE}_{entity_id}"
            try:
                result = await async_check(self.hass, entry, entity_id, start, end, richtung)
            except Exception as err:  # noqa: BLE001 - Prüfung darf Koordinator nicht beenden
                _LOGGER.debug("Lückenprüfung %s fehlgeschlagen: %s", entity_id, err)
                continue
            found[entity_id] = gaps_as_dicts(result.gaps)
            total += len(result.gaps)
            if result.gaps:
                first = result.gaps[0]
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_LUECKE,
                    translation_placeholders={
                        "entity_id": entity_id,
                        "start": dt_util.as_local(first.start).strftime("%d.%m.%Y %H:%M"),
                        "kwh": f"{result.missing_kwh:.2f}",
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        return {"luecken_anzahl": total, "details": found}


class Coordinators:
    """Container in ``entry.runtime_data``."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.tarif = TarifCoordinator(hass, entry)
        self.lastprofil = LastprofilCoordinator(hass, entry)
        self.luecken = LueckenCoordinator(hass, entry)
        self.geraete = (
            GeraeteDetektor(hass, entry) if entry.options.get(OPT_GERAETE_AKTIV) else None
        )

    @property
    def all(self) -> list[DataUpdateCoordinator[dict[str, Any]]]:
        return [self.tarif, self.lastprofil, self.luecken]
