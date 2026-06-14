"""Data update coordinator for Rain Warner."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alerts import (
    is_extended_dry_spell,
    is_rain_imminent,
    is_severe_weather,
    is_winter_weather,
)
from .bright_sky import BrightSkyClient
from .const import (
    CONF_DATA_SOURCE,
    CONF_NOWCAST_ENGINE,
    CONF_RADIUS,
    DATA_SOURCE_AUTO,
    DATA_SOURCE_BRIGHT_SKY,
    DATA_SOURCE_DWD,
    DATA_SOURCE_OPEN_METEO,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    NOWCAST_ENGINE_SIMPLE,
    PRECIP_THRESHOLD_HEAVY,
    PRECIP_THRESHOLD_LIGHT,
    PRECIP_THRESHOLD_MODERATE,
    PRECIP_THRESHOLD_VIOLENT,
)
from .dwd_radar import DWDRadarClient, RadolanFrame
from .open_meteo import OpenMeteoClient, is_in_dwd_coverage
from .precip_type import classify as classify_precip_type
from .stats import RainStatistics
from .temperature import TemperatureProvider

_LOGGER = logging.getLogger(__name__)

_STATS_STORAGE_VERSION = 1
_STATS_STORAGE_KEY_TEMPLATE = f"{DOMAIN}_stats_" + "{entry_id}"


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
        self.nowcast_engine = entry.data.get(CONF_NOWCAST_ENGINE, NOWCAST_ENGINE_SIMPLE)
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
            self._client = DWDRadarClient(
                hass,
                self.latitude,
                self.longitude,
                self.radius,
                nowcast_engine=self.nowcast_engine,
            )
        elif self.data_source == DATA_SOURCE_OPEN_METEO:
            self._client = OpenMeteoClient(hass, self.latitude, self.longitude)
        else:
            self._client = BrightSkyClient(hass, self.latitude, self.longitude)

        # The DWD/Bright Sky payloads don't include air temperature, but we
        # need it for precipitation-type classification. Use a cached
        # Open-Meteo lookup for those backends; Open-Meteo backend gets
        # the temperature inline.
        self._temperature_provider: TemperatureProvider | None = None
        if self.data_source != DATA_SOURCE_OPEN_METEO:
            self._temperature_provider = TemperatureProvider(hass, self.latitude, self.longitude)

        # Last parsed radar frames for the camera entity to render.
        self._last_frames: list[RadolanFrame] = []

        # Persistent rain statistics (today/yesterday/dry streak/history).
        self._stats_store: Store = Store(
            hass,
            _STATS_STORAGE_VERSION,
            _STATS_STORAGE_KEY_TEMPLATE.format(entry_id=entry.entry_id),
        )
        self._stats: RainStatistics = RainStatistics()
        self._stats_loaded = False

        # Exponential moving average of the motion vector across updates.
        # Raw TREC vectors are the instantaneous trend and jitter between
        # 5-min updates; COTREC/MTREC-style continuity smoothing stabilizes
        # the displayed direction. Stored as (dr_per_min, dc_per_min).
        self._motion_ema: tuple[float, float] | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the radar source."""
        if not self._stats_loaded:
            stored = await self._stats_store.async_load()
            self._stats = RainStatistics.from_dict(stored if isinstance(stored, dict) else None)
            self._stats_loaded = True

        try:
            data = await self._client.async_get_data()
        except Exception as err:
            raise UpdateFailed(f"Error fetching rain radar data: {err}") from err

        # Store frames for the camera entity (DWD backend only).
        if hasattr(self._client, "last_frames"):
            self._last_frames = self._client.last_frames or []

        # Enrich with air temperature when the backend doesn't provide one.
        if data.get("temperature_c") is None and self._temperature_provider is not None:
            data["temperature_c"] = await self._temperature_provider.async_get()

        # Fold this observation into the persistent statistics.
        now = datetime.now(timezone.utc)
        self._stats.update(now, float(data.get("current_precipitation", 0.0) or 0.0))
        await self._stats_store.async_save(self._stats.to_dict())

        return self._process_data(data)

    @property
    def last_frames(self) -> list[RadolanFrame]:
        """Return the last set of parsed radar frames for image rendering."""
        return self._last_frames

    @property
    def grid_row(self) -> int:
        """Return the grid row of the user's location."""
        if hasattr(self._client, "_grid_row"):
            return self._client._grid_row
        return 0

    @property
    def grid_col(self) -> int:
        """Return the grid column of the user's location."""
        if hasattr(self._client, "_grid_col"):
            return self._client._grid_col
        return 0

    @property
    def radius_cells(self) -> int:
        """Return the monitoring radius in grid cells."""
        if hasattr(self._client, "_radius_cells"):
            return self._client._radius_cells
        return 5

    def _process_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Process raw radar data into structured forecast."""
        forecast = raw_data.get("forecast", {})
        forecast_extended = raw_data.get("forecast_extended", forecast)
        current = raw_data.get("current_precipitation", 0.0)
        motion = self._smooth_motion(raw_data.get("motion"))
        max_2h = self._max_precip(forecast, 120)
        max_6h = self._max_precip(forecast_extended, 360)
        temperature_c = raw_data.get("temperature_c")
        rain_start_minutes = self._find_rain_start(forecast, current)
        rain_end_minutes = self._find_rain_end(forecast, current)
        rain_end_extrapolated = raw_data.get("rain_end_extrapolated")
        intensity = self._classify_intensity(current)
        precip_type = classify_precip_type(current, temperature_c, max_2h)
        is_raining = current > 0.0

        # Convert relative minutes into absolute timestamps so users see
        # "rain ends at 18:42" instead of having to add minutes in their
        # head. None when the answer is not knowable from the forecast.
        now = datetime.now(timezone.utc)
        rain_starts_at = (
            (now + timedelta(minutes=rain_start_minutes)).isoformat()
            if rain_start_minutes is not None
            else None
        )
        rain_ends_at = self._compute_rain_ends_at(now, rain_end_minutes, rain_end_extrapolated)
        dry_streak_hours = self._stats.dry_streak_hours()

        # Derived alert flags. Each flips a binary sensor users wire into
        # walldisplay notifications, automations and push messages.
        rain_imminent = is_rain_imminent(is_raining, rain_start_minutes)
        severe_weather = is_severe_weather(intensity, max_2h, precip_type)
        winter_weather = is_winter_weather(precip_type)
        extended_dry_spell = is_extended_dry_spell(dry_streak_hours, max_6h)

        return {
            "current_precipitation": current,
            "is_raining": is_raining,
            "precipitation_intensity": intensity,
            "precipitation_type": precip_type,
            "forecast": forecast,
            "forecast_extended": forecast_extended,
            "rain_start_minutes": rain_start_minutes,
            "rain_end_minutes": rain_end_minutes,
            "rain_starts_at": rain_starts_at,
            "rain_ends_at": rain_ends_at,
            "rain_end_extrapolated": rain_end_extrapolated,
            "max_precipitation_next_hour": self._max_precip(forecast, 60),
            "max_precipitation_next_2h": max_2h,
            "max_precipitation_next_6h": max_6h,
            "total_precipitation_next_hour": raw_data.get("total_next_hour", 0.0),
            "total_precipitation_next_2h": raw_data.get("total_next_2h", 0.0),
            "temperature_c": temperature_c,
            "motion": motion,
            "precipitation_today_mm": self._stats.precipitation_today_mm,
            "precipitation_yesterday_mm": self._stats.precipitation_yesterday_mm,
            "dry_streak_hours": dry_streak_hours,
            "last_rain_at": self._stats.last_rain_at_iso,
            "daily_history": list(self._stats.history),
            "rain_imminent": rain_imminent,
            "severe_weather": severe_weather,
            "winter_weather": winter_weather,
            "extended_dry_spell": extended_dry_spell,
            "last_updated": raw_data.get("timestamp"),
            "data_source": self.data_source,
        }

    # Smoothing factor for the motion EMA. 0.4 = 40 % weight on the newest
    # vector, so the arrow tracks genuine direction changes within ~3
    # updates (~15 min) while rejecting single-update jitter.
    _MOTION_EMA_ALPHA = 0.4

    def _smooth_motion(self, motion: dict[str, Any] | None) -> dict[str, Any] | None:
        """Temporally smooth the raw motion vector with an EMA.

        Raw TREC vectors jitter from update to update. We blend the new
        per-minute vector components with the running average and recompute
        speed/direction from the smoothed components. When the new estimate
        is missing (too dry to track) we drop the EMA so a stale arrow does
        not linger once the rain has gone.
        """
        if not motion:
            self._motion_ema = None
            return None

        dr = motion.get("dr_per_min")
        dc = motion.get("dc_per_min")
        if dr is None or dc is None:
            self._motion_ema = None
            return motion

        if self._motion_ema is None:
            smoothed_dr, smoothed_dc = dr, dc
        else:
            prev_dr, prev_dc = self._motion_ema
            a = self._MOTION_EMA_ALPHA
            smoothed_dr = a * dr + (1.0 - a) * prev_dr
            smoothed_dc = a * dc + (1.0 - a) * prev_dc

        self._motion_ema = (smoothed_dr, smoothed_dc)

        speed_cells_per_min = (smoothed_dr**2 + smoothed_dc**2) ** 0.5
        return {
            "dr_per_min": smoothed_dr,
            "dc_per_min": smoothed_dc,
            "speed_kmh": speed_cells_per_min * 1.1 * 60.0,
        }

    @staticmethod
    def _compute_rain_ends_at(
        now: datetime,
        rain_end_minutes: int | None,
        rain_end_extrapolated: int | None,
    ) -> str | None:
        """Convert the various rain-end signals into an absolute ISO timestamp.

        Returns None when the rain end is not knowable (e.g. dry forecast,
        or rain extends past the 6 h extrapolation cap).
        """
        if rain_end_minutes is None:
            return None
        if rain_end_minutes >= 0:
            return (now + timedelta(minutes=rain_end_minutes)).isoformat()
        # rain_end_minutes == -1 → rain doesn't end inside the 2 h window.
        if rain_end_extrapolated is None or rain_end_extrapolated >= 360:
            return None
        return (now + timedelta(minutes=rain_end_extrapolated)).isoformat()

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
    def _find_rain_start(
        forecast: dict[int, float], current_precipitation: float = 0.0
    ) -> int | None:
        """Find minutes until rain starts.

        Returns None when:
            - It's already raining (start time is now / in the past, so the
              question doesn't make sense)
            - No rain anywhere in the forecast window
        """
        if current_precipitation > 0.0:
            return None
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
