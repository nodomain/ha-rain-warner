"""Rain Warner - High-precision rain radar integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.requirements import RequirementsNotFound, async_process_requirements

from .const import CONF_NOWCAST_ENGINE, DOMAIN, NOWCAST_ENGINE_PYSTEPS, OPT_PYSTEPS_INSTALL_FAILED
from .coordinator import RainWarnerCoordinator
from .wms_proxy import async_register_proxy

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CAMERA]

# Heavy optional dependency installed on-demand only when the user picks
# the pysteps engine. Pinning the lower bound avoids surprise breakage
# from API renames; we don't pin upper because pysteps is conservative.
_PYSTEPS_REQUIREMENTS = ["pysteps>=1.7"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Rain Warner from a config entry."""
    if entry.data.get(CONF_NOWCAST_ENGINE) == NOWCAST_ENGINE_PYSTEPS:
        if entry.options.get(OPT_PYSTEPS_INSTALL_FAILED):
            # A previous attempt already failed on this system (typically
            # Python 3.14 + Alpine HA OS where pysteps has no wheels and
            # /tmp is noexec so source builds fail too). Retrying every
            # boot wastes ~30 s and spams the log; the user has to re-submit
            # the Configure dialog to ask us to try again.
            _LOGGER.info(
                "Skipping pysteps install — a previous attempt failed on "
                "this system. Using the simple nowcast engine. Re-submit "
                "the Configure dialog (Settings → Devices & Services → "
                "Rain Warner → Configure) to retry."
            )
        else:
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
                _mark_pysteps_failed(hass, entry)
            except Exception as err:  # noqa: BLE001 — install errors take many shapes
                _LOGGER.warning(
                    "Unexpected error while installing pysteps (%s) — falling back "
                    "to the simple engine.",
                    err,
                )
                _mark_pysteps_failed(hass, entry)

    coordinator = RainWarnerCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Register WMS proxy (once per HA instance)
    if not hass.data[DOMAIN].get("_proxy_registered"):
        async_register_proxy(hass)
        hass.data[DOMAIN]["_proxy_registered"] = True

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


def _mark_pysteps_failed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Persist the install failure into entry.options.

    We use options (not data) because the OptionsFlow already owns options
    and clears this key on submit, while data is what the user sees as
    'their config'. Updating options doesn't trigger an entry reload, so
    this is safe to call from setup.
    """
    new_options = {**entry.options, OPT_PYSTEPS_INSTALL_FAILED: True}
    hass.config_entries.async_update_entry(entry, options=new_options)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
