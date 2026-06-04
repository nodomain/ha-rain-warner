"""Sensor platform for Rain Warner."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPrecipitationDepth, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RainWarnerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Rain Warner sensors."""
    coordinator: RainWarnerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        RainWarnerPrecipitationSensor(coordinator, entry),
        RainWarnerIntensitySensor(coordinator, entry),
        RainWarnerRainStartSensor(coordinator, entry),
        RainWarnerRainEndSensor(coordinator, entry),
        RainWarnerMaxPrecipHourSensor(coordinator, entry),
        RainWarnerMaxPrecip2hSensor(coordinator, entry),
        RainWarnerTotalHourSensor(coordinator, entry),
        RainWarnerTotal2hSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class RainWarnerBaseSensor(CoordinatorEntity[RainWarnerCoordinator], SensorEntity):
    """Base class for Rain Warner sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RainWarnerCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "DWD / Bright Sky",
            "model": "Rain Radar",
            "entry_type": "service",
        }


class RainWarnerPrecipitationSensor(RainWarnerBaseSensor):
    """Current precipitation rate sensor."""

    _attr_native_unit_of_measurement = "mm/h"
    _attr_device_class = SensorDeviceClass.PRECIPITATION_INTENSITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:weather-rainy"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, "current_precipitation", "Current precipitation")

    @property
    def native_value(self) -> float | None:
        """Return current precipitation rate."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("current_precipitation", 0.0)


class RainWarnerIntensitySensor(RainWarnerBaseSensor):
    """Precipitation intensity classification sensor."""

    _attr_icon = "mdi:weather-pouring"

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, "precipitation_intensity", "Precipitation intensity")

    @property
    def native_value(self) -> str | None:
        """Return precipitation intensity class."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("precipitation_intensity", "none")

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        if self.coordinator.data is None:
            return {}
        return {
            "data_source": self.coordinator.data.get("data_source"),
            "last_radar_update": self.coordinator.data.get("last_updated"),
        }


class RainWarnerRainStartSensor(RainWarnerBaseSensor):
    """Minutes until rain starts sensor."""

    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, "rain_start_minutes", "Rain starts in")

    @property
    def native_value(self) -> int | None:
        """Return minutes until rain starts."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("rain_start_minutes")


class RainWarnerRainEndSensor(RainWarnerBaseSensor):
    """Minutes until rain ends sensor."""

    _attr_icon = "mdi:clock-end"

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, "rain_end_minutes", "Rain ends in")

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit only when showing numeric value."""
        if self.coordinator.data is None:
            return "min"
        value = self.coordinator.data.get("rain_end_minutes")
        if value == -1:
            # Check if we have an extrapolation
            extrap = self.coordinator.data.get("rain_end_extrapolated")
            if extrap and extrap >= 360:
                return None  # no unit for ">6h"
            return "min"
        return "min"

    @property
    def native_value(self) -> int | str | None:
        """Return minutes until rain ends.

        Uses extrapolation when rain doesn't end within the 2h forecast window.
        """
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get("rain_end_minutes")
        if value == -1:
            # Use extrapolated estimate if available
            extrap = self.coordinator.data.get("rain_end_extrapolated")
            if extrap is not None:
                if extrap >= 360:
                    return ">6h"
                return extrap
            return ">120"
        return value

    @property
    def extra_state_attributes(self) -> dict:
        """Return extrapolation metadata."""
        if self.coordinator.data is None:
            return {}
        extrap = self.coordinator.data.get("rain_end_extrapolated")
        if extrap is not None:
            return {"extrapolated": True, "confidence": "low" if extrap > 240 else "medium"}
        return {}


class RainWarnerMaxPrecipHourSensor(RainWarnerBaseSensor):
    """Maximum precipitation in next hour sensor."""

    _attr_native_unit_of_measurement = "mm/h"
    _attr_device_class = SensorDeviceClass.PRECIPITATION_INTENSITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:weather-pouring"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            coordinator, entry, "max_precipitation_next_hour", "Max precipitation (1h)"
        )

    @property
    def native_value(self) -> float | None:
        """Return max precipitation rate in next hour."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("max_precipitation_next_hour", 0.0)


class RainWarnerMaxPrecip2hSensor(RainWarnerBaseSensor):
    """Maximum precipitation in next 2 hours sensor."""

    _attr_native_unit_of_measurement = "mm/h"
    _attr_device_class = SensorDeviceClass.PRECIPITATION_INTENSITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:weather-pouring"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator, entry, "max_precipitation_next_2h", "Max precipitation (2h)")

    @property
    def native_value(self) -> float | None:
        """Return max precipitation rate in next 2 hours."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("max_precipitation_next_2h", 0.0)


class RainWarnerTotalHourSensor(RainWarnerBaseSensor):
    """Total precipitation in next hour sensor."""

    _attr_native_unit_of_measurement = "mm"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cup-water"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            coordinator, entry, "total_precipitation_next_hour", "Total precipitation (1h)"
        )

    @property
    def native_value(self) -> float | None:
        """Return total accumulated precipitation in next hour."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("total_precipitation_next_hour", 0.0)


class RainWarnerTotal2hSensor(RainWarnerBaseSensor):
    """Total precipitation in next 2 hours sensor."""

    _attr_native_unit_of_measurement = "mm"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cup-water"
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            coordinator, entry, "total_precipitation_next_2h", "Total precipitation (2h)"
        )

    @property
    def native_value(self) -> float | None:
        """Return total accumulated precipitation in next 2 hours."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("total_precipitation_next_2h", 0.0)
