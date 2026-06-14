"""XYZ tile server for RADOLAN radar data.

Serves radar data as standard map tiles (/api/rain_warner/tile/{z}/{x}/{y}.png)
that Leaflet can consume directly. Each tile request renders the relevant
portion of the RADOLAN grid on-the-fly. Same-origin, no CORS issues.
"""

from __future__ import annotations

import io
import logging
import math

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .dwd_radar import RadolanFrame, latlon_to_grid

_LOGGER = logging.getLogger(__name__)

TILE_SIZE = 256

# Precipitation color ramp (mm/h → RGBA)
_COLOR_RAMP = [
    (0.1, (100, 149, 237, 160)),
    (0.5, (65, 105, 225, 180)),
    (1.0, (30, 144, 255, 200)),
    (2.5, (0, 200, 83, 210)),
    (5.0, (255, 235, 59, 220)),
    (7.5, (255, 152, 0, 230)),
    (10.0, (244, 67, 54, 235)),
    (25.0, (213, 0, 0, 240)),
    (50.0, (156, 39, 176, 245)),
]


def _precip_color(mm_h: float) -> tuple[int, int, int, int] | None:
    if mm_h < 0.1:
        return None
    for threshold, color in _COLOR_RAMP:
        if mm_h <= threshold:
            return color
    return _COLOR_RAMP[-1][1]


def _tile_to_latlon(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Convert tile coords to lat/lon bounding box (south, west, north, east)."""
    n = 2**z
    lon_w = x / n * 360.0 - 180.0
    lon_e = (x + 1) / n * 360.0 - 180.0
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lat_s, lon_w, lat_n, lon_e


class RadarTileView(HomeAssistantView):
    """Serve RADOLAN radar data as XYZ map tiles."""

    url = "/api/rain_warner/tile/{z}/{x}/{y}"
    extra_urls = ["/api/rain_warner/tile/{z}/{x}/{y}.png"]
    name = "api:rain_warner:tile"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def get(self, request: web.Request, z: str, x: str, y: str) -> web.Response:
        """Render a radar tile."""
        _LOGGER.debug("Tile request: z=%s x=%s y=%s", z, x, y)
        # Strip .png suffix if present
        y = y.replace(".png", "")
        try:
            zi, xi, yi = int(z), int(x), int(y)
        except ValueError:
            return web.Response(status=400)

        # Get the current radar frame from any active coordinator
        frame = self._get_current_frame()
        if frame is None:
            # Return empty transparent tile
            return web.Response(
                body=_empty_tile(),
                content_type="image/png",
                headers={"Cache-Control": "public, max-age=60"},
            )

        # Render the tile in executor (CPU-bound)
        png_bytes = await self._hass.async_add_executor_job(_render_tile, frame, zi, xi, yi)

        return web.Response(
            body=png_bytes,
            content_type="image/png",
            headers={"Cache-Control": "public, max-age=300"},
        )

    def _get_current_frame(self) -> RadolanFrame | None:
        """Get the latest t+0 frame from any active coordinator."""
        domain_data = self._hass.data.get(DOMAIN, {})
        for key, value in domain_data.items():
            if key.startswith("_"):
                continue
            coordinator = value
            if hasattr(coordinator, "last_frames") and coordinator.last_frames:
                frames = coordinator.last_frames
                # Return t+0 frame
                for f in frames:
                    if f.forecast_minutes == 0:
                        return f
                return frames[0]
        return None


def _render_tile(frame: RadolanFrame, z: int, x: int, y: int) -> bytes:
    """Render a single 256×256 radar tile."""
    from PIL import Image

    lat_s, lon_w, lat_n, lon_e = _tile_to_latlon(z, x, y)

    # Convert tile corners to grid coordinates
    row_s, col_w = latlon_to_grid(lat_s, lon_w)
    row_n, col_e = latlon_to_grid(lat_n, lon_e)

    # Grid range this tile covers
    row_min = min(row_s, row_n)
    row_max = max(row_s, row_n)
    col_min = min(col_w, col_e)
    col_max = max(col_w, col_e)

    grid_h = row_max - row_min + 1
    grid_w = col_max - col_min + 1

    if grid_h <= 0 or grid_w <= 0:
        return _empty_tile()

    # Build RGBA pixel buffer
    pixels = bytearray(TILE_SIZE * TILE_SIZE * 4)

    for py in range(TILE_SIZE):
        # Map pixel Y to grid row (flip: top of tile = north = high row)
        grid_row = row_max - int(py * grid_h / TILE_SIZE)
        for px in range(TILE_SIZE):
            grid_col = col_min + int(px * grid_w / TILE_SIZE)

            precip = frame.get_precipitation(grid_row, grid_col)
            color = _precip_color(precip)
            if color is None:
                continue

            idx = (py * TILE_SIZE + px) * 4
            pixels[idx] = color[0]
            pixels[idx + 1] = color[1]
            pixels[idx + 2] = color[2]
            pixels[idx + 3] = color[3]

    img = Image.frombytes("RGBA", (TILE_SIZE, TILE_SIZE), bytes(pixels))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


_EMPTY_TILE_CACHE: bytes | None = None


def _empty_tile() -> bytes:
    """Return a cached empty transparent tile."""
    global _EMPTY_TILE_CACHE
    if _EMPTY_TILE_CACHE is None:
        from PIL import Image

        img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        _EMPTY_TILE_CACHE = buf.getvalue()
    return _EMPTY_TILE_CACHE


def async_register_tile_server(hass: HomeAssistant) -> None:
    """Register the tile server view."""
    hass.http.register_view(RadarTileView(hass))
