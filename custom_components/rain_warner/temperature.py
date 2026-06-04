"""Air temperature provider for precipitation type classification.

The DWD radar feed and Bright Sky's /radar endpoint don't include air
temperature, but we need it to distinguish rain from sleet/snow. This
helper fetches the current temperature from Open-Meteo (free, no API
key) and caches it for a configurable TTL so we don't spam the API on
every 5-min coordinator update.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_TEMP_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TTL = timedelta(minutes=30)


class TemperatureProvider:
    """Fetches and caches current air temperature for a location."""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        ttl: timedelta = DEFAULT_TTL,
    ) -> None:
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._ttl = ttl
        self._session = async_get_clientsession(hass)
        self._cached_value: float | None = None
        self._cached_at: datetime | None = None

    async def async_get(self) -> float | None:
        """Return cached temperature or fetch a fresh one when stale."""
        now = datetime.now(timezone.utc)
        if (
            self._cached_at is not None
            and self._cached_value is not None
            and (now - self._cached_at) < self._ttl
        ):
            return self._cached_value

        params = {
            "latitude": str(self._latitude),
            "longitude": str(self._longitude),
            "current": "temperature_2m",
            "timezone": "UTC",
        }

        try:
            async with self._session.get(
                _TEMP_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Temperature fetch failed: HTTP %d", resp.status)
                    return self._cached_value
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Temperature fetch error: %s", err)
            return self._cached_value

        temp = (data.get("current") or {}).get("temperature_2m")
        if temp is None:
            return self._cached_value
        self._cached_value = float(temp)
        self._cached_at = now
        return self._cached_value
