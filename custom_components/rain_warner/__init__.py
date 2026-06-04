"""Rain Warner - High-precision rain radar integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from .const import CONF_NOWCAST_ENGINE, DOMAIN, NOWCAST_ENGINE_PYSTEPS
from .coordinator import RainWarnerCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

# Heavy optional dependency installed on-demand only when the user picks
# the pysteps engine. Pinning the lower bound avoids surprise breakage
# from API renames; we don't pin upper because pysteps is conservative.
_PYSTEPS_REQUIREMENTS = ["pysteps>=1.7"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rain Warner from a config entry."""
    if entry.data.get(CONF_NOWCAST_ENGINE) == NOWCAST_ENGINE_PYSTEPS:
        try:
            await async_process_requirements(hass, f"{DOMAIN}.pysteps", _PYSTEPS_REQUIREMENTS)
            _LOGGER.info("pysteps requirements satisfied")
        except RequirementsNotFound as err:
            _LOGGER.warning(
                "Could not install pysteps (%s) — the integration will fall back "
                "to the simple nowcast engine. On HA OS this usually means a "
                "missing wheel for your architecture; see the README for manual "
                "install options.",
                err,
            )
        except Exception as err:  # noqa: BLE001 — install errors take many shapes
            _LOGGER.warning(
                "Unexpected error while installing pysteps (%s) — falling back "
                "to the simple engine.",
                err,
            )

    coordinator = RainWarnerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
