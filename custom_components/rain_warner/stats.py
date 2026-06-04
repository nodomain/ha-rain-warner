"""Persistent rain statistics for Rain Warner.

Tracks long-running aggregates that complement the live nowcast:

  precipitation_today    : accumulated mm since local midnight
  precipitation_yesterday: copy of today's total at midnight rollover
  dry_streak_hours       : hours since the last significant rain
  last_rain_at           : timestamp of the most recent rainy update

The coordinator feeds 5-min observations in via update(); this module is
pure logic so it can be unit tested without Home Assistant. Persistence
is layered on top via the (de)serialize helpers and HA's Store.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# Threshold below which we consider it "not really raining" for streak
# computation. Drizzles of 0.05 mm/h shouldn't reset a dry streak.
DRY_STREAK_RESET_MM_H = 0.1
UPDATE_INTERVAL_MINUTES = 5


@dataclass
class RainStatistics:
    """Rolling aggregates persisted across HA restarts."""

    precipitation_today_mm: float = 0.0
    precipitation_yesterday_mm: float = 0.0
    last_update_iso: str | None = None
    last_rain_at_iso: str | None = None
    # Stored separately from now-last_rain so we can survive restarts
    # even when last_rain_at is None (i.e. we've never seen rain yet).
    dry_streak_started_iso: str | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def _parse(iso: str | None) -> datetime | None:
        if not iso:
            return None
        try:
            ts = datetime.fromisoformat(iso)
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts

    def update(self, now: datetime, current_mm_h: float) -> None:
        """Fold a new observation into the running totals.

        Args:
            now: Timestamp of the observation (timezone-aware).
            current_mm_h: Current precipitation rate in mm/h.
        """
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        last = self._parse(self.last_update_iso)

        # Detect midnight rollover (calendar day in UTC). We use UTC so
        # behaviour is deterministic regardless of HA's local time zone;
        # users who care about local-day boundaries can derive that
        # from the timestamp attribute instead.
        if last is not None and last.date() != now.date():
            self.precipitation_yesterday_mm = round(self.precipitation_today_mm, 2)
            self.precipitation_today_mm = 0.0

        # Accumulate today's total: rate (mm/h) * dt (h). When the time
        # gap between updates is unusually large (e.g. after a restart),
        # cap it at the nominal interval to avoid wild jumps.
        if last is not None:
            dt_hours = (now - last).total_seconds() / 3600.0
            dt_hours = max(0.0, min(dt_hours, UPDATE_INTERVAL_MINUTES / 60.0))
        else:
            dt_hours = UPDATE_INTERVAL_MINUTES / 60.0

        contribution = max(current_mm_h, 0.0) * dt_hours
        self.precipitation_today_mm = round(self.precipitation_today_mm + contribution, 2)

        # Dry-streak bookkeeping
        if current_mm_h >= DRY_STREAK_RESET_MM_H:
            self.last_rain_at_iso = now.isoformat()
            self.dry_streak_started_iso = now.isoformat()
        elif self.dry_streak_started_iso is None:
            # First-ever update without rain → start counting from now.
            self.dry_streak_started_iso = now.isoformat()

        # Append to a small ring-buffer of daily totals for sparkline
        # history (kept small so the .storage file stays tiny).
        if last is not None and last.date() != now.date():
            entry = {
                "date": last.date().isoformat(),
                "mm": self.precipitation_yesterday_mm,
            }
            # Avoid duplicates if update() is called twice for the same
            # rollover.
            if not self.history or self.history[-1].get("date") != entry["date"]:
                self.history.append(entry)
            # Keep the last 30 days only.
            if len(self.history) > 30:
                self.history = self.history[-30:]

        self.last_update_iso = now.isoformat()

    def dry_streak_hours(self, now: datetime | None = None) -> float | None:
        """Return hours since the last significant rain.

        None when we've never observed any data at all.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        # Prefer the explicit dry-streak start so a restart doesn't
        # forget the streak.
        ref_iso = self.dry_streak_started_iso or self.last_update_iso
        ref = self._parse(ref_iso)
        if ref is None:
            return None
        delta = (now - ref).total_seconds() / 3600.0
        return round(max(delta, 0.0), 2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for HA Store persistence."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RainStatistics:
        """Restore from a previously persisted dict (or fresh on None)."""
        if not data:
            return cls()
        return cls(
            precipitation_today_mm=float(data.get("precipitation_today_mm", 0.0)),
            precipitation_yesterday_mm=float(data.get("precipitation_yesterday_mm", 0.0)),
            last_update_iso=data.get("last_update_iso"),
            last_rain_at_iso=data.get("last_rain_at_iso"),
            dry_streak_started_iso=data.get("dry_streak_started_iso"),
            history=list(data.get("history") or []),
        )
