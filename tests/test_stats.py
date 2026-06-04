"""Unit tests for persistent rain statistics."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))

from rain_warner.stats import RainStatistics

UTC = timezone.utc


class TestRainStatisticsAccumulation:
    def test_first_update_uses_nominal_interval(self):
        """The very first update has no prior timestamp → nominal 5 min."""
        stats = RainStatistics()
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t0, current_mm_h=12.0)  # 12 mm/h * 5/60 = 1.0 mm
        assert stats.precipitation_today_mm == 1.0

    def test_accumulates_across_updates(self):
        stats = RainStatistics()
        t = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        for _ in range(6):
            stats.update(t, current_mm_h=12.0)
            t += timedelta(minutes=5)
        # 6 buckets of 1.0 mm each = 6.0 mm. The first update uses
        # nominal 5 min, the rest use the actual delta of 5 min.
        assert stats.precipitation_today_mm == 6.0

    def test_clamps_long_gaps_to_one_interval(self):
        """A 2-hour gap (e.g. HA restart) shouldn't add 24 mm at 12 mm/h."""
        stats = RainStatistics()
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t0, current_mm_h=0.0)
        # Now jump 2 hours forward
        t1 = t0 + timedelta(hours=2)
        stats.update(t1, current_mm_h=12.0)
        # Should add at most one 5-min bucket = 1.0 mm
        assert stats.precipitation_today_mm == 1.0

    def test_negative_rate_treated_as_zero(self):
        stats = RainStatistics()
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t0, current_mm_h=-1.0)
        assert stats.precipitation_today_mm == 0.0


class TestMidnightRollover:
    def test_today_becomes_yesterday_at_rollover(self):
        stats = RainStatistics()
        # Mid-day on day 1
        t1 = datetime(2026, 1, 15, 23, 55, tzinfo=UTC)
        stats.update(t1, current_mm_h=12.0)
        assert stats.precipitation_today_mm == 1.0
        # Cross midnight
        t2 = datetime(2026, 1, 16, 0, 5, tzinfo=UTC)
        stats.update(t2, current_mm_h=0.0)
        assert stats.precipitation_yesterday_mm == 1.0
        assert stats.precipitation_today_mm == 0.0

    def test_history_records_previous_day(self):
        stats = RainStatistics()
        t1 = datetime(2026, 1, 15, 23, 55, tzinfo=UTC)
        stats.update(t1, current_mm_h=12.0)
        t2 = datetime(2026, 1, 16, 0, 5, tzinfo=UTC)
        stats.update(t2, current_mm_h=0.0)
        assert stats.history[-1] == {"date": "2026-01-15", "mm": 1.0}

    def test_history_capped_at_30_days(self):
        stats = RainStatistics()
        for day in range(1, 36):
            t = datetime(2026, 2, 1, tzinfo=UTC) + timedelta(days=day)
            stats.update(t - timedelta(minutes=5), current_mm_h=2.0)
            stats.update(t, current_mm_h=0.0)
        assert len(stats.history) == 30


class TestDryStreak:
    def test_streak_resets_on_rain(self):
        stats = RainStatistics()
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t0, current_mm_h=0.0)
        # 6h later it rains
        t1 = t0 + timedelta(hours=6)
        stats.update(t1, current_mm_h=2.0)
        # Streak now starts at t1
        streak = stats.dry_streak_hours(now=t1 + timedelta(hours=1))
        assert streak == 1.0

    def test_streak_grows_when_dry(self):
        stats = RainStatistics()
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t0, current_mm_h=2.0)  # last rain
        # 24h later, still dry
        stats.update(t0 + timedelta(hours=24), current_mm_h=0.0)
        streak = stats.dry_streak_hours(now=t0 + timedelta(hours=24))
        assert streak == 24.0

    def test_drizzle_below_threshold_does_not_reset(self):
        stats = RainStatistics()
        t0 = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t0, current_mm_h=0.0)
        # tiny drizzle, below 0.1 mm/h threshold
        stats.update(t0 + timedelta(hours=2), current_mm_h=0.05)
        streak = stats.dry_streak_hours(now=t0 + timedelta(hours=2))
        assert streak == 2.0

    def test_streak_none_before_any_update(self):
        stats = RainStatistics()
        assert stats.dry_streak_hours() is None

    def test_last_rain_at_recorded(self):
        stats = RainStatistics()
        t = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t, current_mm_h=2.0)
        assert stats.last_rain_at_iso == t.isoformat()


class TestPersistence:
    def test_roundtrip(self):
        stats = RainStatistics()
        t = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        stats.update(t, current_mm_h=12.0)
        stats.update(t + timedelta(minutes=5), current_mm_h=6.0)

        as_dict = stats.to_dict()
        restored = RainStatistics.from_dict(as_dict)

        assert restored.precipitation_today_mm == stats.precipitation_today_mm
        assert restored.last_update_iso == stats.last_update_iso
        assert restored.last_rain_at_iso == stats.last_rain_at_iso

    def test_from_empty_dict_yields_defaults(self):
        stats = RainStatistics.from_dict(None)
        assert stats.precipitation_today_mm == 0.0
        assert stats.last_update_iso is None
