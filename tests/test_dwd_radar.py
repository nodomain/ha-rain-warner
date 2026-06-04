"""Integration tests for DWD radar parsing.

These tests download real data from DWD Open Data and verify
the full parsing pipeline works correctly.

Run with: uv run pytest tests/ -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Add the custom_components to the path for direct imports
sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

# Import only the parser module (no homeassistant dependency)
# We import const values directly to avoid pulling in __init__.py
from rain_warner.dwd_radar import (
    RadolanFrame,
    latlon_to_grid,
    parse_radolan_archive,
    parse_radolan_frame,
)

# Constants needed for tests (duplicated to avoid importing const.py
# which may pull in modules with HA dependencies)
DE1200_ROWS = 1200
DE1200_COLS = 1100
DWD_RADAR_BASE_URL = "https://opendata.dwd.de/weather/radar/composite/rv/"


# Load location from .env if available
def _load_env():
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_load_env()

# Test location (defaults to Nuremberg if not in .env)
TEST_LAT = float(os.environ.get("LATITUDE", "49.461681"))
TEST_LON = float(os.environ.get("LONGITUDE", "11.153784"))


class TestLatLonToGrid:
    """Test coordinate to grid conversion."""

    def test_nuremberg(self):
        """Nuremberg should map to a valid grid position."""
        row, col = latlon_to_grid(TEST_LAT, TEST_LON)
        # Nuremberg: ~49.46°N, ~11.15°E
        # With proper polar stereographic: row~381, col~556
        assert 350 <= row <= 420, f"Row {row} out of expected range for Nuremberg"
        assert 530 <= col <= 590, f"Col {col} out of expected range for Nuremberg"

    def test_hamburg(self):
        """Hamburg should be in the upper (higher row) part of the grid."""
        row, col = latlon_to_grid(53.55, 9.99)
        assert 750 <= row <= 870, f"Row {row} unexpected for Hamburg"
        assert 440 <= col <= 520, f"Col {col} unexpected for Hamburg"

    def test_munich(self):
        """Munich should be in the lower (smaller row) area."""
        row, col = latlon_to_grid(48.14, 11.58)
        assert 200 <= row <= 300, f"Row {row} unexpected for Munich"
        assert 550 <= col <= 630, f"Col {col} unexpected for Munich"

    def test_berlin(self):
        """Berlin should be in the upper-right area."""
        row, col = latlon_to_grid(52.52, 13.405)
        assert 650 <= row <= 770, f"Row {row} unexpected for Berlin"
        assert 660 <= col <= 740, f"Col {col} unexpected for Berlin"

    def test_out_of_bounds_clamped(self):
        """Coordinates outside Germany should be clamped to grid edges."""
        # Far north → row should be max (top of grid)
        row, col = latlon_to_grid(70.0, 10.0)
        assert row == DE1200_ROWS - 1

        # Far south → row should be 0 (bottom of grid)
        row, col = latlon_to_grid(40.0, 10.0)
        assert row == 0

        # Far west → col should be 0
        row, col = latlon_to_grid(50.0, -5.0)
        assert col == 0

        # Far east → col should be max
        row, col = latlon_to_grid(50.0, 25.0)
        assert col == DE1200_COLS - 1


class TestParseRadolanFrame:
    """Test RADOLAN binary frame parsing."""

    def test_minimal_valid_frame(self):
        """Parse a minimal synthetic RADOLAN frame."""
        # Build a minimal valid header + data
        import array

        header = (
            b"RV041600100000626BY       227VS 5"
            b"SW  P42001PR E-02INT   5"
            b"GP4x4VV 000MF 00000008MS001<detest>\x03"
        )
        # 4x4 grid = 16 pixels x 2 bytes = 32 bytes
        data = array.array("H", [0] * 16)
        # Set some precipitation values
        data[0] = 100  # 100 * 0.01 * 12 = 12.0 mm/h
        data[5] = 50  # 50 * 0.01 * 12 = 6.0 mm/h
        data[10] = 0x2000 | 200  # Clutter flag -> should be 0
        data[15] = 0x4000 | 300  # No-data flag -> should be 0

        raw = header + data.tobytes()
        frame = parse_radolan_frame(raw)

        assert frame.rows == 4
        assert frame.cols == 4
        assert frame.forecast_minutes == 0
        assert frame.precision == 0.01

        # Check precipitation values
        assert frame.get_precipitation(0, 0) == pytest.approx(12.0)
        assert frame.get_precipitation(1, 1) == pytest.approx(6.0)
        assert frame.get_precipitation(2, 2) == 0.0  # clutter
        assert frame.get_precipitation(3, 3) == 0.0  # no-data
        assert frame.get_precipitation(0, 1) == 0.0  # zero value

    def test_forecast_minute_parsing(self):
        """Verify VV field (forecast minutes) is parsed correctly."""
        header = (
            b"RV041600100000626BY       227VS 5"
            b"SW  P42001PR E-02INT   5"
            b"GP4x4VV 060MF 00000008MS001<detest>\x03"
        )
        data = b"\x00" * (4 * 4 * 2)
        frame = parse_radolan_frame(header + data)
        assert frame.forecast_minutes == 60

    def test_invalid_no_etx(self):
        """Missing ETX should raise ValueError."""
        with pytest.raises(ValueError, match="No ETX"):
            parse_radolan_frame(b"some garbage without etx byte")

    def test_invalid_short_data(self):
        """Data shorter than expected should raise ValueError."""
        header = (
            b"RV041600100000626BY       227VS 5"
            b"SW  P42001PR E-02INT   5"
            b"GP1200x1100VV 000MF 00000008MS001<detest>\x03"
        )
        with pytest.raises(ValueError, match="Data too short"):
            parse_radolan_frame(header + b"\x00" * 100)

    def test_area_precipitation(self):
        """Area averaging should work correctly."""
        import array

        header = (
            b"RV041600100000626BY       227VS 5"
            b"SW  P42001PR E-02INT   5"
            b"GP10x10VV 000MF 00000008MS001<detest>\x03"
        )
        data = array.array("H", [0] * 100)
        # Set a 3x3 block of rain around center (5,5)
        for r in range(4, 7):
            for c in range(4, 7):
                data[r * 10 + c] = 100  # 12 mm/h each

        frame = parse_radolan_frame(header + data.tobytes())

        # Single pixel
        assert frame.get_precipitation(5, 5) == pytest.approx(12.0)

        # Area average with radius=1 (3x3 area)
        avg = frame.get_area_precipitation(5, 5, radius_cells=1)
        assert avg == pytest.approx(12.0)  # All 9 cells have rain

        # Area average with radius=2 (5x5 area, only 9 of 25 have rain)
        avg = frame.get_area_precipitation(5, 5, radius_cells=2)
        assert avg == pytest.approx(12.0 * 9 / 25)

    def test_out_of_bounds_precipitation(self):
        """Out-of-bounds coordinates should return 0."""
        header = (
            b"RV041600100000626BY       227VS 5"
            b"SW  P42001PR E-02INT   5"
            b"GP4x4VV 000MF 00000008MS001<detest>\x03"
        )
        data = b"\x64\x00" * 16  # All pixels = 100 (12 mm/h)
        frame = parse_radolan_frame(header + data)

        assert frame.get_precipitation(-1, 0) == 0.0
        assert frame.get_precipitation(0, -1) == 0.0
        assert frame.get_precipitation(4, 0) == 0.0
        assert frame.get_precipitation(0, 4) == 0.0


@pytest.mark.network
class TestLiveDownload:
    """Tests that download real data from DWD Open Data.

    These require network access and are marked with @pytest.mark.network.
    Run with: uv run pytest tests/ -v -m network
    """

    @pytest.fixture
    def archive_bytes(self):
        """Download the latest radar archive."""
        import urllib.request

        url = f"{DWD_RADAR_BASE_URL}DE1200_RV_LATEST.tar.bz2"
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()

    def test_download_and_parse_archive(self, archive_bytes):
        """Full roundtrip: download, decompress, parse all frames."""
        frames = parse_radolan_archive(archive_bytes)

        # Archive should contain 25 frames (t+0 through t+120 in 5-min steps)
        assert len(frames) == 25, f"Expected 25 frames, got {len(frames)}"

        # First frame should be current (VV=000)
        assert frames[0].forecast_minutes == 0

        # Last frame should be 2h forecast (VV=120)
        assert frames[-1].forecast_minutes == 120

        # All frames should have correct grid dimensions
        for frame in frames:
            assert frame.rows == DE1200_ROWS
            assert frame.cols == DE1200_COLS
            assert frame.precision == 0.01

    def test_extract_local_precipitation(self, archive_bytes):
        """Extract precipitation at the configured test location."""
        frames = parse_radolan_archive(archive_bytes)
        row, col = latlon_to_grid(TEST_LAT, TEST_LON)

        print(f"\n{'=' * 60}")
        print(f"  Location: {TEST_LAT:.4f}N, {TEST_LON:.4f}E")
        print(f"  Grid position: row={row}, col={col}")
        print(f"  {'─' * 50}")

        for frame in frames:
            precip = frame.get_precipitation(row, col)
            area_precip = frame.get_area_precipitation(row, col, radius_cells=3)
            marker = "rain" if precip > 0 else "    "
            print(
                f"   {marker} t+{frame.forecast_minutes:3d} min: "
                f"{precip:5.1f} mm/h (point) | "
                f"{area_precip:5.1f} mm/h (area avg)"
            )

        # Values should be non-negative
        for frame in frames:
            precip = frame.get_precipitation(row, col)
            assert precip >= 0.0, f"Negative precipitation at t+{frame.forecast_minutes}"

    def test_full_pipeline_output(self, archive_bytes):
        """Simulate the full coordinator pipeline output."""
        frames = parse_radolan_archive(archive_bytes)
        row, col = latlon_to_grid(TEST_LAT, TEST_LON)
        radius_cells = max(1, round(5 / 1.1))  # 5km radius

        current = 0.0
        forecast: dict[int, float] = {}

        for frame in frames:
            precip = frame.get_area_precipitation(row, col, radius_cells)
            if frame.forecast_minutes == 0:
                current = round(precip, 2)
            else:
                forecast[frame.forecast_minutes] = round(precip, 2)

        total_next_hour = sum(v for k, v in forecast.items() if k <= 60) * (5 / 60)
        total_next_2h = sum(v for k, v in forecast.items() if k <= 120) * (5 / 60)

        print(f"\n{'=' * 60}")
        print(f"  RAIN WARNER - Pipeline Output")
        print(f"  Location: {TEST_LAT:.4f}N, {TEST_LON:.4f}E (r=5km)")
        print(f"{'=' * 60}")
        print(f"  Current precipitation:  {current:.1f} mm/h")
        print(f"  Is raining:             {'YES' if current > 0 else 'No'}")
        print(f"  Total next 1h:          {total_next_hour:.2f} mm")
        print(f"  Total next 2h:          {total_next_2h:.2f} mm")
        print(
            f"  Max next 1h:            {max((v for k, v in forecast.items() if k <= 60), default=0):.1f} mm/h"
        )
        print(f"  Max next 2h:            {max(forecast.values(), default=0):.1f} mm/h")

        # Find rain start/end
        rain_start = next((k for k in sorted(forecast) if forecast[k] > 0), None)
        print(f"  Rain starts in:         {rain_start or 'n/a'} min")
        print(f"{'=' * 60}")

        # Basic sanity checks
        assert current >= 0.0
        assert total_next_hour >= 0.0
        assert total_next_2h >= total_next_hour
