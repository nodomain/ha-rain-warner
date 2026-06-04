"""Unit tests for the optional pysteps nowcasting backend.

These tests don't require pysteps to actually be installed — they test
the optional-import wiring and the fallback behaviour. The real numeric
output of pysteps is verified by pysteps' own test suite upstream.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.dwd_radar import RadolanFrame
from rain_warner.nowcast import make_synthetic_frame_data
from rain_warner.nowcast_pysteps import (
    extend_forecast_pysteps,
    is_available,
)


def _make_frame(forecast_minutes, h, w, rain_cells, intensity_mm_h=12.0):
    values = [0.0] * (h * w)
    for r, c in rain_cells:
        if 0 <= r < h and 0 <= c < w:
            values[r * w + c] = intensity_mm_h
    data = make_synthetic_frame_data(values, h, w, precision=0.01)
    return RadolanFrame(
        timestamp="2606040000",
        forecast_minutes=forecast_minutes,
        precision=0.01,
        rows=h,
        cols=w,
        data=data,
    )


class TestAvailability:
    def test_is_available_reports_correct_status(self):
        # Either pysteps is importable or it isn't — both are valid in CI.
        result = is_available()
        assert isinstance(result, bool)


class TestFallback:
    def test_falls_back_to_simple_when_pysteps_missing(self):
        """When pysteps is unavailable, the wrapper transparently uses the
        stdlib engine so behaviour is never worse than the baseline."""
        h = w = 200
        frames = [
            _make_frame(
                i * 5, h, w, [(100 + dr, 80 + i + dc) for dr in range(-3, 4) for dc in range(-3, 4)]
            )
            for i in range(25)
        ]
        forecast = {f.forecast_minutes: 0.0 for f in frames if f.forecast_minutes > 0}

        with patch("rain_warner.nowcast_pysteps.is_available", return_value=False):
            extended, motion = extend_forecast_pysteps(
                frames,
                target_row=100,
                target_col=100,
                radius_cells=2,
                forecast=forecast,
                horizon_minutes=300,
            )

        # Should now contain entries beyond 120 min from the simple fallback
        assert any(k > 120 for k in extended.keys())

    def test_returns_original_when_too_few_frames(self):
        with patch("rain_warner.nowcast_pysteps.is_available", return_value=True):
            extended, motion = extend_forecast_pysteps(
                frames=[_make_frame(0, 50, 50, [(25, 25)])],
                target_row=25,
                target_col=25,
                radius_cells=1,
                forecast={},
                horizon_minutes=300,
            )
        assert extended == {}
        assert motion is None

    def test_returns_original_when_horizon_within_known(self):
        h = w = 50
        frames = [_make_frame(i * 5, h, w, [(25, 25)]) for i in range(25)]
        forecast = {30: 1.0}

        with patch("rain_warner.nowcast_pysteps.is_available", return_value=True):
            extended, motion = extend_forecast_pysteps(
                frames,
                target_row=25,
                target_col=25,
                radius_cells=1,
                forecast=forecast,
                horizon_minutes=120,
            )

        assert extended == forecast
        assert motion is None

    def test_pysteps_exception_falls_back_to_simple(self):
        """If pysteps raises during computation, we fall back gracefully."""
        h = w = 200
        frames = [
            _make_frame(
                i * 5,
                h,
                w,
                [(100 + dr, 80 + i + dc) for dr in range(-3, 4) for dc in range(-3, 4)],
            )
            for i in range(25)
        ]
        forecast = {f.forecast_minutes: 0.0 for f in frames if f.forecast_minutes > 0}

        # Simulate is_available() returning True, then have _run_pysteps blow up.
        with (
            patch("rain_warner.nowcast_pysteps.is_available", return_value=True),
            patch(
                "rain_warner.nowcast_pysteps._run_pysteps",
                side_effect=RuntimeError("simulated pysteps failure"),
            ),
        ):
            extended, motion = extend_forecast_pysteps(
                frames,
                target_row=100,
                target_col=100,
                radius_cells=1,
                forecast=forecast,
                horizon_minutes=300,
            )

        # Simple engine should have produced an extended forecast
        assert any(k > 120 for k in extended.keys())
