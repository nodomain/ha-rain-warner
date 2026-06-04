"""Unit tests for the Open-Meteo client parser."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.open_meteo import OpenMeteoClient, is_in_dwd_coverage


def _make_response(now: datetime, slot_minutes_offsets: list[int], precips_mm_15: list[float]):
    """Build a synthetic Open-Meteo response."""
    times = []
    for offset in slot_minutes_offsets:
        ts = (now + timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M")
        times.append(ts)
    return {
        "current": {
            "precipitation": 0.4,
            "temperature_2m": 7.5,
        },
        "minutely_15": {
            "time": times,
            "precipitation": precips_mm_15,
        },
    }


class TestOpenMeteoParser:
    """Test parsing of Open-Meteo responses."""

    def _make_client(self) -> OpenMeteoClient:
        # Bypass __init__ network setup
        client = OpenMeteoClient.__new__(OpenMeteoClient)
        client._hass = MagicMock()
        client._latitude = 49.46
        client._longitude = 11.15
        client._session = MagicMock()
        return client

    def test_parses_current_precipitation(self):
        """Current precipitation and temperature should be passed through."""
        client = self._make_client()
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        data = _make_response(now, [0, 15, 30], [0.0, 0.0, 0.0])

        result = client._parse(data)

        assert result["current_precipitation"] == pytest.approx(0.4)
        assert result["temperature_c"] == pytest.approx(7.5)

    def test_distributes_15min_buckets_into_5min_slots(self):
        """A single 15-min bucket should populate ~3 of the 5-min slots."""
        client = self._make_client()
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        data = _make_response(now, [15, 30, 45], [1.0, 0.0, 0.0])  # 1 mm in 15min slot at +15

        result = client._parse(data)

        # 1 mm/15min = 4 mm/h
        # The +15 slot should land near minutes ~15..25
        forecast = result["forecast"]
        rainy = [k for k, v in forecast.items() if v > 0]
        assert rainy, "Expected at least one populated 5-min slot"
        assert all(10 <= k <= 30 for k in rainy), f"Slots {rainy} should cluster near +15"
        for v in forecast.values():
            if v > 0:
                assert v == pytest.approx(4.0)

    def test_horizon_capped_at_360_minutes(self):
        """Slots beyond +360 min should be ignored."""
        client = self._make_client()
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        offsets = [60, 360, 400, 420]
        precips = [0.5, 0.3, 0.2, 0.1]
        data = _make_response(now, offsets, precips)

        result = client._parse(data)

        # forecast_extended must not contain entries > 360
        assert max(result["forecast_extended"].keys(), default=0) <= 360

    def test_handles_missing_data_blocks(self):
        """Empty / missing fields should fall back to zeros."""
        client = self._make_client()
        result = client._parse({})

        assert result["current_precipitation"] == 0.0
        assert result["forecast"] == {}
        assert result["temperature_c"] is None

    def test_total_calculations(self):
        """Totals should sum the 5-min mm/h buckets correctly."""
        client = self._make_client()
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        # 1 mm in 15min slot at +15 → ~4 mm/h spread over 3 buckets
        # Each 5-min bucket contributes (4 mm/h * 5/60) = 0.333 mm
        data = _make_response(now, [15, 30, 45, 60], [1.0, 0.0, 0.0, 0.0])

        result = client._parse(data)

        # ~3 buckets × 4 mm/h × (5/60) ≈ 1.0 mm — but it's the same 15-min
        # bucket distributed; we just check it's in a sensible range.
        assert 0.5 <= result["total_next_hour"] <= 1.5
        assert result["total_next_2h"] >= result["total_next_hour"]


class TestDwdCoverage:
    """Test the geographic coverage check used for auto-mode."""

    def test_germany_is_in_coverage(self):
        assert is_in_dwd_coverage(52.52, 13.405)  # Berlin
        assert is_in_dwd_coverage(48.14, 11.58)  # Munich
        assert is_in_dwd_coverage(53.55, 9.99)  # Hamburg

    def test_neighboring_countries_are_in_coverage(self):
        """The DE1200 grid extends ~150 km past German borders."""
        assert is_in_dwd_coverage(50.08, 14.43)  # Prague
        assert is_in_dwd_coverage(48.21, 16.37)  # Vienna

    def test_far_locations_are_outside(self):
        assert not is_in_dwd_coverage(40.71, -74.0)  # NYC
        assert not is_in_dwd_coverage(35.68, 139.69)  # Tokyo
        assert not is_in_dwd_coverage(-33.86, 151.21)  # Sydney
        assert not is_in_dwd_coverage(60.17, 24.94)  # Helsinki
