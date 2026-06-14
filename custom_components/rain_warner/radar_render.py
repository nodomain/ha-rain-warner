"""Radar image rendering logic (no Home Assistant dependencies).

Renders RADOLAN grid data as a PNG with:
  - OpenStreetMap tile background
  - Semi-transparent precipitation overlay
  - Motion direction arrow
  - Location crosshair and monitoring radius ring

Separated from camera.py so it can be tested without HA mocks.
"""

from __future__ import annotations

import io
import logging
import math
from typing import TYPE_CHECKING
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from .dwd_radar import RadolanFrame

_LOGGER = logging.getLogger(__name__)

# Image rendering constants
CROP_RADIUS = 120  # cells in each direction → 240×240 grid ≈ 264×264 km
CELL_PX = 4  # pixels per grid cell
IMG_SIZE = CROP_RADIUS * 2 * CELL_PX  # 960×960 px
RESOLUTION_KM = 1.1  # km per grid cell

# Precipitation color ramp (mm/h thresholds → RGBA)
# Classic meteorological radar colors: blue → green → yellow → red → magenta
COLOR_RAMP: list[tuple[float, tuple[int, int, int, int]]] = [
    (0.1, (100, 149, 237, 140)),  # light blue — drizzle
    (0.5, (65, 105, 225, 160)),  # royal blue
    (1.0, (30, 144, 255, 180)),  # dodger blue
    (2.5, (0, 200, 83, 190)),  # green
    (5.0, (255, 235, 59, 200)),  # yellow
    (7.5, (255, 152, 0, 210)),  # orange
    (10.0, (244, 67, 54, 220)),  # red
    (25.0, (213, 0, 0, 230)),  # dark red
    (50.0, (156, 39, 176, 240)),  # purple — extreme
]

BG_COLOR = (200, 200, 210)  # light gray fallback if map tiles fail
CENTER_COLOR = (30, 30, 30, 255)  # dark crosshair
RING_COLOR = (60, 60, 80, 160)  # subtle ring for monitoring radius
ARROW_COLOR = (50, 50, 70, 220)  # dark arrow for motion direction

# OSM tile fetching
_OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_OSM_USER_AGENT = "RainWarnerHA/1.0 (Home Assistant integration)"
_TILE_SIZE = 256
_TILE_CACHE: dict[tuple[int, int, int], bytes] = {}


def precip_to_color(mm_h: float) -> tuple[int, int, int, int] | None:
    """Map precipitation rate to an RGBA color. Returns None for no rain."""
    if mm_h < 0.1:
        return None
    for threshold, color in COLOR_RAMP:
        if mm_h <= threshold:
            return color
    return COLOR_RAMP[-1][1]


# --- Map tile helpers ---


def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int, float, float]:
    """Convert lat/lon to tile coordinates and pixel offset within that tile."""
    n = 2**zoom
    x_tile_f = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y_tile_f = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    x_tile = int(x_tile_f)
    y_tile = int(y_tile_f)
    # Pixel offset within tile
    px_offset = (x_tile_f - x_tile) * _TILE_SIZE
    py_offset = (y_tile_f - y_tile) * _TILE_SIZE
    return x_tile, y_tile, px_offset, py_offset


def _fetch_tile(z: int, x: int, y: int) -> bytes | None:
    """Fetch a single OSM tile, with basic caching."""
    key = (z, x, y)
    if key in _TILE_CACHE:
        return _TILE_CACHE[key]

    url = _OSM_TILE_URL.format(z=z, x=x, y=y)
    try:
        req = Request(url, headers={"User-Agent": _OSM_USER_AGENT})
        with urlopen(req, timeout=5) as resp:
            data = resp.read()
        # Keep cache bounded
        if len(_TILE_CACHE) > 100:
            _TILE_CACHE.clear()
        _TILE_CACHE[key] = data
        return data
    except Exception as err:
        _LOGGER.debug("Failed to fetch OSM tile %s: %s", url, err)
        return None


