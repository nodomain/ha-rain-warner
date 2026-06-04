"""Unit tests for the derived alert-flag logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.alerts import (
    is_extended_dry_spell,
    is_rain_imminent,
    is_severe_weather,
    is_winter_weather,
)


class TestRainImminent:
    def test_on_when_dry_and_rain_in_30_min(self):
        assert is_rain_imminent(False, 15) is True
        assert is_rain_imminent(False, 30) is True

    def test_off_when_already_raining(self):
        assert is_rain_imminent(True, 5) is False

    def test_off_when_rain_too_far_away(self):
        assert is_rain_imminent(False, 60) is False
        assert is_rain_imminent(False, 31) is False

    def test_off_when_no_rain_in_forecast(self):
        assert is_rain_imminent(False, None) is False

    def test_off_when_rain_at_zero(self):
        # Defensive: minutes=0 means "now" which the rain_imminent
        # semantic ("approaching but not arrived") shouldn't claim.
        assert is_rain_imminent(False, 0) is False


class TestSevereWeather:
    def test_on_for_heavy_intensity(self):
        assert is_severe_weather("heavy", 5.0, "rain") is True

    def test_on_for_violent_intensity(self):
        assert is_severe_weather("violent", 100.0, "rain") is True

    def test_on_for_heavy_forecast(self):
        # Currently only light, but forecast crosses heavy threshold
        assert is_severe_weather("light", 12.0, "rain") is True

    def test_on_for_hail_likely(self):
        assert is_severe_weather("light", 1.0, "hail_likely") is True

    def test_off_for_light_rain(self):
        assert is_severe_weather("light", 1.0, "rain") is False

    def test_off_for_moderate_rain(self):
        assert is_severe_weather("moderate", 3.0, "rain") is False

    def test_off_when_dry(self):
        assert is_severe_weather("none", 0.0, "none") is False


class TestWinterWeather:
    def test_on_for_snow(self):
        assert is_winter_weather("snow") is True

    def test_on_for_sleet(self):
        assert is_winter_weather("sleet") is True

    def test_on_for_freezing_rain(self):
        assert is_winter_weather("freezing_rain") is True

    def test_off_for_rain(self):
        assert is_winter_weather("rain") is False

    def test_off_for_hail_likely(self):
        # Hail is severe weather, not "winter weather" — different alert.
        assert is_winter_weather("hail_likely") is False

    def test_off_for_none(self):
        assert is_winter_weather("none") is False


class TestExtendedDrySpell:
    def test_on_after_a_week_without_rain_and_dry_forecast(self):
        assert is_extended_dry_spell(200.0, 0.0) is True
        assert is_extended_dry_spell(168.0, 0.0) is True

    def test_off_when_streak_too_short(self):
        assert is_extended_dry_spell(167.9, 0.0) is False
        assert is_extended_dry_spell(24.0, 0.0) is False

    def test_off_when_rain_in_forecast(self):
        # Long streak but rain is coming → don't tell user to water plants
        assert is_extended_dry_spell(200.0, 1.5) is False
        assert is_extended_dry_spell(200.0, 0.1) is False

    def test_off_when_streak_unknown(self):
        assert is_extended_dry_spell(None, 0.0) is False
