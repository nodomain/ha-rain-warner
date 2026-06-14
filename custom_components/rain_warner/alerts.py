"""Derived alert flags for Rain Warner.

Pure-logic helpers that turn the coordinator's processed data into the
four binary alert states surfaced as binary sensors and used in
walldisplay notifications and automations:

  rain_imminent       : dry now, but rain >= 0.3 mm/h in <= 30 minutes
  severe_weather      : heavy/violent rain or hail likelihood
  winter_weather      : snow / sleet / freezing rain detected
  extended_dry_spell  : >= 7 days without rain and no rain in forecast

Kept stdlib-only and HA-free so the tests can exercise the boundaries
without mocking the coordinator.
"""

from __future__ import annotations

from .const import PRECIP_THRESHOLD_HEAVY, RAIN_IMMINENT_MIN_RATE

# When does "rain coming soon" trigger the imminent flag?
RAIN_IMMINENT_THRESHOLD_MINUTES = 30

# Hours of rain-free observation that count as "extended dry spell".
DRY_SPELL_THRESHOLD_HOURS = 168.0  # 7 days

# Precipitation types treated as winter weather.
WINTER_TYPES = frozenset({"snow", "sleet", "freezing_rain"})


def is_rain_imminent(
    is_raining: bool,
    rain_start_minutes: int | None,
    max_rate_in_window: float = 0.0,
) -> bool:
    """Rain expected within the imminent-window and not currently falling.

    Only triggers when the forecasted peak rate within the window is at
    least RAIN_IMMINENT_MIN_RATE (0.3 mm/h) — trace amounts that you
    wouldn't notice outdoors don't deserve a push notification.
    """
    if is_raining or rain_start_minutes is None:
        return False
    if rain_start_minutes <= 0 or rain_start_minutes > RAIN_IMMINENT_THRESHOLD_MINUTES:
        return False
    return max_rate_in_window >= RAIN_IMMINENT_MIN_RATE


def is_severe_weather(
    intensity: str,
    max_2h_mm_h: float,
    precipitation_type: str,
) -> bool:
    """Heavy/violent precipitation or potential hail.

    Triggers the moment current OR forecast intensity crosses the
    'heavy' threshold (>= 7.6 mm/h) so users get an early warning
    rather than only when the cell is already overhead.
    """
    if intensity in ("heavy", "violent"):
        return True
    if max_2h_mm_h >= PRECIP_THRESHOLD_HEAVY:
        return True
    if precipitation_type == "hail_likely":
        return True
    return False


def is_winter_weather(precipitation_type: str) -> bool:
    """Snow, sleet or freezing rain detected or forecast."""
    return precipitation_type in WINTER_TYPES


def is_extended_dry_spell(
    dry_streak_hours: float | None,
    max_6h_mm_h: float,
) -> bool:
    """At least a week without rain AND nothing meaningful in the forecast.

    Both halves matter: long-running dry streak alone could be about to
    end, and a dry forecast alone could just be a sunny afternoon. We
    only nudge the user (e.g. "water the plants") when both signals
    line up.
    """
    if dry_streak_hours is None:
        return False
    if dry_streak_hours < DRY_SPELL_THRESHOLD_HOURS:
        return False
    return max_6h_mm_h <= 0.0
