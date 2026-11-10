"""Config Flow und Options Flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector as sel

from .const import (
    CONF_BEZUG_ENERGIE,
    CONF_EINSPEISE_ENERGIE,
    CONF_LEISTUNG,
    CONF_ZIEL_BEZUG_ENERGIE,
    CONF_ZIEL_BEZUG_LEISTUNG,
    CONF_ZIEL_EINSPEISE_ENERGIE,
    CONF_ZIEL_EINSPEISE_LEISTUNG,
    DEFAULT_GERAETE_DAUER_S,
    DEFAULT_GERAETE_SCHWELLE_W,
    DEFAULT_K,
    DEFAULT_LUECKE_TAGE,
    DEFAULT_MIN_ABWEICHUNG_W,
    DEFAULT_STUNDEN,
    DOMAIN,
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

_SENSOR = sel.EntitySelectorConfig(domain="sensor")


def _entity(required: bool, key: str, default: str | None = None) -> tuple[Any, Any]:
    marker = vol.Required if required else vol.Optional
    kwargs = {"description": {"suggested_value": default}} if default else {}
    return marker(key, **kwargs), sel.EntitySelector(_SENSOR)


def _number(
    minimum: float, maximum: float, step: float = 1, unit: str | None = None
) -> sel.NumberSelector:
    config = sel.NumberSelectorConfig(
        min=minimum, max=maximum, step=step, mode=sel.NumberSelectorMode.BOX
    )
    if unit:
        config["unit_of_measurement"] = unit
    return sel.NumberSelector(config)


class StromAssistentConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_BEZUG_ENERGIE] == user_input[CONF_EINSPEISE_ENERGIE]:
                errors["base"] = "gleiche_entitaet"
            else:
                return self.async_create_entry(title="Strom-Assistent", data=user_input)
        fields = [
            _entity(True, CONF_BEZUG_ENERGIE),
            _entity(True, CONF_EINSPEISE_ENERGIE),
            _entity(True, CONF_LEISTUNG),
            _entity(False, CONF_ZIEL_BEZUG_ENERGIE),
            _entity(False, CONF_ZIEL_EINSPEISE_ENERGIE),
            _entity(False, CONF_ZIEL_BEZUG_LEISTUNG),
            _entity(False, CONF_ZIEL_EINSPEISE_LEISTUNG),
        ]
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(dict(fields)), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return StromAssistentOptionsFlow()


class StromAssistentOptionsFlow(OptionsFlow):
    """Menü: Tarife, dynamischer Preis, Lastprofil, Geräte, Lücken."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "tarif_hinzufuegen",
                "tarif_entfernen",
                "preis_entitaet",
                "lastprofil",
                "geraete",
                "luecken",
            ],
        )

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(title="", data={**self.config_entry.options, **changes})

    async def async_step_tarif_hinzufuegen(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            tarife = [
                t
                for t in self.config_entry.options.get(OPT_TARIFE, [])
                if t["gueltig_ab"] != user_input["gueltig_ab"]
            ]
            tarife.append(user_input)
            tarife.sort(key=lambda t: t["gueltig_ab"])
            return self._save(**{OPT_TARIFE: tarife})
        schema = vol.Schema(
            {
                vol.Required("gueltig_ab"): sel.DateSelector(),
                vol.Required("grundpreis"): _number(0, 1000, 0.01, "EUR/Monat"),
                vol.Required("arbeitspreis"): _number(0, 10, 0.0001, "EUR/kWh"),
                vol.Required("einspeiseverguetung"): _number(0, 10, 0.0001, "EUR/kWh"),
            }
        )
        return self.async_show_form(step_id="tarif_hinzufuegen", data_schema=schema)

    async def async_step_tarif_entfernen(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        tarife = self.config_entry.options.get(OPT_TARIFE, [])
        if user_input is not None:
            drop = set(user_input.get("tarife", []))
            return self._save(**{OPT_TARIFE: [t for t in tarife if t["gueltig_ab"] not in drop]})
        options = [
            sel.SelectOptionDict(
                value=t["gueltig_ab"],
                label=f"{t['gueltig_ab']}: {t['arbeitspreis']} EUR/kWh, {t['grundpreis']} EUR/Monat",
            )
            for t in tarife
        ]
        schema = vol.Schema(
            {
                vol.Optional("tarife"): sel.SelectSelector(
                    sel.SelectSelectorConfig(options=options, multiple=True)
                )
            }
        )
        return self.async_show_form(step_id="tarif_entfernen", data_schema=schema)

    async def async_step_preis_entitaet(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {**self.config_entry.options}
            options.pop(OPT_PREIS_ENTITAET, None)
            options.update(user_input)
            return self.async_create_entry(title="", data=options)
        current = self.config_entry.options.get(OPT_PREIS_ENTITAET)
        key = vol.Optional(OPT_PREIS_ENTITAET, description={"suggested_value": current})
        return self.async_show_form(
            step_id="preis_entitaet", data_schema=vol.Schema({key: sel.EntitySelector(_SENSOR)})
        )

    async def async_step_lastprofil(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(**user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(OPT_K, default=o.get(OPT_K, DEFAULT_K)): _number(1, 10, 0.5),
                vol.Required(
                    OPT_STUNDEN, default=int(o.get(OPT_STUNDEN, DEFAULT_STUNDEN))
                ): _number(1, 24),
                vol.Required(
                    OPT_MIN_ABWEICHUNG_W,
                    default=o.get(OPT_MIN_ABWEICHUNG_W, DEFAULT_MIN_ABWEICHUNG_W),
                ): _number(0, 5000, 10, "W"),
            }
        )
        return self.async_show_form(step_id="lastprofil", data_schema=schema)

    async def async_step_geraete(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(**user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    OPT_GERAETE_AKTIV, default=o.get(OPT_GERAETE_AKTIV, False)
                ): sel.BooleanSelector(),
                vol.Required(
                    OPT_GERAETE_SCHWELLE_W,
                    default=o.get(OPT_GERAETE_SCHWELLE_W, DEFAULT_GERAETE_SCHWELLE_W),
                ): _number(10, 20000, 10, "W"),
                vol.Required(
                    OPT_GERAETE_DAUER_S, default=o.get(OPT_GERAETE_DAUER_S, DEFAULT_GERAETE_DAUER_S)
                ): _number(5, 3600, 5, "s"),
            }
        )
        return self.async_show_form(step_id="geraete", data_schema=schema)

    async def async_step_luecken(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save(**user_input)
        current = self.config_entry.options.get(OPT_LUECKE_TAGE, DEFAULT_LUECKE_TAGE)
        schema = vol.Schema(
            {vol.Required(OPT_LUECKE_TAGE, default=current): _number(1, 30, 1, "d")}
        )
        return self.async_show_form(step_id="luecken", data_schema=schema)
