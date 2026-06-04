"""Custom optical-flow nowcasting for Rain Warner.

This module extends DWD's 2h RADVOR forecast beyond the 120-minute horizon
by deriving a global motion vector from existing forecast frames and
applying semi-Lagrangian advection to the latest frame.

Approach (pysteps-inspired, stdlib-only — no numpy/scipy):
  1. Extract a sub-window of the radar grid around the user's location
     (covers ~330 km radius → enough to track 2h motion at 80 km/h).
  2. Estimate a single global motion vector (dr/dt, dc/dt) by minimizing
     the L1 distance between two frames over a search range of integer
     cell shifts. This is robust, deterministic and fast in pure Python.
  3. Advect the latest known frame by (k * 5 min * motion) to produce
     synthetic frames at t+125, t+130, ... up to a configurable horizon.

Cost: roughly O(W * H * S²) where W, H are sub-window size and S the
search range (in cells). With W=H=300, S=15 this is ~2 M operations
per frame pair — comfortably below 1 s on a Raspberry Pi 4.
"""

from __future__ import annotations

import array
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dwd_radar import RadolanFrame

_LOGGER = logging.getLogger(__name__)

# Bit masks (must match dwd_radar._VALUE_MASK etc.)
_VALUE_MASK = 0x0FFF
_CLUTTER_FLAG = 0x2000
_NODATA_FLAG = 0x4000

# Tunables
SUBWINDOW_RADIUS_CELLS = 150  # ±150 cells = ±165 km around user
MOTION_SEARCH_RANGE = 15  # ±15 cells per frame-pair (~33 km / 5min ≈ 400 km/h)
MOTION_DOWNSAMPLE = 2  # Stride for motion search (speed ↔ accuracy)
DEFAULT_HORIZON_MINUTES = 360  # Extend up to 6 h
EXTEND_STEP_MINUTES = 5  # 5-min cadence to match RADVOR


def _extract_subgrid(
    frame: RadolanFrame,
    center_row: int,
    center_col: int,
    radius: int,
) -> tuple[list[float], int, int, int, int]:
    """Extract a (2*radius+1)² window of mm/h values around a point.

    Returns:
        (values, height, width, row_origin, col_origin)
        values is a flat list in row-major order. Clutter / no-data → 0.0.
    """
    r0 = max(0, center_row - radius)
    r1 = min(frame.rows, center_row + radius + 1)
    c0 = max(0, center_col - radius)
    c1 = min(frame.cols, center_col + radius + 1)

    h = r1 - r0
    w = c1 - c0
    values = [0.0] * (h * w)

    cols = frame.cols
    data = frame.data
    precision = frame.precision

    for r in range(r0, r1):
        base = r * cols
        out_base = (r - r0) * w
        for c in range(c0, c1):
            raw = data[base + c]
            if raw & (_CLUTTER_FLAG | _NODATA_FLAG):
                continue
            val = raw & _VALUE_MASK
            if val:
                values[out_base + (c - c0)] = val * precision * 12.0

    return values, h, w, r0, c0


def estimate_motion(
    frame_a: RadolanFrame,
    frame_b: RadolanFrame,
    center_row: int,
    center_col: int,
    radius: int = SUBWINDOW_RADIUS_CELLS,
    search_range: int = MOTION_SEARCH_RANGE,
    downsample: int = MOTION_DOWNSAMPLE,
) -> tuple[float, float] | None:
    """Estimate global motion (cells per minute) between two frames.

    Uses a brute-force minimum-L1 search over integer cell shifts on a
    decimated sub-window. Returns None when neither frame contains rain
    or motion cannot be reliably estimated.
    """
    dt = frame_b.forecast_minutes - frame_a.forecast_minutes
    if dt <= 0:
        return None

    a_vals, h, w, _, _ = _extract_subgrid(frame_a, center_row, center_col, radius)
    b_vals, _, _, _, _ = _extract_subgrid(frame_b, center_row, center_col, radius)

    # Skip if too dry to track
    rain_a = sum(1 for v in a_vals if v > 0.0)
    rain_b = sum(1 for v in b_vals if v > 0.0)
    if rain_a < 25 or rain_b < 25:
        return None

    best_cost = float("inf")
    best_shift: tuple[int, int] = (0, 0)

    # Search shift that minimizes sum |A(r,c) - B(r+dr, c+dc)|
    # over decimated grid points.
    for dr in range(-search_range, search_range + 1):
        for dc in range(-search_range, search_range + 1):
            cost = 0.0
            count = 0
            r_start = max(0, -dr)
            r_end = min(h, h - dr)
            c_start = max(0, -dc)
            c_end = min(w, w - dc)
            for r in range(r_start, r_end, downsample):
                a_base = r * w
                b_base = (r + dr) * w
                for c in range(c_start, c_end, downsample):
                    a = a_vals[a_base + c]
                    b = b_vals[b_base + (c + dc)]
                    if a > 0.0 or b > 0.0:
                        cost += abs(a - b)
                        count += 1
            if count == 0:
                continue
            # Normalize by count so larger overlap regions are not penalized.
            normalized = cost / count
            if normalized < best_cost:
                best_cost = normalized
                best_shift = (dr, dc)

    if best_cost == float("inf"):
        return None

    dr_per_min = best_shift[0] / dt
    dc_per_min = best_shift[1] / dt
    return dr_per_min, dc_per_min


