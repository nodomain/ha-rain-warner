"""Config flow for Rain Warner integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_DATA_SOURCE,
    CONF_NOWCAST_ENGINE,
    CONF_RADIUS,
    DATA_SOURCE_AUTO,
    DATA_SOURCE_BRIGHT_SKY,
    DATA_SOURCE_DWD,
    DATA_SOURCE_OPEN_METEO,
    DOMAIN,
    NOWCAST_ENGINE_PYSTEPS,
    NOWCAST_ENGINE_SIMPLE,
)

_LOGGER = logging.getLogger(__name__)


class RainWarnerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rain Warner."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow so users can switch engine / source later.

        We deliberately don't pass `config_entry` to the constructor:
        modern Home Assistant (2024.11+) injects `self.config_entry` on
        the flow handler itself, and `OptionsFlow.__init__` is just
        `object.__init__` which raises `TypeError` if any positional
        argument is supplied. Passing it here was the cause of the 500
        when the user clicked the Configure cog.
        """
        return RainWarnerOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Use provided coordinates or fall back to HA home location
            latitude = user_input.get(CONF_LATITUDE) or self.hass.config.latitude
            longitude = user_input.get(CONF_LONGITUDE) or self.hass.config.longitude

            if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                errors["base"] = "invalid_coordinates"
            else:
                # Check if coordinates are within DWD coverage
                data_source = user_input.get(CONF_DATA_SOURCE, DATA_SOURCE_AUTO)

                await self.async_set_unique_id(f"{latitude:.4f}_{longitude:.4f}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "Rain Warner"),
                    data={
                        CONF_LATITUDE: latitude,
                        CONF_LONGITUDE: longitude,
                        CONF_DATA_SOURCE: data_source,
                        CONF_RADIUS: user_input.get(CONF_RADIUS, 5),
                        CONF_NOWCAST_ENGINE: user_input.get(
                            CONF_NOWCAST_ENGINE, NOWCAST_ENGINE_SIMPLE
                        ),
                    },
                )

        # Pre-fill with home coordinates
        suggested_lat = self.hass.config.latitude
        suggested_lon = self.hass.config.longitude

        data_schema = vol.Schema(
            {
                vol.Optional(CONF_NAME, default="Rain Warner"): str,
                vol.Optional(CONF_LATITUDE, default=suggested_lat): vol.Coerce(float),
                vol.Optional(CONF_LONGITUDE, default=suggested_lon): vol.Coerce(float),
                vol.Optional(CONF_DATA_SOURCE, default=DATA_SOURCE_AUTO): vol.In(
                    {
                        DATA_SOURCE_AUTO: "Auto (DWD in Germany, Open-Meteo elsewhere)",
                        DATA_SOURCE_DWD: "DWD Radar (Germany, highest precision)",
                        DATA_SOURCE_BRIGHT_SKY: "Bright Sky API (Germany, easy JSON)",
                        DATA_SOURCE_OPEN_METEO: "Open-Meteo (global, no API key)",
                    }
                ),
                vol.Optional(CONF_RADIUS, default=5): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=50)
                ),
                vol.Optional(CONF_NOWCAST_ENGINE, default=NOWCAST_ENGINE_SIMPLE): vol.In(
                    {
                        NOWCAST_ENGINE_SIMPLE: "Simple (stdlib, no extra deps) — default",
                        NOWCAST_ENGINE_PYSTEPS: "pysteps (advanced, requires `pip install pysteps`)",
                    }
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


class RainWarnerOptionsFlow(OptionsFlow):
    """Allow editing data source / engine / radius without re-creating the entry.

    We persist the changes back into `config_entry.data` (not `.options`)
    because the existing setup code reads everything from `.data`. After
    a successful submit Home Assistant reloads the entry, which picks up
    the new engine and triggers the on-demand pysteps install if needed.

    Note: HA's framework injects `self.config_entry` automatically since
    2024.11 — we deliberately don't define an `__init__` because writing
    to `self.config_entry` ourselves now raises in modern HA versions.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the same options the user picked at setup time."""
        if user_input is not None:
            new_data = {**self.config_entry.data, **user_input}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_DATA_SOURCE,
                    default=current.get(CONF_DATA_SOURCE, DATA_SOURCE_AUTO),
                ): vol.In(
                    {
                        DATA_SOURCE_AUTO: "Auto (DWD in Germany, Open-Meteo elsewhere)",
                        DATA_SOURCE_DWD: "DWD Radar (Germany, highest precision)",
                        DATA_SOURCE_BRIGHT_SKY: "Bright Sky API (Germany, easy JSON)",
                        DATA_SOURCE_OPEN_METEO: "Open-Meteo (global, no API key)",
                    }
                ),
                vol.Optional(CONF_RADIUS, default=current.get(CONF_RADIUS, 5)): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=50)
                ),
                vol.Optional(
                    CONF_NOWCAST_ENGINE,
                    default=current.get(CONF_NOWCAST_ENGINE, NOWCAST_ENGINE_SIMPLE),
                ): vol.In(
                    {
                        NOWCAST_ENGINE_SIMPLE: "Simple (stdlib, no extra deps) — default",
                        NOWCAST_ENGINE_PYSTEPS: "pysteps (advanced, auto-installs on first use)",
                    }
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
