"""Bright Sky API client for Rain Warner."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import BRIGHT_SKY_BASE_URL

_LOGGER = logging.getLogger(__name__)


class BrightSkyClient:
    """Client for Bright Sky API (DWD JSON wrapper)."""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
    ) -> None:
        """Initialize the Bright Sky client."""
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._session = async_get_clientsession(hass)

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch current weather and radar data from Bright Sky."""
        current = await self._fetch_current_weather()
        radar = await self._fetch_radar()

        return {
            "current_precipitation": current.get("precipitation_60", 0.0) or 0.0,
            "forecast": radar.get("forecast", {}),
            "total_next_hour": radar.get("total_next_hour", 0.0),
            "total_next_2h": radar.get("total_next_2h", 0.0),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _fetch_current_weather(self) -> dict[str, Any]:
        """Fetch current weather conditions."""
        url = f"{BRIGHT_SKY_BASE_URL}/current_weather"
        params = {
            "lat": str(self._latitude),
            "lon": str(self._longitude),
        }

        try:
            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    _LOGGER.warning("Bright Sky current weather failed: HTTP %d", response.status)
                    return {}

                data = await response.json()
                weather = data.get("weather", {})
                return weather

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error fetching Bright Sky weather: %s", err)
            return {}

    async def _fetch_radar(self) -> dict[str, Any]:
        """Fetch radar data from Bright Sky.

        The /radar endpoint provides precipitation values
        from the DWD radar composite for a specific location.
        """
        url = f"{BRIGHT_SKY_BASE_URL}/radar"
        params = {
            "lat": str(self._latitude),
            "lon": str(self._longitude),
        }

        try:
            async with self._session.get(url, params=params) as response:
                if response.status != 200:
                    _LOGGER.warning("Bright Sky radar failed: HTTP %d", response.status)
                    return {"forecast": {}, "total_next_hour": 0.0, "total_next_2h": 0.0}

                data = await response.json()
                return self._parse_radar_response(data)

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error fetching Bright Sky radar: %s", err)
            return {"forecast": {}, "total_next_hour": 0.0, "total_next_2h": 0.0}

    def _parse_radar_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Parse Bright Sky radar response into forecast dict."""
        forecast: dict[int, float] = {}
        radar_data = data.get("radar", [])

        for i, entry in enumerate(radar_data):
            minutes = (i + 1) * 5  # 5-min intervals
            precip = entry.get("precipitation_5", 0.0) or 0.0
            # Convert from mm/5min to mm/h
            forecast[minutes] = round(precip * 12, 2)

        total_next_hour = sum(
            entry.get("precipitation_5", 0.0) or 0.0
            for entry in radar_data[:12]  # First 12 entries = 60 min
        )
        total_next_2h = sum(
            entry.get("precipitation_5", 0.0) or 0.0
            for entry in radar_data[:24]  # First 24 entries = 120 min
        )

        return {
            "forecast": forecast,
            "total_next_hour": round(total_next_hour, 2),
            "total_next_2h": round(total_next_2h, 2),
        }