def advected_precipitation(
    frame: RadolanFrame,
    target_row: int,
    target_col: int,
    dr_per_min: float,
    dc_per_min: float,
    minutes_ahead: int,
    radius_cells: int = 3,
) -> float:
    """Sample the frame at the source location that advects to the target.

    For minutes_ahead > 0, looks back along the motion vector by
    (minutes_ahead * motion) cells and returns the area-averaged
    precipitation there.
    """
    src_row = int(round(target_row - dr_per_min * minutes_ahead))
    src_col = int(round(target_col - dc_per_min * minutes_ahead))
    if not (0 <= src_row < frame.rows and 0 <= src_col < frame.cols):
        return 0.0
    return frame.get_area_precipitation(src_row, src_col, radius_cells)


def extend_forecast(
    frames: list[RadolanFrame],
    target_row: int,
    target_col: int,
    radius_cells: int,
    forecast: dict[int, float],
    horizon_minutes: int = DEFAULT_HORIZON_MINUTES,
) -> tuple[dict[int, float], dict[str, float] | None]:
    """Extend the forecast dict beyond the RADVOR 2h window via advection.

    Returns:
        (extended_forecast, motion_meta) where motion_meta is a dict with
        'dr_per_min', 'dc_per_min', 'speed_kmh' or None if estimation
        failed.
    """
    if len(frames) < 3 or horizon_minutes <= 120:
        return forecast, None

    last = frames[-1]
    if last.forecast_minutes >= horizon_minutes:
        return forecast, None

    # Estimate motion from a robust mid-to-late frame pair.
    # Skip the very first frame (often noisier) and use frames separated by
    # ~30 min so the shift is several cells (better signal-to-noise).
    pair_a = frames[len(frames) // 3]
    pair_b = frames[-1]
    motion = estimate_motion(pair_a, pair_b, target_row, target_col)
    if motion is None:
        return forecast, None

    dr_per_min, dc_per_min = motion
    speed_cells_per_min = (dr_per_min**2 + dc_per_min**2) ** 0.5
    if speed_cells_per_min < 0.05:
        # Stationary front — advection won't help, keep original forecast.
        return forecast, {
            "dr_per_min": dr_per_min,
            "dc_per_min": dc_per_min,
            "speed_kmh": speed_cells_per_min * 1.1 * 60.0,
        }

    extended = dict(forecast)
    last_known_min = last.forecast_minutes
    step = EXTEND_STEP_MINUTES

    for minutes in range(last_known_min + step, horizon_minutes + 1, step):
        delta = minutes - last_known_min
        precip = advected_precipitation(
            last,
            target_row,
            target_col,
            dr_per_min,
            dc_per_min,
            delta,
            radius_cells,
        )
        extended[minutes] = round(precip, 2)

    motion_meta = {
        "dr_per_min": dr_per_min,
        "dc_per_min": dc_per_min,
        "speed_kmh": speed_cells_per_min * 1.1 * 60.0,
    }
    return extended, motion_meta


def find_rain_end_in_extended(
    extended_forecast: dict[int, float],
    current_precipitation: float,
) -> int | None:
    """Same logic as coordinator._find_rain_end but on the extended dict."""
    raining = current_precipitation > 0.0
    for minutes in sorted(extended_forecast.keys()):
        if extended_forecast[minutes] > 0.0:
            raining = True
        elif raining:
            return minutes
    if raining:
        return -1
    return None


def make_synthetic_frame_data(
    values: list[float],
    height: int,
    width: int,
    precision: float = 0.01,
) -> array.array:
    """Convert a flat list of mm/h values to RADOLAN-encoded uint16 data.

    Useful for testing the advection pipeline in unit tests.
    """
    data = array.array("H", [0] * (height * width))
    for i, v in enumerate(values):
        if v <= 0.0:
            continue
        # mm/h → raw units: v / (precision * 12)
        raw = int(round(v / (precision * 12.0)))
        data[i] = min(raw, _VALUE_MASK)
    return data
