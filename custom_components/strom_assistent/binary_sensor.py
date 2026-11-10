"""Binary Sensor "Anomalie"."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import LastprofilCoordinator, StromConfigEntry
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StromConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([AnomalieSensor(entry.runtime_data.lastprofil, entry)])


class AnomalieSensor(CoordinatorEntity[LastprofilCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "anomalie"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: LastprofilCoordinator, entry: StromConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_anomalie"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        return super().available and "anomalie" in (self.coordinator.data or {})

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get("anomalie")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"gruende": (self.coordinator.data or {}).get("gruende", [])}
