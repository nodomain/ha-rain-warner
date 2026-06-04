# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Custom Lovelace card (`dashboard/rain-warner-card.js`) — a single
  vanilla-JS file (no build step) that visualizes the integration's
  full nowcast in one card: status banner, 2 h precipitation bar
  chart, optional 6 h extended-forecast tail (greyed out), current
  type, temperature and today's accumulated rain.
- The `binary_sensor.rain_expected` entity now exposes `forecast` and
  `forecast_extended` as attributes so cards can render the bar chart
  without extra calls.
- Persistent rain statistics (`stats.py`) accumulated across HA
  restarts via the HA Storage helper:
  - `precipitation_today` / `precipitation_yesterday` (mm)
  - `dry_streak` (hours since the last rain >= 0.1 mm/h)
  - `last_rain_at` (timestamp)
  - 30-day daily-total ring buffer exposed as an attribute for
    sparkline cards.
- The accumulator clamps unusually long gaps between updates (e.g. an
  HA restart) to a single 5-min interval so totals never spike from
  bookkeeping anomalies.
- New `precipitation_type` sensor classifying the current precipitation
  as one of `none`, `rain`, `sleet`, `freezing_rain`, `snow`,
  `hail_likely`, or `unknown`. Uses radar intensity plus 2 m air
  temperature (NOAA/DWD-style thresholds at −1 / 0.5 / 1.5 °C).
- Air-temperature provider with 30 min cache that fills in temperature
  for the DWD and Bright Sky data sources via Open-Meteo, so the
  classifier works regardless of which radar backend is selected.
- German and English translations for the new sensor states.
- Open-Meteo data source for global coverage outside Germany
  (`open_meteo.py`). Fulfills the "RainViewer fallback" roadmap item:
  RainViewer only serves rendered tiles, Open-Meteo gives us numeric
  precipitation values world-wide with no API key.
- New `auto` data source mode (now the default) — picks DWD inside the
  DE1200 coverage bounding box and falls back to Open-Meteo elsewhere.
- Custom optical-flow nowcasting (`nowcast.py`) extending the RADVOR
  forecast beyond the 2 h DWD horizon up to 6 h. Estimates a global
  motion vector via cross-correlation on a sub-window around the user's
  location and advects the latest known frame semi-Lagrangian for
  synthetic frames at t+125 … t+360 in 5-min steps.
- Coordinator now exposes the extended forecast dict and motion metadata
  (speed in km/h, dr/dc per minute) for diagnostics.
- Coordinator now passes through air temperature (`temperature_c`) when
  the data source provides it.

### Changed

- Default data source switched from `dwd` to `auto`. Existing
  installations are unaffected; the change only takes effect for new
  config entries.
- Replaced the centroid + trailing-edge heuristic for rain-end
  extrapolation with the proper optical-flow advection pipeline. Same
  6 h cap, but more accurate when the rain field has internal
  structure (not just a single blob).

## [0.1.0] - 2026-06-04

### Added

- Full RADOLAN binary radar composite parsing (no external deps)
- DWD polar stereographic projection for accurate coordinate mapping
- RADVOR 2h nowcast integration (25 frames: t+0 through t+120 in 5-min steps)
- Area averaging over configurable radius (box filter)
- Rain end extrapolation beyond 2h window via centroid tracking + trailing edge measurement
- HACS integration with UI config flow (location, data source, radius)
- Sensors: current precipitation, intensity, rain start/end timing, max/total forecasts
- Binary sensors: is raining, rain expected (with forecast attributes)
- Rain end sensor shows extrapolated estimate when rain extends beyond 2h forecast
- Bright Sky API client as alternative JSON-based data source
- Dashboard with RainViewer radar map, sensor tiles, and history graphs
- Local test suite (unit tests + live DWD download tests, no HA dependency)
- Deploy script with rsync (SMB-compatible) + optional HA restart
- Dashboard push tool via WebSocket API
- German and English translations
- Automation examples in README
