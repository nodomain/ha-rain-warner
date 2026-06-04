"""Binary sensor platform for Rain Warner."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
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
    """Set up Rain Warner binary sensors."""
    coordinator: RainWarnerCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [
        RainWarnerIsRainingSensor(coordinator, entry),
        RainWarnerRainExpectedSensor(coordinator, entry),
    ]

    async_add_entities(entities)


class RainWarnerIsRainingSensor(CoordinatorEntity[RainWarnerCoordinator], BinarySensorEntity):
    """Binary sensor indicating if it's currently raining."""

    _attr_has_entity_name = True
    _attr_name = "Raining"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_is_raining"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "DWD / Bright Sky",
            "model": "Rain Radar",
            "entry_type": "service",
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if it's currently raining."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("is_raining", False)

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        if self.coordinator.data is None:
            return {}
        return {
            "precipitation_mm_h": self.coordinator.data.get("current_precipitation", 0.0),
            "intensity": self.coordinator.data.get("precipitation_intensity", "none"),
        }


class RainWarnerRainExpectedSensor(CoordinatorEntity[RainWarnerCoordinator], BinarySensorEntity):
    """Binary sensor indicating if rain is expected in the next 2 hours."""

    _attr_has_entity_name = True
    _attr_name = "Rain expected"
    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_icon = "mdi:weather-partly-rainy"

    def __init__(self, coordinator: RainWarnerCoordinator, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_rain_expected"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "DWD / Bright Sky",
            "model": "Rain Radar",
            "entry_type": "service",
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if rain is expected in the forecast window."""
        if self.coordinator.data is None:
            return None
        forecast = self.coordinator.data.get("forecast", {})
        return any(v > 0.0 for v in forecast.values())

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes with forecast details."""
        if self.coordinator.data is None:
            return {}
        return {
            "rain_starts_in_minutes": self.coordinator.data.get("rain_start_minutes"),
            "max_precipitation_mm_h": self.coordinator.data.get("max_precipitation_next_2h", 0.0),
            "total_precipitation_mm": self.coordinator.data.get("total_precipitation_next_2h", 0.0),
            "forecast": self.coordinator.data.get("forecast", {}),
            "forecast_extended": self.coordinator.data.get("forecast_extended", {}),
        }
