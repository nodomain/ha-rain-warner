"""Config flow for Rain Warner integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DATA_SOURCE,
    CONF_RADIUS,
    DATA_SOURCE_AUTO,
    DATA_SOURCE_BRIGHT_SKY,
    DATA_SOURCE_DWD,
    DATA_SOURCE_OPEN_METEO,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class RainWarnerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rain Warner."""

    VERSION = 1

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
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )
