"""Open-Meteo client for Rain Warner.

Provides global precipitation nowcasting outside the DWD coverage area.
Open-Meteo is free, requires no API key, and exposes 15-minute precipitation
forecasts world-wide. We resample its 15-min cadence to the same 5-min
buckets that the DWD client returns so downstream code can stay agnostic.

API reference: https://open-meteo.com/en/docs

Why this fulfills the "RainViewer fallback" roadmap item:
RainViewer itself only serves rendered map tiles (PNG/WebP), not numeric
precipitation values, so it can't drive sensors. Open-Meteo is the
practical equivalent that gives us a world-wide numeric backend, while
the RainViewer map tiles continue to power the visual dashboard layer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_HORIZON_MINUTES = 360  # Match the optical-flow extension horizon


class OpenMeteoClient:
    """Client for Open-Meteo precipitation nowcasting (global coverage)."""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
    ) -> None:
        """Initialize the Open-Meteo client."""
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._session = async_get_clientsession(hass)

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch current and forecast precipitation."""
        params = {
            "latitude": str(self._latitude),
            "longitude": str(self._longitude),
            "minutely_15": "precipitation",
            "current": "precipitation,temperature_2m",
            "forecast_days": "2",
            "past_days": "0",
            "timezone": "UTC",
        }

        try:
            async with self._session.get(
                OPEN_METEO_BASE_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning("Open-Meteo request failed: HTTP %d", resp.status)
                    return self._empty_response()
                data = await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error contacting Open-Meteo: %s", err)
            return self._empty_response()

        return self._parse(data)

    @staticmethod
    def _empty_response() -> dict[str, Any]:
        return {
            "current_precipitation": 0.0,
            "forecast": {},
            "forecast_extended": {},
            "total_next_hour": 0.0,
            "total_next_2h": 0.0,
            "temperature_c": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _parse_iso(ts: str) -> datetime | None:
        """Parse an ISO timestamp returned by Open-Meteo (always UTC here)."""
        try:
            return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _parse(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Open-Meteo response into the coordinator's data shape."""
        current_block = data.get("current") or {}
        current_precip = float(current_block.get("precipitation") or 0.0)
        # Open-Meteo reports precipitation in mm (per hour) for the
        # current bucket — already mm/h.
        temperature = current_block.get("temperature_2m")

        minutely = data.get("minutely_15") or {}
        times = minutely.get("time") or []
        precips = minutely.get("precipitation") or []

        now = datetime.now(timezone.utc)

        # Build a forecast dict at 5-min cadence by linearly distributing
        # 15-min precipitation totals across the three 5-min buckets.
        forecast: dict[int, float] = {}
        forecast_extended: dict[int, float] = {}

        for ts_str, mm_per_15min in zip(times, precips):
            if mm_per_15min is None:
                continue
            ts = self._parse_iso(ts_str)
            if ts is None:
                continue
            delta_min = (ts - now).total_seconds() / 60.0
            if delta_min < -7.5:  # Skip clearly past buckets
                continue
            if delta_min > FORECAST_HORIZON_MINUTES:
                break

            mm_per_15 = float(mm_per_15min)
            mm_per_h = mm_per_15 * 4.0  # Convert to mm/h for consistency

            # Distribute into 3 x 5-min buckets centered on the 15-min slot
            base_min = int(round(delta_min / 5.0) * 5)
            for offset in (0, 5, 10):
                bucket = base_min + offset
                if bucket <= 0:
                    continue
                if bucket > FORECAST_HORIZON_MINUTES:
                    continue
                if bucket <= 120:
                    forecast[bucket] = round(mm_per_h, 2)
                forecast_extended[bucket] = round(mm_per_h, 2)

        # Aggregate totals — sum mm contributions over the 5-min buckets
        # (each value is mm/h, so multiply by 5/60 to get mm in that slot).
        total_next_hour = sum(v for k, v in forecast.items() if k <= 60) * (5 / 60)
        total_next_2h = sum(v for k, v in forecast.items() if k <= 120) * (5 / 60)

        return {
            "current_precipitation": round(current_precip, 2),
            "forecast": forecast,
            "forecast_extended": forecast_extended,
            "total_next_hour": round(total_next_hour, 2),
            "total_next_2h": round(total_next_2h, 2),
            "temperature_c": float(temperature) if temperature is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def is_in_dwd_coverage(latitude: float, longitude: float) -> bool:
    """Return True if the location is roughly within the DE1200 DWD radar grid.

    The DE1200 grid covers Germany plus ~150 km of border regions. Outside
    of this box we should fall back to Open-Meteo automatically.
    """
    return 45.0 <= latitude <= 56.0 and 4.0 <= longitude <= 17.0
