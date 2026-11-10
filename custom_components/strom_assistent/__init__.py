"""Strom-Assistent: Tarif/Kosten, Lastprofil/Anomalie, Statistik-Lücken."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    RICHTUNG_BEZUG,
    RICHTUNG_EINSPEISUNG,
    SERVICE_LUECKE_PRUEFEN,
    SERVICE_LUECKE_REPARIEREN,
)
from .coordinator import Coordinators, StromConfigEntry
from .luecken import async_check, default_richtung, gaps_as_dicts, write_repair

PLATFORMS = ["sensor", "binary_sensor"]

_RICHTUNG = vol.In([RICHTUNG_BEZUG, RICHTUNG_EINSPEISUNG])
_BASE = {
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("start"): cv.datetime,
    vol.Required("ende"): cv.datetime,
    vol.Optional("richtung"): _RICHTUNG,
}
PRUEFEN_SCHEMA = vol.Schema(_BASE)
REPARIEREN_SCHEMA = vol.Schema(
    {
        **_BASE,
        vol.Optional("dry_run", default=True): cv.boolean,
        vol.Optional("max_kwh", default=100.0): vol.All(vol.Coerce(float), vol.Range(min=0)),
    }
)


def _entry(hass: HomeAssistant) -> ConfigEntry:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("Strom-Assistent ist nicht eingerichtet")
    return entries[0]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Dienste einmalig registrieren."""

    async def _run(call: ServiceCall, *, repair: bool) -> dict[str, Any]:
        entry = _entry(hass)
        entity_id = call.data["entity_id"]
        richtung = call.data.get("richtung") or default_richtung(entry, entity_id)
        start, end = _aware(call.data["start"]), _aware(call.data["ende"])
        if end <= start:
            raise ServiceValidationError("'ende' muss nach 'start' liegen")
        result = await async_check(hass, entry, entity_id, start, end, richtung)
        response: dict[str, Any] = {
            "entity_id": entity_id,
            "referenz": result.reference,
            "art": result.art,
            "richtung": richtung,
            "luecken": gaps_as_dicts(result.gaps),
            "fehlende_kwh": round(result.missing_kwh, 3),
        }
        if repair:
            dry_run = call.data["dry_run"]
            response |= {
                "dry_run": dry_run,
                "geschrieben": False,
                "vorschau": result.plan_rows,
                "nachfolgende_zeilen_verschoben": result.shifted_rows,
            }
            if not dry_run:
                write_repair(hass, result, max_kwh=call.data["max_kwh"])
                response["geschrieben"] = bool(result.gaps)
                await entry.runtime_data.luecken.async_request_refresh()
        return response

    async def pruefen(call: ServiceCall) -> dict[str, Any]:
        return await _run(call, repair=False)

    async def reparieren(call: ServiceCall) -> dict[str, Any]:
        return await _run(call, repair=True)

    hass.services.async_register(
        DOMAIN,
        SERVICE_LUECKE_PRUEFEN,
        pruefen,
        schema=PRUEFEN_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LUECKE_REPARIEREN,
        reparieren,
        schema=REPARIEREN_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: StromConfigEntry) -> bool:
    coordinators = Coordinators(hass, entry)
    entry.runtime_data = coordinators
    for coordinator in coordinators.all:
        await coordinator.async_config_entry_first_refresh()
    if coordinators.geraete:
        entry.async_on_unload(coordinators.geraete.async_start())
    entry.async_on_unload(entry.add_update_listener(_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: StromConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
