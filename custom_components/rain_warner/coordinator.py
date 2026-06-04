"""Data update coordinator for Rain Warner."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .bright_sky import BrightSkyClient
from .const import (
    CONF_DATA_SOURCE,
    CONF_RADIUS,
    DATA_SOURCE_AUTO,
    DATA_SOURCE_BRIGHT_SKY,
    DATA_SOURCE_DWD,
    DATA_SOURCE_OPEN_METEO,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PRECIP_THRESHOLD_HEAVY,
    PRECIP_THRESHOLD_LIGHT,
    PRECIP_THRESHOLD_MODERATE,
    PRECIP_THRESHOLD_VIOLENT,
)
from .dwd_radar import DWDRadarClient
from .open_meteo import OpenMeteoClient, is_in_dwd_coverage

_LOGGER = logging.getLogger(__name__)


class RainWarnerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate data updates from rain radar sources."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_UPDATE_INTERVAL),
        )
        self.latitude = entry.data[CONF_LATITUDE]
        self.longitude = entry.data[CONF_LONGITUDE]
        self.radius = entry.data.get(CONF_RADIUS, 5)
        configured_source = entry.data.get(CONF_DATA_SOURCE, DATA_SOURCE_DWD)

        # Resolve auto-mode based on geographic coverage.
        if configured_source == DATA_SOURCE_AUTO:
            if is_in_dwd_coverage(self.latitude, self.longitude):
                self.data_source = DATA_SOURCE_DWD
            else:
                self.data_source = DATA_SOURCE_OPEN_METEO
            _LOGGER.info(
                "Auto data source resolved to %s for (%.4f, %.4f)",
                self.data_source,
                self.latitude,
                self.longitude,
            )
        else:
            self.data_source = configured_source

        if self.data_source == DATA_SOURCE_DWD:
            self._client = DWDRadarClient(hass, self.latitude, self.longitude, self.radius)
        elif self.data_source == DATA_SOURCE_OPEN_METEO:
            self._client = OpenMeteoClient(hass, self.latitude, self.longitude)
        else:
            self._client = BrightSkyClient(hass, self.latitude, self.longitude)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the radar source."""
        try:
            data = await self._client.async_get_data()
        except Exception as err:
            raise UpdateFailed(f"Error fetching rain radar data: {err}") from err

        return self._process_data(data)

    def _process_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Process raw radar data into structured forecast."""
        forecast = raw_data.get("forecast", {})
        forecast_extended = raw_data.get("forecast_extended", forecast)
        return {
            "current_precipitation": raw_data.get("current_precipitation", 0.0),
            "is_raining": raw_data.get("current_precipitation", 0.0) > 0.0,
            "precipitation_intensity": self._classify_intensity(
                raw_data.get("current_precipitation", 0.0)
            ),
            "forecast": forecast,
            "forecast_extended": forecast_extended,
            "rain_start_minutes": self._find_rain_start(forecast),
            "rain_end_minutes": self._find_rain_end(
                forecast,
                raw_data.get("current_precipitation", 0.0),
            ),
            "rain_end_extrapolated": raw_data.get("rain_end_extrapolated"),
            "max_precipitation_next_hour": self._max_precip(forecast, 60),
            "max_precipitation_next_2h": self._max_precip(forecast, 120),
            "total_precipitation_next_hour": raw_data.get("total_next_hour", 0.0),
            "total_precipitation_next_2h": raw_data.get("total_next_2h", 0.0),
            "temperature_c": raw_data.get("temperature_c"),
            "motion": raw_data.get("motion"),
            "last_updated": raw_data.get("timestamp"),
            "data_source": self.data_source,
        }

    @staticmethod
    def _classify_intensity(precip_mm_h: float) -> str:
        """Classify precipitation intensity."""
        if precip_mm_h <= 0.0:
            return "none"
        elif precip_mm_h < PRECIP_THRESHOLD_MODERATE:
            return "light"
        elif precip_mm_h < PRECIP_THRESHOLD_HEAVY:
            return "moderate"
        elif precip_mm_h < PRECIP_THRESHOLD_VIOLENT:
            return "heavy"
        else:
            return "violent"

    @staticmethod
    def _find_rain_start(forecast: dict[int, float]) -> int | None:
        """Find minutes until rain starts (None if not raining in forecast window)."""
        for minutes in sorted(forecast.keys()):
            if forecast[minutes] > 0.0:
                return minutes
        return None

    @staticmethod
    def _find_rain_end(forecast: dict[int, float], current_precipitation: float) -> int | None:
        """Find minutes until rain ends.

        Returns:
            - Minutes until rain stops (if rain ends within forecast window)
            - -1 if it's raining but doesn't stop within the forecast window
            - None if it's not raining at all (now or in forecast)
        """
        raining = current_precipitation > 0.0
        for minutes in sorted(forecast.keys()):
            if forecast[minutes] > 0.0:
                raining = True
            elif raining:
                return minutes
        # If it's raining but never stops in the forecast window
        if raining:
            return -1
        return None

    @staticmethod
    def _max_precip(forecast: dict[int, float], window_minutes: int) -> float:
        """Find maximum precipitation rate within time window."""
        return max(
            (v for k, v in forecast.items() if k <= window_minutes),
            default=0.0,
        )
