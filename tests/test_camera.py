"""Tests for the rain radar camera image rendering."""

from __future__ import annotations

import array
import io
import sys
from pathlib import Path

import pytest

# Add the custom_components to the path (same pattern as other tests)
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.dwd_radar import RadolanFrame
from rain_warner.radar_render import (
    BG_COLOR,
    CROP_RADIUS,
    IMG_SIZE,
    precip_to_color,
    render_empty_png,
    render_radar_png,
)


class TestPrecipToColor:
    """Test the precipitation-to-color mapping."""

    def test_no_rain_returns_none(self):
        assert precip_to_color(0.0) is None
        assert precip_to_color(0.05) is None

    def test_light_rain_returns_blue(self):
        color = precip_to_color(0.2)
        assert color is not None
        # Should be in the blue range (RGBA)
        assert color[2] > color[0]  # more blue than red

    def test_heavy_rain_returns_red(self):
        color = precip_to_color(12.0)
        assert color is not None
        # Should be in the red range
        assert color[0] > color[2]  # more red than blue

    def test_extreme_rain_returns_purple(self):
        color = precip_to_color(100.0)
        assert color is not None
        assert color == (156, 39, 176, 240)

    def test_threshold_boundaries(self):
        # At exactly 0.1 mm/h → first color bucket
        color = precip_to_color(0.1)
        assert color == (100, 149, 237, 140)  # light blue

        # Just above 50 mm/h → still last color
        color = precip_to_color(51.0)
        assert color == (156, 39, 176, 240)


class TestRenderFrame:
    """Test that frame rendering produces valid PNG output."""

    def _make_frame(self, value: int = 0, rows: int = 100, cols: int = 100) -> RadolanFrame:
        """Create a minimal test frame with uniform data."""
        data = array.array("H", [value] * rows * cols)
        return RadolanFrame(
            timestamp="2506111200",
            forecast_minutes=0,
            precision=0.01,
            rows=rows,
            cols=cols,
            data=data,
        )

    def test_render_produces_valid_png(self):
        """Test that rendering a frame produces valid PNG bytes."""
        frame = self._make_frame(value=200, rows=200, cols=200)

        png_bytes = render_radar_png(frame, 100, 100, 5)

        # Verify it's a valid PNG (starts with PNG magic bytes)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png_bytes) > 100

    def test_empty_png_is_valid(self):
        """Test that the empty placeholder is valid PNG."""
        png_bytes = render_empty_png()
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png_bytes) > 100

    def test_empty_frame_no_rain_is_dark(self):
        """Test that a frame with no precipitation is mostly background color."""
        frame = self._make_frame(value=0)

        # All pixels should map to no-rain (None from _precip_to_color)
        for row in range(frame.rows):
            for col in range(frame.cols):
                precip = frame.get_precipitation(row, col)
                assert precip == 0.0
                assert precip_to_color(precip) is None

    def test_rainy_frame_has_colored_pixels(self):
        """Test that a frame with rain produces non-background colors."""
        # Value 100 → 100 * 0.01 * 12 = 12.0 mm/h (heavy rain)
        frame = self._make_frame(value=100)

        precip = frame.get_precipitation(50, 50)
        assert precip == 12.0
        color = precip_to_color(precip)
        assert color is not None
        assert color[:3] != BG_COLOR[:3]

    def test_render_rainy_frame_differs_from_empty(self):
        """A rainy frame should produce a different image than a dry one."""
        dry_frame = self._make_frame(value=0, rows=200, cols=200)
        rain_frame = self._make_frame(value=100, rows=200, cols=200)

        dry_png = render_radar_png(dry_frame, 100, 100, 5)
        rain_png = render_radar_png(rain_frame, 100, 100, 5)

        # They must be different (rain adds colored pixels)
        assert dry_png != rain_png
