"""Diagnose für Strom-Assistent."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import StromConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: StromConfigEntry
) -> dict[str, Any]:
    coordinators = entry.runtime_data
    return {
        "data": dict(entry.data),
        "options": dict(entry.options),
        "coordinators": {
            c.name: {"last_update_success": c.last_update_success, "data": c.data}
            for c in coordinators.all
        },
    }
