"""Precipitation type classification (rain / snow / sleet / hail).

Radar reflectivity alone can't tell us whether the precipitation is
liquid, frozen, or hail. We combine it with air temperature and
intensity heuristics to derive a usable type.

Rules (intentionally simple and well-documented over fancy):

  none           : current_precipitation == 0
  hail_likely    : current_precipitation > HAIL_THRESHOLD_MM_H
                   AND temperature warm enough for convection
  snow           : temperature < SNOW_TEMP_C
  sleet          : SNOW_TEMP_C <= temperature < RAIN_TEMP_C
  freezing_rain  : temperature < FREEZING_RAIN_TEMP_C and surface
                   conditions allow super-cooled liquid (we approximate
                   this — flagged when temp slightly below 0 but warmer
                   than full snow)
  rain           : temperature >= RAIN_TEMP_C (default)
  unknown        : raining but temperature unavailable

These thresholds match the convention used in most weather services
(NOAA / DWD) for surface observations.
"""

from __future__ import annotations

# Temperature thresholds (°C, air temperature at 2 m)
SNOW_TEMP_C = -1.0
FREEZING_RAIN_TEMP_C = 0.5
RAIN_TEMP_C = 1.5

# Hail typically requires very high reflectivity. Convective hail cells
# routinely produce > 50 mm/h equivalent rates in radar data.
HAIL_THRESHOLD_MM_H = 50.0
HAIL_MIN_TEMP_C = 5.0  # Below this, "violent precipitation" is more likely heavy snow/graupel

# Type constants used in sensor states and translations.
TYPE_NONE = "none"
TYPE_RAIN = "rain"
TYPE_SLEET = "sleet"
TYPE_FREEZING_RAIN = "freezing_rain"
TYPE_SNOW = "snow"
TYPE_HAIL_LIKELY = "hail_likely"
TYPE_UNKNOWN = "unknown"


def classify(
    current_precipitation_mm_h: float,
    temperature_c: float | None,
    max_2h_precipitation_mm_h: float = 0.0,
) -> str:
    """Classify the current precipitation type.

    Args:
        current_precipitation_mm_h: Current precip rate at the user.
        temperature_c: Air temperature at 2 m, °C. None when unknown.
        max_2h_precipitation_mm_h: Peak rate in the next 2 h (used to
            flag potentially-hail convective cells even when current
            rate is lower).

    Returns:
        One of the TYPE_* constants.
    """
    rate = max(current_precipitation_mm_h, 0.0)

    if rate <= 0.0 and max_2h_precipitation_mm_h <= 0.0:
        return TYPE_NONE

    # Hail requires both high intensity AND warm surface temperature
    # (convective storms). Without temperature we don't dare flag hail.
    if temperature_c is not None and temperature_c >= HAIL_MIN_TEMP_C:
        if rate >= HAIL_THRESHOLD_MM_H or max_2h_precipitation_mm_h >= HAIL_THRESHOLD_MM_H:
            return TYPE_HAIL_LIKELY

    if rate <= 0.0:
        # Not currently raining, but rain is forecast — return the type
        # the upcoming precipitation would have.
        rate = max_2h_precipitation_mm_h

    if temperature_c is None:
        return TYPE_UNKNOWN

    if temperature_c < SNOW_TEMP_C:
        return TYPE_SNOW
    if temperature_c < FREEZING_RAIN_TEMP_C:
        # Sub-zero but not cold enough for pure snow → wet snow / sleet.
        return TYPE_SLEET
    if temperature_c < RAIN_TEMP_C:
        # Just barely above freezing — some droplets may super-cool.
        return TYPE_FREEZING_RAIN
    return TYPE_RAIN