def _render_map_background(lat: float, lon: float, img_size: int) -> "Image":
    """Render an OSM map background centered on lat/lon covering our image area."""
    from PIL import Image

    # Choose zoom level: at zoom 9, each tile covers ~0.7° ≈ ~78 km
    # Our image covers ~176 km, so zoom 8-9 is good
    zoom = 8

    # Calculate center tile and pixel offset
    center_tx, center_ty, cx_offset, cy_offset = _lat_lon_to_tile(lat, lon, zoom)

    # How many tiles we need to cover img_size pixels
    # At this zoom, we need to figure out the scale: pixels per degree
    n = 2**zoom
    # Total world width in pixels at this zoom
    world_px = n * _TILE_SIZE

    # Meters per pixel at this latitude
    meters_per_px = (40075016.686 * math.cos(math.radians(lat))) / world_px
    # Our image covers CROP_RADIUS*2 * RESOLUTION_KM * 1000 meters
    coverage_m = CROP_RADIUS * 2 * RESOLUTION_KM * 1000
    # How many map pixels does that correspond to?
    map_px_needed = coverage_m / meters_per_px

    # Scale factor from map pixels to our image pixels
    scale = img_size / map_px_needed

    # We need to render enough tiles to fill our image
    # In map-pixel space, center is at (center_tx * 256 + cx_offset, center_ty * 256 + cy_offset)
    center_map_x = center_tx * _TILE_SIZE + cx_offset
    center_map_y = center_ty * _TILE_SIZE + cy_offset

    # Map pixel bounds we need
    half_map_px = map_px_needed / 2
    map_x0 = center_map_x - half_map_px
    map_y0 = center_map_y - half_map_px
    map_x1 = center_map_x + half_map_px
    map_y1 = center_map_y + half_map_px

    # Which tiles do we need?
    tile_x0 = int(map_x0 // _TILE_SIZE)
    tile_y0 = int(map_y0 // _TILE_SIZE)
    tile_x1 = int(map_x1 // _TILE_SIZE) + 1
    tile_y1 = int(map_y1 // _TILE_SIZE) + 1

    # Assemble map canvas in map-pixel space
    canvas_w = int(map_x1 - map_x0)
    canvas_h = int(map_y1 - map_y0)
    canvas = Image.new("RGB", (canvas_w, canvas_h), BG_COLOR[:3])

    for ty in range(tile_y0, tile_y1 + 1):
        for tx in range(tile_x0, tile_x1 + 1):
            tile_data = _fetch_tile(zoom, tx, ty)
            if tile_data is None:
                continue
            try:
                tile_img = Image.open(io.BytesIO(tile_data)).convert("RGB")
            except Exception:
                continue
            # Position this tile on the canvas
            paste_x = int(tx * _TILE_SIZE - map_x0)
            paste_y = int(ty * _TILE_SIZE - map_y0)
            canvas.paste(tile_img, (paste_x, paste_y))

    # Resize to our target image size
    result = canvas.resize((img_size, img_size), Image.LANCZOS)
    return result


def render_radar_png(
    frame: "RadolanFrame",
    center_row: int,
    center_col: int,
    radius_cells: int,
    latitude: float = 0.0,
    longitude: float = 0.0,
    motion: dict | None = None,
) -> bytes:
    """Render a RADOLAN frame as a transparent PNG overlay.

    The image has a transparent background with only precipitation pixels
    colored. Designed to be overlaid on an interactive map (Leaflet).

    Args:
        frame: The RADOLAN frame with grid data.
        center_row: Grid row of the user's location.
        center_col: Grid column of the user's location.
        radius_cells: Monitoring radius in grid cells (for the ring overlay).
        latitude: User's latitude (for map background — unused in transparent mode).
        longitude: User's longitude (unused in transparent mode).
        motion: Motion dict with dr_per_min, dc_per_min, speed_kmh.

    Returns:
        PNG image bytes (960×960 px, RGBA with transparent background).
    """
    from PIL import Image, ImageDraw

    # Transparent RGBA image — only precipitation pixels will be visible
    img = Image.new("RGBA", (IMG_SIZE, IMG_SIZE), (0, 0, 0, 0))

    for dy in range(-CROP_RADIUS, CROP_RADIUS):
        grid_row = center_row + dy
        img_row = CROP_RADIUS - 1 - dy
        for dx in range(-CROP_RADIUS, CROP_RADIUS):
            grid_col = center_col + dx
            precip = frame.get_precipitation(grid_row, grid_col)
            color = precip_to_color(precip)
            if color is None:
                continue

            img_col = dx + CROP_RADIUS
            px_x = img_col * CELL_PX
            px_y = img_row * CELL_PX
            for py in range(px_y, px_y + CELL_PX):
                for px in range(px_x, px_x + CELL_PX):
                    if 0 <= px < IMG_SIZE and 0 <= py < IMG_SIZE:
                        img.putpixel((px, py), color)

    draw = ImageDraw.Draw(img)
    cx, cy = IMG_SIZE // 2, IMG_SIZE // 2

    # Draw monitoring radius ring
    ring_px = radius_cells * CELL_PX
    draw.ellipse(
        [cx - ring_px, cy - ring_px, cx + ring_px, cy + ring_px],
        outline=RING_COLOR,
        width=2,
    )

    # Draw center crosshair
    cross_size = 8
    draw.line([(cx - cross_size, cy), (cx + cross_size, cy)], fill=CENTER_COLOR, width=2)
    draw.line([(cx, cy - cross_size), (cx, cy + cross_size)], fill=CENTER_COLOR, width=2)
    draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=CENTER_COLOR)

    # Draw motion arrow
    if motion and motion.get("speed_kmh", 0) > 2.0:
        _draw_motion_arrow(draw, cx, cy, motion)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_motion_arrow(
    draw: "ImageDraw.Draw",
    cx: int,
    cy: int,
    motion: dict,
) -> None:
    """Draw a motion trajectory like the 'Regen' app.

    Style: A line extending FROM the user's location OUTWARD in the direction
    the rain is moving, with tick marks showing hourly positions and an
    arrowhead at the tip. This shows "rain is heading this way".
    """
    dr_per_min = motion.get("dr_per_min", 0.0)
    dc_per_min = motion.get("dc_per_min", 0.0)
    speed_kmh = motion.get("speed_kmh", 0.0)

    if speed_kmh < 2.0:
        return

    # Motion vector in image space:
    # dr > 0 = rain moves north (row increases) → image -Y
    # dc > 0 = rain moves east (col increases) → image +X
    # We draw where rain is COMING FROM: reverse the motion vector.
    # The line extends from center toward where rain originates.
    dx_img = -dc_per_min  # reverse east motion → source is west
    dy_img = -dr_per_min  # in image: north source = up = -Y when dr < 0 (south motion)

    # Normalize
    length = math.sqrt(dx_img**2 + dy_img**2)
    if length < 1e-6:
        return
    dx_norm = dx_img / length
    dy_norm = dy_img / length

    # Arrow length: show ~3h trajectory scaled to image
    # speed_kmh → km per 3h → pixels (1 cell = CELL_PX px = 1.1 km)
    trajectory_km = speed_kmh * 3.0  # 3 hours
    trajectory_px = min(IMG_SIZE * 0.4, trajectory_km / RESOLUTION_KM * CELL_PX)
    trajectory_px = max(80, trajectory_px)

    # Line from center outward (showing where rain came from)
    end_x = cx + dx_norm * trajectory_px
    end_y = cy + dy_norm * trajectory_px

    # Draw main trajectory line
    draw.line(
        [(cx, cy), (int(end_x), int(end_y))],
        fill=ARROW_COLOR,
        width=3,
    )

    # Draw arrowhead at center (pointing AT user = direction rain arrives from)
    head_len = 14
    # Arrow points toward center from the line
    arr_angle = math.atan2(-dy_norm, -dx_norm)  # toward center
    left_a = arr_angle + math.radians(25)
    right_a = arr_angle - math.radians(25)
    arr_base_x = cx + dx_norm * 25
    arr_base_y = cy + dy_norm * 25
    head_left = (arr_base_x + head_len * math.cos(left_a), arr_base_y + head_len * math.sin(left_a))
    head_right = (
        arr_base_x + head_len * math.cos(right_a),
        arr_base_y + head_len * math.sin(right_a),
    )
    draw.polygon(
        [
            (cx, cy),
            (int(head_left[0]), int(head_left[1])),
            (int(head_right[0]), int(head_right[1])),
        ],
        fill=ARROW_COLOR,
    )

    # Draw hourly tick marks along the trajectory
    from datetime import datetime, timedelta, timezone

    now = datetime.now().astimezone()  # local timezone
    for hours_ahead in range(1, 4):
        # Position along the line (proportional to time)
        frac = (speed_kmh * hours_ahead) / (speed_kmh * 3.0)
        if frac > 1.0:
            break
        tick_x = cx + dx_norm * trajectory_px * frac
        tick_y = cy + dy_norm * trajectory_px * frac

        # Perpendicular tick mark
        perp_x = -dy_norm
        perp_y = dx_norm
        tick_len = 12
        draw.line(
            [
                (int(tick_x - perp_x * tick_len), int(tick_y - perp_y * tick_len)),
                (int(tick_x + perp_x * tick_len), int(tick_y + perp_y * tick_len)),
            ],
            fill=ARROW_COLOR,
            width=2,
        )

        # Time label
        future_time = now + timedelta(hours=hours_ahead)
        label = future_time.strftime("%H:%M")
        lx = int(tick_x + perp_x * 16)
        ly = int(tick_y + perp_y * 16) - 6
        # Background for readability
        draw.rectangle([lx - 2, ly - 1, lx + 38, ly + 13], fill=(255, 255, 255, 210))
        draw.text((lx, ly), label, fill=(40, 40, 40, 255))

    # Speed label near the end
    label = f"{speed_kmh:.0f} km/h"
    label_x = int(end_x + dx_norm * 8)
    label_y = int(end_y + dy_norm * 8)
    draw.rectangle(
        [label_x - 2, label_y - 2, label_x + 55, label_y + 13], fill=(255, 255, 255, 210)
    )
    draw.text((label_x, label_y), label, fill=(40, 40, 40, 255))


def render_empty_png() -> bytes:
    """Render an empty placeholder image when no data is available."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (IMG_SIZE, IMG_SIZE), BG_COLOR[:3])
    draw = ImageDraw.Draw(img)

    cx, cy = IMG_SIZE // 2, IMG_SIZE // 2
    draw.text((cx - 30, cy - 5), "No data", fill=(100, 100, 120))

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
