"""Sensoren von Strom-Assistent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN
from .coordinator import StromConfigEntry


@dataclass(frozen=True, kw_only=True)
class StromSensorDescription(SensorEntityDescription):
    group: str  # tarif | lastprofil | luecken


def _money(key: str) -> StromSensorDescription:
    return StromSensorDescription(
        key=key,
        translation_key=key,
        group="tarif",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="EUR",
        suggested_display_precision=2,
    )


def _price(key: str) -> StromSensorDescription:
    return StromSensorDescription(
        key=key,
        translation_key=key,
        group="tarif",
        native_unit_of_measurement="EUR/kWh",
        suggested_display_precision=4,
    )


DESCRIPTIONS: tuple[StromSensorDescription, ...] = (
    _money("kosten_heute"),
    _money("kosten_monat"),
    _money("kosten_jahr"),
    _money("erloes_monat"),
    _money("netto_kosten_monat"),
    _money("prognose_monat"),
    _money("prognose_jahr"),
    _price("preis_bezug"),
    _price("preis_einspeisung"),
    StromSensorDescription(
        key="grundlast",
        translation_key="grundlast",
        group="lastprofil",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    StromSensorDescription(
        key="abweichung",
        translation_key="abweichung",
        group="lastprofil",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    StromSensorDescription(
        key="luecken_anzahl",
        translation_key="luecken_anzahl",
        group="luecken",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def device_info(entry: StromConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Strom-Assistent",
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: StromConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinators = {
        "tarif": entry.runtime_data.tarif,
        "lastprofil": entry.runtime_data.lastprofil,
        "luecken": entry.runtime_data.luecken,
    }
    async_add_entities(StromSensor(coordinators[d.group], entry, d) for d in DESCRIPTIONS)


class StromSensor(CoordinatorEntity[DataUpdateCoordinator[dict[str, Any]]], SensorEntity):
    _attr_has_entity_name = True
    entity_description: StromSensorDescription

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[dict[str, Any]],
        entry: StromConfigEntry,
        description: StromSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> Any:
        return (self.coordinator.data or {}).get(self.entity_description.key)

    @property
    def available(self) -> bool:
        # Fehlende Quelle/Daten -> unavailable, niemals 0.
        return super().available and self.native_value is not None
