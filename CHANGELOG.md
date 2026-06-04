# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Custom optical-flow nowcasting (`nowcast.py`) extending the RADVOR
  forecast beyond the 2 h DWD horizon up to 6 h. Estimates a global
  motion vector via cross-correlation on a sub-window around the user's
  location and advects the latest known frame semi-Lagrangian for
  synthetic frames at t+125 … t+360 in 5-min steps.
- Coordinator now exposes the extended forecast dict and motion metadata
  (speed in km/h, dr/dc per minute) for diagnostics.

### Changed

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
