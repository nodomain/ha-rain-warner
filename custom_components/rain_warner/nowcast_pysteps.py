"""Optional pysteps-based nowcasting backend for Rain Warner.

This module wraps the pysteps library to provide a much more sophisticated
nowcasting engine than the stdlib `nowcast.py` fallback. pysteps adds:

  - Per-pixel optical flow (Lucas-Kanade) instead of one global vector.
    Captures rotation, divergence and locally varying winds.
  - Cascade decomposition: separates large-scale (front-level) from
    small-scale (cell-level) features and predicts them at different
    decay rates. This is the main reason pysteps stays accurate at 1-3 h
    when our simple advection has already degraded.
  - Lifecycle modeling via S-PROG's AR(2) autoregression: cells grow,
    intensify, weaken and dissipate based on observed history.

This module is an OPTIONAL backend. pysteps is NOT listed in
`manifest.json` requirements because it pulls in numpy + scipy and is
heavyweight on Raspberry Pi-class hardware. Users who want it must
`pip install pysteps` into their Home Assistant Python environment.

If pysteps cannot be imported, `extend_forecast_pysteps` transparently
falls back to the stdlib nowcast engine so behaviour is never worse
than the baseline.

Engine selection lives in the config entry; see `const.NOWCAST_ENGINE_*`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .dwd_radar import RadolanFrame

_LOGGER = logging.getLogger(__name__)

# Bit masks (must match dwd_radar)
_VALUE_MASK = 0x0FFF
_CLUTTER_FLAG = 0x2000
_NODATA_FLAG = 0x4000

# Sub-window radius for the pysteps computation. Pysteps cascade
# decomposition wants enough room to meaningfully resolve large-scale
# features → 250 cells = ~275 km box, plenty for 6 h advection.
SUBWINDOW_RADIUS_CELLS = 250
DEFAULT_HORIZON_MINUTES = 360
TIMESTEP_MINUTES = 5

# Number of input frames we feed pysteps for motion estimation.
# The Lucas-Kanade method needs at least 2 frames; using the last 3
# gives more robust motion fields without significantly increasing
# runtime.
INPUT_FRAMES = 3


def is_available() -> bool:
    """Return True if pysteps and its hard dependencies can be imported."""
    try:
        import numpy  # noqa: F401
        import pysteps  # noqa: F401

        return True
    except ImportError:
        return False


def _frames_to_numpy(
    frames: list[RadolanFrame],
    center_row: int,
    center_col: int,
    radius: int,
) -> tuple[Any, int, int]:
    """Stack the last `INPUT_FRAMES` frames into a numpy (T, Y, X) array.

    Returns:
        (array, row_origin, col_origin) — array shape is (INPUT_FRAMES, h, w),
        values are mm/h with NaN for clutter/no-data.
    """
    import numpy as np

    last_frames = frames[-INPUT_FRAMES:]
    rows = last_frames[0].rows
    cols = last_frames[0].cols

    r0 = max(0, center_row - radius)
    r1 = min(rows, center_row + radius + 1)
    c0 = max(0, center_col - radius)
    c1 = min(cols, center_col + radius + 1)
    h = r1 - r0
    w = c1 - c0

    out = np.full((len(last_frames), h, w), np.nan, dtype=np.float32)

    for t, frame in enumerate(last_frames):
        precision = frame.precision
        data = frame.data
        for r in range(r0, r1):
            base = r * cols
            row_idx = r - r0
            for c in range(c0, c1):
                raw = data[base + c]
                if raw & (_CLUTTER_FLAG | _NODATA_FLAG):
                    # Leave as NaN — pysteps handles missing data natively
                    continue
                val = raw & _VALUE_MASK
                out[t, row_idx, c - c0] = val * precision * 12.0

    return out, r0, c0


def extend_forecast_pysteps(
    frames: list[RadolanFrame],
    target_row: int,
    target_col: int,
    radius_cells: int,
    forecast: dict[int, float],
    horizon_minutes: int = DEFAULT_HORIZON_MINUTES,
) -> tuple[dict[int, float], dict[str, Any] | None]:
    """Extend the forecast using pysteps S-PROG (with stdlib fallback).

    Drop-in replacement for `nowcast.extend_forecast` with the same
    signature so the coordinator can swap engines transparently.
    """
    if not is_available():
        _LOGGER.info(
            "pysteps not installed — falling back to simple nowcast engine. "
            "Install with `pip install pysteps` in your HA Python env to enable."
        )
        from .nowcast import extend_forecast

        return extend_forecast(
            frames, target_row, target_col, radius_cells, forecast, horizon_minutes
        )

    if len(frames) < INPUT_FRAMES or horizon_minutes <= 120:
        return forecast, None

    last = frames[-1]
    if last.forecast_minutes >= horizon_minutes:
        return forecast, None

    try:
        return _run_pysteps(frames, target_row, target_col, radius_cells, forecast, horizon_minutes)
    except Exception as err:  # noqa: BLE001 — pysteps can fail in many ways
        _LOGGER.warning("pysteps nowcast failed (%s) — falling back to simple engine", err)
        from .nowcast import extend_forecast

        return extend_forecast(
            frames, target_row, target_col, radius_cells, forecast, horizon_minutes
        )


def _run_pysteps(
    frames: list[RadolanFrame],
    target_row: int,
    target_col: int,
    radius_cells: int,
    forecast: dict[int, float],
    horizon_minutes: int,
) -> tuple[dict[int, float], dict[str, Any] | None]:
    """Actual pysteps computation — separated so callers can wrap errors."""
    import numpy as np
    from pysteps import motion, nowcasts

    last = frames[-1]
    last_known = last.forecast_minutes
    extra_steps = (horizon_minutes - last_known) // TIMESTEP_MINUTES
    if extra_steps <= 0:
        return forecast, None

    # Build the (T, Y, X) numpy stack pysteps expects
    R, r_origin, c_origin = _frames_to_numpy(frames, target_row, target_col, SUBWINDOW_RADIUS_CELLS)

    # Skip pysteps when the field is essentially dry — it produces
    # warnings and gives no useful signal. We still return the original
    # forecast unmodified so other sensors keep working.
    if np.nansum(R[-1]) < 1.0:
        return forecast, None

    # Pysteps wants log-space for SPROG — do the standard decibel
    # transform so AR(2) operates on something near-Gaussian.
    threshold = 0.1  # mm/h — anything below is treated as "no rain"
    R_log, metadata = _to_db_units(R, threshold)

    # Lucas-Kanade optical flow on the log-space stack
    oflow_method = motion.get_method("lucaskanade")
    V = oflow_method(R_log)

    # Run SPROG (Spectral Prognosis) — deterministic cascade nowcast
    nowcast_method = nowcasts.get_method("sprog")
    R_forecast = nowcast_method(
        R_log[-1],
        V,
        timesteps=extra_steps,
        n_cascade_levels=8,
        R_thr=metadata["zerovalue"],
        precip_thr=metadata["zerovalue"],
        ar_order=2,
    )

    # Convert back from dB to mm/h
    R_forecast = _from_db_units(R_forecast, metadata)

    # Sample at the user location with the same area-averaging the
    # simple engine uses, so values stay comparable between engines.
    sample_row = target_row - r_origin
    sample_col = target_col - c_origin
    extended = dict(forecast)

    h, w = R_forecast.shape[1], R_forecast.shape[2]
    for i in range(extra_steps):
        minutes = last_known + (i + 1) * TIMESTEP_MINUTES
        if minutes > horizon_minutes:
            break
        rmin = max(0, sample_row - radius_cells)
        rmax = min(h, sample_row + radius_cells + 1)
        cmin = max(0, sample_col - radius_cells)
        cmax = min(w, sample_col + radius_cells + 1)
        if rmin >= rmax or cmin >= cmax:
            extended[minutes] = 0.0
            continue
        slice_ = R_forecast[i, rmin:rmax, cmin:cmax]
        with np.errstate(invalid="ignore"):
            mean_val = float(np.nanmean(slice_))
        if not np.isfinite(mean_val) or mean_val < 0:
            mean_val = 0.0
        extended[minutes] = round(mean_val, 2)

    # Motion metadata: average flow over the field for diagnostics
    with np.errstate(invalid="ignore"):
        mean_u = float(np.nanmean(V[0]))  # x / column direction
        mean_v = float(np.nanmean(V[1]))  # y / row direction
    speed_cells_per_step = (mean_u**2 + mean_v**2) ** 0.5
    motion_meta = {
        "engine": "pysteps",
        "method": "sprog",
        "dr_per_min": mean_v / TIMESTEP_MINUTES,
        "dc_per_min": mean_u / TIMESTEP_MINUTES,
        "speed_kmh": speed_cells_per_step / TIMESTEP_MINUTES * 1.1 * 60.0,
    }
    return extended, motion_meta


def _to_db_units(R, threshold: float) -> tuple[Any, dict[str, Any]]:
    """Convert mm/h to dB units the way pysteps' SPROG expects.

    Uses the standard pysteps transformation: 10 * log10(R) for values
    above the threshold, a fixed "zero value" below. NaNs pass through.
    """
    import numpy as np

    R_log = R.copy()
    zero_value = 10.0 * np.log10(threshold) - 5.0  # well below threshold

    mask = np.isfinite(R_log) & (R_log >= threshold)
    R_log[mask] = 10.0 * np.log10(R_log[mask])
    R_log[np.isfinite(R_log) & ~mask] = zero_value

    metadata = {"zerovalue": zero_value, "threshold_mmh": threshold}
    return R_log, metadata


def _from_db_units(R_log, metadata: dict[str, Any]):
    """Inverse of `_to_db_units`."""
    import numpy as np

    out = R_log.copy()
    mask = np.isfinite(out) & (out > metadata["zerovalue"] + 0.1)
    out[mask] = 10.0 ** (out[mask] / 10.0)
    out[np.isfinite(out) & ~mask] = 0.0
    return out
