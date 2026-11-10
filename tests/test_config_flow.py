from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.strom_assistent.const import DOMAIN

USER = {
    "bezug_energie": "sensor.a",
    "einspeise_energie": "sensor.b",
    "leistung": "sensor.p",
}


async def test_user_flow_creates_entry(hass: HomeAssistant, recorder_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.strom_assistent.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER


async def test_same_entity_rejected(hass: HomeAssistant, recorder_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER, "einspeise_energie": "sensor.a"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "gleiche_entitaet"}
