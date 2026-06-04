"""DWD Radar data client for Rain Warner.

Parses RADOLAN binary composites from DWD Open Data.
A single archive (DE1200_RV_LATEST.tar.bz2) contains:
  - _000: current observation (t+0)
  - _005 through _120: RADVOR nowcast forecast in 5-min steps

File format:
  - ASCII header ending with ETX (0x03), ~195 bytes
  - Binary data: 1200×1100 grid of uint16 LE values
  - Precision: 0.01 mm/5min (header field "E-02")
  - Bit flags in each 16-bit value:
    - Bits 0-11: precipitation value
    - Bit 13: clutter flag (discard)
    - Bit 14: no-data / negative flag (discard)
"""

from __future__ import annotations

import array
import bz2
import io
import logging
import re
import tarfile
from datetime import datetime, timezone
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DE1200_COLS,
    DE1200_RESOLUTION_KM,
    DE1200_ROWS,
    DWD_RADAR_BASE_URL,
    NOWCAST_ENGINE_PYSTEPS,
    NOWCAST_ENGINE_SIMPLE,
)
from .nowcast import extend_forecast

_LOGGER = logging.getLogger(__name__)

# Header regex to extract key fields
_HEADER_RE = re.compile(
    rb"(?P<product>\w{2})"
    rb"(?P<timestamp>\d{5,6})"
    rb"(?P<dummy>\d+)"
    rb"(?P<month>\d{4})"
    rb"BY\s+(?P<filesize>\d+)"
    rb"VS\s+(?P<version>\d+)"
    rb"SW\s+(?P<software>\S+)"
    rb"PR\s+(?P<precision>[E][+-]\d+)"
    rb"INT\s+(?P<interval>\d+)"
    rb"GP(?P<rows>\d+)x(?P<cols>\d+)"
    rb"VV\s+(?P<forecast>\d+)"
)

# Bit masks for 16-bit RADOLAN values
_VALUE_MASK = 0x0FFF  # Bits 0-11: precipitation value
_CLUTTER_FLAG = 0x2000  # Bit 13: clutter
_NODATA_FLAG = 0x4000  # Bit 14: no data / negative


class RadolanFrame:
    """A single parsed RADOLAN radar frame."""

    __slots__ = ("timestamp", "forecast_minutes", "precision", "rows", "cols", "data")

    def __init__(
        self,
        timestamp: str,
        forecast_minutes: int,
        precision: float,
        rows: int,
        cols: int,
        data: array.array,
    ) -> None:
        """Initialize a radar frame."""
        self.timestamp = timestamp
        self.forecast_minutes = forecast_minutes
        self.precision = precision
        self.rows = rows
        self.cols = cols
        self.data = data

    def get_precipitation(self, row: int, col: int) -> float:
        """Get precipitation rate in mm/h at a grid position.

        Returns 0.0 for clutter, no-data, or out-of-bounds.
        """
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return 0.0

        idx = row * self.cols + col
        raw = self.data[idx]

        if raw & (_CLUTTER_FLAG | _NODATA_FLAG):
            return 0.0

        value = raw & _VALUE_MASK
        # Convert from precision units per interval to mm/h
        # precision=0.01, interval=5min → value * 0.01 mm/5min * 12 = mm/h
        return value * self.precision * 12.0

    def get_area_precipitation(
        self, center_row: int, center_col: int, radius_cells: int = 3
    ) -> float:
        """Get average precipitation over a square area.

        Uses a simple box average over (2*radius+1)^2 cells.
        Ignores no-data cells in the average.
        """
        total = 0.0
        count = 0

        for r in range(center_row - radius_cells, center_row + radius_cells + 1):
            for c in range(center_col - radius_cells, center_col + radius_cells + 1):
                if not (0 <= r < self.rows and 0 <= c < self.cols):
                    continue
                idx = r * self.cols + c
                raw = self.data[idx]
                if raw & (_CLUTTER_FLAG | _NODATA_FLAG):
                    continue
                value = raw & _VALUE_MASK
                total += value
                count += 1

        if count == 0:
            return 0.0

        return (total / count) * self.precision * 12.0


