"""Unit tests for precipitation type classification."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.precip_type import (
    TYPE_FREEZING_RAIN,
    TYPE_HAIL_LIKELY,
    TYPE_NONE,
    TYPE_RAIN,
    TYPE_SLEET,
    TYPE_SNOW,
    TYPE_UNKNOWN,
    classify,
)


class TestClassify:
    def test_no_rain_no_temp(self):
        assert classify(0.0, None, 0.0) == TYPE_NONE

    def test_no_rain_with_warm_temp(self):
        assert classify(0.0, 20.0, 0.0) == TYPE_NONE

    def test_warm_rain(self):
        assert classify(2.5, 12.0, 5.0) == TYPE_RAIN

    def test_pure_snow(self):
        # Solid snow when sufficiently cold
        assert classify(1.0, -5.0, 1.0) == TYPE_SNOW
        assert classify(1.0, -1.5, 1.0) == TYPE_SNOW

    def test_sleet_zone(self):
        # SNOW_TEMP_C (-1) <= temp < FREEZING_RAIN_TEMP_C (0.5)
        assert classify(1.0, 0.0, 1.0) == TYPE_SLEET
        assert classify(1.0, -1.0, 1.0) == TYPE_SLEET

    def test_freezing_rain_zone(self):
        # FREEZING_RAIN_TEMP_C (0.5) <= temp < RAIN_TEMP_C (1.5)
        assert classify(1.0, 1.0, 1.0) == TYPE_FREEZING_RAIN

    def test_hail_likely_only_when_warm_and_intense(self):
        # Heavy rain in cold air → snow, not hail
        assert classify(60.0, -3.0, 60.0) == TYPE_SNOW
        # Heavy rain at warm summer temp → hail
        assert classify(60.0, 22.0, 60.0) == TYPE_HAIL_LIKELY
        # Even when current is low but max-2h is hail-territory
        assert classify(2.0, 20.0, 70.0) == TYPE_HAIL_LIKELY

    def test_unknown_when_temperature_missing(self):
        # We refuse to flag hail without temperature, even at huge intensity.
        assert classify(80.0, None, 80.0) == TYPE_UNKNOWN
        assert classify(2.0, None, 2.0) == TYPE_UNKNOWN

    def test_uses_max_2h_when_currently_dry(self):
        # Currently dry, but rain forecast → use max as proxy
        assert classify(0.0, 18.0, 5.0) == TYPE_RAIN
        assert classify(0.0, -5.0, 5.0) == TYPE_SNOW

    def test_negative_inputs_treated_as_zero(self):
        assert classify(-1.0, 10.0, -1.0) == TYPE_NONE
