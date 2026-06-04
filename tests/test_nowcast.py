"""Unit tests for custom optical-flow nowcasting."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.dwd_radar import RadolanFrame
from rain_warner.nowcast import (
    advected_precipitation,
    estimate_motion,
    extend_forecast,
    make_synthetic_frame_data,
)


def _make_frame(
    forecast_minutes: int,
    height: int,
    width: int,
    rain_cells: list[tuple[int, int]],
    intensity_mm_h: float = 12.0,
) -> RadolanFrame:
    """Build a synthetic RadolanFrame with rain at given (row, col) positions."""
    values = [0.0] * (height * width)
    for r, c in rain_cells:
        if 0 <= r < height and 0 <= c < width:
            values[r * width + c] = intensity_mm_h
    data = make_synthetic_frame_data(values, height, width, precision=0.01)
    return RadolanFrame(
        timestamp="2606040000",
        forecast_minutes=forecast_minutes,
        precision=0.01,
        rows=height,
        cols=width,
        data=data,
    )


class TestEstimateMotion:
    """Test motion estimation between two frames."""

    def test_pure_eastward_motion(self):
        """A 5x5 rain block shifted +5 cols in 30 min = +1 col/6min ≈ +0.166 col/min."""
        h = w = 100
        rain_a = [(50 + dr, 40 + dc) for dr in range(-2, 3) for dc in range(-2, 3)]
        rain_b = [(50 + dr, 50 + dc) for dr in range(-2, 3) for dc in range(-2, 3)]

        frame_a = _make_frame(0, h, w, rain_a)
        frame_b = _make_frame(30, h, w, rain_b)

        motion = estimate_motion(frame_a, frame_b, center_row=50, center_col=45, radius=40)
        assert motion is not None
        dr_per_min, dc_per_min = motion
        assert abs(dr_per_min) < 0.05  # No row movement
        assert dc_per_min == pytest.approx(10 / 30, abs=0.05)  # +10 cols / 30 min

    def test_diagonal_motion(self):
        """Block shifted +6 rows, +6 cols in 60 min."""
        h = w = 120
        rain_a = [(50 + dr, 50 + dc) for dr in range(-3, 4) for dc in range(-3, 4)]
        rain_b = [(56 + dr, 56 + dc) for dr in range(-3, 4) for dc in range(-3, 4)]

        frame_a = _make_frame(0, h, w, rain_a)
        frame_b = _make_frame(60, h, w, rain_b)

        motion = estimate_motion(frame_a, frame_b, center_row=53, center_col=53, radius=40)
        assert motion is not None
        dr_per_min, dc_per_min = motion
        assert dr_per_min == pytest.approx(6 / 60, abs=0.05)
        assert dc_per_min == pytest.approx(6 / 60, abs=0.05)

    def test_returns_none_when_no_rain(self):
        """No rain in either frame → motion estimation should return None."""
        h = w = 60
        frame_a = _make_frame(0, h, w, [])
        frame_b = _make_frame(30, h, w, [])

        motion = estimate_motion(frame_a, frame_b, center_row=30, center_col=30, radius=25)
        assert motion is None

    def test_zero_dt_returns_none(self):
        """Same forecast time should return None (dt=0)."""
        h = w = 40
        rain = [(20, 20)]
        frame_a = _make_frame(0, h, w, rain)
        frame_b = _make_frame(0, h, w, rain)

        motion = estimate_motion(frame_a, frame_b, center_row=20, center_col=20, radius=15)
        assert motion is None


class TestAdvectedPrecipitation:
    """Test semi-Lagrangian sampling along motion vector."""

    def test_sample_back_along_motion(self):
        """Eastward-moving rain: sampling 30 min ahead looks 10 cols west."""
        h = w = 100
        # Rain block centered at col=30, height row=50
        rain = [(50 + dr, 30 + dc) for dr in range(-2, 3) for dc in range(-2, 3)]
        frame = _make_frame(120, h, w, rain, intensity_mm_h=10.0)

        # Motion: +10 cols / 30 min → 0.333 cols/min east
        # At t+150 (30 min after t+120), the rain block centroid is
        # currently at col=30 in the last frame. Looking back 30 min from
        # target=(50, 40): src=(50, 40 - 0.333*30) = (50, 30) → rain!
        precip = advected_precipitation(
            frame,
            target_row=50,
            target_col=40,
            dr_per_min=0.0,
            dc_per_min=10 / 30,
            minutes_ahead=30,
            radius_cells=2,
        )
        assert precip > 5.0  # Should hit the rain block

    def test_out_of_bounds_returns_zero(self):
        """Sampling outside the grid returns 0."""
        h = w = 50
        rain = [(25, 25)]
        frame = _make_frame(120, h, w, rain)

        precip = advected_precipitation(
            frame,
            target_row=25,
            target_col=25,
            dr_per_min=10.0,  # Huge motion → src way out of bounds
            dc_per_min=10.0,
            minutes_ahead=60,
        )
        assert precip == 0.0


class TestExtendForecast:
    """Test the full extend_forecast pipeline."""

    def test_extends_beyond_120_min(self):
        """A westward-moving rain front should be extrapolated past t+120."""
        h = w = 200
        center_row, center_col = 100, 100

        # Build 25 frames where rain moves +1 col per 5 min.
        # At t+0 rain is at col=80; at t+120 rain is at col=104.
        frames = []
        for i in range(25):
            t = i * 5
            col_center = 80 + i
            rain = [
                (center_row + dr, col_center + dc) for dr in range(-3, 4) for dc in range(-3, 4)
            ]
            frames.append(_make_frame(t, h, w, rain, intensity_mm_h=8.0))

        # Build forecast dict matching what dwd_radar.py would produce
        forecast = {f.forecast_minutes: 0.0 for f in frames if f.forecast_minutes > 0}
        # Rain currently at col=80, our location at col=100
        # → rain reaches us at t = 20 frames * 5 min = 100 min, lasts a few frames
        # For this test we just check that forecast gets extended.
        forecast[100] = 4.0  # pretend rain hits at t+100

        extended, motion = extend_forecast(
            frames,
            target_row=center_row,
            target_col=center_col,
            radius_cells=2,
            forecast=forecast,
            horizon_minutes=300,
        )

        # Forecast should now have entries beyond 120
        assert any(k > 120 for k in extended.keys())
        assert max(extended.keys()) >= 240
        # Motion should be detected as eastward (~+1 col per 5 min)
        assert motion is not None
        assert motion["dc_per_min"] == pytest.approx(0.2, abs=0.1)

    def test_no_extension_when_horizon_le_120(self):
        """horizon_minutes <= 120 should leave forecast untouched."""
        h = w = 100
        frames = [_make_frame(i * 5, h, w, [(50, 50)]) for i in range(25)]
        original = {5: 1.0, 60: 2.0}

        extended, motion = extend_forecast(
            frames,
            target_row=50,
            target_col=50,
            radius_cells=1,
            forecast=original,
            horizon_minutes=120,
        )
        assert extended == original
        assert motion is None

    def test_no_extension_when_too_few_frames(self):
        """Need at least 3 frames to estimate motion."""
        h = w = 100
        frames = [_make_frame(0, h, w, [(50, 50)])]
        extended, motion = extend_forecast(
            frames,
            target_row=50,
            target_col=50,
            radius_cells=1,
            forecast={},
            horizon_minutes=300,
        )
        assert extended == {}
        assert motion is None

    def test_dry_frames_keep_forecast_unchanged(self):
        """No rain → can't estimate motion → forecast unchanged."""
        h = w = 100
        frames = [_make_frame(i * 5, h, w, []) for i in range(25)]
        original = {30: 0.0, 60: 0.0}

        extended, motion = extend_forecast(
            frames,
            target_row=50,
            target_col=50,
            radius_cells=1,
            forecast=original,
            horizon_minutes=300,
        )
        assert extended == original
        assert motion is None
