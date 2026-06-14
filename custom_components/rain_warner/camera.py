"""Rain radar camera entity for Rain Warner.

Provides a native HA camera entity showing the local rain radar image.
Uses render functions from radar_render.py (no HA deps, testable standalone).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RainWarnerCoordinator
from .radar_render import CROP_RADIUS, IMG_SIZE, render_empty_png, render_radar_png

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Rain Warner camera."""
    coordinator: RainWarnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RainWarnerRadarCamera(coordinator, entry)])


class RainWarnerRadarCamera(CoordinatorEntity[RainWarnerCoordinator], Camera):
    """Camera entity showing local rain radar image."""

    _attr_has_entity_name = True
    _attr_translation_key = "radar_image"
    _attr_icon = "mdi:radar"

    def __init__(
        self,
        coordinator: RainWarnerCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the radar camera."""
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._attr_unique_id = f"{entry.entry_id}_radar_image"

    @property
    def frame_interval(self) -> float:
        """Return the polling interval for the camera image."""
        return 300.0

    @property
    def is_on(self) -> bool:
        """Return whether the camera is active."""
        return self.coordinator.last_update_success

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the current radar image as PNG bytes."""
        frames = self.coordinator.last_frames
        if not frames:
            return render_empty_png()

        # Render the current observation (t+0) frame
        current_frame = frames[0] if frames[0].forecast_minutes == 0 else None
        if current_frame is None:
            current_frame = frames[0]

        # Get motion data from coordinator
        motion = None
        if self.coordinator.data:
            motion = self.coordinator.data.get("motion")

        return await self.hass.async_add_executor_job(
            render_radar_png,
            current_frame,
            self.coordinator.grid_row,
            self.coordinator.grid_col,
            self.coordinator.radius_cells,
            self.coordinator.latitude,
            self.coordinator.longitude,
            motion,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        frames = self.coordinator.last_frames
        attrs: dict[str, Any] = {
            "crop_size_km": round(CROP_RADIUS * 2 * 1.1, 1),
            "resolution_km": 1.1,
            "image_size_px": IMG_SIZE,
            "latitude": self.coordinator.latitude,
            "longitude": self.coordinator.longitude,
        }
        if frames:
            attrs["frame_timestamp"] = frames[0].timestamp
            attrs["available_frames"] = len(frames)

        # Motion data for the interactive map arrow
        if self.coordinator.data:
            motion = self.coordinator.data.get("motion")
            if motion:
                attrs["motion_dr_per_min"] = motion.get("dr_per_min", 0)
                attrs["motion_dc_per_min"] = motion.get("dc_per_min", 0)
                attrs["motion_speed_kmh"] = motion.get("speed_kmh", 0)
        return attrs