def parse_radolan_frame(raw_bytes: bytes) -> RadolanFrame:
    """Parse a single RADOLAN binary file into a RadolanFrame.

    Args:
        raw_bytes: Complete file content (header + binary data).

    Returns:
        Parsed RadolanFrame with grid data.

    Raises:
        ValueError: If the file format is invalid.
    """
    # Find header end (ETX byte = 0x03)
    etx_pos = raw_bytes.find(b"\x03")
    if etx_pos == -1:
        raise ValueError("No ETX (0x03) found — not a valid RADOLAN file")

    header_end = etx_pos + 1
    header = raw_bytes[:header_end]

    # Parse header fields
    match = _HEADER_RE.search(header)
    if not match:
        raise ValueError(f"Cannot parse RADOLAN header: {header[:100]!r}")

    rows = int(match.group("rows"))
    cols = int(match.group("cols"))
    forecast_minutes = int(match.group("forecast"))
    precision_str = match.group("precision").decode()
    # "E-02" → 10^(-2) = 0.01
    precision = 10 ** int(precision_str[1:])

    timestamp = match.group("timestamp").decode()

    # Parse binary data
    data_bytes = raw_bytes[header_end:]
    expected_size = rows * cols * 2
    if len(data_bytes) < expected_size:
        raise ValueError(
            f"Data too short: got {len(data_bytes)} bytes, "
            f"expected {expected_size} for {rows}x{cols} grid"
        )

    data = array.array("H")  # unsigned 16-bit
    data.frombytes(data_bytes[:expected_size])

    return RadolanFrame(
        timestamp=timestamp,
        forecast_minutes=forecast_minutes,
        precision=precision,
        rows=rows,
        cols=cols,
        data=data,
    )


def parse_radolan_archive(archive_bytes: bytes) -> list[RadolanFrame]:
    """Parse a tar.bz2 archive containing multiple RADOLAN frames.

    The archive contains files like:
      DE1200_RV2606041600_000  (t+0, current)
      DE1200_RV2606041600_005  (t+5 min)
      ...
      DE1200_RV2606041600_120  (t+120 min)

    Returns:
        List of RadolanFrames sorted by forecast_minutes.
    """
    decompressed = bz2.decompress(archive_bytes)
    frames: list[RadolanFrame] = []

    with tarfile.open(fileobj=io.BytesIO(decompressed)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            try:
                frame = parse_radolan_frame(f.read())
                frames.append(frame)
            except ValueError as err:
                _LOGGER.warning("Skipping %s: %s", member.name, err)

    frames.sort(key=lambda f: f.forecast_minutes)
    return frames


# DWD RADOLAN polar stereographic projection constants
_EARTH_RADIUS_KM = 6370.04  # DWD-specific earth radius
_PHI0 = 1.0471975511965976  # radians(60°) — standard parallel
_LAM0 = 0.17453292519943295  # radians(10°) — central meridian
_SIN_PHI0 = 0.8660254037844386  # sin(60°)
_ONE_PLUS_SIN_PHI0 = 1.8660254037844386  # 1 + sin(60°)

# Grid origin: projected coordinates (km) of the lower-left corner
# of cell [row=0, col=0]. Derived from wradlib/DWD documentation.
_GRID_ORIGIN_X = -523.462
_GRID_ORIGIN_Y = -4808.645


def latlon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """Convert lat/lon to DE1200 grid indices.

    Uses the DWD RADOLAN polar stereographic projection:
    - Earth radius: 6370.04 km
    - Standard parallel: 60°N
    - Central meridian: 10°E
    - Grid spacing: 1.1 km
    - Row 0 at southern edge, increasing northward

    Returns:
        Tuple of (row, col) indices clamped to valid grid range.
    """
    import math

    phi = math.radians(lat)
    lam = math.radians(lon)

    # Polar stereographic scale factor
    m = _ONE_PLUS_SIN_PHI0 / (1.0 + math.sin(phi))

    # Projected coordinates in km
    cos_phi = math.cos(phi)
    x = _EARTH_RADIUS_KM * m * cos_phi * math.sin(lam - _LAM0)
    y = -_EARTH_RADIUS_KM * m * cos_phi * math.cos(lam - _LAM0)

    # Convert to grid indices (origin at lower-left)
    col = int((x - _GRID_ORIGIN_X) / DE1200_RESOLUTION_KM)
    row = int((y - _GRID_ORIGIN_Y) / DE1200_RESOLUTION_KM)

    # Clamp to valid range
    row = max(0, min(DE1200_ROWS - 1, row))
    col = max(0, min(DE1200_COLS - 1, col))

    return row, col


class DWDRadarClient:
    """Client for DWD radar composite data."""

    def __init__(
        self,
        hass: HomeAssistant,
        latitude: float,
        longitude: float,
        radius: int = 5,
        nowcast_engine: str = NOWCAST_ENGINE_SIMPLE,
    ) -> None:
        """Initialize the DWD radar client."""
        self._hass = hass
        self._latitude = latitude
        self._longitude = longitude
        self._radius = radius
        self._nowcast_engine = nowcast_engine
        self._session = async_get_clientsession(hass)

        # Pre-calculate grid position
        self._grid_row, self._grid_col = latlon_to_grid(latitude, longitude)
        # Radius in grid cells (each cell ≈ 1.1 km)
        self._radius_cells = max(1, round(radius / 1.1))

        _LOGGER.debug(
            "Grid position for (%.4f, %.4f): row=%d, col=%d, radius=%d cells",
            latitude,
            longitude,
            self._grid_row,
            self._grid_col,
            self._radius_cells,
        )

    async def async_get_data(self) -> dict[str, Any]:
        """Fetch current radar data and nowcast forecast."""
        archive_bytes = await self._download_archive()
        if archive_bytes is None:
            return {
                "current_precipitation": 0.0,
                "forecast": {},
                "total_next_hour": 0.0,
                "total_next_2h": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        frames = await self._hass.async_add_executor_job(parse_radolan_archive, archive_bytes)

        if not frames:
            _LOGGER.warning("No valid frames found in radar archive")
            return {
                "current_precipitation": 0.0,
                "forecast": {},
                "total_next_hour": 0.0,
                "total_next_2h": 0.0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Extract precipitation at our location from each frame
        current = 0.0
        forecast: dict[int, float] = {}

        for frame in frames:
            precip = frame.get_area_precipitation(
                self._grid_row, self._grid_col, self._radius_cells
            )

            if frame.forecast_minutes == 0:
                current = round(precip, 2)
            else:
                forecast[frame.forecast_minutes] = round(precip, 2)

        # Calculate totals (each step covers 5 minutes)
        total_next_hour = sum(v for k, v in forecast.items() if k <= 60) * (5 / 60)
        total_next_2h = sum(v for k, v in forecast.items() if k <= 120) * (5 / 60)

        # Extend forecast beyond 2 h via the configured nowcast engine.
        # Both engines have the same signature so we can swap them out.
        if self._nowcast_engine == NOWCAST_ENGINE_PYSTEPS:
            from .nowcast_pysteps import extend_forecast_pysteps

            extend_fn = extend_forecast_pysteps
        else:
            extend_fn = extend_forecast

        extended_forecast, motion_meta = await self._hass.async_add_executor_job(
            extend_fn,
            frames,
            self._grid_row,
            self._grid_col,
            self._radius_cells,
            forecast,
        )

        rain_end_estimate = self._extract_extrapolated_end(extended_forecast, current)

        return {
            "current_precipitation": current,
            "forecast": forecast,
            "forecast_extended": extended_forecast,
            "total_next_hour": round(total_next_hour, 2),
            "total_next_2h": round(total_next_2h, 2),
            "rain_end_extrapolated": rain_end_estimate,
            "motion": motion_meta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _download_archive(self) -> bytes | None:
        """Download the latest RV composite archive."""
        url = f"{DWD_RADAR_BASE_URL}DE1200_RV_LATEST.tar.bz2"

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    _LOGGER.warning("DWD radar download failed: HTTP %d", resp.status)
                    return None
                return await resp.read()

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Error downloading DWD radar: %s", err)
            return None

    @staticmethod
    def _extract_extrapolated_end(
        extended_forecast: dict[int, float], current: float
    ) -> int | None:
        """Find the minute the rain ends in the optical-flow-extended forecast.

        Returns None when rain ends within the original 2 h window (no
        extrapolation needed) or when the extended forecast doesn't
        resolve the end either.
        """
        raining = current > 0.0
        ends_in_2h = False
        end_minute: int | None = None
        for minutes in sorted(extended_forecast.keys()):
            if extended_forecast[minutes] > 0.0:
                raining = True
            elif raining:
                end_minute = minutes
                if minutes <= 120:
                    ends_in_2h = True
                break

        if ends_in_2h or not raining:
            return None  # Not needed — forecast already tells us
        return end_minute
